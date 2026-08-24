# Standard
import asyncio
import base64
import logging

# Remote
import httpx
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

# Local
from .config import settings

logger = logging.getLogger(__name__)

API_VERSION = "1.0"

_avatar_cache: dict[str, str | None] = {}
_group_cache: dict[str, dict[str, list[str]]] = {}
_connection: Connection | None = None


def _get_connection() -> Connection | None:
    global _connection
    if _connection is None and settings.ADO_PAT and settings.ADO_ORGANIZATION_URL:
        creds = BasicAuthentication("", settings.ADO_PAT)
        _connection = Connection(base_url=settings.ADO_ORGANIZATION_URL, creds=creds)
    return _connection


def _get_identity_client():
    conn = _get_connection()
    if not conn:
        return None
    try:
        return conn.clients.get_identity_client()
    except Exception as e:
        logger.debug(f"Could not create identity client: {e}")
        return None


def _auth_headers() -> dict:
    token = base64.b64encode(f":{settings.ADO_PAT}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


async def get_user_avatar_b64(identity_id: str | None) -> str | None:
    """Left on the raw REST endpoint — the SDK's Graph avatar API expects a
    subjectDescriptor (Services-style), and on-prem ADO Server's binary
    /_apis/graph/avatars/{id} endpoint isn't modeled in the SDK.
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
    """Return ADO group IDs/names this user belongs to, via the SDK's
    IdentityClient instead of a raw `_apis/identities` call.
    """
    if not settings.ADO_PAT or not settings.ADO_ORGANIZATION_URL or not identity_id:
        return {"ids": [], "names": []}
    if identity_id in _group_cache:
        return _group_cache[identity_id]

    groups_data: dict[str, list[str]] = {"ids": [], "names": []}
    client = _get_identity_client()
    if not client:
        _group_cache[identity_id] = groups_data
        return groups_data

    try:
        identities = await asyncio.to_thread(
            client.read_identities,
            identity_ids=identity_id,
            query_membership="Expanded",
        )
        if identities:
            groups_data["ids"] = list(identities[0].member_of or [])

        batch_size = 40
        for i in range(0, len(groups_data["ids"]), batch_size):
            batch = ",".join(groups_data["ids"][i : i + batch_size])
            resolved = await asyncio.to_thread(
                client.read_identities,
                identity_ids=batch,
            )
            for item in resolved or []:
                name = getattr(item, "provider_display_name", None) or getattr(
                    item,
                    "custom_display_name",
                    None,
                )
                if name:
                    groups_data["names"].append(name)
    except Exception as e:
        logger.debug(f"Group fetch failed for {identity_id}: {e}")

    _group_cache[identity_id] = groups_data
    return groups_data


async def get_pr_reviewers(pr_resource: dict) -> list[dict]:
    return pr_resource.get("reviewers", [])


async def get_thread_participants(threads_url: str | None) -> list[dict]:
    """Fetch all unique authors from a PR comment thread."""
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
