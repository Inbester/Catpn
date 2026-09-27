"""Storing exchange API keys (SPEC §3.5, §5, §9).

Three rules, in the order they matter:

1. **A key that can withdraw is never stored.** The platform never holds
   funds and never needs that permission, so a key carrying it is refused
   at the door rather than kept and trusted not to be misused.
2. **A key that is not pinned to this server's IP is never stored.** An
   unrestricted key works from anywhere, which is what the whitelist exists
   to prevent, and it is also how SPEC §9 keeps order traffic on the
   server's static IP instead of a user's VPN.
3. **A stored key is never returned.** Not to the client, not to the user
   who typed it, not in a log or a traceback. What comes back is a label,
   the last four characters and a fingerprint — enough to tell two keys
   apart and nothing more.

**Envelope encryption.** Each secret gets its own random data key; the
secret is sealed under that, and the data key is sealed under a master key
that never touches the database. Two things follow: rotating the master key
re-wraps small data keys rather than re-encrypting every secret, and a
database dump on its own decrypts nothing.

The master key is behind `MasterKeyProvider`, so KMS or Vault is a new
implementation of two methods and no change here. `LocalMasterKey` derives
from the application secret and is what runs in development.

**Binding.** Every ciphertext is sealed with the owning user and key id as
associated data. A row copied into another user's account fails to open
rather than quietly decrypting — the tampering shows up as an error.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from quanta.core.config import Settings, get_settings
from quanta.exchanges.trading import (
    Credentials,
    KeyPermissions,
    KeyRejectedError,
    TradingAdapter,
)

#: AES-GCM nonces are 96 bits. Never reused: one fresh nonce per seal.
NONCE_BYTES = 12
DATA_KEY_BYTES = 32


class VaultError(Exception):
    """A secret that would not open. Corruption, tampering, or a rotated
    master key that no longer has the version this row was sealed under."""


class MasterKeyProvider(Protocol):
    """Wraps and unwraps data keys. The master key itself never leaves it."""

    #: Which master key sealed a given row, so rotation can be staged.
    version: str

    def wrap(self, data_key: bytes, context: str) -> bytes: ...

    def unwrap(self, wrapped: bytes, context: str, version: str) -> bytes: ...


class LocalMasterKey:
    """A master key derived from the application secret.

    Adequate for development and a single-server deployment, where the
    secret is already the thing protecting sessions. It is not a KMS: the
    key material lives in the same process as the data it protects, so a
    process compromise gets both. SPEC §5 wants KMS or Vault in production,
    and that is a second implementation of this protocol, not a change to
    anything that calls it.
    """

    version = "local-1"

    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise VaultError("the master secret must be at least 32 characters")
        # A distinct label so this key is not the session-signing key even
        # though both come from the same secret.
        self._key = hashlib.blake2b(
            secret.encode(), digest_size=32, person=b"quanta-keyvault"
        ).digest()

    def wrap(self, data_key: bytes, context: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + AESGCM(self._key).encrypt(nonce, data_key, context.encode())

    def unwrap(self, wrapped: bytes, context: str, version: str) -> bytes:
        if version != self.version:
            raise VaultError(f"no master key for version {version!r}")
        if len(wrapped) <= NONCE_BYTES:
            raise VaultError("wrapped data key is truncated")
        nonce, sealed = wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:]
        try:
            return AESGCM(self._key).decrypt(nonce, sealed, context.encode())
        except InvalidTag as exc:
            raise VaultError("wrapped data key failed to open") from exc


@dataclass(frozen=True, slots=True)
class SealedSecret:
    """What goes in the database. None of it is useful without the master key."""

    wrapped_key: bytes
    ciphertext: bytes
    key_version: str


class KeyVault:
    """Seals and opens exchange credentials."""

    def __init__(self, provider: MasterKeyProvider, *, settings: Settings | None = None) -> None:
        self._provider = provider
        self._settings = settings or get_settings()

    @classmethod
    def local(cls, settings: Settings | None = None) -> KeyVault:
        """The vault this deployment uses.

        `vault_master_key` is its own secret, not the one that signs
        sessions: the web process holds `secret_key`, and one leak should
        not also hand over the keys that can place orders. In development
        it may be unset and falls back, which production refuses — see the
        configuration guard.
        """
        resolved = settings or get_settings()
        master = resolved.vault_master_key or resolved.secret_key
        return cls(LocalMasterKey(master), settings=resolved)

    # --- Sealing ---------------------------------------------------------

    def seal(self, plaintext: str, *, context: str) -> SealedSecret:
        """Encrypt one secret under a fresh data key.

        `context` is bound into both layers as associated data, so a row
        moved to another user or another key id fails to open.
        """
        data_key = os.urandom(DATA_KEY_BYTES)
        nonce = os.urandom(NONCE_BYTES)
        ciphertext = nonce + AESGCM(data_key).encrypt(nonce, plaintext.encode(), context.encode())
        return SealedSecret(
            wrapped_key=self._provider.wrap(data_key, context),
            ciphertext=ciphertext,
            key_version=self._provider.version,
        )

    def open(self, sealed: SealedSecret, *, context: str) -> str:
        data_key = self._provider.unwrap(sealed.wrapped_key, context, sealed.key_version)
        if len(sealed.ciphertext) <= NONCE_BYTES:
            raise VaultError("ciphertext is truncated")
        nonce, body = sealed.ciphertext[:NONCE_BYTES], sealed.ciphertext[NONCE_BYTES:]
        try:
            return AESGCM(data_key).decrypt(nonce, body, context.encode()).decode()
        except InvalidTag as exc:
            raise VaultError("secret failed to open: wrong context or tampered row") from exc

    def rewrap(self, sealed: SealedSecret, *, context: str) -> SealedSecret:
        """Move a row onto the current master key without touching the secret.

        The point of the envelope: rotation reads and rewrites 32 bytes per
        row instead of decrypting and re-encrypting every secret.
        """
        data_key = self._provider.unwrap(sealed.wrapped_key, context, sealed.key_version)
        return SealedSecret(
            wrapped_key=self._provider.wrap(data_key, context),
            ciphertext=sealed.ciphertext,
            key_version=self._provider.version,
        )

    # --- Display ---------------------------------------------------------

    def fingerprint(self, api_key: str) -> str:
        """A stable, non-reversible id for one key.

        Keyed rather than a bare hash, so the same key at two deployments
        does not produce the same fingerprint and nobody can confirm a
        guessed key offline from a leaked fingerprint alone.
        """
        keyed = self._settings.vault_master_key or self._settings.secret_key
        digest = hmac.new(keyed.encode(), api_key.encode(), hashlib.sha256).hexdigest()
        return digest[:16]

    @staticmethod
    def last_four(api_key: str) -> str:
        return api_key[-4:] if len(api_key) >= 4 else ""


def context_for(user_id: object, key_id: object) -> str:
    """The associated data binding a row to its owner and its id."""
    return f"exchange-key:{user_id}:{key_id}"


async def verify_admissible(
    adapter: TradingAdapter,
    credentials: Credentials,
    *,
    server_ip: str,
) -> KeyPermissions:
    """Check a key against SPEC §3.5 before it is ever stored.

    Raises `KeyRejectedError` with a `reason` the UI can turn into a
    specific message, because "invalid key" tells a user nothing about
    which of three settings to go and change.
    """
    permissions = await adapter.key_permissions(credentials)

    if permissions.can_withdraw:
        raise KeyRejectedError(
            "This key can withdraw funds. Create one with trading permission only.",
            reason="withdrawal_permission",
        )
    if not permissions.can_trade:
        raise KeyRejectedError(
            "This key cannot place orders. Enable futures trading on it.",
            reason="no_trade_permission",
        )
    if not permissions.is_ip_restricted:
        raise KeyRejectedError(
            f"This key is not restricted to an IP. Whitelist {server_ip} on it.",
            reason="not_ip_restricted",
        )
    if not permissions.allows_ip(server_ip):
        raise KeyRejectedError(
            f"This key is not whitelisted for {server_ip}, which is where orders are sent from.",
            reason="wrong_ip",
        )
    return permissions
