# Standard
import base64
import logging
import socket

# Remote
import httpx

logger = logging.getLogger("hermes.client.azdo")

API_VERSION = "1.0"


def _auth_headers(pat: str) -> dict[str, str]:
    """Generate Basic Authentication HTTP headers for Azure DevOps REST endpoints.

    :param pat: Personal Access Token.
    :returns: Dictionary with Authorization and Accept headers.
    """
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def resolve_identity(azdo_url: str, pat: str) -> dict[str, str]:
    """Resolve the caller's AzDO identity via the Azure DevOps connectionData REST API endpoint.

    :param azdo_url: The Azure DevOps organization or collection base URL.
    :param pat: Personal Access Token with read access to the user profile.
    :returns: Dictionary with keys ``user_id`` and ``display_name``.
    :raises ValueError: If AzDO returns no user ID.
    :raises httpx.HTTPStatusError: On auth failure or HTTP error.
    """
    url = f"{azdo_url.rstrip('/')}/_apis/connectionData"
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
    # AzDO Server returns the display name under providerDisplayName
    display_name = (
        user.get("providerDisplayName")
        or user.get("customDisplayName")
        or user.get("subjectDescriptor", "")
    )

    if not user_id:
        raise ValueError(
            "AzDO returned no user ID — check the organisation URL and PAT.",
        )

    return {"user_id": user_id, "display_name": display_name}


def resolve_callback_url(port: int) -> str:
    """Resolve the local machine's reachable IP address and format the notification callback URL.

    :param port: The local TCP port the client listens on.
    :returns: The complete callback URL for notification delivery.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    return f"http://{ip}:{port}/notify"
