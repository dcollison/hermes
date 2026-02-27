"""Hermes Server Configuration"""

# Standard
import os
from pathlib import Path

# Remote
from pydantic_settings import BaseSettings


def _find_env_file() -> str | None:
    """Search for .env.hermes-server in order:
      1. Current working directory
      2. The directory containing this file (repo root when running from source)
      3. %APPDATA%/Hermes  (Windows)

    Falls back to a plain .env in the current directory for backwards compatibility.
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

    # Azure DevOps
    ADO_ORGANIZATION_URL: str = ""
    ADO_PAT: str = ""
    ADO_WEBHOOK_SECRET: str | None = None

    # Storage
    DATA_DIR: str = "data"
    LOG_MAX_BYTES: int = (
        5_242_880  # Rotate notifications.log at this size (default: 5 MB)
    )
    LOG_BACKUP_COUNT: int = 3  # Number of rolled log files to keep

    # Server public URL (used in setup instructions and health endpoint)
    SERVER_PUBLIC_URL: str = "http://localhost:8000"

    model_config = {
        "env_file": _find_env_file(),
        "env_file_encoding": "utf-8",
    }


settings = Settings()
