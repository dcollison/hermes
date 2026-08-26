# Standard
from unittest.mock import MagicMock, patch

# Remote
import pytest
from httpx import ASGITransport, AsyncClient

from hermes_client.cli import _prompt, app, register_with_server
from hermes_client.config import ClientSettings


class TestClientCliEndpoints:
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "Hermes Client"

    @pytest.mark.asyncio
    async def test_notify_endpoint_spawns_thread(self):
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/notify", json={"heading": "Test", "body": "Msg"})

            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            mock_thread.start.assert_called_once()


class TestRegisterWithServer:
    def test_register_success(self):
        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://client:9000/notify",
            ADO_USER_ID="u1",
            ADO_DISPLAY_NAME="Alice",
            CLIENT_NAME="AlicePC",
        )
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": "c1", "status": "ok"}

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = register_with_server(settings, retries=1)

        assert result["id"] == "c1"
        mock_post.assert_called_once()

    def test_register_retry_and_failure(self):
        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://client:9000/notify",
            ADO_USER_ID="u1",
            ADO_DISPLAY_NAME="Alice",
            CLIENT_NAME="AlicePC",
        )
        with (
            patch("httpx.post", side_effect=Exception("Connection refused")),
            patch("time.sleep"),
        ):
            result = register_with_server(settings, retries=2)

        assert result is None


class TestPromptHelper:
    def test_prompt_with_default(self):
        with patch("builtins.input", return_value=""):
            val = _prompt("Enter value", default="my-default")
            assert val == "my-default"

    def test_prompt_with_custom_input(self):
        with patch("builtins.input", return_value="user-input"):
            val = _prompt("Enter value", default="my-default")
            assert val == "user-input"

    def test_prompt_secret(self):
        with patch("getpass.getpass", return_value="secret-pat"):
            val = _prompt("Enter PAT", default="", secret=True)
            assert val == "secret-pat"


class TestStartupNotification:
    def test_cmd_run_spawns_heartbeat_thread_and_notifies(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_run

        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://host:9000/notify",
            ADO_USER_ID="u1",
            ADO_DISPLAY_NAME="Alice",
            CLIENT_NAME="AlicePC",
        )

        with (
            patch("hermes_client.cli._resolve_runtime_settings", return_value=settings),
            patch("threading.Thread") as mock_thread_cls,
            patch("uvicorn.run") as mock_uvicorn_run,
        ):
            mock_thread = MagicMock()
            mock_thread_cls.return_value = mock_thread

            _cmd_run(argparse.Namespace(log_level="info"))

            mock_thread_cls.assert_called_once()
            mock_thread.start.assert_called_once()
            mock_uvicorn_run.assert_called_once()

