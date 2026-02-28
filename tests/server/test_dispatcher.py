# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Remote
import pytest


def _make_client(
    client_id="c1",
    ado_user_id="user-1",
    display_name="Alice",
    subscriptions=None,
    active=True,
    callback_url="http://host:9000/notify",
):
    return {
        "id": client_id,
        "name": "Test Client",
        "callback_url": callback_url,
        "ado_user_id": ado_user_id,
        "display_name": display_name,
        "subscriptions": subscriptions or ["pr", "workitem", "pipeline", "manual"],
        "active": active,
        "registered_at": "2026-01-01T00:00:00+00:00",
        "last_seen": None,
    }


def _make_notification(
    event_type="pr",
    actor_id=None,
    mentioned_user_ids=None,
    mentioned_names=None,
):
    return {
        "event_type": event_type,
        "heading": "Test",
        "body": "Test body",
        "actor_id": actor_id,
        "mentions": {
            "user_ids": mentioned_user_ids or [],
            "names": mentioned_names or [],
        },
        "status_image": None,
        "url": "",
        "project": "Proj",
        "avatar_b64": None,
        "meta": {},
    }


# ---------------------------------------------------------------------------
# _client_is_relevant
# ---------------------------------------------------------------------------


class TestClientIsRelevant:
    @pytest.fixture(autouse=True)
    def patch_groups(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": [], "names": []}),
        ):
            yield

    async def _check(self, client, notification):
        from hermes_server.dispatcher import _client_is_relevant

        return await _client_is_relevant(client, notification)

    # --- subscription ---

    async def test_matching_subscription_passes(self):
        assert (
            await self._check(
                _make_client(subscriptions=["pr"]),
                _make_notification(event_type="pr"),
            )
            is True
        )

    async def test_non_matching_subscription_blocked(self):
        assert (
            await self._check(
                _make_client(subscriptions=["workitem"]),
                _make_notification(event_type="pr"),
            )
            is False
        )

    async def test_all_subscription_matches_any_event(self):
        client = _make_client(subscriptions=["all"])
        for event_type in ("pr", "workitem", "pipeline", "manual"):
            assert (
                await self._check(client, _make_notification(event_type=event_type))
                is True
            )

    # --- manual always delivered ---

    async def test_manual_always_delivered_to_subscriber(self):
        assert (
            await self._check(
                _make_client(subscriptions=["manual"]),
                _make_notification(event_type="manual"),
            )
            is True
        )

    # --- actor suppression ---

    async def test_actor_does_not_receive_own_event(self):
        assert (
            await self._check(
                _make_client(ado_user_id="user-1"),
                _make_notification(actor_id="user-1", mentioned_user_ids=["user-1"]),
            )
            is False
        )

    async def test_other_user_not_suppressed_by_actor(self):
        assert (
            await self._check(
                _make_client(ado_user_id="user-2"),
                _make_notification(actor_id="user-1", mentioned_user_ids=["user-2"]),
            )
            is True
        )

    # --- broadcast ---

    async def test_broadcast_with_no_mentions_delivered_to_all(self):
        assert (
            await self._check(
                _make_client(subscriptions=["pr"]),
                _make_notification(
                    event_type="pr",
                    mentioned_user_ids=[],
                    mentioned_names=[],
                ),
            )
            is True
        )

    # --- direct user ID match ---

    async def test_mentioned_user_receives_notification(self):
        assert (
            await self._check(
                _make_client(ado_user_id="user-1"),
                _make_notification(mentioned_user_ids=["user-1"]),
            )
            is True
        )

    async def test_non_mentioned_user_blocked_when_mentions_exist(self):
        assert (
            await self._check(
                _make_client(ado_user_id="user-99"),
                _make_notification(mentioned_user_ids=["user-1"]),
            )
            is False
        )

    # --- group matching ---

    async def test_group_member_receives_notification(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": [], "names": ["Backend Team"]}),
        ):
            assert (
                await self._check(
                    _make_client(ado_user_id="user-1"),
                    _make_notification(mentioned_names=["Backend Team"]),
                )
                is True
            )

    async def test_group_match_by_id(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": ["group-123"], "names": []}),
        ):
            assert (
                await self._check(
                    _make_client(ado_user_id="user-1"),
                    _make_notification(mentioned_user_ids=["group-123"]),
                )
                is True
            )

    async def test_group_match_is_case_insensitive(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": [], "names": ["backend team"]}),
        ):
            assert (
                await self._check(
                    _make_client(ado_user_id="user-1"),
                    _make_notification(mentioned_names=["Backend Team"]),
                )
                is True
            )

    async def test_non_group_member_blocked(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": [], "names": ["Frontend Team"]}),
        ):
            assert (
                await self._check(
                    _make_client(ado_user_id="user-1"),
                    _make_notification(mentioned_names=["Backend Team"]),
                )
                is False
            )

    async def test_groups_not_fetched_when_user_id_already_matched(self):
        mock_groups = AsyncMock(return_value={"ids": [], "names": ["Some Group"]})
        with patch("hermes_server.dispatcher.get_user_groups", new=mock_groups):
            await self._check(
                _make_client(ado_user_id="user-1"),
                _make_notification(
                    mentioned_user_ids=["user-1"],
                    mentioned_names=["Some Group"],
                ),
            )
        mock_groups.assert_not_called()

    async def test_groups_fetched_when_unmatched_user_ids_exist(self):
        mock_groups = AsyncMock(return_value={"ids": [], "names": ["Backend Team"]})
        with patch("hermes_server.dispatcher.get_user_groups", new=mock_groups):
            await self._check(
                _make_client(ado_user_id="user-1"),
                _make_notification(mentioned_user_ids=["user-99"], mentioned_names=[]),
            )
        mock_groups.assert_called_once()


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    @pytest.fixture(autouse=True)
    def patch_groups(self):
        with patch(
            "hermes_server.dispatcher.get_user_groups",
            new=AsyncMock(return_value={"ids": [], "names": []}),
        ):
            yield

    def _mock_http(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)
        return mock_http

    async def test_eligible_client_receives_notification(self):
        client = _make_client(ado_user_id="user-1", callback_url="http://host/notify")
        notif = _make_notification(event_type="pr", mentioned_user_ids=["user-1"])
        mock_http = self._mock_http()

        with (
            patch(
                "hermes_server.dispatcher.get_all_clients",
                new=AsyncMock(return_value=[client]),
            ),
            patch("hermes_server.dispatcher.append_log", new=AsyncMock()),
            patch("hermes_server.dispatcher.save_client", new=AsyncMock()),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            from hermes_server.dispatcher import dispatch

            await dispatch(notif)

        mock_http.post.assert_called_once()
        assert mock_http.post.call_args[0][0] == "http://host/notify"

    async def test_ineligible_client_not_called(self):
        client = _make_client(ado_user_id="user-99")
        notif = _make_notification(event_type="pr", mentioned_user_ids=["user-1"])
        mock_http = self._mock_http()

        with (
            patch(
                "hermes_server.dispatcher.get_all_clients",
                new=AsyncMock(return_value=[client]),
            ),
            patch("hermes_server.dispatcher.append_log", new=AsyncMock()),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            from hermes_server.dispatcher import dispatch

            await dispatch(notif)

        mock_http.post.assert_not_called()

    async def test_inactive_client_skipped(self):
        client = _make_client(ado_user_id="user-1", active=False)
        notif = _make_notification(event_type="pr", mentioned_user_ids=["user-1"])
        mock_http = self._mock_http()

        with (
            patch(
                "hermes_server.dispatcher.get_all_clients",
                new=AsyncMock(return_value=[client]),
            ),
            patch("hermes_server.dispatcher.append_log", new=AsyncMock()),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            from hermes_server.dispatcher import dispatch

            await dispatch(notif)

        mock_http.post.assert_not_called()

    async def test_failed_delivery_logged_with_error(self):
        client = _make_client(ado_user_id="user-1", callback_url="http://host/notify")
        notif = _make_notification(event_type="pr", mentioned_user_ids=["user-1"])
        mock_log = AsyncMock()

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(side_effect=Exception("Connection refused"))

        with (
            patch(
                "hermes_server.dispatcher.get_all_clients",
                new=AsyncMock(return_value=[client]),
            ),
            patch("hermes_server.dispatcher.append_log", new=mock_log),
            patch("hermes_server.dispatcher.save_client", new=AsyncMock()),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            from hermes_server.dispatcher import dispatch

            await dispatch(notif)

        mock_log.assert_called_once()
        log_entry = mock_log.call_args[0][0]
        assert log_entry["success"] is False
        assert "Connection refused" in log_entry["error"]
