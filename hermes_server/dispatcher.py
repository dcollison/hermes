"""
Hermes Dispatcher - Sends formatted notifications to registered clients.

Routing is identity-based: a client receives a notification when:
  1. The event type is in their subscription list, AND
  2. Any of the following are true:
       - The notification has no specific mentions (broadcast event)
       - The client's ADO user ID appears in notification's mentions.user_ids
       - Any of the client's ADO group names appear in notification's mentions.names
     AND the client is not the actor who triggered the event.
"""

import asyncio
import httpx
import logging
from datetime import datetime, timezone

from .ado_client import get_user_groups
from .database import get_all_clients, append_log, save_client, make_log_entry

logger = logging.getLogger(__name__)


async def _client_is_relevant(client: dict, notification: dict) -> bool:
    """
    Return True if this client should receive the notification.
    Checks event type subscription, then identity/group relevance.
    """
    # --- subscription check ---
    subs = client.get("subscriptions", [])
    event_type = notification.get("event_type", "")
    if event_type not in subs and "all" not in subs:
        return False

    # Manual/broadcast notifications go to everyone subscribed
    if event_type == "manual":
        return True

    # --- identity check ---
    # Don't notify someone about their own action
    actor_id = notification.get("actor_id")
    client_uid = client.get("ado_user_id")
    if actor_id and client_uid and actor_id == client_uid:
        return False

    mentions: dict = notification.get("mentions", {})
    mentioned_user_ids: list[str] = mentions.get("user_ids", [])
    mentioned_names: list[str] = [n.lower() for n in mentions.get("names", [])]

    # If there are no mentions it's a broadcast — send to all subscribers
    if not mentioned_user_ids and not mentioned_names:
        return True

    # Direct user match
    if client_uid and client_uid in mentioned_user_ids:
        return True

    # Group membership match — fetch lazily and cache
    if client_uid and mentioned_names:
        client_groups = await get_user_groups(client_uid)
        for group in client_groups:
            if group.lower() in mentioned_names:
                return True

    return False


async def dispatch(notification: dict):
    """Send a notification to all eligible registered clients."""
    clients = await get_all_clients()
    active = [c for c in clients if c.get("active")]

    # Evaluate relevance concurrently
    relevance = await asyncio.gather(
        *[_client_is_relevant(c, notification) for c in active],
        return_exceptions=False,
    )

    tasks = [
        _send(client, notification)
        for client, relevant in zip(active, relevance)
        if relevant
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _send(client: dict, notification: dict):
    success = True
    error_msg = None
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.post(client["callback_url"], json=notification)
            resp.raise_for_status()
        logger.info(f"Notified client '{client['name']}' ({client['callback_url']})")
        client["last_seen"] = datetime.now(timezone.utc).isoformat()
        await save_client(client)
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.warning(f"Failed to notify client '{client['name']}': {e}")

    await append_log(make_log_entry(
        client_id=client["id"],
        event_type=notification.get("event_type", "unknown"),
        payload=notification,
        success=success,
        error=error_msg,
    ))
