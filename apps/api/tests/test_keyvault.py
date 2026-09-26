"""The vault holds the one secret whose leak costs money.

These test the properties that matter rather than the implementation: that
a dump decrypts nothing on its own, that a row cannot be moved between
accounts, that a tampered row errors instead of opening, and that the three
SPEC §3.5 refusals actually refuse.
"""

from __future__ import annotations

import pytest

from quanta.core.config import Settings
from quanta.exchanges.sim.trading import (
    SIM_SERVER_IP,
    SimAccount,
    SimulatedTradingAdapter,
    default_permissions,
)
from quanta.exchanges.trading import Credentials, KeyPermissions, KeyRejectedError
from quanta.services.keyvault import (
    KeyVault,
    LocalMasterKey,
    SealedSecret,
    VaultError,
    context_for,
    verify_admissible,
)

SECRET = "a-test-secret-long-enough-to-be-accepted-0123456789"
SETTINGS = Settings(secret_key=SECRET)
CONTEXT = context_for("user-1", "key-1")


@pytest.fixture
def vault() -> KeyVault:
    return KeyVault(LocalMasterKey(SECRET), settings=SETTINGS)


class TestSealing:
    def test_a_secret_survives_a_round_trip(self, vault: KeyVault) -> None:
        sealed = vault.seal("bitunix-api-secret", context=CONTEXT)
        assert vault.open(sealed, context=CONTEXT) == "bitunix-api-secret"

    def test_the_plaintext_is_nowhere_in_the_stored_bytes(self, vault: KeyVault) -> None:
        sealed = vault.seal("needle-in-the-haystack", context=CONTEXT)
        blob = sealed.ciphertext + sealed.wrapped_key
        assert b"needle" not in blob

    def test_sealing_twice_gives_different_bytes(self, vault: KeyVault) -> None:
        """Otherwise equal ciphertexts would reveal equal keys across rows."""
        one = vault.seal("same", context=CONTEXT)
        two = vault.seal("same", context=CONTEXT)
        assert one.ciphertext != two.ciphertext
        assert one.wrapped_key != two.wrapped_key

    def test_each_row_gets_its_own_data_key(self, vault: KeyVault) -> None:
        one = vault.seal("a", context=CONTEXT)
        two = vault.seal("b", context=CONTEXT)
        assert one.wrapped_key != two.wrapped_key


class TestBinding:
    def test_a_row_moved_to_another_user_will_not_open(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=context_for("user-1", "key-1"))
        with pytest.raises(VaultError):
            vault.open(sealed, context=context_for("user-2", "key-1"))

    def test_a_row_moved_to_another_key_id_will_not_open(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=context_for("user-1", "key-1"))
        with pytest.raises(VaultError):
            vault.open(sealed, context=context_for("user-1", "key-2"))


class TestTampering:
    def test_a_flipped_ciphertext_byte_errors(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=CONTEXT)
        broken = bytearray(sealed.ciphertext)
        broken[-1] ^= 0x01
        with pytest.raises(VaultError):
            vault.open(
                SealedSecret(sealed.wrapped_key, bytes(broken), sealed.key_version),
                context=CONTEXT,
            )

    def test_a_flipped_wrapped_key_byte_errors(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=CONTEXT)
        broken = bytearray(sealed.wrapped_key)
        broken[-1] ^= 0x01
        with pytest.raises(VaultError):
            vault.open(
                SealedSecret(bytes(broken), sealed.ciphertext, sealed.key_version),
                context=CONTEXT,
            )

    def test_a_truncated_row_errors_rather_than_crashing(self, vault: KeyVault) -> None:
        with pytest.raises(VaultError, match="truncated"):
            vault.open(SealedSecret(b"", b"", "local-1"), context=CONTEXT)


class TestDifferentMasterKeys:
    def test_another_deployment_cannot_open_the_row(self) -> None:
        """A database dump is worth nothing without the master key."""
        mine = KeyVault(LocalMasterKey(SECRET), settings=SETTINGS)
        theirs = KeyVault(
            LocalMasterKey("a-completely-different-secret-0123456789abcdef"),
            settings=SETTINGS,
        )
        sealed = mine.seal("secret", context=CONTEXT)
        with pytest.raises(VaultError):
            theirs.open(sealed, context=CONTEXT)

    def test_a_short_master_secret_is_refused(self) -> None:
        with pytest.raises(VaultError, match="at least 32"):
            LocalMasterKey("too-short")

    def test_an_unknown_key_version_errors_clearly(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=CONTEXT)
        with pytest.raises(VaultError, match="no master key"):
            vault.open(
                SealedSecret(sealed.wrapped_key, sealed.ciphertext, "local-99"),
                context=CONTEXT,
            )


class TestRotation:
    def test_rewrapping_keeps_the_secret_readable(self, vault: KeyVault) -> None:
        sealed = vault.seal("secret", context=CONTEXT)
        rewrapped = vault.rewrap(sealed, context=CONTEXT)
        assert vault.open(rewrapped, context=CONTEXT) == "secret"

    def test_rewrapping_does_not_re_encrypt_the_secret(self, vault: KeyVault) -> None:
        """That is the point of the envelope: rotation touches 32 bytes."""
        sealed = vault.seal("secret", context=CONTEXT)
        rewrapped = vault.rewrap(sealed, context=CONTEXT)
        assert rewrapped.ciphertext == sealed.ciphertext
        assert rewrapped.wrapped_key != sealed.wrapped_key


class TestDisplay:
    def test_a_fingerprint_is_stable_for_the_same_key(self, vault: KeyVault) -> None:
        assert vault.fingerprint("abc123") == vault.fingerprint("abc123")

    def test_different_keys_fingerprint_differently(self, vault: KeyVault) -> None:
        assert vault.fingerprint("abc123") != vault.fingerprint("abc124")

    def test_the_fingerprint_does_not_contain_the_key(self, vault: KeyVault) -> None:
        assert "abc123" not in vault.fingerprint("abc123")

    def test_the_fingerprint_is_keyed_to_this_deployment(self) -> None:
        """A leaked fingerprint must not let a guessed key be confirmed
        offline against another deployment."""
        one = KeyVault(LocalMasterKey(SECRET), settings=SETTINGS)
        two = KeyVault(
            LocalMasterKey(SECRET),
            settings=Settings(secret_key="another-deployment-secret-0123456789abcdef"),
        )
        assert one.fingerprint("abc123") != two.fingerprint("abc123")

    def test_last_four_is_the_tail(self, vault: KeyVault) -> None:
        assert vault.last_four("abcdefgh") == "efgh"

    def test_last_four_of_a_short_string_reveals_nothing(self, vault: KeyVault) -> None:
        assert vault.last_four("ab") == ""


class TestAdmission:
    """SPEC §3.5: the three reasons a key is refused before it is stored."""

    def venue_with(self, permissions: KeyPermissions) -> SimulatedTradingAdapter:
        adapter = SimulatedTradingAdapter()
        adapter.add_account("k", SimAccount(permissions=permissions))
        return adapter

    async def test_a_well_formed_key_is_admitted(self) -> None:
        adapter = self.venue_with(default_permissions())
        permissions = await verify_admissible(
            adapter,
            Credentials(api_key="k", api_secret="sim-secret"),
            server_ip=SIM_SERVER_IP,
        )
        assert permissions.can_trade

    async def test_a_key_that_can_withdraw_is_refused(self) -> None:
        adapter = self.venue_with(
            KeyPermissions(
                can_read=True, can_trade=True, can_withdraw=True, ip_whitelist=(SIM_SERVER_IP,)
            )
        )
        with pytest.raises(KeyRejectedError) as caught:
            await verify_admissible(
                adapter,
                Credentials(api_key="k", api_secret="sim-secret"),
                server_ip=SIM_SERVER_IP,
            )
        assert caught.value.reason == "withdrawal_permission"

    async def test_a_key_with_no_ip_restriction_is_refused(self) -> None:
        adapter = self.venue_with(default_permissions(whitelist_ip=None))
        with pytest.raises(KeyRejectedError) as caught:
            await verify_admissible(
                adapter,
                Credentials(api_key="k", api_secret="sim-secret"),
                server_ip=SIM_SERVER_IP,
            )
        assert caught.value.reason == "not_ip_restricted"
        # The message has to name the IP, or the user cannot act on it.
        assert SIM_SERVER_IP in caught.value.message

    async def test_a_key_pinned_to_the_wrong_ip_is_refused(self) -> None:
        adapter = self.venue_with(default_permissions(whitelist_ip="198.51.100.9"))
        with pytest.raises(KeyRejectedError) as caught:
            await verify_admissible(
                adapter,
                Credentials(api_key="k", api_secret="sim-secret"),
                server_ip=SIM_SERVER_IP,
            )
        assert caught.value.reason == "wrong_ip"
        assert SIM_SERVER_IP in caught.value.message

    async def test_a_read_only_key_is_refused(self) -> None:
        adapter = self.venue_with(
            KeyPermissions(
                can_read=True, can_trade=False, can_withdraw=False, ip_whitelist=(SIM_SERVER_IP,)
            )
        )
        with pytest.raises(KeyRejectedError) as caught:
            await verify_admissible(
                adapter,
                Credentials(api_key="k", api_secret="sim-secret"),
                server_ip=SIM_SERVER_IP,
            )
        assert caught.value.reason == "no_trade_permission"

    async def test_withdrawal_is_checked_before_the_ip(self) -> None:
        """A key that can withdraw is refused for that, whatever else is
        wrong with it: it is the reason the user must act on first."""
        adapter = self.venue_with(
            KeyPermissions(can_read=True, can_trade=True, can_withdraw=True, ip_whitelist=())
        )
        with pytest.raises(KeyRejectedError) as caught:
            await verify_admissible(
                adapter,
                Credentials(api_key="k", api_secret="sim-secret"),
                server_ip=SIM_SERVER_IP,
            )
        assert caught.value.reason == "withdrawal_permission"
