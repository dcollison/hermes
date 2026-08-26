from hermes_server.models import (
    ClientRecord,
    DeliveryLogEntry,
    Mentions,
    NotificationPayload,
)


def test_mentions_defaults():
    m = Mentions()
    assert m.user_ids == []
    assert m.names == []


def test_notification_payload_serialization():
    payload = NotificationPayload(
        event_type="pr",
        heading="PR Created",
        body="New PR",
        url="http://ado/pr/1",
        project="Proj",
        actor="Alice",
        mentions=Mentions(user_ids=["u-1"], names=["Bob"]),
        meta={"pr_id": 1},
    )
    d = payload.to_dict()
    assert d["event_type"] == "pr"
    assert d["mentions"]["user_ids"] == ["u-1"]
    assert d["meta"]["pr_id"] == 1

    reconstructed = NotificationPayload.from_dict(d)
    assert reconstructed.heading == "PR Created"
    assert reconstructed.mentions.names == ["Bob"]


def test_client_record_model():
    client = ClientRecord(
        id="c-123",
        name="My PC",
        callback_url="http://127.0.0.1:9000/notify",
        ado_user_id="u-1",
        display_name="Alice",
        registered_at="2026-01-01T00:00:00Z",
    )
    assert client.active is True
    assert client.subscriptions == []


def test_delivery_log_entry_model():
    entry = DeliveryLogEntry(
        id="l-1",
        client_id="c-1",
        event_type="workitem",
        payload={"foo": "bar"},
        success=True,
        sent_at="2026-01-01T00:00:00Z",
    )
    assert entry.error is None
    assert entry.success is True
