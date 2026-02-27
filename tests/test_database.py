"""
Tests for hermes_server/database.py

Covers:
  - make_client / make_log_entry constructors
  - get_all_clients / get_client / get_client_by_callback
  - save_client (insert and update)
  - delete_client (soft-delete via active=False)
  - append_log / get_logs (filtering, ordering, limit)
"""

# Standard
import json
import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

# Remote
import pytest

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    """
    Patch all path constants in hermes_server.database to a fresh temp dir
    and wire up a RotatingFileHandler for the notification logger.
    """
    # Remote
    import hermes_server.database as db_module

    clients_file = str(tmp_path / "clients.json")
    log_file = str(tmp_path / "notifications.log")

    Path(clients_file).write_text("{}", encoding="utf-8")
    Path(log_file).touch()

    nl = logging.getLogger(f"hermes.notifications.{tmp_path.name}")
    nl.propagate = False
    nl.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    nl.addHandler(handler)

    with (
        patch.object(db_module, "DATA_DIR", str(tmp_path)),
        patch.object(db_module, "CLIENTS_FILE", clients_file),
        patch.object(db_module, "LOG_FILE", log_file),
        patch.object(db_module, "_notif_logger", nl),
    ):
        yield db_module

    nl.handlers.clear()


# ---------------------------------------------------------------------------
# Constructors  (synchronous — no event loop needed)
# ---------------------------------------------------------------------------


class TestConstructors:
    def test_make_client_has_required_fields(self):
        # Remote
        from hermes_server.database import make_client

        c = make_client(
            "Alice's PC", "http://host/notify", "uid-1", "Alice Smith", ["pr"]
        )
        assert c["name"] == "Alice's PC"
        assert c["ado_user_id"] == "uid-1"
        assert c["display_name"] == "Alice Smith"
        assert c["subscriptions"] == ["pr"]
        assert c["active"] is True
        assert c["last_seen"] is None
        assert "id" in c
        assert "registered_at" in c

    def test_make_client_generates_unique_ids(self):
        # Remote
        from hermes_server.database import make_client

        c1 = make_client("A", "http://a/notify", "u1", "A", [])
        c2 = make_client("B", "http://b/notify", "u2", "B", [])
        assert c1["id"] != c2["id"]

    def test_make_log_entry_fields(self):
        # Remote
        from hermes_server.database import make_log_entry

        entry = make_log_entry("c1", "pr", {"key": "val"}, True, None)
        assert entry["client_id"] == "c1"
        assert entry["event_type"] == "pr"
        assert entry["payload"] == {"key": "val"}
        assert entry["success"] is True
        assert entry["error"] is None
        assert "id" in entry
        assert "sent_at" in entry


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------


class TestClientCRUD:
    def _make(self, name="Alice", uid="u1", url="http://host/notify"):
        # Remote
        from hermes_server.database import make_client

        return make_client(name, url, uid, name, ["pr", "workitem"])

    async def test_save_and_retrieve_client(self, db):
        client = self._make()
        await db.save_client(client)
        fetched = await db.get_client(client["id"])
        assert fetched["id"] == client["id"]
        assert fetched["name"] == "Alice"

    async def test_get_all_clients_returns_all(self, db):
        c1 = self._make("Alice", "u1", "http://a/notify")
        c2 = self._make("Bob", "u2", "http://b/notify")
        await db.save_client(c1)
        await db.save_client(c2)
        clients = await db.get_all_clients()
        ids = [c["id"] for c in clients]
        assert c1["id"] in ids
        assert c2["id"] in ids

    async def test_get_client_missing_returns_none(self, db):
        result = await db.get_client("nonexistent-id")
        assert result is None

    async def test_get_client_by_callback(self, db):
        client = self._make(url="http://specific/notify")
        await db.save_client(client)
        found = await db.get_client_by_callback("http://specific/notify")
        assert found["id"] == client["id"]

    async def test_get_client_by_callback_not_found(self, db):
        result = await db.get_client_by_callback("http://nobody/notify")
        assert result is None

    async def test_save_client_updates_existing(self, db):
        client = self._make()
        await db.save_client(client)
        client["name"] = "Alice Updated"
        await db.save_client(client)
        fetched = await db.get_client(client["id"])
        assert fetched["name"] == "Alice Updated"
        all_clients = await db.get_all_clients()
        assert len([c for c in all_clients if c["id"] == client["id"]]) == 1

    async def test_delete_client_soft_deletes(self, db):
        client = self._make()
        await db.save_client(client)
        deleted = await db.delete_client(client["id"])
        assert deleted is True
        fetched = await db.get_client(client["id"])
        assert fetched["active"] is False

    async def test_delete_nonexistent_client_returns_false(self, db):
        result = await db.delete_client("does-not-exist")
        assert result is False

    async def test_clients_json_valid_after_operations(self, db, tmp_path):
        client = self._make()
        await db.save_client(client)
        raw = (tmp_path / "clients.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert client["id"] in parsed


# ---------------------------------------------------------------------------
# Notification log
# ---------------------------------------------------------------------------


class TestNotificationLog:
    def _entry(self, event_type="pr", client_id="c1", success=True):
        # Remote
        from hermes_server.database import make_log_entry

        return make_log_entry(client_id, event_type, {"test": True}, success, None)

    async def test_append_and_retrieve_log(self, db):
        await db.append_log(self._entry())
        logs = await db.get_logs(limit=10)
        assert any(e["client_id"] == "c1" for e in logs)

    async def test_get_logs_respects_limit(self, db):
        for _ in range(5):
            await db.append_log(self._entry())
        logs = await db.get_logs(limit=3)
        assert len(logs) <= 3

    async def test_get_logs_filters_by_event_type(self, db):
        await db.append_log(self._entry(event_type="pr"))
        await db.append_log(self._entry(event_type="workitem"))
        logs = await db.get_logs(event_type="pr")
        assert all(e["event_type"] == "pr" for e in logs)

    async def test_get_logs_filters_by_client_id(self, db):
        await db.append_log(self._entry(client_id="c1"))
        await db.append_log(self._entry(client_id="c2"))
        logs = await db.get_logs(client_id="c1")
        assert all(e["client_id"] == "c1" for e in logs)

    async def test_get_logs_newest_first(self, db):
        # Standard
        import time

        # Remote
        from hermes_server.database import make_log_entry

        e1 = make_log_entry("c1", "pr", {"seq": 1}, True, None)
        time.sleep(0.02)
        e2 = make_log_entry("c1", "pr", {"seq": 2}, True, None)
        await db.append_log(e1)
        await db.append_log(e2)
        logs = await db.get_logs(limit=10)
        payloads = [e["payload"]["seq"] for e in logs]
        assert payloads.index(2) < payloads.index(1)

    async def test_malformed_log_lines_skipped(self, db, tmp_path):
        log_file = tmp_path / "notifications.log"
        log_file.write_text("not valid json\n", encoding="utf-8")
        logs = await db.get_logs(limit=10)
        assert isinstance(logs, list)
