# Standard
import asyncio
import json
import logging
import logging.handlers
import os
import uuid
from datetime import UTC, datetime

# Local
from .config import settings as _settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & tunable constants
# ---------------------------------------------------------------------------


DATA_DIR = _settings.DATA_DIR
CLIENTS_FILE = os.path.join(DATA_DIR, "clients.json")
LOG_FILE = os.path.join(DATA_DIR, "notifications.log")

LOG_MAX_BYTES = _settings.LOG_MAX_BYTES
LOG_BACKUP_COUNT = _settings.LOG_BACKUP_COUNT

_lock = asyncio.Lock()

# Dedicated Python logger that writes one JSON line per notification event.
# Configured in init_db() once the data directory exists.
_notif_logger: logging.Logger | None = None


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def _build_notif_logger() -> logging.Logger:
    """Create (or reuse) a Python logger backed by a RotatingFileHandler.

    Each record written to it must already be a single-line JSON string.

    :returns: Configured logging.Logger instance.
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


async def init_db() -> None:
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
        f"(max {LOG_MAX_BYTES // 1024} KB, {LOG_BACKUP_COUNT} backups)",
    )


# ---------------------------------------------------------------------------
# Low-level JSON helpers for clients.json
# ---------------------------------------------------------------------------


def _read_json(path: str) -> dict:
    """Read and parse a JSON file.

    :param path: Filesystem path to the JSON file.
    :returns: Parsed JSON data structure.
    """
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data: dict) -> None:
    """Atomically write dictionary content to a JSON file via a temporary file.

    :param path: Target destination path.
    :param data: JSON-serializable dictionary.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)  # atomic rename on all major OS


# ---------------------------------------------------------------------------
# Client helpers
# ---------------------------------------------------------------------------


async def get_all_clients() -> list[dict]:
    """Retrieve all registered client records.

    :returns: List of client dictionary records.
    """
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    return list(data.values())


async def get_client(client_id: str) -> dict | None:
    """Retrieve a client record by unique ID.

    :param client_id: Client identifier string.
    :returns: Client dictionary if found, or None.
    """
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    return data.get(client_id)


async def get_client_by_callback(callback_url: str) -> dict | None:
    """Retrieve a client record matching the given callback URL.

    :param callback_url: Notification callback URL.
    :returns: Matching client record dictionary or None.
    """
    async with _lock:
        data = _read_json(CLIENTS_FILE)
    for client in data.values():
        if client["callback_url"] == callback_url:
            return client
    return None


async def save_client(client: dict) -> dict:
    """Insert or update a client record in storage.

    :param client: Client record dictionary with an 'id' key.
    :returns: The saved client dictionary.
    """
    async with _lock:
        data = _read_json(CLIENTS_FILE)
        data[client["id"]] = client
        _write_json(CLIENTS_FILE, data)
    return client


async def delete_client(client_id: str) -> bool:
    """Mark a registered client as inactive.

    :param client_id: Client identifier string.
    :returns: True if client was found and updated, False otherwise.
    """
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


async def append_log(entry: dict) -> None:
    """Write one notification entry to the rotating log file.

    Each line is a compact JSON object (NDJSON format).
    The RotatingFileHandler rolls the file automatically when it hits
    LOG_MAX_BYTES — no manual size checks needed here.

    :param entry: Log entry dictionary to append.
    """
    line = json.dumps(entry, default=str)
    async with _lock:
        if _notif_logger:
            _notif_logger.info(line)


def _log_files_newest_first() -> list[str]:
    """Return all log file paths in newest-first order:
      [notifications.log, notifications.log.1, notifications.log.2, ...]

    Only paths that actually exist are included.

    :returns: List of existing log file paths.
    """
    paths = [LOG_FILE] + [f"{LOG_FILE}.{i}" for i in range(1, LOG_BACKUP_COUNT + 1)]
    return [p for p in paths if os.path.exists(p)]


async def get_logs(
    limit: int = 50,
    event_type: str | None = None,
    client_id: str | None = None,
) -> list[dict]:
    """Read log entries across all rolled files, returning the most recent
    entries first. Applies optional filters by event_type and client_id.

    :param limit: Maximum number of entries to return.
    :param event_type: Optional event type filter.
    :param client_id: Optional client ID filter.
    :returns: List of log entry dictionaries.
    """
    entries: list[dict] = []

    async with _lock:
        for path in _log_files_newest_first():
            try:
                with open(path, encoding="utf-8") as f:
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


def make_client(
    name: str,
    callback_url: str,
    ado_user_id: str,
    display_name: str,
    subscriptions: list[str],
) -> dict:
    """Construct a new client record dictionary.

    :param name: Human-readable client label.
    :param callback_url: Webhook callback URL on the client.
    :param ado_user_id: Azure DevOps identity GUID.
    :param display_name: Azure DevOps user display name.
    :param subscriptions: List of subscribed event categories.
    :returns: Initialized client dictionary.
    """
    now = datetime.now(UTC).isoformat()
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


def make_log_entry(
    client_id: str,
    event_type: str,
    payload: dict,
    success: bool,
    error: str | None,
) -> dict:
    """Construct a notification log entry dictionary.

    :param client_id: Target client identifier.
    :param event_type: Event category string.
    :param payload: Notification payload dictionary.
    :param success: Whether delivery succeeded.
    :param error: Error message string or None.
    :returns: Formatted log entry dictionary.
    """
    return {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "event_type": event_type,
        "payload": payload,
        "success": success,
        "error": error,
        "sent_at": datetime.now(UTC).isoformat(),
    }


async def get_system_stats() -> dict:
    """Retrieve system diagnostics, client counts, and subscription breakdowns.

    :returns: Dictionary with system statistics.
    """
    async with _lock:
        data = _read_json(CLIENTS_FILE)

    clients = list(data.values())
    active_clients = [c for c in clients if c.get("active")]

    sub_counts: dict[str, int] = {}
    for c in active_clients:
        for sub in c.get("subscriptions", []):
            sub_counts[sub] = sub_counts.get(sub, 0) + 1

    return {
        "total_clients": len(clients),
        "active_clients": len(active_clients),
        "subscriptions": sub_counts,
    }

