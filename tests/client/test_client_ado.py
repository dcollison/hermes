# Standard
import base64
from unittest.mock import MagicMock, patch

# Remote
import pytest

from hermes_client.ado import resolve_callback_url, resolve_identity


class TestResolveIdentity:
    def _mock_connection(self, user_id="abc-123", display_name="Alice Smith", error=None):
        mock_profile = MagicMock()
        mock_profile.id = user_id
        mock_profile.display_name = display_name

        mock_profile_client = MagicMock()
        if error:
            mock_profile_client.get_profile.side_effect = error
        else:
            mock_profile_client.get_profile.return_value = mock_profile

        mock_conn = MagicMock()
        mock_conn.clients.get_profile_client.return_value = mock_profile_client
        return mock_conn

    def test_success_returns_user_id_and_display_name(self):
        mock_conn = self._mock_connection(user_id="abc-123", display_name="Alice Smith")
        with patch("hermes_client.ado.Connection", return_value=mock_conn):
            result = resolve_identity("http://ado/DefaultCollection", "my-pat")

        assert result["user_id"] == "abc-123"
        assert result["display_name"] == "Alice Smith"

    def test_url_has_trailing_slash_stripped(self):
        mock_conn = self._mock_connection(user_id="abc-123", display_name="Alice")
        with patch("hermes_client.ado.Connection", return_value=mock_conn) as conn_cls:
            resolve_identity("http://ado/DefaultCollection/", "my-pat")
            base_url_called = conn_cls.call_args[1]["base_url"]
            assert base_url_called == "http://ado/DefaultCollection"

    def test_missing_user_id_raises(self):
        mock_conn = self._mock_connection(user_id="", display_name="Alice")
        with patch("hermes_client.ado.Connection", return_value=mock_conn):
            with pytest.raises(ValueError, match="no user ID"):
                resolve_identity("http://ado/DefaultCollection", "my-pat")

    def test_api_error_raises_exception(self):
        mock_conn = self._mock_connection(error=Exception("Unauthorized"))
        with patch("hermes_client.ado.Connection", return_value=mock_conn):
            with pytest.raises(Exception, match="Unauthorized"):
                resolve_identity("http://ado/DefaultCollection", "bad-pat")


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
