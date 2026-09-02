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
            AZDO_USER_ID="u1",
            AZDO_DISPLAY_NAME="Dale",
            CLIENT_NAME="DalePC",
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
            AZDO_USER_ID="u1",
            AZDO_DISPLAY_NAME="Dale",
            CLIENT_NAME="DalePC",
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

    def test_prompt_secret_tty(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("getpass.getpass", return_value="secret-pat"),
        ):
            val = _prompt("Enter PAT", default="", secret=True)
            assert val == "secret-pat"

    def test_prompt_secret_non_tty_git_bash_fallback(self):
        with (
            patch("sys.stdin.isatty", return_value=False),
            patch("builtins.input", return_value="secret-pat-from-pipe"),
        ):
            val = _prompt("Enter PAT", default="", secret=True)
            assert val == "secret-pat-from-pipe"

    def test_prompt_secret_getpass_error_fallback(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("getpass.getpass", side_effect=OSError("Not a console")),
            patch("builtins.input", return_value="secret-fallback"),
        ):
            val = _prompt("Enter PAT", default="", secret=True)
            assert val == "secret-fallback"


class TestStartupNotification:
    def test_cmd_run_spawns_heartbeat_thread_and_notifies(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_run

        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://host:9000/notify",
            AZDO_USER_ID="u1",
            AZDO_DISPLAY_NAME="Dale",
            CLIENT_NAME="DalePC",
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

    def test_resolve_runtime_settings_log_file(self):
        # Standard
        import argparse

        from hermes_client.cli import _resolve_runtime_settings

        args = argparse.Namespace(
            server=None,
            name=None,
            host=None,
            port=None,
            callback_url="http://localhost:9000/notify",
            ado_user_id="u1",
            ado_display_name="User",
            log_file="C:\\custom\\client.log",
        )
        settings = _resolve_runtime_settings(args)
        assert settings.LOG_FILE == "C:\\custom\\client.log"

    def test_cmd_run_with_custom_log_file(self, tmp_path):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_run

        log_file = str(tmp_path / "run_test.log")
        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://host:9000/notify",
            AZDO_USER_ID="u1",
            AZDO_DISPLAY_NAME="Dale",
            CLIENT_NAME="DalePC",
            LOG_FILE=log_file,
        )

        with (
            patch("hermes_client.cli._resolve_runtime_settings", return_value=settings),
            patch("threading.Thread"),
            patch("uvicorn.run"),
        ):
            _cmd_run(argparse.Namespace(log_level="info"))

    def test_main_handles_none_streams(self):
        # Standard
        import sys

        from hermes_client.cli import main

        orig_stdin = sys.stdin
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        try:
            sys.stdin = None
            sys.stdout = None
            sys.stderr = None

            with (
                patch("sys.argv", ["hermes-client", "startup", "status"]),
                patch("hermes_client.startup.status") as mock_status,
            ):
                main()
                mock_status.assert_called_once()
        finally:
            if sys.stdout and sys.stdout is not orig_stdout:
                sys.stdout.close()
            if sys.stderr and sys.stderr is not orig_stderr:
                sys.stderr.close()
            if sys.stdin and sys.stdin is not orig_stdin:
                sys.stdin.close()
            sys.stdin = orig_stdin
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr


