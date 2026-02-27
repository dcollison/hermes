"""
Azure DevOps API helpers.
Targets ADO Server with API version 5.1-preview.

Caches avatar images and group memberships in-process so repeated webhook
events for the same users don't hammer the ADO API.
"""

# Standard
import base64
import logging
from functools import lru_cache
from typing import Optional

# Remote
import httpx

# Local
from .config import settings

logger = logging.getLogger(__name__)

API_VERSION = "5.1-preview"

# In-process caches (survive for the lifetime of the server process).
_avatar_cache: dict[str, Optional[str]] = {}
_group_cache: dict[str, list[str]] = {}


def _auth_headers() -> dict:
    token = base64.b64encode(f":{settings.ADO_PAT}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


async def get_user_avatar_b64(
    identity_id: Optional[str],
    display_name: Optional[str] = None,
) -> Optional[str]:
    """
    Fetch a user's avatar from ADO and return it as a base64 data URI.
    Results are cached for the lifetime of the process.
    Falls back gracefully if unavailable.
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


async def get_user_groups(identity_id: str) -> list[str]:
    """
    Return the list of ADO group display names that this user belongs to.
    Results are cached per user for the lifetime of the process.

    Uses the Identities API to expand group memberships:
      GET /_apis/identities/{id}?queryMembership=Direct
    """
    if not settings.ADO_PAT or not settings.ADO_ORGANIZATION_URL or not identity_id:
        return []

    if identity_id in _group_cache:
        return _group_cache[identity_id]

    groups: list[str] = []
    try:
        # Step 1: get the identity record with direct membership info
        url = f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities/{identity_id}"
        params = {"api-version": API_VERSION, "queryMembership": "Direct"}
        async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
            resp = await client.get(url, headers=_auth_headers(), params=params)
            if resp.status_code != 200:
                _group_cache[identity_id] = groups
                return groups

            identity = resp.json()
            member_of_ids: list[str] = identity.get("memberOf", [])

        # Step 2: resolve each group ID to a display name
        if member_of_ids:
            ids_param = ",".join(member_of_ids)
            resolve_url = (
                f"{settings.ADO_ORGANIZATION_URL.rstrip('/')}/_apis/identities"
            )
            resolve_params = {
                "api-version": API_VERSION,
                "identityIds": ids_param,
            }
            async with httpx.AsyncClient(timeout=5.0, verify=False) as client:
                resp = await client.get(
                    resolve_url, headers=_auth_headers(), params=resolve_params
                )
                if resp.status_code == 200:
                    for item in resp.json().get("value", []):
                        name = item.get("providerDisplayName") or item.get(
                            "customDisplayName", ""
                        )
                        if name:
                            groups.append(name)

    except Exception as e:
        logger.debug(f"Group fetch failed for {identity_id}: {e}")

    _group_cache[identity_id] = groups
    return groups


async def get_pr_reviewers(pr_resource: dict) -> list[dict]:
    """Extract reviewer identity dicts from a PR resource payload."""
    return pr_resource.get("reviewers", [])
