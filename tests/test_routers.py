"""Tests for server routers via the FastAPI test client.

Covers:
    - POST /clients/register (new, re-register idempotent)
    - GET  /clients/
    - DELETE /clients/{id}
    - PUT /clients/{id}/subscriptions
    - POST /webhooks/ado (accepted, bad secret, missing event type)
    - POST /notifications/send
    - GET  /notifications/logs
"""

# Standard
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Remote
import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Shared test client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async httpx client wrapping the FastAPI app, with the database
    pointed at a fresh temp directory for each test.
    """
    # Standard
    import logging
    import logging.handlers

    # Remote
    import hermes_server.database as db

    clients_file = str(tmp_path / "clients.json")
    log_file = str(tmp_path / "notifications.log")

    Path(clients_file).write_text("{}", encoding="utf-8")
    Path(log_file).touch()

    nl = logging.getLogger(f"hermes.notifications.router.{tmp_path.name}")
    nl.propagate = False
    nl.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    nl.addHandler(handler)

    with (
        patch.object(db, "DATA_DIR", str(tmp_path)),
        patch.object(db, "CLIENTS_FILE", clients_file),
        patch.object(db, "LOG_FILE", log_file),
        patch.object(db, "_notif_logger", nl),
    ):
        # Remote
        from httpx import ASGITransport, AsyncClient

        # Remote
        from hermes_server.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            yield c

    nl.handlers.clear()


REGISTER_BODY = {
    "name": "Alice's PC",
    "callback_url": "http://192.168.1.10:9000/notify",
    "ado_user_id": "alice-id",
    "display_name": "Alice Smith",
    "subscriptions": ["pr", "workitem"],
}


# ---------------------------------------------------------------------------
# Client registration
# ---------------------------------------------------------------------------


class TestClientRegistration:
    @pytest.mark.asyncio
    async def test_register_new_client(self, client):
        resp = await client.post("/clients/register", json=REGISTER_BODY)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Alice's PC"
        assert data["ado_user_id"] == "alice-id"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_returns_identity_fields(self, client):
        resp = await client.post("/clients/register", json=REGISTER_BODY)
        data = resp.json()
        assert data["display_name"] == "Alice Smith"
        assert data["subscriptions"] == ["pr", "workitem"]

    @pytest.mark.asyncio
    async def test_re_register_same_callback_is_idempotent(self, client):
        await client.post("/clients/register", json=REGISTER_BODY)
        updated = {**REGISTER_BODY, "name": "Alice's New PC"}
        resp = await client.post("/clients/register", json=updated)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Alice's New PC"
        # Only one client should exist
        list_resp = await client.get("/clients/")
        assert len(list_resp.json()) == 1

    @pytest.mark.asyncio
    async def test_list_clients_empty(self, client):
        resp = await client.get("/clients/")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_clients_after_register(self, client):
        await client.post("/clients/register", json=REGISTER_BODY)
        resp = await client.get("/clients/")
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_delete_client(self, client):
        reg = await client.post("/clients/register", json=REGISTER_BODY)
        client_id = reg.json()["id"]
        resp = await client.delete(f"/clients/{client_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unregistered"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_client_returns_404(self, client):
        resp = await client.delete("/clients/does-not-exist")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_subscriptions(self, client):
        reg = await client.post("/clients/register", json=REGISTER_BODY)
        client_id = reg.json()["id"]
        resp = await client.put(
            f"/clients/{client_id}/subscriptions",
            json=["pipeline", "manual"],
        )
        assert resp.status_code == 200
        assert resp.json()["subscriptions"] == ["pipeline", "manual"]


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------


class TestWebhookReceiver:
    def _pr_payload(self):
        return {
            "eventType": "git.pullrequest.created",
            "resource": {
                "pullRequestId": 1,
                "title": "Test PR",
                "status": "active",
                "repository": {"name": "Repo"},
                "sourceRefName": "refs/heads/feature",
                "targetRefName": "refs/heads/main",
                "url": "http://ado/pr/1",
                "createdBy": {"id": "u1", "displayName": "Alice"},
                "reviewers": [],
            },
            "resourceContainers": {"project": {"name": "MyProject"}},
        }

    @pytest.mark.asyncio
    async def test_webhook_returns_accepted(self, client):
        with (
            patch(
                "hermes_server.routers.webhooks.format_webhook",
                new=AsyncMock(return_value=None),
            ),
            patch("hermes_server.routers.webhooks.dispatch", new=AsyncMock()),
        ):
            resp = await client.post("/webhooks/ado", json=self._pr_payload())
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_webhook_missing_event_type_returns_400(self, client):
        resp = await client.post("/webhooks/ado", json={"resource": {}})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_webhook_invalid_secret_returns_401(self, client):
        with patch("hermes_server.routers.webhooks.settings") as mock_settings:
            mock_settings.ADO_WEBHOOK_SECRET = "correct-secret"
            resp = await client.post(
                "/webhooks/ado",
                json=self._pr_payload(),
                headers={"X-Hub-Signature": "sha1=wrong"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_webhook_no_secret_configured_accepts_all(self, client):
        with (
            patch("hermes_server.routers.webhooks.settings") as mock_settings,
            patch(
                "hermes_server.routers.webhooks.format_webhook",
                new=AsyncMock(return_value=None),
            ),
            patch("hermes_server.routers.webhooks.dispatch", new=AsyncMock()),
        ):
            mock_settings.ADO_WEBHOOK_SECRET = None
            resp = await client.post("/webhooks/ado", json=self._pr_payload())
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Manual notifications
# ---------------------------------------------------------------------------


class TestManualNotifications:
    @pytest.mark.asyncio
    async def test_send_manual_with_no_clients(self, client):
        resp = await client.post(
            "/notifications/send",
            json={"heading": "Hello", "body": "World"},
        )
        assert resp.status_code == 200
        assert resp.json()["dispatched_to"] == 0

    @pytest.mark.asyncio
    async def test_send_manual_reaches_subscribed_clients(self, client):
        await client.post(
            "/clients/register",
            json={
                **REGISTER_BODY,
                "subscriptions": ["manual"],
            },
        )

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_http:
            mock_http.return_value.__aenter__ = AsyncMock(
                return_value=mock_http.return_value,
            )
            mock_http.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_http.return_value.post = AsyncMock(return_value=mock_resp)

            resp = await client.post(
                "/notifications/send",
                json={"heading": "Deploy", "body": "Going live"},
            )

        assert resp.status_code == 200
        assert resp.json()["dispatched_to"] == 1

    @pytest.mark.asyncio
    async def test_send_manual_not_delivered_to_non_subscriber(self, client):
        await client.post(
            "/clients/register",
            json={
                **REGISTER_BODY,
                "subscriptions": ["pr"],  # not subscribed to manual
            },
        )
        resp = await client.post(
            "/notifications/send",
            json={"heading": "Hello", "body": "World"},
        )
        assert resp.json()["dispatched_to"] == 0

    @pytest.mark.asyncio
    async def test_get_notification_logs(self, client):
        resp = await client.get("/notifications/logs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_notification_logs_limit_param(self, client):
        resp = await client.get("/notifications/logs?limit=5")
        assert resp.status_code == 200
