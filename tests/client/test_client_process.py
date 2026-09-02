# Standard
from unittest.mock import MagicMock, patch

from hermes_client import process


class TestVersionParsing:
    def test_parse_version_comparisons(self):
        assert process.parse_version("2.0.0.dev18") > process.parse_version("2.0.0.dev17")
        assert process.parse_version("2.1.0") > process.parse_version("2.0.0")
        assert process.parse_version("2.0.0") == process.parse_version("2.0.0")
        assert process.parse_version("") == (0,)


class TestIsClientRunning:
    def test_running_returns_true_and_data(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "version": "2.0.0"}

        with patch("httpx.get", return_value=mock_resp):
            running, data = process.is_client_running(9000)
            assert running is True
            assert data["version"] == "2.0.0"

    def test_not_running_returns_false(self):
        with patch("httpx.get", side_effect=Exception("Connection refused")):
            running, data = process.is_client_running(9000)
            assert running is False
            assert data is None


class TestStopClient:
    def test_stop_when_already_stopped(self):
        with patch("hermes_client.process.is_client_running", return_value=(False, None)):
            assert process.stop_client(9000) is True

    def test_stop_sends_shutdown_and_waits(self):
        # First call running, second call stopped
        with (
            patch(
                "hermes_client.process.is_client_running",
                side_effect=[(True, {"pid": 123}), (False, None)],
            ),
            patch("httpx.post") as mock_post,
        ):
            assert process.stop_client(9000) is True
            mock_post.assert_called_once()


class TestStartClient:
    def test_start_client_launches_detached_and_verifies(self):
        with (
            patch("hermes_client.startup._resolve_paths", return_value=("pythonw.exe", "client.exe")),
            patch("subprocess.Popen") as mock_popen,
            patch("hermes_client.process.is_client_running", return_value=(True, {"pid": 456})),
        ):
            success, info = process.start_client(wait_seconds=1.0)
            assert success is True
            assert info["pid"] == 456
            mock_popen.assert_called_once()


class TestRestartClient:
    def test_restart_client_calls_stop_then_start(self):
        with (
            patch("hermes_client.process.stop_client", return_value=True) as mock_stop,
            patch("hermes_client.process.start_client", return_value=(True, {"pid": 789})) as mock_start,
        ):
            success, info = process.restart_client()
            assert success is True
            assert info["pid"] == 789
            mock_stop.assert_called_once()
            mock_start.assert_called_once()


class TestDetectUpgradeCommand:
    def test_detect_command_with_uv_in_venv(self):
        with (
            patch("shutil.which", return_value="C:\\bin\\uv.exe"),
            patch("sys.executable", "D:\\repo\\.venv\\Scripts\\python.exe"),
        ):
            cmd = process._detect_upgrade_command("hermes")
            assert cmd[0] == "uv"
            assert cmd[1] == "pip"
            assert cmd[2] == "install"
            assert "--python" in cmd
            assert "D:\\repo\\.venv\\Scripts\\python.exe" in cmd
            assert "--upgrade" in cmd
            assert "hermes" in cmd

    def test_detect_command_with_uv_tool(self):
        with (
            patch("shutil.which", return_value="C:\\bin\\uv.exe"),
            patch("sys.executable", "C:\\Users\\Dale\\AppData\\Roaming\\uv\\tools\\hermes\\Scripts\\python.exe"),
        ):
            cmd = process._detect_upgrade_command("hermes")
            assert cmd == ["uv", "tool", "upgrade", "hermes"]

    def test_detect_command_with_pip(self):
        with (
            patch("shutil.which", return_value=None),
            patch("sys.executable", "C:\\Python311\\python.exe"),
        ):
            cmd = process._detect_upgrade_command("hermes")
            assert cmd == ["C:\\Python311\\python.exe", "-m", "pip", "install", "--upgrade", "hermes"]


class TestUpgradeClient:
    def test_upgrade_client_with_uv(self):
        mock_run = MagicMock()
        mock_run.returncode = 0

        with (
            patch("hermes_client.process.is_client_running", side_effect=[(True, {}), (False, None), (True, {"pid": 100})]),
            patch("hermes_client.process.stop_client", return_value=True),
            patch("shutil.which", return_value="C:\\bin\\uv.exe"),
            patch("subprocess.run", return_value=mock_run) as mock_sub_run,
            patch("hermes_client.process.start_client", return_value=(True, {"pid": 100})),
            patch("hermes_client.process.show_notification") as mock_toast,
        ):
            res = process.upgrade_client(package_name="hermes", restart=True)
            assert res is True
            mock_sub_run.assert_called_once()
            cmd = mock_sub_run.call_args[0][0]
            assert "uv" in cmd[0]
            assert "install" in cmd
            assert "--upgrade" in cmd
            mock_toast.assert_called_once()

    def test_upgrade_client_with_pip(self):
        mock_run = MagicMock()
        mock_run.returncode = 0

        with (
            patch("hermes_client.process.is_client_running", return_value=(False, None)),
            patch("shutil.which", return_value=None),
            patch("subprocess.run", return_value=mock_run) as mock_sub_run,
            patch("hermes_client.process.start_client", return_value=(True, {"pid": 100})),
        ):
            res = process.upgrade_client(package_name="hermes", restart=True)
            assert res is True
            mock_sub_run.assert_called_once()
            cmd = mock_sub_run.call_args[0][0]
            assert "pip" in cmd
            assert "--upgrade" in cmd
