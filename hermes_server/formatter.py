# Standard
import html
import logging
import re

# Local
from .ado_client import (
    get_thread_participants,
    get_user_avatar_b64,
    resolve_identity,
)

logger = logging.getLogger(__name__)

_HTML_HREF_RE = re.compile(r'href="([^"]+)"')
_MD_LINK_RE = re.compile(r"\((https?://[^\s)]+)\)")
_IDENTITY_STR_RE = re.compile(r"^(.*?)\s*<([^>]+)>\s*$")


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
    html_content = msg.get("html", "")
    md_content = msg.get("markdown", "")
    m = _HTML_HREF_RE.search(html_content)
    if m or (m := _MD_LINK_RE.search(md_content)):
        link = m.group(1).strip()

    if link:
        link = html.unescape(link)
        while "&amp;" in link:
            link = link.replace("&amp;", "&")

    return text, link


def parse_identity(ident: dict | str | None) -> dict[str, str | None]:
    """Parse an Azure DevOps identity dictionary or composite string.

    Handles strings formatted as ``DisplayName <DOMAIN\\AccountName>``,
    ``DisplayName <email@domain.com>``, or plain ``DisplayName``.

    :param ident: ADO identity dictionary, string, or None.
    :returns: Dictionary with keys ``id``, ``displayName``, ``uniqueName``, ``accountName``.
    """
    if not ident:
        return {"id": None, "displayName": "", "uniqueName": "", "accountName": ""}

    if isinstance(ident, dict):
        uid = (
            ident.get("id")
            or ident.get("uniqueName")
            or ident.get("identity", {}).get("id")
            or ident.get("identity", {}).get("uniqueName")
        )
        raw_disp = (
            ident.get("displayName")
            or ident.get("providerDisplayName")
            or ident.get("customDisplayName")
            or ident.get("name")
            or ident.get("identity", {}).get("displayName")
            or ""
        )
        unique_name = (
            ident.get("uniqueName")
            or ident.get("accountName")
            or ident.get("identity", {}).get("uniqueName")
            or ""
        )

        disp_name = raw_disp
        if "<" in raw_disp and ">" in raw_disp:
            m = _IDENTITY_STR_RE.match(raw_disp)
            if m:
                disp_name = m.group(1).strip()
                if not unique_name:
                    unique_name = m.group(2).strip()

        account_name = ""
        if unique_name:
            account_name = unique_name.split("\\")[-1].split("@")[0].strip()

        return {
            "id": str(uid) if uid else None,
            "displayName": disp_name.strip(),
            "uniqueName": unique_name.strip(),
            "accountName": account_name,
        }

    s = str(ident).strip()
    m = _IDENTITY_STR_RE.match(s)
    if m:
        disp_name = m.group(1).strip()
        unique_name = m.group(2).strip()
    else:
        disp_name = s
        unique_name = ""

    account_name = ""
    if unique_name:
        account_name = unique_name.split("\\")[-1].split("@")[0].strip()

    return {
        "id": None,
        "displayName": disp_name,
        "uniqueName": unique_name,
        "accountName": account_name,
    }


def _mentions(
    *identities: dict | str | None,
    actor_id: str | None = None,
    actor_name: str | None = None,
    message: str | None = None,
) -> dict[str, list[str]]:
    """Build a mentions dict from ADO identity dicts, parsed identities, or plain strings.

    The actor is excluded so they don't get notified of their own actions.
    Users whose names appear in the notification message are also excluded.

    :param identities: ADO identity dictionaries, strings, or None.
    :param actor_id: Optional ID of the user initiating the action to exclude.
    :param actor_name: Optional display name or account name of the actor to exclude.
    :param message: Optional notification message text to filter named users.
    :returns: Dictionary with lists of ``user_ids`` and ``names``.
    """
    user_ids: list[str] = []
    names: list[str] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()

    actor_name_lower = actor_name.lower().strip() if actor_name else None

    for ident in identities:
        if not ident:
            continue

        parsed = parse_identity(ident)
        uid = parsed["id"]
        disp_name = parsed["displayName"]
        unique_name = parsed["uniqueName"]
        account_name = parsed["accountName"]

        # Skip if matches actor ID
        if uid and actor_id and uid == actor_id:
            continue

        # Skip if matches actor name
        if actor_name_lower:
            if disp_name and disp_name.lower() == actor_name_lower:
                continue
            if unique_name and unique_name.lower() == actor_name_lower:
                continue
            if account_name and account_name.lower() == actor_name_lower:
                continue

        # Skip if user's display name appears in the message (e.g. "Bug created by Alice")
        if message and disp_name and disp_name in message:
            continue

        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            user_ids.append(uid)

        for name_val in (disp_name, unique_name, account_name):
            if name_val and name_val not in seen_names:
                seen_names.add(name_val)
                names.append(name_val)

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
    "git.pullrequest.completed": "PR Completed",
    "ms.vss-code.git-pullrequest-comment-event": "PR Comment",
}
_PR_STATUS_IMAGES = {
    "git.pullrequest.created": "new pr",
    "git.pullrequest.updated": "pr updated",
    "git.pullrequest.completed": "pr completed",
    "ms.vss-code.git-pullrequest-comment-event": "pr comment",
}


async def _format_pr(
    event_type: str,
    resource: dict,
    project: str,
    payload: dict,
) -> dict | None:
    """Format a pull request webhook event into a notification dictionary.

    :param event_type: Specific PR event type string.
    :param resource: Pull request resource payload.
    :param project: Team project name.
    :param payload: Full webhook payload dictionary.
    :returns: Formatted Hermes notification dictionary or None if ignored.
    """
    # Ignore standalone PR merge attempts
    if event_type == "git.pullrequest.merged":
        return None

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

    # In ADO Service Hooks 1.0, PR completions are sent as `updated` events with status: completed
    if event_type == "git.pullrequest.updated" and status.lower() == "completed":
        event_type = "git.pullrequest.completed"

    actor_id = actor.get("id")
    actor_name = actor.get("displayName", "Someone")

    text, link = _extract_message(payload)

    if event_type == "git.pullrequest.completed":
        # Notify reviewers AND the author of PR completion
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
    default_body = f"PR #{pr_id} completed" if event_type == "git.pullrequest.completed" else f"PR #{pr_id} updated ({status})"

    return {
        "event_type": "pr",
        "heading": _PR_HEADINGS.get(event_type, "Pull Request"),
        "body": text or default_body,
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

    assigned_to_raw = fields.get("System.AssignedTo")
    assigned_to_info = parse_identity(assigned_to_raw)
    assigned_to_name = assigned_to_info["displayName"] or ""

    if event_type == "workitem.updated":
        changed_by_raw = resource.get("revisedBy") or fields.get("System.ChangedBy")
    else:
        changed_by_raw = fields.get(
            "System.ChangedBy",
            fields.get("System.CreatedBy"),
        )

    actor_info = parse_identity(changed_by_raw)
    actor_name = actor_info["displayName"] or "Someone"
    actor_id = actor_info.get("id")

    # If actor_id is missing, try resolving identity from ADO
    if not actor_id:
        query = actor_info.get("uniqueName") or actor_info.get("displayName")
        if query:
            resolved = await resolve_identity(query)
            if resolved:
                actor_id = resolved.get("id")
                if resolved.get("displayName") and not actor_info["displayName"]:
                    actor_name = resolved["displayName"]

    # Also resolve assigned_to identity ID if missing
    if assigned_to_name and not assigned_to_info.get("id"):
        query = assigned_to_info.get("uniqueName") or assigned_to_info.get("displayName")
        if query:
            resolved = await resolve_identity(query)
            if resolved and resolved.get("id"):
                assigned_to_info["id"] = resolved.get("id")

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
    mentioned = _mentions(
        assigned_to_info if assigned_to_name else None,
        actor_id=actor_id,
        actor_name=actor_name,
        message=text,
    )

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
    "partiallysucceeded": "failure",
    "failed": "failure",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "stopped": "cancelled",
    "abandoned": "cancelled",
    "completed": "success",
}
_DEPLOY_STATUS_IMAGE = {
    "succeeded": "success",
    "rejected": "failure",
    "failed": "failure",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "stopped": "cancelled",
    "abandoned": "cancelled",
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
        result = (
            resource.get("result")
            or resource.get("status")
            or "unknown"
        ).lower()

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
        status_image = _BUILD_STATUS_IMAGE.get(
            result,
            "cancelled" if ("stop" in result or "cancel" in result) else "fallback",
        )
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


_BUILD_HUB_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apps/hub/ms\.vss-build-web\.[^?]+\?.*?\bbuildId=(\d+)",
    re.IGNORECASE,
)
_RELEASE_HUB_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apps/hub/ms\.vss-release-web\.[^?]+\?.*?\breleaseId=(\d+)",
    re.IGNORECASE,
)
_BUILD_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/build/builds/(\d+)",
    re.IGNORECASE,
)
_GIT_PR_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/git/repositories/([^/]+)/pullRequests/(\d+)",
    re.IGNORECASE,
)
_WIT_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/wit/workItems/(\d+)",
    re.IGNORECASE,
)
_RELEASE_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/Release/releases/(\d+)",
    re.IGNORECASE,
)


def _clean_url(url: str) -> str:
    """Clean raw API URLs, VSIX extension URLs, and HTML-escaped characters to ensure browser-friendly URLs.

    :param url: Raw URL string.
    :returns: Sanitized URL string or empty string.
    """
    if not url:
        return ""
    url = html.unescape(url.strip())
    while "&amp;" in url:
        url = url.replace("&amp;", "&")

    if m := _BUILD_HUB_RE.search(url):
        return f"{m.group(1)}/_build/results?buildId={m.group(2)}"
    if m := _RELEASE_HUB_RE.search(url):
        return f"{m.group(1)}/_release?releaseId={m.group(2)}"
    if m := _BUILD_API_RE.search(url):
        return f"{m.group(1)}/_build/results?buildId={m.group(2)}"
    if m := _GIT_PR_API_RE.search(url):
        return f"{m.group(1)}/_git/{m.group(2)}/pullrequest/{m.group(3)}"

    wit_url = url.split("/revisions/")[0].split("/updates/")[0]
    if m := _WIT_API_RE.search(wit_url):
        return f"{m.group(1)}/_workitems/edit/{m.group(2)}"

    if m := _RELEASE_API_RE.search(url):
        return f"{m.group(1)}/_release?releaseId={m.group(2)}"

    if "/_apis/" in url and "/_workitems" not in url:
        return ""
    return url
