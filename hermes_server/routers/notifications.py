"""
Hermes - Manual notification endpoints.
"""

import asyncio
import httpx
import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from ..database import get_all_clients, get_logs, append_log, save_client, make_log_entry

logger = logging.getLogger(__name__)
router = APIRouter()


class ManualNotificationRequest(BaseModel):
    heading: str
    body: str
    url: Optional[str] = None
    avatar_b64: Optional[str] = None


class ManualNotificationResponse(BaseModel):
    dispatched_to: int
    message: str


@router.post("/send", response_model=ManualNotificationResponse)
async def send_manual_notification(body: ManualNotificationRequest):
    """
    Push a manual notification to all active clients subscribed to 'manual' or 'all'.
    Use the notify.py CLI script for a friendlier interface.
    """
    clients = await get_all_clients()
    targets = [
        c for c in clients
        if c.get("active")
        and ("manual" in c.get("subscriptions", []) or "all" in c.get("subscriptions", []))
    ]

    if not targets:
        return ManualNotificationResponse(dispatched_to=0, message="No clients subscribed to manual notifications")

    notification = {
        "event_type": "manual",
        "heading": body.heading,
        "body": body.body,
        "url": body.url or "",
        "project": "",
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
            client["last_seen"] = datetime.now(timezone.utc).isoformat()
            await save_client(client)
        except Exception as e:
            success = False
            error_msg = str(e)
            logger.warning(f"Failed to notify '{client['name']}': {e}")

        await append_log(make_log_entry(
            client_id=client["id"],
            event_type="manual",
            payload=notification,
            success=success,
            error=error_msg,
        ))

    await asyncio.gather(*[_send_one(c) for c in targets], return_exceptions=True)

    return ManualNotificationResponse(
        dispatched_to=len(targets),
        message=f"Notification sent to {len(targets)} client(s)",
    )


@router.get("/logs")
async def get_notification_logs(
    limit: int = 50,
    event_type: Optional[str] = None,
    client_id: Optional[str] = None,
):
    """View recent notification delivery logs."""
    return await get_logs(limit=limit, event_type=event_type, client_id=client_id)
