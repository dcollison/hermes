# Standard
import base64
from unittest.mock import AsyncMock, MagicMock, patch

# Remote
import pytest

from hermes_server import ado_client


class TestServerAdoClient:
    def test_auth_headers(self):
        with patch.object(ado_client.settings, "ADO_PAT", "secret-pat"):
            headers = ado_client._auth_headers()
            assert "Authorization" in headers
            expected_token = base64.b64encode(b":secret-pat").decode()
            assert headers["Authorization"] == f"Basic {expected_token}"

    @pytest.mark.asyncio
    async def test_get_user_avatar_b64_missing_config(self):
        with (
            patch.object(ado_client.settings, "ADO_PAT", ""),
            patch.object(ado_client.settings, "ADO_ORGANIZATION_URL", ""),
        ):
            res = await ado_client.get_user_avatar_b64("u1")
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

        ado_client._avatar_cache.clear()

        with (
            patch.object(ado_client.settings, "ADO_PAT", "pat"),
            patch.object(ado_client.settings, "ADO_ORGANIZATION_URL", "http://ado"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            res1 = await ado_client.get_user_avatar_b64("user-avatar-1")
            assert res1.startswith("data:image/png;base64,")
            mock_http.get.assert_called_once()

            # Second call should hit the memory cache
            res2 = await ado_client.get_user_avatar_b64("user-avatar-1")
            assert res2 == res1
            assert mock_http.get.call_count == 1

    @pytest.mark.asyncio
    async def test_get_user_groups_missing_config(self):
        with (
            patch.object(ado_client.settings, "ADO_PAT", ""),
            patch.object(ado_client.settings, "ADO_ORGANIZATION_URL", ""),
        ):
            res = await ado_client.get_user_groups("u1")
            assert res == {"ids": [], "names": []}

    @pytest.mark.asyncio
    async def test_get_user_groups_success_and_cache(self):
        mock_identity = MagicMock()
        mock_identity.member_of = ["group-id-1"]

        mock_group_obj = MagicMock()
        mock_group_obj.provider_display_name = "Engineers"
        mock_group_obj.custom_display_name = None

        mock_identity_client = MagicMock()
        mock_identity_client.read_identities.side_effect = [
            [mock_identity],
            [mock_group_obj],
        ]

        ado_client._group_cache.clear()

        with (
            patch.object(ado_client.settings, "ADO_PAT", "pat"),
            patch.object(ado_client.settings, "ADO_ORGANIZATION_URL", "http://ado"),
            patch.object(ado_client, "_get_identity_client", return_value=mock_identity_client),
        ):
            res1 = await ado_client.get_user_groups("user-grp-1")
            assert res1["ids"] == ["group-id-1"]
            assert res1["names"] == ["Engineers"]

            # Second call should use cache
            res2 = await ado_client.get_user_groups("user-grp-1")
            assert res2 == res1

    @pytest.mark.asyncio
    async def test_get_pr_reviewers(self):
        reviewers = [{"id": "r1", "displayName": "Reviewer 1"}]
        res = await ado_client.get_pr_reviewers({"reviewers": reviewers})
        assert res == reviewers
