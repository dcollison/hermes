"""
Hermes - Webhook receiver endpoint for Azure DevOps 5.1-preview events.

ADO sends webhooks as POST requests with JSON bodies.
Supported event types:
  - git.pullrequest.created / updated / merged
  - ms.vss-code.git-pullrequest-comment-event
  - workitem.created / updated / commented / resolved / closed
  - build.complete
  - ms.vss-release.release-created-event / deployment-completed-event / release-abandoned-event
"""

import hmac
import hashlib
import logging
from fastapi import APIRouter, Request, HTTPException, Header
from typing import Optional
import asyncio

from ..config import settings
from ..formatter import format_webhook
from ..dispatcher import dispatch

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_secret(body: bytes, signature: Optional[str]) -> bool:
    """Validate ADO shared secret if configured."""
    if not settings.ADO_WEBHOOK_SECRET:
        return True  # No secret configured - accept all
    if not signature:
        return False
    expected = hmac.new(
        settings.ADO_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha1,
    ).hexdigest()
    return hmac.compare_digest(f"sha1={expected}", signature)


@router.post("/ado")
async def receive_webhook(
    request: Request,
    x_hub_signature: Optional[str] = Header(None),
):
    """
    Receive Azure DevOps webhook events.
    Configure your ADO service hook to POST to: {SERVER_URL}/webhooks/ado
    """
    body = await request.body()

    if not _verify_secret(body, x_hub_signature):
        logger.warning("Webhook received with invalid secret")
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    payload = await request.json()
    event_type = payload.get("eventType", "")

    if not event_type:
        raise HTTPException(status_code=400, detail="Missing eventType")

    logger.info(f"Received ADO webhook: {event_type}")

    # Format and dispatch in the background so ADO gets a fast 200 response
    asyncio.create_task(_process(event_type, payload))

    return {"status": "accepted", "eventType": event_type}


async def _process(event_type: str, payload: dict):
    notification = await format_webhook(event_type, payload)
    if notification:
        await dispatch(notification)
    else:
        logger.debug(f"Event {event_type} produced no notification")
