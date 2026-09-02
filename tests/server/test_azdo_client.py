# Standard
import base64
from unittest.mock import AsyncMock, MagicMock, patch

# Remote
import pytest

from hermes_server import azdo_client


class TestServerAzdoClient:
    def test_auth_headers(self):
        with patch.object(azdo_client.settings, "AZDO_PAT", "secret-pat"):
            headers = azdo_client._auth_headers()
            assert "Authorization" in headers
            expected_token = base64.b64encode(b":secret-pat").decode()
            assert headers["Authorization"] == f"Basic {expected_token}"

    @pytest.mark.asyncio
    async def test_get_user_avatar_b64_missing_config(self):
        with (
            patch.object(azdo_client.settings, "AZDO_PAT", ""),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", ""),
        ):
            res = await azdo_client.get_user_avatar_b64("u1")
            assert res is None

    @pytest.mark.asyncio
    async def test_get_user_avatar_b64_success_and_cache(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake-png-bytes"
        mock_resp.headers = {"content-type": "image/png"}

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_resp)

        azdo_client._avatar_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res1 = await azdo_client.get_user_avatar_b64("user-avatar-1")
            assert res1.startswith("data:image/png;base64,")
            mock_http.get.assert_called_once()

            # Second call should hit the memory cache
            res2 = await azdo_client.get_user_avatar_b64("user-avatar-1")
            assert res2 == res1
            assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_get_user_avatar_b64_handles_exception(self):
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("Network error"))

        azdo_client._avatar_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res = await azdo_client.get_user_avatar_b64("user-err")
            assert res is None

    @pytest.mark.asyncio
    async def test_get_user_groups_missing_config(self):
        with (
            patch.object(azdo_client.settings, "AZDO_PAT", ""),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", ""),
        ):
            res = await azdo_client.get_user_groups("u1")
            assert res == {"ids": [], "names": []}

    @pytest.mark.asyncio
    async def test_get_user_groups_success_and_cache(self):
        resp_identity = MagicMock()
        resp_identity.status_code = 200
        resp_identity.json.return_value = {"memberOf": ["group-id-1"]}

        resp_group = MagicMock()
        resp_group.status_code = 200
        resp_group.json.return_value = {
            "value": [{"providerDisplayName": "Engineers", "customDisplayName": None}]
        }

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=[resp_identity, resp_group])

        azdo_client._group_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res1 = await azdo_client.get_user_groups("user-grp-1")
            assert res1["ids"] == ["group-id-1"]
            assert res1["names"] == ["Engineers"]

            # Second call should use cache
            res2 = await azdo_client.get_user_groups("user-grp-1")
            assert res2 == res1
            assert mock_http.get.call_count == 2

    @pytest.mark.asyncio
    async def test_get_user_groups_handles_api_error(self):
        resp_identity = MagicMock()
        resp_identity.status_code = 500

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=resp_identity)

        azdo_client._group_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res = await azdo_client.get_user_groups("user-grp-err")
            assert res == {"ids": [], "names": []}

    @pytest.mark.asyncio
    async def test_get_pr_reviewers(self):
        reviewers = [{"id": "r1", "displayName": "Reviewer 1"}]
        res = await azdo_client.get_pr_reviewers({"reviewers": reviewers})
        assert res == reviewers

    @pytest.mark.asyncio
    async def test_get_thread_participants(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "comments": [
                {"author": {"id": "author-1", "displayName": "Dale"}},
                {"author": {"id": "author-2", "displayName": "Taiye"}},
            ]
        }
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_resp)

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            participants = await azdo_client.get_thread_participants("http://ado/threads/1")
            assert len(participants) == 2
            assert participants[0]["id"] == "author-1"
            assert participants[1]["id"] == "author-2"

    @pytest.mark.asyncio
    async def test_get_thread_participants_missing_config(self):
        with patch.object(azdo_client.settings, "AZDO_PAT", ""):
            participants = await azdo_client.get_thread_participants("http://ado/threads/1")
            assert participants == []

    @pytest.mark.asyncio
    async def test_resolve_identity_missing_config(self):
        with (
            patch.object(azdo_client.settings, "AZDO_PAT", ""),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", ""),
        ):
            res = await azdo_client.resolve_identity("Dale")
            assert res is None

    @pytest.mark.asyncio
    async def test_resolve_identity_success_and_cache(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "id": "guid-1234",
                    "providerDisplayName": "Euan",
                    "uniqueName": "DOMAIN\\Euan",
                }
            ]
        }
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_resp)

        azdo_client._identity_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res1 = await azdo_client.resolve_identity("DOMAIN\\Euan")
            assert res1 is not None
            assert res1["id"] == "guid-1234"
            assert res1["displayName"] == "Euan"
            assert res1["uniqueName"] == "DOMAIN\\Euan"

            # Second call uses cache
            res2 = await azdo_client.resolve_identity("DOMAIN\\Euan")
            assert res2 == res1
            assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_resolve_identity_handles_exception(self):
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("Network error"))

        azdo_client._identity_cache.clear()

        with (
            patch.object(azdo_client.settings, "AZDO_PAT", "pat"),
            patch.object(azdo_client.settings, "AZDO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res = await azdo_client.resolve_identity("err-user")
            assert res is None

