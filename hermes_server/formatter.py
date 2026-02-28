"""Hermes Formatter - Converts Azure DevOps 5.1-preview webhook payloads
into structured toast notification objects.

Every notification includes a `mentions` dict:
  {
    "user_ids":  ["<ado-identity-id>", ...],
    "names":     ["Alice Smith", ...],
  }

Pipeline and PR-complete notifications also include a `status_image` field:
  "success" | "failure" | "cancelled" | None

The dispatcher uses mentions to decide which clients receive each notification.
The actor is excluded from mentions for all events EXCEPT PR merged, where the
PR author is always included so they are notified when their own PR completes.
"""

# Standard
import logging

# Local
from .ado_client import get_user_avatar_b64

logger = logging.getLogger(__name__)


def _mentions(
    *identity_dicts: dict | None,
    actor_id: str | None = None,
) -> dict:
    """Build a mentions dict from ADO identity dicts.
    The actor is excluded so they don't get notified of their own actions.
    """
    user_ids: list[str] = []
    names: list[str] = []
    seen: set[str] = set()

    for ident in identity_dicts:
        if not ident:
            continue
        uid = ident.get("id") or ident.get("uniqueName", "")
        name = ident.get("displayName", "")
        if not uid or uid == actor_id or uid in seen:
            continue
        seen.add(uid)
        user_ids.append(uid)
        if name:
            names.append(name)

    return {"user_ids": user_ids, "names": names}


async def format_webhook(event_type: str, payload: dict) -> dict | None:
    """Parse an ADO webhook payload and return a notification dict.
    Returns None if the event type is not handled.
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
            return await _format_pr(event_type, resource, project)

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
            return await _format_pipeline(event_type, resource, project)

        logger.debug(f"Unhandled event type: {event_type}")
        return None

    except Exception as e:
        logger.exception(f"Error formatting webhook {event_type}: {e}")
        return None


# ---------------------------------------------------------------------------
# Pull Request
# ---------------------------------------------------------------------------


async def _format_pr(event_type: str, resource: dict, project: str) -> dict:
    pr = (
        resource
        if "pullRequestId" in resource
        else resource.get("pullRequest", resource)
    )

    pr_id = pr.get("pullRequestId", "")
    title = pr.get("title", "Pull Request")
    repo = pr.get("repository", {}).get("name", "")
    source = pr.get("sourceRefName", "").replace("refs/heads/", "")
    target = pr.get("targetRefName", "").replace("refs/heads/", "")
    url = (
        pr.get("url")
        or pr.get("remoteUrl")
        or pr.get("_links", {}).get("web", {}).get("href", "")
    )
    status = pr.get("status", "")
    created_by = pr.get("createdBy", {})
    reviewers: list[dict] = pr.get("reviewers", [])
    status_image = None

    if event_type == "ms.vss-code.git-pullrequest-comment-event":
        comment_author = resource.get("comment", {}).get("author", {})
        actor_name = comment_author.get("displayName", "Someone")
        actor_id = comment_author.get("id")
        body = f"💬 {actor_name} commented on PR #{pr_id}: {title}"
        heading = "PR Comment"
        status_image = "pr comment"
        mentioned = _mentions(created_by, *reviewers, actor_id=actor_id)

    elif event_type == "git.pullrequest.created":
        actor_name = created_by.get("displayName", "Someone")
        actor_id = created_by.get("id")
        body = f"{actor_name} opened PR #{pr_id} in {repo}\n{source} → {target}"
        heading = "New Pull Request"
        status_image = "new pr"
        mentioned = _mentions(*reviewers, actor_id=actor_id)

    elif event_type == "git.pullrequest.merged":
        merged_by = resource.get("closedBy", created_by)
        actor_name = merged_by.get("displayName", "Someone")
        actor_id = merged_by.get("id")
        body = f"PR #{pr_id} merged in {repo}\n{title}"
        heading = "PR Merged"
        status_image = "pr merged"
        # Notify reviewers, and always include the PR author — even if they
        # were the one who clicked merge — so they know their PR completed.
        mentioned = _mentions(*reviewers, actor_id=actor_id)
        author_id = created_by.get("id")
        if author_id and author_id not in mentioned["user_ids"]:
            mentioned["user_ids"].append(author_id)
            author_name = created_by.get("displayName", "")
            if author_name and author_name not in mentioned["names"]:
                mentioned["names"].append(author_name)

    else:  # updated
        actor_name = created_by.get("displayName", "Someone")
        actor_id = created_by.get("id")
        body = f"PR #{pr_id} updated ({status}): {title}"
        heading = "PR Updated"
        status_image = "pr updated"
        mentioned = _mentions(*reviewers, actor_id=actor_id)

    avatar = await get_user_avatar_b64(actor_id)

    return {
        "event_type": "pr",
        "heading": heading,
        "body": body,
        "url": _clean_url(url),
        "project": project,
        "avatar_b64": avatar,
        "status_image": status_image,
        "actor": actor_name,
        "actor_id": actor_id,
        "mentions": mentioned,
        "meta": {
            "pr_id": pr_id,
            "repo": repo,
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
    fields = resource.get("fields", {})
    wi_id = resource.get("id", "")
    wi_type = fields.get("System.WorkItemType", "Work Item")
    wi_title = fields.get("System.Title", "Untitled")

    assigned_to_raw = fields.get("System.AssignedTo", {})
    assigned_to_name = (
        assigned_to_raw.get("displayName")
        if isinstance(assigned_to_raw, dict)
        else str(assigned_to_raw or "")
    )

    changed_by_raw = fields.get("System.ChangedBy", {})
    actor_name = (
        changed_by_raw.get("displayName")
        if isinstance(changed_by_raw, dict)
        else str(changed_by_raw or "Someone")
    )
    actor_id = changed_by_raw.get("id") if isinstance(changed_by_raw, dict) else None

    url = resource.get("url", "")
    if "/_apis/" in url:
        url = url.replace("/_apis/wit/workItems/", "/_workitems/edit/")

    state = fields.get("System.State", "")

    if event_type == "workitem.created":
        heading = f"New {wi_type}"
        body = f"{actor_name} created {wi_type} #{wi_id}: {wi_title}"
        if assigned_to_name:
            body += f"\nAssigned to: {assigned_to_name}"
    elif event_type == "workitem.commented":
        heading = f"{wi_type} Comment"
        body = f"{actor_name} commented on {wi_type} #{wi_id}: {wi_title}"
    elif event_type in ("workitem.resolved", "workitem.closed"):
        heading = f"{wi_type} {state}"
        body = f"{actor_name} {state.lower()} {wi_type} #{wi_id}: {wi_title}"
    else:
        heading = f"{wi_type} Updated"
        body = f"✏{actor_name} updated {wi_type} #{wi_id}: {wi_title}"
        if state:
            body += f" [{state}]"

    if event_type == "workitem.commented":
        status_image = "workitem comment"
    else:
        status_image = wi_type.lower()

    avatar = await get_user_avatar_b64(actor_id)
    mentioned = _mentions(
        assigned_to_raw if isinstance(assigned_to_raw, dict) else None,
        actor_id=actor_id,
    )

    return {
        "event_type": "workitem",
        "heading": heading,
        "body": body,
        "url": _clean_url(url),
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

# Maps ADO result/status strings to status image keys
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


async def _format_pipeline(event_type: str, resource: dict, project: str) -> dict:
    actor_id: str | None = None
    status_image: str | None = None

    if event_type == "build.complete":
        build_id = resource.get("id", "")
        build_num = resource.get("buildNumber", str(build_id))
        definition = resource.get("definition", {}).get("name", "Pipeline")
        result = resource.get("result", "unknown").lower()
        requested_for = resource.get("requestedFor", {})
        actor_name = requested_for.get("displayName", "Someone")
        actor_id = requested_for.get("id")
        url = resource.get("_links", {}).get("web", {}).get("href") or resource.get(
            "url",
            "",
        )
        heading = f"Build {result.replace('partiallysucceeded', 'partially succeeded').title()}"
        body = f"{definition} #{build_num} {result}\nTriggered by: {actor_name}"
        status_image = _BUILD_STATUS_IMAGE.get(result)
        # Always notify the person who triggered the build — it's their result
        mentioned = _mentions(requested_for, actor_id=None)

    elif event_type == "ms.vss-release.release-created-event":
        release = resource
        rel_name = release.get("name", "Release")
        definition = release.get("releaseDefinition", {}).get("name", "")
        created_by = release.get("createdBy", {})
        actor_name = created_by.get("displayName", "Someone")
        actor_id = created_by.get("id")
        url = release.get("_links", {}).get("web", {}).get("href", "")
        heading = "Release Created"
        body = f"{actor_name} created {rel_name}"
        if definition:
            body += f" ({definition})"
        mentioned = _mentions(actor_id=actor_id)

    elif event_type == "ms.vss-release.deployment-completed-event":
        env = resource.get("environment", {})
        env_name = env.get("name", "Environment")
        rel_name = resource.get("release", {}).get("name", "Release")
        deploy_status = env.get("status", "unknown").lower()
        deployment = resource.get("deployment", {})
        requested_for = deployment.get("requestedFor", {})
        actor_name = requested_for.get("displayName", "Someone")
        actor_id = requested_for.get("id")
        url = (
            resource.get("release", {}).get("_links", {}).get("web", {}).get("href", "")
        )
        heading = f"Deployment {deploy_status.title()}"
        body = f"{rel_name} → {env_name}: {deploy_status}"
        status_image = _DEPLOY_STATUS_IMAGE.get(deploy_status)
        mentioned = _mentions(requested_for, actor_id=None)

    elif event_type == "ms.vss-release.release-abandoned-event":
        rel_name = resource.get("name", "Release")
        modified_by = resource.get("modifiedBy", {})
        actor_name = modified_by.get("displayName", "Someone")
        actor_id = modified_by.get("id")
        url = resource.get("_links", {}).get("web", {}).get("href", "")
        heading = "Release Abandoned"
        body = f"{actor_name} abandoned {rel_name}"
        status_image = "cancelled"
        mentioned = _mentions(actor_id=actor_id)

    else:
        actor_name = "System"
        url = ""
        heading = "Pipeline Event"
        body = f"Pipeline event: {event_type}"
        mentioned = {"user_ids": [], "names": []}

    avatar = await get_user_avatar_b64(actor_id)

    return {
        "event_type": "pipeline",
        "heading": heading,
        "body": body,
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
    if not url:
        return ""
    if "/_apis/" in url and "/_workitems" not in url:
        return ""
    return url
