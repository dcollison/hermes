# Standard
import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime
from pathlib import Path

# Remote
from fastapi import APIRouter, Header, HTTPException, Request

# Local
from ..config import settings
from ..dispatcher import dispatch
from ..formatter import format_webhook

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_secret(body: bytes, signature: str | None) -> bool:
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


def _append_to_jsonl(data: dict):
    """
    Synchronous file write to be run in a thread.
    """
    try:
        log_path = Path(settings.DATA_DIR) / "webhooks.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        logger.exception("Failed to log raw webhook", exc_info=e)


async def _log_webhook(payload: dict, event_type: str):
    """
    Log the raw webhook payload to a JSONL file in the background.
    """
    if not settings.LOG_RAW_WEBHOOKS:
        return

    entry = {
        "timestamp": datetime.now().isoformat(),
        "event_type": event_type,
        "payload": payload,
    }

    # Run the blocking I/O in a separate thread
    await asyncio.to_thread(_append_to_jsonl, entry)


@router.post("/ado")
async def receive_webhook(
    request: Request,
    x_hub_signature: str | None = Header(None),
):
    """Receive Azure DevOps webhook events.
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

    await _log_webhook(payload, event_type)

    # Format and dispatch in the background so ADO gets a fast 200 response
    asyncio.create_task(_process(event_type, payload))

    return {"status": "accepted", "eventType": event_type}


async def _process(event_type: str, payload: dict):
    notification = await format_webhook(event_type, payload)
    if notification:
        await dispatch(notification)
    else:
        logger.debug(f"Event {event_type} produced no notification")
