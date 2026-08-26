# Standard
import base64
import logging

# Local
from .cache import TTLCache
from .config import settings
from .http_client import get_http_client

logger = logging.getLogger(__name__)

API_VERSION = "1.0"

_avatar_cache: TTLCache[str, str | None] = TTLCache(ttl_seconds=86400.0, max_size=2000)
_group_cache: TTLCache[str, dict[str, list[str]]] = TTLCache(ttl_seconds=3600.0, max_size=2000)
_identity_cache: TTLCache[str, dict[str, str] | None] = TTLCache(ttl_seconds=86400.0, max_size=2000)


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
    cached = _avatar_cache.get(identity_id)
    if cached is not None or identity_id in _avatar_cache:
        return cached
    try:
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/graph/avatars/{identity_id}"
        params = {"api-version": API_VERSION, "size": "small"}
        client = get_http_client()
        resp = await client.get(url, headers=_auth_headers(), params=params)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "image/png")
            b64 = base64.b64encode(resp.content).decode()
            result = f"data:{content_type};base64,{b64}"
            _avatar_cache.set(identity_id, result)
            return result
    except Exception as e:
        logger.debug(f"Avatar fetch failed for {identity_id}: {e}")
    _avatar_cache.set(identity_id, None)
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
    cached = _group_cache.get(identity_id)
    if cached is not None:
        return cached

    groups_data: dict[str, list[str]] = {"ids": [], "names": []}
    try:
        # Step 1: get the identity record with expanded nested membership info
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities/{identity_id}"
        params = {"api-version": API_VERSION, "queryMembership": "Expanded"}
        client = get_http_client()
        resp = await client.get(url, headers=_auth_headers(), params=params)
        if resp.status_code != 200:
            _group_cache.set(identity_id, groups_data)
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

    _group_cache.set(identity_id, groups_data)
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
        client = get_http_client()
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


async def resolve_identity(query: str | None) -> dict[str, str] | None:
    """Resolve an ADO user identity by account name, unique name, or display name.

    Queries:
        GET /_apis/identities?searchFilter=General&filterValue={query}

    :param query: Account name (e.g. DOMAIN\\user), email, or display name.
    :returns: Dictionary with keys ``id``, ``displayName``, ``uniqueName``, or None.
    """
    if not settings.ADO_PAT or not settings.ADO_ORGANIZATION_URL or not query:
        return None
    cleaned = query.strip()
    if not cleaned:
        return None
    if cleaned in _identity_cache:
        return _identity_cache.get(cleaned)

    try:
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities"
        params = {
            "api-version": API_VERSION,
            "searchFilter": "General",
            "filterValue": cleaned,
        }
        client = get_http_client()
        resp = await client.get(url, headers=_auth_headers(), params=params)
        if resp.status_code == 200:
            data = resp.json()
            items = (
                data.get("value", []) if isinstance(data, dict) else []
            )
            for item in items:
                if item and item.get("id"):
                    result = {
                        "id": str(item.get("id", "")),
                        "displayName": str(
                            item.get("providerDisplayName")
                            or item.get("customDisplayName")
                            or item.get("displayName")
                            or "",
                        ),
                        "uniqueName": str(
                            item.get("uniqueName")
                            or item.get("accountName")
                            or "",
                        ),
                    }
                    _identity_cache.set(cleaned, result)
                    return result
    except Exception as e:
        logger.debug(f"Identity resolution failed for '{cleaned}': {e}")

    _identity_cache.set(cleaned, None)
    return None

