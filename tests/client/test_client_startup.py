# Standard
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Remote
import pytest

from hermes_client import startup


class TestStartupShortcut:
    def test_get_startup_dir(self):
        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\Dale\\AppData\\Roaming"}):
            dir_path = startup._get_startup_dir()
            assert "Startup" in str(dir_path)
            assert "Dale" in str(dir_path)

    def test_get_shortcut_path(self):
        with patch.dict("os.environ", {"APPDATA": "C:\\Users\\Dale\\AppData\\Roaming"}):
            path = startup._get_shortcut_path()
            assert path.name == startup.SHORTCUT_NAME

    def test_ps_escape(self):
        assert startup._ps_escape("foo'bar") == "'foo''bar'"
        assert startup._ps_escape("simple") == "'simple'"

    def test_resolve_paths_fallback(self):
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("sys.executable", "C:\\Python\\python.exe"),
            patch("shutil.which", return_value=None),
        ):
            pythonw, script = startup._resolve_paths()
            assert "python.exe" in pythonw
            if sys.platform == "win32":
                assert script.endswith(".exe")

    def test_resolve_paths_windows_appends_exe(self):
        with (
            patch("sys.platform", "win32"),
            patch("sys.argv", ["C:\\Python\\Scripts\\hermes-client"]),
            patch("sys.executable", "C:\\Python\\python.exe"),
            patch.object(Path, "exists", autospec=True, side_effect=lambda p: str(p).endswith(".exe")),
        ):
            pythonw, script = startup._resolve_paths()
            assert script == "C:\\Python\\Scripts\\hermes-client.exe"

    def test_resolve_paths_windows_finds_which_exe(self):
        with (
            patch("sys.platform", "win32"),
            patch("sys.argv", ["C:\\Hermes\\hermes_client\\cli.py"]),
            patch("sys.executable", "C:\\Python\\python.exe"),
            patch("pathlib.Path.exists", return_value=False),
            patch("shutil.which", return_value="C:\\Python\\Scripts\\hermes-client.exe"),
        ):
            pythonw, script = startup._resolve_paths()
            assert script == "C:\\Python\\Scripts\\hermes-client.exe"

    def test_resolve_paths_windows_already_exe(self):
        with (
            patch("sys.platform", "win32"),
            patch("sys.argv", ["C:\\Python\\Scripts\\hermes-client.exe"]),
            patch("sys.executable", "C:\\Python\\python.exe"),
            patch("pathlib.Path.exists", return_value=True),
        ):
            pythonw, script = startup._resolve_paths()
            assert script == "C:\\Python\\Scripts\\hermes-client.exe"

    def test_create_shortcut_invokes_powershell(self):
        mock_run = MagicMock()
        with (
            patch("subprocess.run", mock_run),
            patch("pathlib.Path.mkdir"),
        ):
            startup._create_shortcut(
                Path("C:\\Startup\\Hermes Client.lnk"),
                "C:\\Python\\pythonw.exe",
                '"C:\\Scripts\\hermes-client.exe" run',
                "C:\\Users\\Dale",
                "Hermes",
            )

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "powershell" in args
        assert "CreateShortcut" in args[4]

    def test_read_shortcut_not_found(self):
        with patch("pathlib.Path.exists", return_value=False):
            assert startup._read_shortcut(Path("C:\\nonexistent.lnk")) is None

    def test_read_shortcut_success(self):
        mock_res = MagicMock()
        mock_res.stdout = "C:\\pythonw.exe\n\"client.exe\" run\nC:\\Users\\Dale\nHermes\n"
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("subprocess.run", return_value=mock_res),
        ):
            info = startup._read_shortcut(Path("C:\\Hermes.lnk"))
            assert info is not None
            assert info["target_path"] == "C:\\pythonw.exe"
            assert info["arguments"] == '"client.exe" run'
            assert info["working_directory"] == "C:\\Users\\Dale"

    def test_install_success(self):
        mock_create = MagicMock()
        mock_cleanup = MagicMock()
        with (
            patch("sys.platform", "win32"),
            patch("hermes_client.startup._resolve_paths", return_value=("pythonw.exe", "client.exe")),
            patch("hermes_client.startup._create_shortcut", mock_create),
            patch("hermes_client.startup._cleanup_legacy_task", mock_cleanup),
            patch("builtins.print") as mock_print,
        ):
            startup.install()

        mock_create.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_print.assert_any_call("✓ Startup shortcut installed.")

    def test_install_non_windows(self):
        with (
            patch("sys.platform", "linux"),
            patch("builtins.print") as mock_print,
            pytest.raises(SystemExit) as exc_info,
        ):
            startup.install()

        assert exc_info.value.code == 1
        mock_print.assert_called_with("Startup integration is only supported on Windows.")

    def test_remove_success(self):
        mock_unlink = MagicMock()
        mock_cleanup = MagicMock()
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.unlink", mock_unlink),
            patch("hermes_client.startup._cleanup_legacy_task", mock_cleanup),
            patch("builtins.print") as mock_print,
        ):
            startup.remove()

        mock_unlink.assert_called_once()
        mock_cleanup.assert_called_once()
        assert any("removed" in str(c) for c in mock_print.call_args_list)

    def test_remove_not_installed(self):
        mock_cleanup = MagicMock()
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=False),
            patch("hermes_client.startup._cleanup_legacy_task", mock_cleanup),
            patch("builtins.print") as mock_print,
        ):
            startup.remove()

        mock_cleanup.assert_called_once()
        mock_print.assert_called_with("Startup shortcut was not found — nothing to remove.")

    def test_status_not_installed(self):
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=False),
            patch("builtins.print") as mock_print,
        ):
            startup.status()

        mock_print.assert_called_with("Startup shortcut is NOT installed.")

    def test_status_installed(self):
        with (
            patch("sys.platform", "win32"),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "hermes_client.startup._read_shortcut",
                return_value={
                    "target_path": "C:\\pythonw.exe",
                    "arguments": "client.exe run",
                    "working_directory": "C:\\Users\\Dale",
                },
            ),
            patch("builtins.print") as mock_print,
        ):
            startup.status()

        mock_print.assert_any_call("Startup shortcut is installed.\n")
