# Standard
from unittest.mock import patch

from hermes_server.config import _find_env_file


class TestServerConfig:
    def test_find_env_file_cwd(self, tmp_path):
        env_path = tmp_path / ".env.hermes-server"
        env_path.touch()
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            found = _find_env_file()
            assert found == str(env_path)

    def test_find_env_file_appdata(self, tmp_path):
        appdata_dir = tmp_path / "AppData" / "Roaming"
        hermes_dir = appdata_dir / "Hermes"
        hermes_dir.mkdir(parents=True)
        env_file = hermes_dir / ".env.hermes-server"
        env_file.touch()

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path / "other"),
            patch.dict("os.environ", {"APPDATA": str(appdata_dir)}),
        ):
            found = _find_env_file()
            assert found == str(env_file)

    def test_find_env_file_fallback_plain_env(self, tmp_path):
        plain_env = tmp_path / ".env"
        plain_env.touch()

        with (
            patch("pathlib.Path.cwd", return_value=tmp_path),
            patch.dict("os.environ", {}, clear=True),
        ):
            found = _find_env_file()
            assert found == str(plain_env)

    def test_find_env_file_none(self, tmp_path):
        with (
            patch("pathlib.Path.cwd", return_value=tmp_path / "nowhere"),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert _find_env_file() is None
