"""Autosave sync, conflict handling and the History tab."""

from __future__ import annotations

from httpx import AsyncClient

from tests.test_auth_routes import login, register


async def auth_header(client: AsyncClient, prefix: str) -> dict[str, str]:
    await register(client, prefix)
    tokens = await login(client, prefix)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


DRAWINGS = {
    "drawings": [
        {"id": "d1", "type": "trend", "points": [[1727000000, 64000], [1727086400, 65200]]}
    ],
    "indicators": [{"name": "EMA", "length": 20}],
}


class TestDocumentSync:
    async def test_push_creates_revision_one(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth_header(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "chart",
                "scope_key": "BTCUSDT:15m",
                "data": DRAWINGS,
                "base_revision": 0,
                "device_label": "Chrome on Linux",
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["revision"] == 1
        assert body["data"] == DRAWINGS
        assert body["scope_key"] == "BTCUSDT:15m"

    async def test_second_push_bumps_the_revision(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth_header(client, api_prefix)
        await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "scope_key": "BTCUSDT:15m", "data": {}, "base_revision": 0},
        )
        second = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "chart",
                "scope_key": "BTCUSDT:15m",
                "data": DRAWINGS,
                "base_revision": 1,
            },
        )
        assert second.status_code == 200
        assert second.json()["revision"] == 2

    async def test_stale_base_revision_is_a_conflict(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """Two devices editing the same chart must not silently overwrite."""
        headers = await auth_header(client, api_prefix)
        await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "scope_key": "ETHUSDT:1h", "data": {"v": 1}, "base_revision": 0},
        )
        await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "scope_key": "ETHUSDT:1h", "data": {"v": 2}, "base_revision": 1},
        )

        # A second device still believes it is editing revision 1.
        conflict = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "scope_key": "ETHUSDT:1h", "data": {"v": 9}, "base_revision": 1},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["current"]["data"] == {"v": 2}

    async def test_fetch_by_kind_and_scope(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth_header(client, api_prefix)
        await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "settings",
                "scope_key": "default",
                "data": {"theme": "paper"},
                "base_revision": 0,
            },
        )
        response = await client.get(
            f"{api_prefix}/workspace/document",
            headers=headers,
            params={"kind": "settings", "scope_key": "default"},
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"theme": "paper"}

    async def test_unknown_kind_is_rejected(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth_header(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "not-a-kind", "data": {}, "base_revision": 0},
        )
        assert response.status_code == 422

    async def test_oversized_document_is_rejected(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        headers = await auth_header(client, api_prefix)
        response = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "data": {"blob": "x" * 1_100_000}, "base_revision": 0},
        )
        assert response.status_code == 413

    async def test_autosave_requires_authentication(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        response = await client.put(
            f"{api_prefix}/workspace/documents",
            json={"kind": "chart", "data": {}, "base_revision": 0},
        )
        assert response.status_code == 401


class TestTenantIsolation:
    async def test_one_user_cannot_read_another_users_document(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        owner = await auth_header(client, api_prefix)
        created = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=owner,
            json={
                "kind": "chart",
                "scope_key": "SOLUSDT:5m",
                "data": {"secret": True},
                "base_revision": 0,
            },
        )
        document_id = created.json()["id"]

        await register(client, api_prefix, email="intruder@example.com")
        intruder_tokens = await login(client, api_prefix, email="intruder@example.com")
        intruder = {"Authorization": f"Bearer {intruder_tokens['access_token']}"}

        # Not visible in their list...
        listed = await client.get(f"{api_prefix}/workspace/documents", headers=intruder)
        assert listed.json() == []

        # ...and not reachable by id.
        for path in (
            f"{api_prefix}/workspace/documents/{document_id}/revisions",
            f"{api_prefix}/workspace/documents/{document_id}",
        ):
            response = await client.get(path, headers=intruder)
            assert response.status_code in (404, 405)

        deleted = await client.delete(
            f"{api_prefix}/workspace/documents/{document_id}", headers=intruder
        )
        assert deleted.status_code == 404


class TestHistory:
    async def test_revisions_accumulate(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth_header(client, api_prefix)
        created = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={"kind": "chart", "scope_key": "BTCUSDT:1h", "data": {"v": 1}, "base_revision": 0},
        )
        document_id = created.json()["id"]
        for revision in range(1, 4):
            await client.put(
                f"{api_prefix}/workspace/documents",
                headers=headers,
                json={
                    "kind": "chart",
                    "scope_key": "BTCUSDT:1h",
                    "data": {"v": revision + 1},
                    "base_revision": revision,
                },
            )

        response = await client.get(
            f"{api_prefix}/workspace/documents/{document_id}/revisions", headers=headers
        )
        assert response.status_code == 200
        revisions = response.json()
        assert [r["revision"] for r in revisions] == [4, 3, 2, 1]

    async def test_restore_creates_a_new_revision(
        self, client: AsyncClient, api_prefix: str
    ) -> None:
        """Restoring must be undoable, so it moves forward rather than back."""
        headers = await auth_header(client, api_prefix)
        created = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "chart",
                "scope_key": "BTCUSDT:4h",
                "data": {"v": "first"},
                "base_revision": 0,
            },
        )
        document_id = created.json()["id"]
        await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "chart",
                "scope_key": "BTCUSDT:4h",
                "data": {"v": "second"},
                "base_revision": 1,
            },
        )

        revisions = (
            await client.get(
                f"{api_prefix}/workspace/documents/{document_id}/revisions", headers=headers
            )
        ).json()
        first = next(r for r in revisions if r["revision"] == 1)

        restored = await client.post(
            f"{api_prefix}/workspace/documents/{document_id}/revisions/{first['id']}/restore",
            headers=headers,
        )
        assert restored.status_code == 200
        assert restored.json()["revision"] == 3
        assert restored.json()["data"] == {"v": "first"}

        current = await client.get(
            f"{api_prefix}/workspace/document",
            headers=headers,
            params={"kind": "chart", "scope_key": "BTCUSDT:4h"},
        )
        assert current.json()["data"] == {"v": "first"}

    async def test_labelling_a_revision(self, client: AsyncClient, api_prefix: str) -> None:
        headers = await auth_header(client, api_prefix)
        created = await client.put(
            f"{api_prefix}/workspace/documents",
            headers=headers,
            json={
                "kind": "strategy",
                "scope_key": "rsi-mean-reversion",
                "data": {"v": 1},
                "base_revision": 0,
            },
        )
        document_id = created.json()["id"]
        revisions = (
            await client.get(
                f"{api_prefix}/workspace/documents/{document_id}/revisions", headers=headers
            )
        ).json()

        response = await client.patch(
            f"{api_prefix}/workspace/documents/{document_id}/revisions/{revisions[0]['id']}",
            headers=headers,
            json={"label": "Before the ATR change"},
        )
        assert response.status_code == 200
        assert response.json()["label"] == "Before the ATR change"
