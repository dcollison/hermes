"""Hermes Server Configuration"""

# Standard
import os
from pathlib import Path

# Remote
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


def _find_env_file() -> str | None:
    """Search for .env.hermes-server in standard configuration locations.

    Search order:
      1. Current working directory
      2. The directory containing this file (repo root when running from source)
      3. %APPDATA%/Hermes (Windows)
      4. Fallback: plain .env in the current working directory

    :returns: The first matching path found, or None.
    """
    candidates = [
        Path.cwd() / ".env.hermes-server",
        Path(__file__).parent.parent / ".env.hermes-server",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Hermes" / ".env.hermes-server")

    for path in candidates:
        if path.exists():
            return str(path)

    # Backwards-compatible fallback
    fallback = Path.cwd() / ".env"
    if fallback.exists():
        return str(fallback)

    return None


class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Azure DevOps (AzDO)
    AZDO_ORGANIZATION_URL: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_ORGANIZATION_URL", "ADO_ORGANIZATION_URL"),
    )
    AZDO_PAT: str = Field(
        default="",
        validation_alias=AliasChoices("AZDO_PAT", "ADO_PAT"),
    )
    AZDO_WEBHOOK_SECRET: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AZDO_WEBHOOK_SECRET", "ADO_WEBHOOK_SECRET"),
    )
    AZDO_SSL_VERIFY: bool = Field(
        default=False,
        validation_alias=AliasChoices("AZDO_SSL_VERIFY", "ADO_SSL_VERIFY"),
    )

    # Storage
    DATA_DIR: str = "data"
    LOG_MAX_BYTES: int = (
        5_242_880  # Rotate notifications.log at this size (default: 5 MB)
    )
    LOG_BACKUP_COUNT: int = 3  # Number of rolled log files to keep
    LOG_RAW_WEBHOOKS: bool = (
        True  # Whether to log the received webhook payloads from AzDO to JSONL
    )

    # Server public URL (used in setup instructions and health endpoint)
    SERVER_PUBLIC_URL: str = "http://localhost:8000"

    model_config = {
        "env_file": _find_env_file(),
        "env_file_encoding": "utf-8",
    }

    # Backward-compatible property aliases
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

    @property
    def ADO_WEBHOOK_SECRET(self) -> str | None:
        return self.AZDO_WEBHOOK_SECRET

    @ADO_WEBHOOK_SECRET.setter
    def ADO_WEBHOOK_SECRET(self, value: str | None) -> None:
        self.AZDO_WEBHOOK_SECRET = value

    @ADO_WEBHOOK_SECRET.deleter
    def ADO_WEBHOOK_SECRET(self) -> None:
        self.AZDO_WEBHOOK_SECRET = None

    @property
    def ADO_SSL_VERIFY(self) -> bool:
        return self.AZDO_SSL_VERIFY

    @ADO_SSL_VERIFY.setter
    def ADO_SSL_VERIFY(self, value: bool) -> None:
        self.AZDO_SSL_VERIFY = value

    @ADO_SSL_VERIFY.deleter
    def ADO_SSL_VERIFY(self) -> None:
        self.AZDO_SSL_VERIFY = False


settings = Settings()

