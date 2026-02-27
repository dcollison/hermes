"""Hermes Client — Azure DevOps identity resolution.

Synchronous (blocking) helpers used at startup/configure time — before the
asyncio event loop is running. Not used during normal notification receive.
"""

# Standard
import base64
import logging
import socket

# Remote
import httpx

logger = logging.getLogger("hermes.client.ado")

API_VERSION = "5.1-preview"


def _auth_headers(pat: str) -> dict:
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def resolve_identity(ado_url: str, pat: str) -> dict:
    """Call /_apis/connectionData with the given PAT and return a dict with:
      user_id      — ADO identity GUID
      display_name — ADO display name

    Raises httpx.HTTPStatusError on auth failure or network error so the
    caller can show a clear message.
    """
    url = f"{ado_url.rstrip('/')}/_apis/connectionData"
    resp = httpx.get(
        url,
        headers=_auth_headers(pat),
        params={"api-version": API_VERSION},
        timeout=10.0,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()

    user = data.get("authenticatedUser", {})
    user_id = user.get("id", "")
    # ADO Server returns the display name under providerDisplayName
    display_name = (
        user.get("providerDisplayName")
        or user.get("customDisplayName")
        or user.get("subjectDescriptor", "")
    )

    if not user_id:
        raise ValueError(
            "ADO returned no user ID — check the organisation URL and PAT.",
        )

    return {"user_id": user_id, "display_name": display_name}


def resolve_callback_url(port: int) -> str:
    """Return the best available LAN IP for this machine formatted as a callback URL.

    Uses a UDP connect trick to find the IP the OS would use when talking to
    an external host — this avoids returning 127.0.0.1 or the wrong interface
    on multi-homed machines.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Doesn't actually send anything — just lets the OS pick a source IP
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    return f"http://{ip}:{port}/notify"
