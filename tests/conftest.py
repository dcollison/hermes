# Standard
import logging
import logging.handlers
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Remote
import pytest
from httpx import ASGITransport, AsyncClient

import hermes_server.database as db
from hermes_server.main import app

# ---------------------------------------------------------------------------
# Temporary data directory — isolates every test from real files
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path):
    """
    Point the database module at a fresh temp directory for each test.
    Resets module-level globals that cache file paths.
    """

    clients_file = str(tmp_path / "clients.json")
    log_file = str(tmp_path / "notifications.log")

    with (
        patch.object(db, "DATA_DIR", str(tmp_path)),
        patch.object(db, "CLIENTS_FILE", clients_file),
        patch.object(db, "LOG_FILE", log_file),
    ):
        # Seed the clients file
        Path(clients_file).write_text("{}", encoding="utf-8")
        Path(log_file).touch()

        # Give the module a working notif logger pointing at the temp file

        nl = logging.getLogger("hermes.notifications.test")
        nl.propagate = False
        nl.setLevel(logging.INFO)
        handler = logging.handlers.RotatingFileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        nl.addHandler(handler)

        with patch.object(db, "_notif_logger", nl):
            yield tmp_path

        # Clean up the handler so other tests don't inherit it
        nl.handlers.clear()


# ---------------------------------------------------------------------------
# Canonical ADO identity dicts
# ---------------------------------------------------------------------------


@pytest.fixture
def alice():
    return {
        "id": "alice-id-001",
        "displayName": "Alice Smith",
        "uniqueName": "alice@corp.com",
    }


@pytest.fixture
def bob():
    return {
        "id": "bob-id-002",
        "displayName": "Bob Jones",
        "uniqueName": "bob@corp.com",
    }


@pytest.fixture
def carol():
    return {
        "id": "carol-id-003",
        "displayName": "Carol White",
        "uniqueName": "carol@corp.com",
    }


# ---------------------------------------------------------------------------
# A registered client record
# ---------------------------------------------------------------------------


@pytest.fixture
def client_record(alice):
    return {
        "id": "client-uuid-1",
        "name": "Alice's PC",
        "callback_url": "http://192.168.1.10:9000/notify",
        "ado_user_id": alice["id"],
        "display_name": alice["displayName"],
        "subscriptions": ["pr", "workitem", "pipeline", "manual"],
        "active": True,
        "registered_at": "2026-01-01T00:00:00+00:00",
        "last_seen": None,
    }


# ---------------------------------------------------------------------------
# Suppress avatar fetch in formatter tests (returns None for all calls)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=False)
def no_avatar():
    """Patch get_user_avatar_b64 to return None — no network needed."""
    with patch(
        "server.ado_client.get_user_avatar_b64",
        new=AsyncMock(return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client(tmp_data_dir):
    """Httpx AsyncClient wrapping the FastAPI app with the database
    already pointed at the temp directory.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
