# Standard
from typing import Any

# Remote
from pydantic import BaseModel, Field


class Mentions(BaseModel):
    """Recipient mention identifiers extracted from an event."""

    user_ids: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)


class NotificationPayload(BaseModel):
    """Strongly-typed representation of a formatted Hermes notification."""

    event_type: str
    heading: str
    body: str
    url: str = ""
    project: str = ""
    avatar_b64: str | None = None
    status_image: str | None = None
    actor: str = "Someone"
    actor_id: str | None = None
    mentions: Mentions = Field(default_factory=Mentions)
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize notification payload to dictionary."""
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NotificationPayload":
        """Construct notification payload from dictionary data."""
        return cls.model_validate(data)


class ClientRecord(BaseModel):
    """Registered client recipient record."""

    id: str
    name: str
    callback_url: str
    ado_user_id: str
    display_name: str
    subscriptions: list[str] = Field(default_factory=list)
    active: bool = True
    registered_at: str
    last_seen: str | None = None


class DeliveryLogEntry(BaseModel):
    """Notification delivery log record."""

    id: str
    client_id: str
    event_type: str
    payload: dict[str, Any]
    success: bool
    error: str | None = None
    sent_at: str
