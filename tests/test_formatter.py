"""
Tests for hermes_server/formatter.py

Covers:
  - _mentions() logic (exclusion of actor, deduplication)
  - PR notifications (created, updated, merged, commented)
  - Work item notifications
  - Pipeline/build notifications (status_image mapping)
  - PR author always mentioned on merge
"""

# Standard
from unittest.mock import AsyncMock, patch

# Remote
import pytest


@pytest.fixture(autouse=True)
def no_avatar():
    with patch(
        "hermes_server.ado_client.get_user_avatar_b64", new=AsyncMock(return_value=None)
    ):
        yield


# ---------------------------------------------------------------------------
# _mentions  (synchronous — no event loop needed)
# ---------------------------------------------------------------------------


class TestMentions:
    def setup_method(self):
        # Remote
        from hermes_server.formatter import _mentions

        self._mentions = _mentions

    def test_empty(self):
        result = self._mentions()
        assert result == {"user_ids": [], "names": []}

    def test_single_identity(self):
        result = self._mentions({"id": "u1", "displayName": "Alice"})
        assert result["user_ids"] == ["u1"]
        assert result["names"] == ["Alice"]

    def test_actor_excluded(self):
        result = self._mentions({"id": "u1", "displayName": "Alice"}, actor_id="u1")
        assert result["user_ids"] == []
        assert result["names"] == []

    def test_deduplication(self):
        ident = {"id": "u1", "displayName": "Alice"}
        result = self._mentions(ident, ident)
        assert result["user_ids"] == ["u1"]

    def test_none_identities_skipped(self):
        result = self._mentions(None, {"id": "u1", "displayName": "Alice"}, None)
        assert result["user_ids"] == ["u1"]

    def test_actor_excluded_others_kept(self):
        result = self._mentions(
            {"id": "actor", "displayName": "Actor"},
            {"id": "other", "displayName": "Other"},
            actor_id="actor",
        )
        assert result["user_ids"] == ["other"]
        assert result["names"] == ["Other"]

    def test_identity_without_display_name(self):
        result = self._mentions({"id": "u1"})
        assert result["user_ids"] == ["u1"]
        assert result["names"] == []

    def test_uses_uniqueName_as_fallback_id(self):
        result = self._mentions(
            {"uniqueName": "alice@corp.com", "displayName": "Alice"}
        )
        assert result["user_ids"] == ["alice@corp.com"]


# ---------------------------------------------------------------------------
# PR events
# ---------------------------------------------------------------------------


class TestFormatPR:
    def _payload(self, event_type, resource_overrides=None):
        base_resource = {
            "pullRequestId": 42,
            "title": "Add feature X",
            "status": "active",
            "repository": {"name": "MyRepo"},
            "sourceRefName": "refs/heads/feature/x",
            "targetRefName": "refs/heads/main",
            "url": "http://ado/pr/42",
            "createdBy": {"id": "author-id", "displayName": "Alice"},
            "reviewers": [{"id": "reviewer-id", "displayName": "Bob"}],
        }
        if resource_overrides:
            base_resource.update(resource_overrides)
        return {
            "eventType": event_type,
            "resource": base_resource,
            "resourceContainers": {"project": {"name": "MyProject"}},
        }

    async def _format(self, event_type, resource_overrides=None):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = self._payload(event_type, resource_overrides)
        return await format_webhook(event_type, payload)

    async def test_pr_created_heading(self):
        notif = await self._format("git.pullrequest.created")
        assert notif["heading"] == "New Pull Request"
        assert notif["event_type"] == "pr"

    async def test_pr_created_mentions_reviewers_not_author(self):
        notif = await self._format("git.pullrequest.created")
        assert "reviewer-id" in notif["mentions"]["user_ids"]
        assert "author-id" not in notif["mentions"]["user_ids"]

    async def test_pr_updated_mentions_reviewers(self):
        notif = await self._format("git.pullrequest.updated")
        assert "reviewer-id" in notif["mentions"]["user_ids"]

    async def test_pr_merged_mentions_author_and_reviewers(self):
        # Carol merges the PR — Alice (author) and Bob (reviewer) should both be notified
        notif = await self._format(
            "git.pullrequest.merged",
            {
                "closedBy": {"id": "merger-id", "displayName": "Carol"},
            },
        )
        assert "author-id" in notif["mentions"]["user_ids"]
        assert "reviewer-id" in notif["mentions"]["user_ids"]
        assert "merger-id" not in notif["mentions"]["user_ids"]

    async def test_pr_merged_author_is_merger_still_notified(self):
        notif = await self._format(
            "git.pullrequest.merged",
            {
                "closedBy": {"id": "author-id", "displayName": "Alice"},
            },
        )
        assert "author-id" in notif["mentions"]["user_ids"]

    async def test_pr_merged_has_success_status_image(self):
        notif = await self._format("git.pullrequest.merged")
        assert notif["status_image"] == "success"

    async def test_pr_created_has_no_status_image(self):
        notif = await self._format("git.pullrequest.created")
        assert notif["status_image"] is None

    async def test_pr_comment_mentions_author_not_commenter(self):
        resource = {
            "pullRequest": {
                "pullRequestId": 42,
                "title": "Add feature X",
                "status": "active",
                "repository": {"name": "MyRepo"},
                "sourceRefName": "refs/heads/feature/x",
                "targetRefName": "refs/heads/main",
                "url": "http://ado/pr/42",
                "createdBy": {"id": "author-id", "displayName": "Alice"},
                "reviewers": [{"id": "reviewer-id", "displayName": "Bob"}],
            },
            "comment": {
                "author": {"id": "reviewer-id", "displayName": "Bob"},
                "content": "LGTM",
            },
        }
        # Remote
        from hermes_server.formatter import format_webhook

        event_type = "ms.vss-code.git-pullrequest-comment-event"
        notif = await format_webhook(
            event_type,
            {
                "eventType": event_type,
                "resource": resource,
                "resourceContainers": {"project": {"name": "MyProject"}},
            },
        )
        assert "author-id" in notif["mentions"]["user_ids"]
        assert "reviewer-id" not in notif["mentions"]["user_ids"]

    async def test_unknown_event_returns_none(self):
        # Remote
        from hermes_server.formatter import format_webhook

        result = await format_webhook("unknown.event.type", {})
        assert result is None

    async def test_project_extracted_from_resource_containers(self):
        notif = await self._format("git.pullrequest.created")
        assert notif["project"] == "MyProject"

    async def test_notification_has_all_required_fields(self):
        notif = await self._format("git.pullrequest.created")
        for field in (
            "event_type",
            "heading",
            "body",
            "url",
            "project",
            "avatar_b64",
            "status_image",
            "actor",
            "actor_id",
            "mentions",
            "meta",
        ):
            assert field in notif, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Work item events
# ---------------------------------------------------------------------------


class TestFormatWorkItem:
    async def _format(self, event_type, fields_override=None):
        # Remote
        from hermes_server.formatter import format_webhook

        fields = {
            "System.WorkItemType": "Task",
            "System.Title": "Fix the bug",
            "System.State": "Active",
            "System.AssignedTo": {"id": "assignee-id", "displayName": "Carol"},
            "System.ChangedBy": {"id": "changer-id", "displayName": "Dave"},
        }
        if fields_override:
            fields.update(fields_override)
        payload = {
            "resource": {"id": 99, "fields": fields, "url": "http://ado/wit/99"},
            "resourceContainers": {"project": {"name": "MyProject"}},
        }
        return await format_webhook(event_type, payload)

    async def test_created_mentions_assignee_not_creator(self):
        notif = await self._format("workitem.created")
        assert "assignee-id" in notif["mentions"]["user_ids"]
        assert "changer-id" not in notif["mentions"]["user_ids"]

    async def test_updated_mentions_assignee(self):
        notif = await self._format("workitem.updated")
        assert "assignee-id" in notif["mentions"]["user_ids"]

    async def test_workitem_has_no_status_image(self):
        notif = await self._format("workitem.created")
        assert notif["status_image"] is None

    async def test_unassigned_workitem_has_empty_mentions(self):
        notif = await self._format("workitem.created", {"System.AssignedTo": {}})
        assert notif["mentions"]["user_ids"] == []

    async def test_workitem_url_converted_from_api_to_web(self):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "id": 99,
                "fields": {
                    "System.WorkItemType": "Bug",
                    "System.Title": "A bug",
                    "System.State": "New",
                    "System.AssignedTo": {},
                    "System.ChangedBy": {"id": "u1", "displayName": "User"},
                },
                "url": "http://ado/_apis/wit/workItems/99",
            },
            "resourceContainers": {},
        }
        notif = await format_webhook("workitem.updated", payload)
        assert "/_apis/" not in notif["url"]
        assert "/_workitems/edit/" in notif["url"]


# ---------------------------------------------------------------------------
# Pipeline / build events
# ---------------------------------------------------------------------------


class TestFormatPipeline:
    def _build_payload(self, result, requested_for=None):
        return {
            "resource": {
                "id": 1,
                "buildNumber": "20260101.1",
                "result": result,
                "definition": {"name": "CI Pipeline"},
                "requestedFor": requested_for
                or {"id": "user-id", "displayName": "Alice"},
                "_links": {"web": {"href": "http://ado/build/1"}},
            },
            "resourceContainers": {"project": {"name": "MyProject"}},
        }

    async def _format_build(self, result, requested_for=None):
        # Remote
        from hermes_server.formatter import format_webhook

        return await format_webhook(
            "build.complete", self._build_payload(result, requested_for)
        )

    @pytest.mark.parametrize(
        "result,expected_image",
        [
            ("succeeded", "success"),
            ("failed", "failure"),
            ("canceled", "cancelled"),
            ("partiallysucceeded", "failure"),
        ],
    )
    async def test_build_status_image(self, result, expected_image):
        notif = await self._format_build(result)
        assert notif["status_image"] == expected_image

    async def test_build_notifies_triggerer(self):
        notif = await self._format_build(
            "succeeded", {"id": "user-id", "displayName": "Alice"}
        )
        assert "user-id" in notif["mentions"]["user_ids"]

    async def test_deployment_succeeded_status_image(self):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "environment": {"name": "Production", "status": "succeeded"},
                "release": {
                    "name": "Release-1",
                    "_links": {"web": {"href": "http://ado/release/1"}},
                },
                "deployment": {
                    "requestedFor": {"id": "deployer-id", "displayName": "Bob"}
                },
            },
            "resourceContainers": {"project": {"name": "MyProject"}},
        }
        notif = await format_webhook(
            "ms.vss-release.deployment-completed-event", payload
        )
        assert notif["status_image"] == "success"
        assert "deployer-id" in notif["mentions"]["user_ids"]

    async def test_deployment_failed_status_image(self):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "environment": {"name": "Production", "status": "failed"},
                "release": {"name": "Release-1", "_links": {"web": {"href": ""}}},
                "deployment": {
                    "requestedFor": {"id": "deployer-id", "displayName": "Bob"}
                },
            },
            "resourceContainers": {},
        }
        notif = await format_webhook(
            "ms.vss-release.deployment-completed-event", payload
        )
        assert notif["status_image"] == "failure"

    async def test_release_abandoned_status_image(self):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "name": "Release-2",
                "modifiedBy": {"id": "user-id", "displayName": "Alice"},
                "_links": {"web": {"href": "http://ado/release/2"}},
            },
            "resourceContainers": {},
        }
        notif = await format_webhook("ms.vss-release.release-abandoned-event", payload)
        assert notif["status_image"] == "cancelled"

    async def test_release_created_no_status_image(self):
        # Remote
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "name": "Release-1",
                "releaseDefinition": {"name": "Main release"},
                "createdBy": {"id": "user-id", "displayName": "Alice"},
                "_links": {"web": {"href": "http://ado/release/1"}},
            },
            "resourceContainers": {},
        }
        notif = await format_webhook("ms.vss-release.release-created-event", payload)
        assert notif["status_image"] is None
