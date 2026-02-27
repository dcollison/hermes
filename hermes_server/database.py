"""
Hermes Store - Persistent storage using plain JSON/log files.

Two files are maintained in the data directory:
  clients.json        — registered client records (JSON dict keyed by ID)
  notifications.log   — delivery log; one JSON object per line (NDJSON),
                        automatically rotated when the file reaches
                        LOG_MAX_BYTES (default 5 MB). Up to LOG_BACKUP_COUNT
                        (default 3) rolled files are kept alongside it:
                          notifications.log.1  ← most recent rolled file
                          notifications.log.2
                          notifications.log.3  ← oldest

All reads and writes are protected by an asyncio lock so concurrent
webhook dispatches don't corrupt the files.
"""

# Standard
import asyncio
import json
import logging
import logging.handlers
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & tunable constants
# ---------------------------------------------------------------------------

DATA_DIR = os.environ.get(
    "HERMES_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data"),
)
CLIENTS_FILE = os.path.join(DATA_DIR, "clients.json")
LOG_FILE = os.path.join(DATA_DIR, "notifications.log")

# Rotate when the active log reaches this size (bytes). Default: 5 MB.
LOG_MAX_BYTES = int(os.environ.get("HERMES_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
# Number of rolled files to keep alongside the active log.
LOG_BACKUP_COUNT = int(os.environ.get("HERMES_LOG_BACKUP_COUNT", "3"))

_lock = asyncio.Lock()

# Dedicated Python logger that writes one JSON line per notification event.
# Configured in init_db() once the data directory exists.
_notif_logger: Optional[logging.Logger] = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def _build_notif_logger() -> logging.Logger:
    """
    Create (or reuse) a Python logger backed by a RotatingFileHandler.
    Each record written to it must already be a single-line JSON string.
    """
    nl = logging.getLogger("hermes.notifications")
    nl.propagate = False  # Don't bubble up to the root logger
    nl.setLevel(logging.INFO)

    if not nl.handlers:
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        # Emit the raw message only — no timestamps or levels added by the handler.
        handler.setFormatter(logging.Formatter("%(message)s"))
        nl.addHandler(handler)

    return nl


async def init_db():
    """Create the data directory and seed missing files."""
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.exists(CLIENTS_FILE):
        _write_json(CLIENTS_FILE, {})
        logger.info(f"Created {CLIENTS_FILE}")

    # Touch the log file so it exists from the start.
    if not os.path.exists(LOG_FILE):
        open(LOG_FILE, "a", encoding="utf-8").close()
        logger.info(f"Created {LOG_FILE}")

    global _notif_logger
    _notif_logger = _build_notif_logger()
    logger.info(
        f"Notification log: {LOG_FILE} "
        f"(max {LOG_MAX_BYTES // 1024} KB, {LOG_BACKUP_COUNT} backups)"
    )


# ---------------------------------------------------------------------------
# Low-level JSON helpers for clients.json
# ---------------------------------------------------------------------------


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)  # atomic rename on all major OS


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


async def get_all_clients() -> list:
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    return list(data.values())


async def get_client(client_id: str) -> Optional[dict]:
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    return data.get(client_id)


async def get_client_by_callback(callback_url: str) -> Optional[dict]:
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    for client in data.values():
        if client["callback_url"] == callback_url:
            return client
    return None


async def save_client(client: dict) -> dict:
    """Insert or update a client record."""
    async with _lock:
        data = _read_json(CLIENTS_FILE)
        data[client["id"]] = client
        _write_json(CLIENTS_FILE, data)
    return client


async def delete_client(client_id: str) -> bool:
    async with _lock:
        data = _read_json(CLIENTS_FILE)
        if client_id not in data:
            return False
        data[client_id]["active"] = False
        _write_json(CLIENTS_FILE, data)
    return True


# ---------------------------------------------------------------------------
# Notification log helpers
# ---------------------------------------------------------------------------


async def append_log(entry: dict):
    """
    Write one notification entry to the rotating log file.
    Each line is a compact JSON object (NDJSON format).
    The RotatingFileHandler rolls the file automatically when it hits
    LOG_MAX_BYTES — no manual size checks needed here.
    """
    line = json.dumps(entry, default=str)
    async with _lock:
        _notif_logger.info(line)


def _log_files_newest_first() -> list[str]:
    """
    Return all log file paths in newest-first order:
      [notifications.log, notifications.log.1, notifications.log.2, ...]
    Only paths that actually exist are included.
    """
    paths = [LOG_FILE] + [f"{LOG_FILE}.{i}" for i in range(1, LOG_BACKUP_COUNT + 1)]
    return [p for p in paths if os.path.exists(p)]


async def get_logs(
    limit: int = 50,
    event_type: Optional[str] = None,
    client_id: Optional[str] = None,
) -> list:
    """
    Read log entries across all rolled files, returning the most recent
    entries first. Applies optional filters by event_type and client_id.
    """
    entries: list[dict] = []

    async with _lock:
        for path in _log_files_newest_first():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    # Read lines in reverse so newest come first within each file.
                    lines = f.readlines()
            except OSError:
                continue

            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event_type and entry.get("event_type") != event_type:
                    continue
                if client_id and entry.get("client_id") != client_id:
                    continue

                entries.append(entry)
                if len(entries) >= limit:
                    return entries

    return entries


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def make_client(name, callback_url, ado_user_id, display_name, subscriptions):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "callback_url": callback_url,
        "ado_user_id": ado_user_id,
        "display_name": display_name,
        "subscriptions": subscriptions,
        "active": True,
        "registered_at": now,
        "last_seen": None,
    }


def make_log_entry(client_id, event_type, payload, success, error):
    return {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "event_type": event_type,
        "payload": payload,
        "success": success,
        "error": error,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
