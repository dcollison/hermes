# Standard
import asyncio
import logging
from datetime import UTC, datetime

# Remote
import httpx
from fastapi import APIRouter
from pydantic import BaseModel

# Local
from ..database import (
    append_log,
    get_all_clients,
    get_logs,
    make_log_entry,
    save_client,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ManualNotificationRequest(BaseModel):
    heading: str
    body: str
    url: str | None = None
    avatar_b64: str | None = None
    filter_name_contains: str | None = None
    filter_project: str | None = None


class ManualNotificationResponse(BaseModel):
    dispatched_to: int
    message: str


@router.post("/send", response_model=ManualNotificationResponse)
async def send_manual_notification(body: ManualNotificationRequest):
    """Push a manual notification to all active clients subscribed to 'manual' or 'all'.
    Use the notify.py CLI script for a friendlier interface.
    """
    clients = await get_all_clients()
    targets = [
        c
        for c in clients
        if c.get("active")
        and (
            "manual" in c.get("subscriptions", [])
            or "all" in c.get("subscriptions", [])
        )
    ]

    if body.filter_name_contains:
        needle = body.filter_name_contains.lower()
        targets = [
            c
            for c in targets
            if needle in c.get("name", "").lower()
            or needle in c.get("display_name", "").lower()
        ]

    if not targets:
        return ManualNotificationResponse(
            dispatched_to=0,
            message="No matching clients subscribed to manual notifications",
        )

    notification = {
        "event_type": "manual",
        "heading": body.heading,
        "body": body.body,
        "url": body.url or "",
        "project": body.filter_project or "",
        "avatar_b64": body.avatar_b64,
        "actor": "Hermes",
        "actor_id": None,
        "mentions": {"user_ids": [], "names": []},
        "meta": {},
    }

    async def _send_one(client: dict):
        success = True
        error_msg = None
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.post(client["callback_url"], json=notification)
                resp.raise_for_status()
            client["last_seen"] = datetime.now(UTC).isoformat()
            await save_client(client)
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.warning(f"Failed to notify '{client['name']}': {e}")

        await append_log(
            make_log_entry(
                client_id=client["id"],
                event_type="manual",
                payload=notification,
                success=success,
                error=error_msg,
            ),
        )

    await asyncio.gather(*[_send_one(c) for c in targets], return_exceptions=True)

    return ManualNotificationResponse(
        dispatched_to=len(targets),
        message=f"Notification sent to {len(targets)} client(s)",
    )


@router.get("/logs")
async def get_notification_logs(
    limit: int = 50,
    event_type: str | None = None,
    client_id: str | None = None,
):
    """View recent notification delivery logs."""
    return await get_logs(limit=limit, event_type=event_type, client_id=client_id)
