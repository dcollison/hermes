# Standard
import logging
import socket

# Remote
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication

logger = logging.getLogger("hermes.client.ado")


def resolve_identity(ado_url: str, pat: str) -> dict[str, str]:
    """Resolve the caller's ADO identity via the azure-devops SDK's profile client.

    :param ado_url: The Azure DevOps organization or collection base URL.
    :param pat: Personal Access Token with read access to the user profile.
    :returns: Dictionary with keys ``user_id`` and ``display_name``.
    :raises ValueError: If ADO returns no user ID.
    """
    connection = Connection(
        base_url=ado_url.rstrip("/"),
        creds=BasicAuthentication("", pat),
    )
    profile_client = connection.clients.get_profile_client()
    profile = profile_client.get_profile(id="me")

    user_id = getattr(profile, "id", "") or ""
    display_name = getattr(profile, "display_name", "") or ""

    if not user_id:
        raise ValueError(
            "ADO returned no user ID — check the organisation URL and PAT.",
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
