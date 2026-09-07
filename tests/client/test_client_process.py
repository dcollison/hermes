# Standard
from pathlib import Path
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

    def test_upgrade_client_failure_restores_executables(self):
        mock_run = MagicMock()
        mock_run.returncode = 1

        with (
            patch("hermes_client.process.is_client_running", return_value=(False, None)),
            patch(
                "hermes_client.process.prepare_executables_for_upgrade",
                return_value=[(Path("a.exe"), Path("a.exe.old"))],
            ) as mock_prep,
            patch("hermes_client.process.restore_executables") as mock_restore,
            patch("subprocess.run", return_value=mock_run),
        ):
            res = process.upgrade_client(package_name="hermes", restart=False)
            assert res is False
            mock_prep.assert_called_once()
            mock_restore.assert_called_once()

    def test_upgrade_client_success_schedules_cleanup(self):
        mock_run = MagicMock()
        mock_run.returncode = 0

        with (
            patch("hermes_client.process.is_client_running", return_value=(False, None)),
            patch(
                "hermes_client.process.prepare_executables_for_upgrade",
                return_value=[(Path("a.exe"), Path("a.exe.old"))],
            ) as mock_prep,
            patch("hermes_client.process.schedule_old_executables_cleanup") as mock_sched,
            patch("subprocess.run", return_value=mock_run),
        ):
            res = process.upgrade_client(package_name="hermes", restart=False)
            assert res is True
            mock_prep.assert_called_once()
            mock_sched.assert_called_once()


class TestIsFileLocked:
    def test_nonexistent_file_returns_false(self, tmp_path):
        assert process.is_file_locked(tmp_path / "nonexistent.exe") is False

    def test_unlocked_file_returns_false(self, tmp_path):
        f = tmp_path / "app.exe"
        f.write_bytes(b"content")
        assert process.is_file_locked(f) is False

    def test_locked_file_returns_true(self, tmp_path):
        f = tmp_path / "app.exe"
        f.write_bytes(b"content")
        with patch("builtins.open", side_effect=PermissionError("Locked")):
            assert process.is_file_locked(f) is True


class TestFindHermesExecutables:
    def test_finds_executables(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        client_exe = bin_dir / "hermes-client.exe"
        client_exe.write_bytes(b"")
        server_exe = bin_dir / "hermes-server.exe"
        server_exe.write_bytes(b"")

        with (
            patch("sys.argv", [str(client_exe)]),
            patch("shutil.which", return_value=None),
            patch("sys.executable", str(tmp_path / "python.exe")),
        ):
            found = process.find_hermes_executables()
            assert client_exe in found
            assert server_exe in found


class TestPrepareExecutablesForUpgrade:
    def test_non_windows_returns_empty(self):
        with patch("sys.platform", "linux"):
            assert process.prepare_executables_for_upgrade() == []

    def test_windows_renames_current_executable(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        client_exe = bin_dir / "hermes-client.exe"
        client_exe.write_bytes(b"exe content")

        with (
            patch("sys.platform", "win32"),
            patch("hermes_client.process.find_hermes_executables", return_value=[client_exe]),
            patch("hermes_client.process._is_current_executable", return_value=True),
        ):
            renamed = process.prepare_executables_for_upgrade()
            assert len(renamed) == 1
            orig, old = renamed[0]
            assert orig == client_exe
            assert not orig.exists()
            assert old.exists()
            assert ".old" in old.name

    def test_windows_renames_locked_executable(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        server_exe = bin_dir / "hermes-server.exe"
        server_exe.write_bytes(b"server content")

        with (
            patch("sys.platform", "win32"),
            patch("hermes_client.process.find_hermes_executables", return_value=[server_exe]),
            patch("hermes_client.process._is_current_executable", return_value=False),
            patch("hermes_client.process.is_file_locked", return_value=True),
        ):
            renamed = process.prepare_executables_for_upgrade()
            assert len(renamed) == 1
            orig, old = renamed[0]
            assert orig == server_exe
            assert not orig.exists()
            assert old.exists()


class TestRestoreExecutables:
    def test_restore_renamed_file_when_original_missing(self, tmp_path):
        orig = tmp_path / "hermes-client.exe"
        old = tmp_path / "hermes-client.exe.old"
        old.write_bytes(b"saved content")

        process.restore_executables([(orig, old)])
        assert orig.exists()
        assert not old.exists()
        assert orig.read_bytes() == b"saved content"

    def test_restore_does_not_overwrite_if_original_exists(self, tmp_path):
        orig = tmp_path / "hermes-client.exe"
        orig.write_bytes(b"new content")
        old = tmp_path / "hermes-client.exe.old"
        old.write_bytes(b"old content")

        process.restore_executables([(orig, old)])
        assert orig.read_bytes() == b"new content"
        assert old.exists()


class TestScheduleOldExecutablesCleanup:
    def test_immediate_unlink_if_not_locked(self, tmp_path):
        orig = tmp_path / "hermes-client.exe"
        old = tmp_path / "hermes-client.exe.old"
        old.write_bytes(b"old content")

        process.schedule_old_executables_cleanup([(orig, old)])
        assert not old.exists()

    def test_spawns_detached_process_when_locked_on_windows(self, tmp_path):
        orig = tmp_path / "hermes-client.exe"
        old = tmp_path / "hermes-client.exe.old"
        old.write_bytes(b"old content")

        with (
            patch("sys.platform", "win32"),
            patch.object(Path, "unlink", side_effect=PermissionError("Locked")),
            patch("subprocess.Popen") as mock_popen,
        ):
            process.schedule_old_executables_cleanup([(orig, old)])
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "del /f /q" in cmd
            assert str(old) in cmd


class TestCleanupOldExecutables:
    def test_cleanup_removes_old_files(self, tmp_path):
        old1 = tmp_path / "hermes-client.exe.1234.old"
        old1.write_bytes(b"")
        old2 = tmp_path / "hermes-server.exe.old"
        old2.write_bytes(b"")
        keep = tmp_path / "hermes-client.exe"
        keep.write_bytes(b"")

        process.cleanup_old_executables([tmp_path])
        assert not old1.exists()
        assert not old2.exists()
        assert keep.exists()
