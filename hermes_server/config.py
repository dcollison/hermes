"""Hermes Server Configuration"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DATA_DIR: str = "data"          # Directory where clients.json and notifications.log are stored
    LOG_MAX_BYTES: int = 5_242_880  # Rotate notifications.log at this size (default: 5 MB)
    LOG_BACKUP_COUNT: int = 3       # Number of rolled log files to keep (.log.1, .log.2, .log.3)

    # Azure DevOps
    ADO_ORGANIZATION_URL: str = ""          # e.g. http://your-server/DefaultCollection
    ADO_PAT: str = ""                       # Personal Access Token with read permissions
    ADO_WEBHOOK_SECRET: Optional[str] = None  # Optional shared secret for webhook validation

    # Server public URL (used when registering webhooks with ADO)
    SERVER_PUBLIC_URL: str = "http://localhost:8000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
