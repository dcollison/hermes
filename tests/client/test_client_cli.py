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


class TestClientEndpoints:
    @pytest.mark.asyncio
    async def test_health_and_status(self):
        # Remote
        from httpx import ASGITransport, AsyncClient

        from hermes_client.cli import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "version" in data
            assert "pid" in data

            status_resp = await client.get("/status")
            assert status_resp.status_code == 200

    @pytest.mark.asyncio
    async def test_shutdown_endpoint(self):
        # Remote
        from httpx import ASGITransport, AsyncClient

        from hermes_client.cli import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("threading.Thread") as mock_thread_cls:
                resp = await client.post("/shutdown")
                assert resp.status_code == 200
                assert resp.json()["status"] == "shutting_down"
                mock_thread_cls.assert_called_once()


class TestProcessCommands:
    def test_cmd_start_when_not_running(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_start

        with (
            patch("hermes_client.process.is_client_running", return_value=(False, None)),
            patch("hermes_client.process.start_client", return_value=(True, {"pid": 111})),
            patch("builtins.print") as mock_print,
        ):
            _cmd_start(argparse.Namespace())
            assert any("111" in str(c) for c in mock_print.call_args_list)

    def test_cmd_start_when_already_running(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_start

        with (
            patch("hermes_client.process.is_client_running", return_value=(True, {"pid": 222})),
            patch("builtins.print") as mock_print,
        ):
            _cmd_start(argparse.Namespace())
            assert any("already running" in str(c) for c in mock_print.call_args_list)

    def test_cmd_stop(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_stop

        with (
            patch("hermes_client.process.is_client_running", return_value=(True, {"pid": 333})),
            patch("hermes_client.process.stop_client", return_value=True),
            patch("builtins.print") as mock_print,
        ):
            _cmd_stop(argparse.Namespace())
            assert any("stopped" in str(c) for c in mock_print.call_args_list)

    def test_cmd_restart(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_restart

        with (
            patch("hermes_client.process.restart_client", return_value=(True, {"pid": 444})),
            patch("builtins.print") as mock_print,
        ):
            _cmd_restart(argparse.Namespace())
            assert any("restarted" in str(c) for c in mock_print.call_args_list)

    def test_cmd_status(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_status

        with (
            patch("hermes_client.process.is_client_running", return_value=(True, {"pid": 555, "version": "2.0.0"})),
            patch("hermes_client.startup.status"),
            patch("builtins.print") as mock_print,
        ):
            _cmd_status(argparse.Namespace())
            assert any("RUNNING" in str(c) for c in mock_print.call_args_list)

    def test_cmd_upgrade(self):
        # Standard
        import argparse

        from hermes_client.cli import _cmd_upgrade

        with (
            patch("hermes_client.process.upgrade_client", return_value=True) as mock_up,
            patch("builtins.print"),
        ):
            _cmd_upgrade(argparse.Namespace(package="hermes", no_restart=False))
            mock_up.assert_called_once_with(package_name="hermes", restart=True, extra_args=None)


class TestRegisterWithServerUpdateCheck:
    def test_notifies_when_server_version_is_newer(self):
        from hermes_client.cli import register_with_server

        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://host:9000/notify",
            AZDO_USER_ID="u1",
            AZDO_DISPLAY_NAME="Dale",
            CLIENT_NAME="DalePC",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"id": "1", "server_version": "99.0.0"}

        with (
            patch("httpx.post", return_value=mock_resp),
            patch("hermes_client.cli.show_notification") as mock_toast,
        ):
            register_with_server(settings)
            mock_toast.assert_called_once()
            notif = mock_toast.call_args[0][0]
            assert "Update Available" in notif["heading"]



