# Standard
import logging

# Remote
from fastapi import APIRouter, HTTPException
from pydantic import AliasChoices, BaseModel, Field

# Local
from ..database import (
    delete_client,
    get_all_clients,
    get_client,
    get_client_by_callback,
    make_client,
    save_client,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class RegisterRequest(BaseModel):
    name: str  # Human-readable label, e.g. "Dale's PC"
    callback_url: str  # e.g. http://192.168.1.50:9000/notify
    azdo_user_id: str = Field(
        default="",
        validation_alias=AliasChoices("azdo_user_id", "ado_user_id"),
    )  # AzDO identity ID (GUID) — used for mention matching
    display_name: str  # AzDO display name — used for group name matching
    subscriptions: list[str] = ["pr", "workitem", "pipeline", "manual"]

    @property
    def ado_user_id(self) -> str:
        return self.azdo_user_id


class ClientResponse(BaseModel):
    id: str
    name: str
    callback_url: str
    azdo_user_id: str = Field(
        default="",
        validation_alias=AliasChoices("azdo_user_id", "ado_user_id"),
    )
    ado_user_id: str = ""
    display_name: str
    subscriptions: list[str]
    active: bool
    server_version: str | None = None


def _to_response(client: dict) -> ClientResponse:
    """Convert an internal client dictionary record into a ClientResponse model.

    :param client: Client record dictionary.
    :returns: ClientResponse schema instance.
    """
    # Local
    from .. import __version__

    uid = client.get("azdo_user_id") or client.get("ado_user_id", "")
    return ClientResponse(
        id=client["id"],
        name=client["name"],
        callback_url=client["callback_url"],
        azdo_user_id=uid,
        ado_user_id=uid,
        display_name=client.get("display_name", ""),
        subscriptions=client.get("subscriptions", []),
        active=client.get("active", True),
        server_version=__version__,
    )


@router.post("/register", response_model=ClientResponse)
async def register_client(body: RegisterRequest) -> ClientResponse:
    """Register (or re-register) a client.

    Re-registering with the same callback_url updates the existing record —
    safe to call on every client startup.

    :param body: Client registration parameters.
    :returns: Registered ClientResponse data.
    """
    existing = await get_client_by_callback(body.callback_url)
    uid = body.azdo_user_id or body.ado_user_id
    if existing:
        existing.update(
            {
                "name": body.name,
                "azdo_user_id": uid,
                "ado_user_id": uid,
                "display_name": body.display_name,
                "subscriptions": body.subscriptions,
                "active": True,
            },
        )
        await save_client(existing)
        logger.info(f"Updated client registration: {body.name} ({body.callback_url})")
        return _to_response(existing)

    client = make_client(
        name=body.name,
        callback_url=body.callback_url,
        azdo_user_id=uid,
        ado_user_id=uid,
        display_name=body.display_name,
        subscriptions=body.subscriptions,
    )
    await save_client(client)
    logger.info(f"Registered new client: {body.name} ({body.callback_url})")
    return _to_response(client)


@router.get("/", response_model=list[ClientResponse])
async def list_clients() -> list[ClientResponse]:
    """List all registered clients.

    :returns: List of ClientResponse objects.
    """
    clients = await get_all_clients()
    return [_to_response(c) for c in clients]


@router.delete("/{client_id}")
async def unregister_client(client_id: str) -> dict[str, str]:
    """Unregister a client.

    :param client_id: Unique client identifier.
    :returns: Dictionary with status and client ID.
    :raises HTTPException: If client ID is not found.
    """
    found = await delete_client(client_id)
    if not found:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"status": "unregistered", "id": client_id}


@router.put("/{client_id}/subscriptions", response_model=ClientResponse)
async def update_subscriptions(
    client_id: str,
    subscriptions: list[str],
) -> ClientResponse:
    """Update which event types a client subscribes to.

    :param client_id: Unique client identifier.
    :param subscriptions: List of event type category strings.
    :returns: Updated ClientResponse.
    :raises HTTPException: If client ID is not found.
    """
    client = await get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client["subscriptions"] = subscriptions
    await save_client(client)
    return _to_response(client)
