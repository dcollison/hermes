# Standard
import json
import os
import socket
import sys
from pathlib import Path

# Remote
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def _find_env_file() -> str | None:
    """Search for .env.hermes-client in standard configuration locations.

    Search order:
      1. Current working directory
      2. User home directory
      3. %APPDATA%/Hermes (Windows)

    :returns: The first matching path found, or None.
    """
    candidates = [
        Path.cwd() / ".env.hermes-client",
        Path.home() / ".env.hermes-client",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Hermes" / ".env.hermes-client")

    for path in candidates:
        if path.exists():
            return str(path)
    return None


def default_env_file_path() -> Path:
    """Return the preferred path for writing a new .env.hermes-client file.

    Chooses %APPDATA%/Hermes/ on Windows, home directory otherwise.

    :returns: The Path to the preferred .env.hermes-client location.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "Hermes"
        d.mkdir(parents=True, exist_ok=True)
        return d / ".env.hermes-client"
    return Path.home() / ".env.hermes-client"


def default_log_file_path() -> Path:
    """Return the preferred path for the hermes-client log file.

    Chooses %APPDATA%/Hermes/hermes-client.log on Windows, ~/.hermes/hermes-client.log otherwise.

    :returns: The Path to the preferred hermes-client log file location.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "Hermes"
        d.mkdir(parents=True, exist_ok=True)
        return d / "hermes-client.log"
    d = Path.home() / ".hermes"
    d.mkdir(parents=True, exist_ok=True)
    return d / "hermes-client.log"


def _ensure_std_streams(log_file: Path | str | None = None) -> None:
    """Ensure standard input/output/error streams are valid open file-like objects.

    When running under pythonw.exe or in a GUI context with no attached console,
    CPython sets sys.stdin, sys.stdout, and sys.stderr to None. This causes crashes
    in argparse, logging, and uvicorn. This function safely re-assigns any None stream
    to an open file stream (default log file, explicit log file, or os.devnull) and
    reconfigures UTF-8 encoding where supported.

    :param log_file: Optional explicit file path to redirect stdout/stderr to.
    """
    if sys.stdin is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except Exception:
            pass

    if sys.stdout is None or sys.stderr is None:
        target_path: Path | str
        if log_file and str(log_file).lower() == "devnull":
            target_path = os.devnull
        elif log_file:
            target_path = log_file
        else:
            target_path = default_log_file_path()

        stream = None
        if target_path != os.devnull:
            try:
                p = Path(target_path).expanduser().resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                stream = open(p, "a", encoding="utf-8")
            except Exception:
                stream = None

        if stream is None:
            try:
                stream = open(os.devnull, "w", encoding="utf-8")
            except Exception:
                pass

        if sys.stdout is None and stream is not None:
            sys.stdout = stream
        if sys.stderr is None and stream is not None:
            sys.stderr = stream

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class ClientSettings(BaseSettings):
    SERVER_URL: str = "http://localhost:8000"
    CLIENT_NAME: str = socket.gethostname()
    LOCAL_HOST: str = "0.0.0.0"
    LOCAL_PORT: int = 9000

    # Resolved at configure-time and persisted to .env.hermes-client.
    # Left blank so the startup logic knows to prompt/resolve them if missing.
    CALLBACK_URL: str = ""
    AZDO_USER_ID: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_USER_ID", "ADO_USER_ID"),
    )
    AZDO_DISPLAY_NAME: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_DISPLAY_NAME", "ADO_DISPLAY_NAME"),
    )

    # AzDO credentials — used once during `configure` to resolve identity.
    # Stored in the env file so `run` can re-resolve on demand if needed.
    AZDO_ORGANIZATION_URL: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_ORGANIZATION_URL", "ADO_ORGANIZATION_URL"),
    )
    AZDO_PAT: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_PAT", "ADO_PAT"),
    )

    LOG_FILE: str = ""

    SUBSCRIPTIONS: list[str] = ["pr", "workitem", "pipeline", "manual"]

    model_config = {
        "env_file": _find_env_file(),
        "env_file_encoding": "utf-8",
    }

    # Backward-compatible property aliases
    @property
    def ADO_USER_ID(self) -> str:
        return self.AZDO_USER_ID

    @ADO_USER_ID.setter
    def ADO_USER_ID(self, value: str) -> None:
        self.AZDO_USER_ID = value

    @ADO_USER_ID.deleter
    def ADO_USER_ID(self) -> None:
        self.AZDO_USER_ID = ""

    @property
    def ADO_DISPLAY_NAME(self) -> str:
        return self.AZDO_DISPLAY_NAME

    @ADO_DISPLAY_NAME.setter
    def ADO_DISPLAY_NAME(self, value: str) -> None:
        self.AZDO_DISPLAY_NAME = value

    @ADO_DISPLAY_NAME.deleter
    def ADO_DISPLAY_NAME(self) -> None:
        self.AZDO_DISPLAY_NAME = ""

    @property
    def ADO_ORGANIZATION_URL(self) -> str:
        return self.AZDO_ORGANIZATION_URL

    @ADO_ORGANIZATION_URL.setter
    def ADO_ORGANIZATION_URL(self, value: str) -> None:
        self.AZDO_ORGANIZATION_URL = value

    @ADO_ORGANIZATION_URL.deleter
    def ADO_ORGANIZATION_URL(self) -> None:
        self.AZDO_ORGANIZATION_URL = ""

    @property
    def ADO_PAT(self) -> str:
        return self.AZDO_PAT

    @ADO_PAT.setter
    def ADO_PAT(self, value: str) -> None:
        self.AZDO_PAT = value

    @ADO_PAT.deleter
    def ADO_PAT(self) -> None:
        self.AZDO_PAT = ""

    def is_fully_configured(self) -> bool:
        """Check whether all required runtime settings are populated.

        :returns: True if SERVER_URL, CALLBACK_URL, AZDO_USER_ID, and AZDO_DISPLAY_NAME are present.
        """
        return bool(
            self.SERVER_URL
            and self.CALLBACK_URL
            and self.AZDO_USER_ID
            and self.AZDO_DISPLAY_NAME,
        )

    def write_env_file(self, path: Path | None = None) -> Path:
        """Write current settings to an .env.hermes-client file.

        Creates the file (and parent directories) if it doesn't exist.

        :param path: Optional target path; defaults to default_env_file_path().
        :returns: The Path written to.
        """
        target = path or default_env_file_path()
        target.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            "# Hermes Client Configuration — auto-generated by `hermes-client configure`",
            "# Edit manually or re-run `hermes-client configure` to update.",
            "",
            f"SERVER_URL={self.SERVER_URL}",
            f"CLIENT_NAME={self.CLIENT_NAME}",
            f"LOCAL_HOST={self.LOCAL_HOST}",
            f"LOCAL_PORT={self.LOCAL_PORT}",
            f"CALLBACK_URL={self.CALLBACK_URL}",
            f"LOG_FILE={self.LOG_FILE}",
            "",
            "# AzDO identity (resolved from PAT by hermes-client configure)",
            f"AZDO_ORGANIZATION_URL={self.AZDO_ORGANIZATION_URL}",
            f"AZDO_PAT={self.AZDO_PAT}",
            f"AZDO_USER_ID={self.AZDO_USER_ID}",
            f"AZDO_DISPLAY_NAME={self.AZDO_DISPLAY_NAME}",
            "",
            f"SUBSCRIPTIONS={json.dumps(self.SUBSCRIPTIONS)}",
        ]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target
