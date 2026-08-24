# Standard
import logging
import re

# Local
from .ado_client import get_thread_participants, get_user_avatar_b64

logger = logging.getLogger(__name__)

_HTML_HREF_RE = re.compile(r'href="([^"]+)"')
_MD_LINK_RE = re.compile(r"\((https?://[^\s)]+)\)")


def _extract_message(payload: dict) -> tuple[str, str]:
    """Pull the human-readable text straight from ADO's own "message" block
    instead of hand-building it, and try to recover a link from the html
    or markdown variant. Falls back to detailedMessage if message is absent.

    :param payload: Azure DevOps webhook event payload.
    :returns: Tuple containing (message_text, hyperlink_url).
    """
    msg = payload.get("message") or payload.get("detailedMessage") or {}
    text = (msg.get("text") or "").strip()

    link = ""
    html = msg.get("html", "")
    md = msg.get("markdown", "")
    m = _HTML_HREF_RE.search(html)
    if m or (m := _MD_LINK_RE.search(md)):
        link = m.group(1)

    return text, link


def _mentions(
    *identities: dict | str | None,
    actor_id: str | None = None,
    message: str | None = None,
) -> dict[str, list[str]]:
    """Build a mentions dict from ADO identity dicts or plain strings.

    The actor is excluded so they don't get notified of their own actions.
    Users whose names appear in the notification message are also excluded.

    :param identities: ADO identity dictionaries or user display name strings.
    :param actor_id: Optional ID of the user initiating the action to exclude.
    :param message: Optional notification message text to filter named users.
    :returns: Dictionary with lists of ``user_ids`` and ``names``.
    """
    user_ids: list[str] = []
    names: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    for ident in identities:
        if not ident:
            continue

        if isinstance(ident, str):
            name = ident.strip()
            if not name or name == actor_id:
                continue
            if message and name in message:
                continue
            if name not in seen_names:
                seen_names.add(name)
                names.append(name)
            continue

        uid = ident.get("id") or ident.get("uniqueName", "")
        name = ident.get("displayName", "")

        if uid and uid == actor_id:
            continue

        if message and name and name in message:
            continue

        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            user_ids.append(uid)

        if name and name not in seen_names:
            seen_names.add(name)
            names.append(name)

    return {"user_ids": user_ids, "names": names}


async def format_webhook(event_type: str, payload: dict) -> dict[str, object] | None:
    """Parse an ADO webhook payload and return a notification dict.

    :param event_type: Azure DevOps webhook event type identifier.
    :param payload: Complete ADO webhook payload dictionary.
    :returns: Formatted notification dictionary, or None if unhandled.
    """
    try:
        resource = payload.get("resource", {})
        resource_containers = payload.get("resourceContainers", {})
        project = resource_containers.get("project", {}).get("name") or resource.get(
            "teamProject",
            "",
        )

        if event_type in (
            "git.pullrequest.created",
            "git.pullrequest.updated",
            "git.pullrequest.merged",
            "ms.vss-code.git-pullrequest-comment-event",
        ):
            return await _format_pr(event_type, resource, project, payload)

        if event_type in (
            "workitem.created",
            "workitem.updated",
            "workitem.commented",
            "workitem.resolved",
            "workitem.closed",
        ):
            return await _format_workitem(event_type, resource, project, payload)

        if event_type in (
            "build.complete",
            "ms.vss-release.release-created-event",
            "ms.vss-release.deployment-completed-event",
            "ms.vss-release.release-abandoned-event",
        ):
            return await _format_pipeline(event_type, resource, project, payload)

        logger.debug(f"Unhandled event type: {event_type}")
        return None

    except Exception as e:
        logger.exception(f"Error formatting webhook {event_type}: {e}")
        return None


# ---------------------------------------------------------------------------
# Pull Request
# ---------------------------------------------------------------------------

_PR_HEADINGS = {
    "git.pullrequest.created": "New Pull Request",
    "git.pullrequest.updated": "PR Updated",
    "git.pullrequest.merged": "PR Merged",
    "ms.vss-code.git-pullrequest-comment-event": "PR Comment",
}
_PR_STATUS_IMAGES = {
    "git.pullrequest.created": "new pr",
    "git.pullrequest.updated": "pr updated",
    "git.pullrequest.merged": "pr merged",
    "ms.vss-code.git-pullrequest-comment-event": "pr comment",
}


async def _format_pr(
    event_type: str,
    resource: dict,
    project: str,
    payload: dict,
) -> dict:
    """Format a pull request webhook event into a notification dictionary.

    :param event_type: Specific PR event type string.
    :param resource: Pull request resource payload.
    :param project: Team project name.
    :param payload: Full webhook payload dictionary.
    :returns: Formatted Hermes notification dictionary.
    """
    if event_type == "ms.vss-code.git-pullrequest-comment-event":
        pr = resource.get("pullRequest", {})
        actor = resource.get("author", {})
    else:
        pr = resource
        actor = pr.get("createdBy", {})

    pr_id = pr.get("pullRequestId", resource.get("pullRequestId", ""))
    if not pr_id:
        threads_href = resource.get("_links", {}).get("threads", {}).get("href", "")
        m = re.search(r"/pullRequests/(\d+)", threads_href)
        if m:
            pr_id = m.group(1)

    status = pr.get("status", "")
    created_by = pr.get("createdBy", {})
    reviewers: list[dict] = pr.get("reviewers", [])

    # In 1.0, merges are sent as `updated` events with status: completed
    if event_type == "git.pullrequest.updated" and status == "completed":
        event_type = "git.pullrequest.merged"

    actor_id = actor.get("id")
    actor_name = actor.get("displayName", "Someone")

    text, link = _extract_message(payload)

    if event_type == "git.pullrequest.merged":
        # Notify reviewers AND the author — even if the author is the one
        # who clicked merge, they still want the confirmation.
        mentioned = _mentions(*reviewers, actor_id=actor_id, message=text)
        author_id = created_by.get("id")
        if author_id and author_id not in mentioned["user_ids"]:
            mentioned["user_ids"].append(author_id)
            author_name = created_by.get("displayName")
            if author_name and author_name not in mentioned["names"]:
                mentioned["names"].append(author_name)
    elif event_type == "ms.vss-code.git-pullrequest-comment-event":
        threads_url = resource.get("_links", {}).get("threads", {}).get("href", "")
        thread_participants = await get_thread_participants(threads_url)
        mentioned = _mentions(
            *thread_participants,
            *reviewers,
            created_by,
            actor_id=actor_id,
            message=text,
        )
    else:
        mentioned = _mentions(*reviewers, actor_id=actor_id, message=text)

    url = link or (
        pr.get("url")
        or pr.get("remoteUrl")
        or pr.get("_links", {}).get("web", {}).get("href", "")
    )

    avatar = await get_user_avatar_b64(actor_id)

    return {
        "event_type": "pr",
        "heading": _PR_HEADINGS.get(event_type, "Pull Request"),
        "body": text or f"PR #{pr_id} updated ({status})",
        "url": _clean_url(url),
        "project": project,
        "avatar_b64": avatar,
        "status_image": _PR_STATUS_IMAGES.get(event_type),
        "actor": actor_name,
        "actor_id": actor_id,
        "mentions": mentioned,
        "meta": {
            "pr_id": pr_id,
            "repo": pr.get("repository", {}).get("name", ""),
            "status": status,
        },
    }


# ---------------------------------------------------------------------------
# Work Items
# ---------------------------------------------------------------------------


async def _format_workitem(
    event_type: str,
    resource: dict,
    project: str,
    payload: dict,
) -> dict:
    """Format a work item webhook event into a notification dictionary.

    :param event_type: Specific work item event type string.
    :param resource: Work item resource payload.
    :param project: Team project name.
    :param payload: Full webhook payload dictionary.
    :returns: Formatted Hermes notification dictionary.
    """
    wi_resource = (
        resource.get("revision", resource)
        if event_type == "workitem.updated"
        else resource
    )

    fields = wi_resource.get("fields", {})
    wi_id = wi_resource.get("id", resource.get("id", ""))
    wi_type = fields.get("System.WorkItemType", "Work Item")

    assigned_to_raw = fields.get("System.AssignedTo", {})
    assigned_to_name = (
        assigned_to_raw.get("displayName")
        if isinstance(assigned_to_raw, dict)
        else str(assigned_to_raw or "")
    )

    if event_type == "workitem.updated":
        changed_by_raw = resource.get("revisedBy", {})
    else:
        changed_by_raw = fields.get(
            "System.ChangedBy",
            fields.get("System.CreatedBy", {}),
        )

    actor_name = (
        changed_by_raw.get("displayName")
        if isinstance(changed_by_raw, dict)
        else str(changed_by_raw or "Someone")
    )
    actor_id = changed_by_raw.get("id") if isinstance(changed_by_raw, dict) else None

    url = wi_resource.get("url", "")
    if "/_apis/" in url:
        url = url.replace("/_apis/wit/workItems/", "/_workitems/edit/")
        url = url.split("/revisions/")[0]
        url = url.split("/updates/")[0]

    state = fields.get("System.State", "")
    if event_type == "workitem.updated":
        changed_fields = resource.get("fields", {})
        state_change = changed_fields.get("System.State")
        if isinstance(state_change, dict) and "newValue" in state_change:
            state = state_change["newValue"]
            if state.lower() in ("resolved", "closed", "done"):
                event_type = f"workitem.{state.lower()}"

    if event_type == "workitem.created":
        heading = f"New {wi_type}"
    elif event_type == "workitem.commented":
        heading = f"{wi_type} Comment"
    elif event_type in ("workitem.resolved", "workitem.closed", "workitem.done"):
        heading = f"{wi_type} {state}"
    else:
        heading = f"{wi_type} Updated"

    status_image = (
        "workitem comment" if event_type == "workitem.commented" else wi_type.lower()
    )

    text, link = _extract_message(payload)
    resolved_url = link or url

    avatar = await get_user_avatar_b64(actor_id)
    mentioned = _mentions(assigned_to_raw, actor_id=actor_id, message=text)

    return {
        "event_type": "workitem",
        "heading": heading,
        "body": text or f"{wi_type} #{wi_id}: {heading}",
        "url": _clean_url(resolved_url),
        "project": project,
        "avatar_b64": avatar,
        "status_image": status_image,
        "actor": actor_name,
        "actor_id": actor_id,
        "mentions": mentioned,
        "meta": {
            "wi_id": wi_id,
            "wi_type": wi_type,
            "state": state,
            "assigned_to": assigned_to_name,
        },
    }


# ---------------------------------------------------------------------------
# Pipelines / Builds / Releases
# ---------------------------------------------------------------------------

_BUILD_STATUS_IMAGE = {
    "succeeded": "success",
    "failed": "failure",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "partiallysucceeded": "failure",
}
_DEPLOY_STATUS_IMAGE = {
    "succeeded": "success",
    "rejected": "failure",
    "failed": "failure",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}


async def _format_pipeline(
    event_type: str,
    resource: dict,
    project: str,
    payload: dict,
) -> dict:
    """Format a build or release pipeline event into a notification dictionary.

    :param event_type: Specific pipeline event type string.
    :param resource: Build or release resource payload.
    :param project: Team project name.
    :param payload: Full webhook payload dictionary.
    :returns: Formatted Hermes notification dictionary.
    """
    actor_id: str | None = None
    status_image: str | None = None
    text, link = _extract_message(payload)

    if event_type == "build.complete":
        build_id = resource.get("id", "")
        build_num = resource.get("buildNumber", str(build_id))
        definition = resource.get("definition", {}).get("name", "Pipeline")
        result = resource.get("status", "unknown").lower()

        requests = resource.get("requests", [])
        requested_for = requests[0].get("requestedFor", {}) if requests else {}
        actor_name = requested_for.get("displayName", "Someone")
        actor_id = requested_for.get("id")

        url = (
            link
            or resource.get("_links", {}).get("web", {}).get("href")
            or resource.get("url", "")
        )
        heading = f"Build {result.replace('partiallysucceeded', 'partially succeeded').title()}"
        status_image = _BUILD_STATUS_IMAGE.get(result)
        default_body = f"{definition} #{build_num} {result}"
        # Always notify the person who triggered the build — it's their result
        mentioned = _mentions(requested_for, actor_id=None, message=text)

    elif event_type == "ms.vss-release.release-created-event":
        rel_name = resource.get("name", "Release")
        definition = resource.get("releaseDefinition", {}).get("name", "")
        created_by = resource.get("createdBy", {})
        actor_name = created_by.get("displayName", "Someone")
        actor_id = created_by.get("id")
        url = link or resource.get("_links", {}).get("web", {}).get("href", "")
        heading = "Release Created"
        default_body = f"{actor_name} created {rel_name}" + (
            f" ({definition})" if definition else ""
        )
        mentioned = _mentions(actor_id=actor_id, message=text)

    elif event_type == "ms.vss-release.deployment-completed-event":
        env = resource.get("environment", {})
        env_name = env.get("name", "Environment")
        rel_name = resource.get("release", {}).get("name", "Release")
        deploy_status = env.get("status", "unknown").lower()
        deployment = resource.get("deployment", {})
        requested_for = deployment.get("requestedFor", {})
        actor_name = requested_for.get("displayName", "Someone")
        actor_id = requested_for.get("id")
        url = link or resource.get("release", {}).get("_links", {}).get("web", {}).get(
            "href",
            "",
        )
        heading = f"Deployment {deploy_status.title()}"
        default_body = f"{rel_name} → {env_name}: {deploy_status}"
        status_image = _DEPLOY_STATUS_IMAGE.get(deploy_status)
        mentioned = _mentions(requested_for, actor_id=None, message=text)

    elif event_type == "ms.vss-release.release-abandoned-event":
        rel_name = resource.get("name", "Release")
        modified_by = resource.get("modifiedBy", {})
        actor_name = modified_by.get("displayName", "Someone")
        actor_id = modified_by.get("id")
        url = link or resource.get("_links", {}).get("web", {}).get("href", "")
        heading = "Release Abandoned"
        default_body = f"{actor_name} abandoned {rel_name}"
        status_image = "cancelled"
        mentioned = _mentions(actor_id=actor_id, message=text)

    else:
        actor_name = "System"
        url = ""
        heading = "Pipeline Event"
        default_body = f"Pipeline event: {event_type}"
        mentioned = {"user_ids": [], "names": []}

    avatar = await get_user_avatar_b64(actor_id)

    return {
        "event_type": "pipeline",
        "heading": heading,
        "body": text or default_body,
        "url": _clean_url(url),
        "project": project,
        "avatar_b64": avatar,
        "status_image": status_image,
        "actor": actor_name,
        "actor_id": actor_id,
        "mentions": mentioned,
        "meta": {"raw_event": event_type},
    }


def _clean_url(url: str) -> str:
    """Clean raw API URLs to ensure only browser-friendly URLs are provided.

    :param url: Raw URL string.
    :returns: Sanitized URL string or empty string.
    """
    if not url:
        return ""
    if "/_apis/" in url and "/_workitems" not in url:
        return ""
    return url
