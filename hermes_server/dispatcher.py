# Standard
import asyncio
import logging
from datetime import UTC, datetime

# Local
from .ado_client import get_user_groups
from .database import append_log, get_all_clients, make_log_entry, save_client
from .http_client import get_http_client
from .models import NotificationPayload

logger = logging.getLogger(__name__)


async def _client_is_relevant(
    client: dict,
    notification: dict | NotificationPayload,
) -> bool:
    """Return True if this client should receive the notification.

    Checks event type subscription, then identity/group relevance.

    :param client: Client record dictionary.
    :param notification: Formatted notification dictionary or NotificationPayload.
    :returns: True if the client is eligible to receive the notification.
    """
    notif = notification.to_dict() if isinstance(notification, NotificationPayload) else notification

    # --- subscription check ---
    subs = client.get("subscriptions", [])
    event_type = notif.get("event_type", "")
    if event_type not in subs and "all" not in subs:
        return False

    # Manual/broadcast notifications go to everyone subscribed
    if event_type == "manual":
        return True

    # --- identity check ---
    client_uid = client.get("ado_user_id")
    client_display_name = (client.get("display_name") or "").lower().strip()
    client_name = (client.get("name") or "").lower().strip()

    actor_id = notif.get("actor_id")
    actor_name = (notif.get("actor") or "").lower().strip()

    mentions: dict = notif.get("mentions", {})
    mentioned_user_ids: list[str] = mentions.get("user_ids", [])
    mentioned_names: list[str] = [
        n.lower().strip() for n in mentions.get("names", []) if n.strip()
    ]

    # Don't notify someone about their own action...
    is_actor = False
    if actor_id and client_uid and actor_id == client_uid:
        is_actor = True
    elif actor_name and client_display_name and actor_name == client_display_name:
        is_actor = True

    if is_actor:
        # ...UNLESS the formatter explicitly mentioned them anyway.
        # This allows users to see their own build results or PR merge confirmations.
        explicitly_mentioned = False
        if client_uid and client_uid in mentioned_user_ids:
            explicitly_mentioned = True
        elif client_display_name and client_display_name in mentioned_names:
            explicitly_mentioned = True
        elif client_name and client_name in mentioned_names:
            explicitly_mentioned = True

        if not explicitly_mentioned:
            return False

    # Work item events are targeted notifications (to assignees, mentioned users, or groups).
    # Unassigned work items or work item actions without mentions must never broadcast.
    if event_type == "workitem":
        if not mentioned_user_ids and not mentioned_names:
            return False

    # If there are no mentions it's a broadcast — send to all subscribers
    if not mentioned_user_ids and not mentioned_names:
        return True

    # Direct user ID match
    if client_uid and client_uid in mentioned_user_ids:
        return True

    # Direct display name / client name match
    if client_display_name and client_display_name in mentioned_names:
        return True
    if client_name and client_name in mentioned_names:
        return True

    # Group membership match — fetch lazily and cache
    if client_uid and (mentioned_names or mentioned_user_ids):
        client_groups = await get_user_groups(client_uid)

        # Check group IDs
        client_group_ids = client_groups.get("ids", [])
        for group_id in client_group_ids:
            if group_id in mentioned_user_ids:
                return True

        # Check group names
        client_group_names = client_groups.get("names", [])
        for group_name in client_group_names:
            if group_name.lower().strip() in mentioned_names:
                return True

    return False


async def dispatch(notification: dict | NotificationPayload) -> None:
    """Send a notification to all eligible registered clients.

    :param notification: Formatted notification dictionary or NotificationPayload.
    """
    notif_dict = (
        notification.to_dict()
        if isinstance(notification, NotificationPayload)
        else notification
    )
    clients = await get_all_clients()
    active = [c for c in clients if c.get("active")]

    # Evaluate relevance concurrently
    relevance = await asyncio.gather(
        *[_client_is_relevant(c, notif_dict) for c in active],
        return_exceptions=False,
    )

    tasks = [
        _send(client, notif_dict)
        for client, relevant in zip(active, relevance)
        if relevant
    ]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _send(client: dict, notification: dict) -> None:
    """Send notification payload to a single client and log the outcome.

    :param client: Target client dictionary record.
    :param notification: Formatted notification dictionary.
    """
    success = True
    error_msg = None
    try:
        http = get_http_client()
        resp = await http.post(client["callback_url"], json=notification, timeout=5.0)
        resp.raise_for_status()
        logger.info(f"Notified client '{client['name']}' ({client['callback_url']})")
        client["last_seen"] = datetime.now(UTC).isoformat()
        await save_client(client)
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.warning(f"Failed to notify client '{client['name']}': {e!r}")

    await append_log(
        make_log_entry(
            client_id=client["id"],
            event_type=notification.get("event_type", "unknown"),
            payload=notification,
            success=success,
            error=error_msg,
        ),
    )

