# Standard
import sys
from unittest.mock import patch

from hermes_client.config import (
    ClientSettings,
    _ensure_std_streams,
    _find_env_file,
    default_env_file_path,
    default_log_file_path,
)


class TestClientConfig:
    def test_find_env_file_cwd(self, tmp_path):
        env_path = tmp_path / ".env.hermes-client"
        env_path.touch()
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            found = _find_env_file()
            assert found == str(env_path)

    def test_find_env_file_home(self, tmp_path):
        home_path = tmp_path / ".env.hermes-client"
        home_path.touch()
        with (
            patch("pathlib.Path.cwd", return_value=tmp_path / "subdir"),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            found = _find_env_file()
            assert found == str(home_path)

    def test_find_env_file_appdata(self, tmp_path):
        appdata_dir = tmp_path / "AppData" / "Roaming"
        hermes_dir = appdata_dir / "Hermes"
        hermes_dir.mkdir(parents=True)
        env_file = hermes_dir / ".env.hermes-client"
        env_file.touch()

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path / "other"),
            patch("pathlib.Path.home", return_value=tmp_path / "home"),
            patch.dict("os.environ", {"APPDATA": str(appdata_dir)}),
        ):
            found = _find_env_file()
            assert found == str(env_file)

    def test_find_env_file_none(self, tmp_path):
        with (
            patch("pathlib.Path.cwd", return_value=tmp_path / "1"),
            patch("pathlib.Path.home", return_value=tmp_path / "2"),
            patch.dict("os.environ", {"APPDATA": str(tmp_path / "3")}),
        ):
            assert _find_env_file() is None

    def test_default_env_file_path_appdata(self, tmp_path):
        appdata_dir = tmp_path / "AppData"
        with patch.dict("os.environ", {"APPDATA": str(appdata_dir)}):
            p = default_env_file_path()
            assert str(p).endswith(".env.hermes-client")
            assert "Hermes" in str(p)

    def test_default_log_file_path_appdata(self, tmp_path):
        appdata_dir = tmp_path / "AppData"
        with patch.dict("os.environ", {"APPDATA": str(appdata_dir)}):
            p = default_log_file_path()
            assert str(p).endswith("hermes-client.log")
            assert "Hermes" in str(p)

    def test_default_log_file_path_home(self, tmp_path):
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            p = default_log_file_path()
            assert str(p).endswith("hermes-client.log")
            assert ".hermes" in str(p)

    def test_ensure_std_streams_when_none(self, tmp_path):
        orig_stdin = sys.stdin
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        target_log = tmp_path / "custom_client.log"

        try:
            sys.stdin = None
            sys.stdout = None
            sys.stderr = None

            _ensure_std_streams(target_log)

            assert sys.stdin is not None
            assert sys.stdout is not None
            assert sys.stderr is not None

            sys.stdout.write("stdout test\n")
            sys.stdout.flush()
            sys.stderr.write("stderr test\n")
            sys.stderr.flush()

            content = target_log.read_text(encoding="utf-8")
            assert "stdout test" in content
            assert "stderr test" in content
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

    def test_ensure_std_streams_devnull(self):
        orig_stdin = sys.stdin
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        try:
            sys.stdin = None
            sys.stdout = None
            sys.stderr = None

            _ensure_std_streams("devnull")

            assert sys.stdin is not None
            assert sys.stdout is not None
            assert sys.stderr is not None

            sys.stdout.write("devnull stdout\n")
            sys.stderr.write("devnull stderr\n")
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

    def test_is_fully_configured(self):
        settings = ClientSettings(
            SERVER_URL="http://localhost:8000",
            CALLBACK_URL="http://localhost:9000/notify",
            ADO_USER_ID="user-123",
            ADO_DISPLAY_NAME="Alice",
        )
        assert settings.is_fully_configured() is True

        incomplete = ClientSettings(
            SERVER_URL="",
            CALLBACK_URL="",
            ADO_USER_ID="",
            ADO_DISPLAY_NAME="",
        )
        assert incomplete.is_fully_configured() is False

    def test_write_env_file(self, tmp_path):
        target = tmp_path / "test_env" / ".env.hermes-client"
        settings = ClientSettings(
            SERVER_URL="http://srv:8000",
            CALLBACK_URL="http://host:9000/notify",
            ADO_USER_ID="u1",
            ADO_DISPLAY_NAME="Bob",
            CLIENT_NAME="BobPC",
            LOG_FILE="C:\\logs\\hermes.log",
        )
        written_path = settings.write_env_file(target)
        assert written_path == target
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "SERVER_URL=http://srv:8000" in content
        assert "ADO_USER_ID=u1" in content
        assert "ADO_DISPLAY_NAME=Bob" in content
        assert "LOG_FILE=C:\\logs\\hermes.log" in content

