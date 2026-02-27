# Standard
import base64
from unittest.mock import MagicMock, patch

# Remote
import pytest

from hermes_client.ado import _auth_headers, resolve_callback_url, resolve_identity


class TestAuthHeaders:
    def test_basic_auth_encoding(self):

        headers = _auth_headers("my-secret-pat")
        expected_token = base64.b64encode(b":my-secret-pat").decode()
        assert headers["Authorization"] == f"Basic {expected_token}"

    def test_accept_header_is_json(self):
        from hermes_client.ado import _auth_headers

        headers = _auth_headers("pat")
        assert headers["Accept"] == "application/json"

    def test_empty_pat(self):
        from hermes_client.ado import _auth_headers

        headers = _auth_headers("")
        expected_token = base64.b64encode(b":").decode()
        assert headers["Authorization"] == f"Basic {expected_token}"


class TestResolveIdentity:
    def _mock_response(self, status_code=200, json_body=None):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_body or {}
        if status_code >= 400:
            # Remote
            import httpx

            mock.raise_for_status.side_effect = httpx.HTTPStatusError(
                "error",
                request=MagicMock(),
                response=mock,
            )
        else:
            mock.raise_for_status = MagicMock()
        return mock

    def test_success_returns_user_id_and_display_name(self):

        resp = self._mock_response(
            json_body={
                "authenticatedUser": {
                    "id": "abc-123",
                    "providerDisplayName": "Alice Smith",
                },
            },
        )

        with patch("httpx.get", return_value=resp):
            result = resolve_identity("http://ado/DefaultCollection", "my-pat")

        assert result["user_id"] == "abc-123"
        assert result["display_name"] == "Alice Smith"

    def test_falls_back_to_customDisplayName(self):

        resp = self._mock_response(
            json_body={
                "authenticatedUser": {
                    "id": "abc-123",
                    "customDisplayName": "Alice (Custom)",
                },
            },
        )
        with patch("httpx.get", return_value=resp):
            result = resolve_identity("http://ado/DefaultCollection", "my-pat")
        assert result["display_name"] == "Alice (Custom)"

    def test_url_has_trailing_slash_stripped(self):
        from hermes_client.ado import resolve_identity

        resp = self._mock_response(
            json_body={
                "authenticatedUser": {"id": "abc-123", "providerDisplayName": "Alice"},
            },
        )
        with patch("httpx.get", return_value=resp) as mock_get:
            resolve_identity("http://ado/DefaultCollection/", "my-pat")
            url_called = mock_get.call_args[0][0]
            assert not url_called.startswith("http://ado/DefaultCollection//")

    def test_missing_user_id_raises(self):

        resp = self._mock_response(json_body={"authenticatedUser": {}})
        with patch("httpx.get", return_value=resp):
            with pytest.raises(ValueError, match="no user ID"):
                resolve_identity("http://ado/DefaultCollection", "my-pat")

    def test_401_raises_http_status_error(self):
        # Remote
        import httpx

        from hermes_client.ado import resolve_identity

        resp = self._mock_response(status_code=401)
        with patch("httpx.get", return_value=resp):
            with pytest.raises(httpx.HTTPStatusError):
                resolve_identity("http://ado/DefaultCollection", "bad-pat")

    def test_uses_correct_api_endpoint(self):

        resp = self._mock_response(
            json_body={
                "authenticatedUser": {"id": "u1", "providerDisplayName": "Alice"},
            },
        )
        with patch("httpx.get", return_value=resp) as mock_get:
            resolve_identity("http://ado/DefaultCollection", "my-pat")
            url_called = mock_get.call_args[0][0]
            assert url_called == "http://ado/DefaultCollection/_apis/connectionData"


class TestResolveCallbackUrl:
    def test_returns_http_url_with_port(self):

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.getsockname.return_value = ("192.168.1.42", 12345)

        with patch("socket.socket", return_value=mock_sock):
            result = resolve_callback_url(9000)

        assert result == "http://192.168.1.42:9000/notify"

    def test_falls_back_to_hostname_on_socket_error(self):

        with (
            patch("socket.socket", side_effect=OSError("network unreachable")),
            patch("socket.gethostbyname", return_value="10.0.0.1"),
        ):
            result = resolve_callback_url(9000)

        assert result == "http://10.0.0.1:9000/notify"

    def test_falls_back_to_loopback_when_all_else_fails(self):

        with (
            patch("socket.socket", side_effect=OSError),
            patch("socket.gethostbyname", side_effect=OSError),
        ):
            result = resolve_callback_url(9000)

        assert result == "http://127.0.0.1:9000/notify"

    def test_port_embedded_in_url(self):

        mock_sock = MagicMock()
        mock_sock.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.getsockname.return_value = ("10.0.0.5", 0)

        with patch("socket.socket", return_value=mock_sock):
            result = resolve_callback_url(8888)

        assert ":8888/" in result
