# Standard
import logging

# Remote
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    name: str  # Human-readable label, e.g. "Alice's PC"
    callback_url: str  # e.g. http://192.168.1.50:9000/notify
    ado_user_id: str  # ADO identity ID (GUID) — used for mention matching
    display_name: str  # ADO display name — used for group name matching
    subscriptions: list[str] = ["pr", "workitem", "pipeline", "manual"]


class ClientResponse(BaseModel):
    id: str
    name: str
    callback_url: str
    ado_user_id: str
    display_name: str
    subscriptions: list[str]
    active: bool


def _to_response(client: dict) -> ClientResponse:
    return ClientResponse(
        id=client["id"],
        name=client["name"],
        callback_url=client["callback_url"],
        ado_user_id=client.get("ado_user_id", ""),
        display_name=client.get("display_name", ""),
        subscriptions=client.get("subscriptions", []),
        active=client.get("active", True),
    )


@router.post("/register", response_model=ClientResponse)
async def register_client(body: RegisterRequest):
    """
    Register (or re-register) a client.

    Re-registering with the same callback_url updates the existing record —
    safe to call on every client startup.
    """
    existing = await get_client_by_callback(body.callback_url)
    if existing:
        existing.update(
            {
                "name": body.name,
                "ado_user_id": body.ado_user_id,
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
        ado_user_id=body.ado_user_id,
        display_name=body.display_name,
        subscriptions=body.subscriptions,
    )
    await save_client(client)
    logger.info(f"Registered new client: {body.name} ({body.callback_url})")
    return _to_response(client)


@router.get("/", response_model=list[ClientResponse])
async def list_clients():
    """
    List all registered clients.
    """
    clients = await get_all_clients()
    return [_to_response(c) for c in clients]


@router.delete("/{client_id}")
async def unregister_client(client_id: str):
    """
    Unregister a client.
    """
    found = await delete_client(client_id)
    if not found:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"status": "unregistered", "id": client_id}


@router.put("/{client_id}/subscriptions")
async def update_subscriptions(client_id: str, subscriptions: list[str]):
    """
    Update which event types a client subscribes to.
    """
    client = await get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    client["subscriptions"] = subscriptions
    await save_client(client)
    return _to_response(client)
