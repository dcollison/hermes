# Standard
import base64
import logging

# Remote
import httpx

# Local
from .config import settings

logger = logging.getLogger(__name__)

API_VERSION = "1.0"

_avatar_cache: dict[str, str | None] = {}
_group_cache: dict[str, dict[str, list[str]]] = {}


def _auth_headers() -> dict[str, str]:
    """Generate Basic Authentication HTTP headers for Azure DevOps REST endpoints.

    :returns: Dictionary with Authorization and Accept headers.
    """
    token = base64.b64encode(f":{settings.ADO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


async def get_user_avatar_b64(identity_id: str | None) -> str | None:
    """Fetch and base64-encode a user's avatar image from the ADO Graph API.

    :param identity_id: Azure DevOps user identity GUID.
    :returns: Base64 data URI string or None if unconfigured or unavailable.
    """
    if not settings.ADO_PAT or not settings.ADO_ORGANIZATION_URL or not identity_id:
        return None
    if identity_id in _avatar_cache:
        return _avatar_cache[identity_id]
    try:
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/graph/avatars/{identity_id}"
        params = {"api-version": API_VERSION, "size": "small"}
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(url, headers=_auth_headers(), params=params)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "image/png")
                b64 = base64.b64encode(resp.content).decode()
                result = f"data:{content_type};base64,{b64}"
                _avatar_cache[identity_id] = result
                return result
    except Exception as e:
        logger.debug(f"Avatar fetch failed for {identity_id}: {e}")
    _avatar_cache[identity_id] = None
    return None


async def get_user_groups(identity_id: str) -> dict[str, list[str]]:
    """Return ADO group IDs and display names that this user belongs to.

    Uses the Identities API to expand group memberships:
        GET /_apis/identities/{id}?queryMembership=Expanded

    :param identity_id: Azure DevOps user identity GUID.
    :returns: Dictionary with group ``ids`` and ``names`` lists.
    """
    if not settings.ADO_PAT or not settings.ADO_ORGANIZATION_URL or not identity_id:
        return {"ids": [], "names": []}
    if identity_id in _group_cache:
        return _group_cache[identity_id]

    groups_data: dict[str, list[str]] = {"ids": [], "names": []}
    try:
        # Step 1: get the identity record with expanded nested membership info
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities/{identity_id}"
        params = {"api-version": API_VERSION, "queryMembership": "Expanded"}
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(url, headers=_auth_headers(), params=params)
            if resp.status_code != 200:
                _group_cache[identity_id] = groups_data
                return groups_data

            identity = resp.json()
            member_of_ids: list[str] = identity.get("memberOf", []) if isinstance(identity, dict) else []
            groups_data["ids"] = member_of_ids

        # Step 2: resolve each group ID to a display name
        if member_of_ids:
            # Batch requests to avoid URL-too-long errors
            batch_size = 40
            for i in range(0, len(member_of_ids), batch_size):
                batch_ids = member_of_ids[i : i + batch_size]
                ids_param = ",".join(batch_ids)
                resolve_url = (
                    f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities"
                )
                resolve_params = {
                    "api-version": API_VERSION,
                    "identityIds": ids_param,
                }
                async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                    resp = await client.get(
                        resolve_url,
                        headers=_auth_headers(),
                        params=resolve_params,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("value", []) if isinstance(data, dict) else []
                        for item in items:
                            if not item:
                                continue
                            name = item.get("providerDisplayName") or item.get(
                                "customDisplayName",
                                "",
                            )
                            if name:
                                groups_data["names"].append(name)
    except Exception as e:
        logger.debug(f"Group fetch failed for {identity_id}: {e}")

    _group_cache[identity_id] = groups_data
    return groups_data


async def get_pr_reviewers(
    pr_resource: dict[str, object],
) -> list[dict[str, object]]:
    """Extract the list of reviewers from a pull request resource payload.

    :param pr_resource: Pull request resource dictionary.
    :returns: List of reviewer identity dictionaries.
    """
    reviewers = pr_resource.get("reviewers", [])
    if isinstance(reviewers, list):
        return reviewers
    return []


async def get_thread_participants(
    threads_url: str | None,
) -> list[dict[str, object]]:
    """Fetch all unique authors from a PR comment thread.

    :param threads_url: The REST URL for the PR comment thread.
    :returns: List of author identity dictionaries.
    """
    if not settings.ADO_PAT or not threads_url:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(threads_url, headers=_auth_headers())
            if resp.status_code == 200:
                thread = resp.json()
                authors = [
                    c.get("author")
                    for c in thread.get("comments", [])
                    if c.get("author")
                ]
                return authors
    except Exception as e:
        logger.warning(f"Failed to fetch PR thread participants: {e}")
    return []
