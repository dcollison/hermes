# Remote
import pytest

from hermes_server.simulate import EVENTS, generate_payload


class TestSimulatePayloads:
    @pytest.mark.parametrize("event_name", EVENTS)
    def test_all_events_generate_valid_payload(self, event_name):
        user_id = "target-user-123"
        payload = generate_payload(event_name, user_id)
        assert isinstance(payload, dict)
        assert "eventType" in payload
        assert "resource" in payload
        assert "resourceContainers" in payload
