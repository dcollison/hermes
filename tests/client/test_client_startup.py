# Standard
from unittest.mock import MagicMock, patch

from hermes_client import startup


class TestStartupTask:
    def test_build_task_xml(self):
        xml = startup._build_task_xml("C:\\Python\\pythonw.exe", "C:\\Scripts\\hermes-client.exe")
        assert "HermesNotificationClient" in startup.TASK_NAME
        assert "<Command>C:\\Python\\pythonw.exe</Command>" in xml
        assert '<Arguments>"C:\\Scripts\\hermes-client.exe" run</Arguments>' in xml

    def test_resolve_paths_fallback(self):
        with (
            patch("pathlib.Path.exists", return_value=False),
            patch("sys.executable", "C:\\Python\\python.exe"),
        ):
            pythonw, script = startup._resolve_paths()
            assert "python.exe" in pythonw

    def test_install_invokes_schtasks(self):
        mock_run = MagicMock()
        with (
            patch("hermes_client.startup._resolve_paths", return_value=("pythonw.exe", "client.exe")),
            patch("hermes_client.startup._run", mock_run),
            patch("builtins.print"),
        ):
            startup.install()

        assert mock_run.call_count == 2
        delete_call, create_call = mock_run.call_args_list
        assert "/Delete" in delete_call[0]
        assert "/Create" in create_call[0]

    def test_remove_invokes_schtasks(self):
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        with (
            patch("hermes_client.startup._run", mock_run),
            patch("builtins.print"),
        ):
            startup.remove()

        mock_run.assert_called_once()
        args = mock_run.call_args[0]
        assert "schtasks" in args
        assert "/Delete" in args

    def test_status_invokes_schtasks(self):
        mock_res = MagicMock()
        mock_res.stdout = "Status: Ready"
        with (
            patch("hermes_client.startup._run", return_value=mock_res),
            patch("builtins.print"),
        ):
            startup.status()
