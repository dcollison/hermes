# Standard
from unittest.mock import AsyncMock, MagicMock, patch

# Remote
import pytest


@pytest.fixture(autouse=True)
def no_avatar():
    with patch(
        "hermes_server.azdo_client.get_user_avatar_b64",
        new=AsyncMock(return_value=None),
    ):
        yield


# ---------------------------------------------------------------------------
# _mentions  (synchronous — no event loop needed)
# ---------------------------------------------------------------------------


class TestMentions:
    def setup_method(self):
        from hermes_server.formatter import _mentions

        self._mentions = _mentions

    def test_empty(self):
        result = self._mentions()
        assert result == {"user_ids": [], "names": []}

    def test_single_identity(self):
        result = self._mentions({"id": "u1", "displayName": "Dale"})
        assert result["user_ids"] == ["u1"]
        assert result["names"] == ["Dale"]

    def test_actor_excluded(self):
        result = self._mentions({"id": "u1", "displayName": "Dale"}, actor_id="u1")
        assert result["user_ids"] == []
        assert result["names"] == []

    def test_deduplication(self):
        ident = {"id": "u1", "displayName": "Dale"}
        result = self._mentions(ident, ident)
        assert result["user_ids"] == ["u1"]

    def test_none_identities_skipped(self):
        result = self._mentions(None, {"id": "u1", "displayName": "Dale"}, None)
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
            {"uniqueName": "dale@corp.com", "displayName": "Dale"},
        )
        assert result["user_ids"] == ["dale@corp.com"]

    def test_string_identities_parsed_as_names(self):
        result = self._mentions("Backend Team", {"id": "u1", "displayName": "Dale"})
        assert "Backend Team" in result["names"]
        assert "Dale" in result["names"]
        assert result["user_ids"] == ["u1"]

    def test_user_not_mentioned_if_name_in_message(self):
        result = self._mentions(
            {"id": "u1", "displayName": "Dale"},
            message="Bug #5 created by Dale.",
        )
        assert result == {"user_ids": [], "names": []}

    def test_user_mentioned_if_name_not_in_message(self):
        result = self._mentions(
            {"id": "u1", "displayName": "Alex"},
            message="Bug #5 created by Euan.",
        )
        assert result["user_ids"] == ["u1"]
        assert result["names"] == ["Alex"]

    def test_string_identity_not_mentioned_if_in_message(self):
        result = self._mentions(
            "Stephen",
            message="Stephen commented on PR #42",
        )
        assert result == {"user_ids": [], "names": []}

    def test_multiple_identities_message_filtering(self):
        result = self._mentions(
            {"id": "u1", "displayName": "Dale"},
            {"id": "u2", "displayName": "Taiye"},
            message="PR created by Dale",
        )
        assert result["user_ids"] == ["u2"]
        assert result["names"] == ["Taiye"]


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
            "createdBy": {"id": "author-id", "displayName": "Alex"},
            "reviewers": [{"id": "reviewer-id", "displayName": "Hamzaan"}],
        }
        if resource_overrides:
            base_resource.update(resource_overrides)
        return {
            "eventType": event_type,
            "resource": base_resource,
            "resourceContainers": {"project": {"name": "MyProject"}},
        }

    async def _format(self, event_type, resource_overrides=None):
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

    async def test_pr_completed_mentions_author_and_reviewers(self):
        # In 1.0, PR completes are updated events with status: completed
        notif = await self._format(
            "git.pullrequest.updated",
            {"status": "completed"},
        )
        assert notif is not None
        assert notif["heading"] == "PR Completed"
        assert notif["status_image"] == "pr completed"
        assert "author-id" in notif["mentions"]["user_ids"]
        assert "reviewer-id" in notif["mentions"]["user_ids"]

    async def test_pr_approved_and_completed_heading_and_actor(self):
        from hermes_server.formatter import format_webhook

        payload = self._payload(
            "git.pullrequest.updated",
            {"status": "completed"},
        )
        payload["message"] = {"text": "Hamzaan approved pull request 42"}

        notif = await format_webhook("git.pullrequest.updated", payload)
        assert notif is not None
        assert notif["heading"] == "PR Approved & Completed"
        assert notif["status_image"] == "pr completed"
        assert notif["actor"] == "Hamzaan"
        assert notif["actor_id"] == "reviewer-id"
        # Hamzaan approved, so author Alex is notified, Hamzaan is excluded
        assert "author-id" in notif["mentions"]["user_ids"]
        assert "reviewer-id" not in notif["mentions"]["user_ids"]

    async def test_pr_approved_active_heading_and_actor(self):
        from hermes_server.formatter import format_webhook

        payload = self._payload(
            "git.pullrequest.updated",
            {"status": "active"},
        )
        payload["message"] = {"text": "Hamzaan approved pull request 42"}

        notif = await format_webhook("git.pullrequest.updated", payload)
        assert notif is not None
        assert notif["heading"] == "PR Approved"
        assert notif["status_image"] == "pr updated"
        assert notif["actor"] == "Hamzaan"
        assert notif["actor_id"] == "reviewer-id"
        assert "author-id" in notif["mentions"]["user_ids"]
        assert "reviewer-id" not in notif["mentions"]["user_ids"]

    async def test_pr_completed_closed_by_actor(self):
        from hermes_server.formatter import format_webhook

        payload = self._payload(
            "git.pullrequest.updated",
            {
                "status": "completed",
                "closedBy": {"id": "closer-id", "displayName": "Liam"},
            },
        )
        payload["message"] = {"text": "Liam marked the pull request as completed"}

        notif = await format_webhook("git.pullrequest.updated", payload)
        assert notif is not None
        assert notif["heading"] == "PR Completed"
        assert notif["actor"] == "Liam"
        assert notif["actor_id"] == "closer-id"

    async def test_pr_merged_attempt_event_returns_none(self):
        # Background PR merge attempts (git.pullrequest.merged) should be ignored
        notif = await self._format("git.pullrequest.merged")
        assert notif is None

    async def test_pr_created_has_new_pr_status_image(self):
        notif = await self._format("git.pullrequest.created")
        assert notif["status_image"] == "new pr"

    async def test_pr_comment_excludes_commenter(self):
        # 1.0 comment payload structure
        resource = {
            "author": {"id": "commenter-id", "displayName": "Taiye"},
            "content": "LGTM",
            "_links": {
                "threads": {
                    "href": "http://ado/_apis/git/repositories/MyRepo/pullRequests/42/threads/1",
                },
            },
        }
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
        # Verify the commenter isn't pinged for their own comment
        assert "commenter-id" not in notif["mentions"]["user_ids"]
        # Verify PR ID was extracted from links
        assert "42" in notif["body"]

    async def test_pr_comment_notifies_thread_participants_excluding_commenter(self):
        resource = {
            "author": {"id": "commenter-id", "displayName": "Taiye"},
            "content": "LGTM",
            "_links": {
                "threads": {
                    "href": "http://ado/_apis/git/repositories/MyRepo/pullRequests/42/threads/1",
                },
            },
        }
        thread_authors = [
            {"id": "author-1", "displayName": "Dale"},
            {"id": "author-2", "displayName": "Liam"},
            {"id": "commenter-id", "displayName": "Taiye"},
        ]
        with patch(
            "hermes_server.formatter.get_thread_participants",
            new=AsyncMock(return_value=thread_authors),
        ):
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

        assert "author-1" in notif["mentions"]["user_ids"]
        assert "author-2" in notif["mentions"]["user_ids"]
        assert "commenter-id" not in notif["mentions"]["user_ids"]

    async def test_unknown_event_returns_none(self):
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
        from hermes_server.formatter import format_webhook

        fields = {
            "System.WorkItemType": "Task",
            "System.Title": "Fix the bug",
            "System.State": "Active",
            "System.AssignedTo": {"id": "assignee-id", "displayName": "Katherine"},
            "System.CreatedBy": {"id": "creator-id", "displayName": "Dale"},
            "System.ChangedBy": {"id": "changer-id", "displayName": "Simon"},
        }
        if fields_override:
            fields.update(fields_override)

        resource = {"id": 99, "url": "http://ado/wit/99"}

        # In 1.0, updates put the full object in `revision` and delta in `fields`
        if event_type == "workitem.updated":
            resource["revision"] = {"id": 99, "fields": fields.copy()}
            resource["fields"] = {
                "System.State": {"newValue": fields.get("System.State")},
            }
            resource["revisedBy"] = {"id": "changer-id", "displayName": "Simon"}
        else:
            resource["fields"] = fields.copy()

        payload = {
            "resource": resource,
            "resourceContainers": {"project": {"name": "MyProject"}},
        }
        return await format_webhook(event_type, payload)

    async def test_created_mentions_assignee_not_creator(self):
        notif = await self._format("workitem.created")
        assert "assignee-id" in notif["mentions"]["user_ids"]
        assert "creator-id" not in notif["mentions"]["user_ids"]

    async def test_updated_mentions_assignee(self):
        notif = await self._format("workitem.updated")
        assert "assignee-id" in notif["mentions"]["user_ids"]

    async def test_workitem_has_status_image_based_on_type(self):
        notif = await self._format("workitem.created")
        assert notif["status_image"] == "task"

    async def test_unassigned_workitem_has_empty_mentions(self):
        notif = await self._format("workitem.created", {"System.AssignedTo": {}})
        assert notif["mentions"]["user_ids"] == []
        assert notif["mentions"]["names"] == []

    async def test_workitem_url_converted_from_api_to_web(self):
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
        notif = await format_webhook("workitem.created", payload)
        assert "/_apis/" not in notif["url"]
        assert "/_workitems/edit/" in notif["url"]

    async def test_workitem_string_identities_parsed_and_filtered(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "id": 101,
                "fields": {
                    "System.WorkItemType": "Bug",
                    "System.Title": "Crash on login",
                    "System.State": "Active",
                    "System.AssignedTo": "Vinod <DOMAIN\\Vinod>",
                    "System.ChangedBy": "Dale <DOMAIN\\Dale>",
                },
                "url": "http://ado/_apis/wit/workItems/101",
            },
            "resourceContainers": {"project": {"name": "ProjectX"}},
        }
        notif = await format_webhook("workitem.updated", payload)
        assert notif["actor"] == "Dale"
        assert notif["meta"]["assigned_to"] == "Vinod"
        assert "Vinod" in notif["mentions"]["names"]
        assert "DOMAIN\\Vinod" in notif["mentions"]["names"]
        assert "Dale" not in notif["mentions"]["names"]

    async def test_workitem_self_edit_string_identity_excludes_self(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "id": 102,
                "fields": {
                    "System.WorkItemType": "Task",
                    "System.Title": "Refactor router",
                    "System.State": "Active",
                    "System.AssignedTo": "Dale <DOMAIN\\Dale>",
                    "System.ChangedBy": "Dale <DOMAIN\\Dale>",
                },
                "url": "http://ado/_apis/wit/workItems/102",
            },
            "resourceContainers": {"project": {"name": "ProjectX"}},
        }
        notif = await format_webhook("workitem.updated", payload)
        assert notif["actor"] == "Dale"
        assert notif["meta"]["assigned_to"] == "Dale"
        assert notif["mentions"]["names"] == []
        assert notif["mentions"]["user_ids"] == []


class TestParseIdentity:
    def test_composite_domain_account_string(self):
        from hermes_server.formatter import parse_identity

        res = parse_identity("Stephen <DOMAIN\\Stephen>")
        assert res["displayName"] == "Stephen"
        assert res["uniqueName"] == "DOMAIN\\Stephen"
        assert res["accountName"] == "Stephen"
        assert res["id"] is None

    def test_composite_email_string(self):
        from hermes_server.formatter import parse_identity

        res = parse_identity("Katherine <katherine@example.com>")
        assert res["displayName"] == "Katherine"
        assert res["uniqueName"] == "katherine@example.com"
        assert res["accountName"] == "katherine"

    def test_plain_display_name_string(self):
        from hermes_server.formatter import parse_identity

        res = parse_identity("Backend Engineers")
        assert res["displayName"] == "Backend Engineers"
        assert res["uniqueName"] == ""
        assert res["accountName"] == ""

    def test_identity_dict(self):
        from hermes_server.formatter import parse_identity

        res = parse_identity({"id": "u-123", "displayName": "Dale", "uniqueName": "DOMAIN\\Dale"})
        assert res["id"] == "u-123"
        assert res["displayName"] == "Dale"
        assert res["uniqueName"] == "DOMAIN\\Dale"
        assert res["accountName"] == "Dale"

    def test_none_or_empty(self):
        from hermes_server.formatter import parse_identity

        assert parse_identity(None) == {"id": None, "displayName": "", "uniqueName": "", "accountName": ""}
        assert parse_identity("") == {"id": None, "displayName": "", "uniqueName": "", "accountName": ""}
        assert parse_identity({}) == {"id": None, "displayName": "", "uniqueName": "", "accountName": ""}



# ---------------------------------------------------------------------------
# Pipeline / build events
# ---------------------------------------------------------------------------


class TestFormatPipeline:
    def _build_payload(self, status, requested_for=None):
        return {
            "resource": {
                "id": 1,
                "buildNumber": "20260101.1",
                "status": status,
                "definition": {"name": "CI Pipeline"},
                # 1.0 puts requestor inside a requests array
                "requests": [
                    {
                        "requestedFor": requested_for
                        or {"id": "user-id", "displayName": "Dale"},
                    },
                ],
                "_links": {"web": {"href": "http://ado/build/1"}},
            },
            "resourceContainers": {"project": {"name": "MyProject"}},
        }

    async def _format_build(self, status, requested_for=None):
        from hermes_server.formatter import format_webhook

        return await format_webhook(
            "build.complete",
            self._build_payload(status, requested_for),
        )

    @pytest.mark.parametrize(
        "status,expected_image",
        [
            ("succeeded", "success"),
            ("failed", "failure"),
            ("cancelled", "cancelled"),
            ("canceled", "cancelled"),
            ("stopped", "cancelled"),
            ("partiallysucceeded", "failure"),
        ],
    )
    async def test_build_status_image(self, status, expected_image):
        notif = await self._format_build(status)
        assert notif["status_image"] == expected_image

    async def test_build_notifies_triggerer(self):
        notif = await self._format_build(
            "succeeded",
            {"id": "user-id", "displayName": "Dale"},
        )
        assert "user-id" in notif["mentions"]["user_ids"]

    async def test_deployment_succeeded_status_image(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "environment": {"name": "Production", "status": "succeeded"},
                "release": {
                    "name": "Release-1",
                    "_links": {"web": {"href": "http://ado/release/1"}},
                },
                "deployment": {
                    "requestedFor": {"id": "deployer-id", "displayName": "David"},
                },
            },
            "resourceContainers": {"project": {"name": "MyProject"}},
        }
        notif = await format_webhook(
            "ms.vss-release.deployment-completed-event",
            payload,
        )
        assert notif["status_image"] == "success"
        assert "deployer-id" in notif["mentions"]["user_ids"]

    async def test_deployment_failed_status_image(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "environment": {"name": "Production", "status": "failed"},
                "release": {"name": "Release-1", "_links": {"web": {"href": ""}}},
                "deployment": {
                    "requestedFor": {"id": "deployer-id", "displayName": "David"},
                },
            },
            "resourceContainers": {},
        }
        notif = await format_webhook(
            "ms.vss-release.deployment-completed-event",
            payload,
        )
        assert notif["status_image"] == "failure"

    async def test_release_abandoned_status_image(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "name": "Release-2",
                "modifiedBy": {"id": "user-id", "displayName": "Tom"},
                "_links": {"web": {"href": "http://ado/release/2"}},
            },
            "resourceContainers": {},
        }
        notif = await format_webhook("ms.vss-release.release-abandoned-event", payload)
        assert notif["status_image"] == "cancelled"

    async def test_release_created_no_status_image(self):
        from hermes_server.formatter import format_webhook

        payload = {
            "resource": {
                "name": "Release-1",
                "releaseDefinition": {"name": "Main release"},
                "createdBy": {"id": "user-id", "displayName": "Rob"},
                "_links": {"web": {"href": "http://ado/release/1"}},
            },
            "resourceContainers": {},
        }
        notif = await format_webhook("ms.vss-release.release-created-event", payload)
        assert notif["status_image"] is None


class TestGetThreadParticipants:
    async def test_empty_or_missing_url(self):
        from hermes_server.azdo_client import get_thread_participants

        assert await get_thread_participants("") == []
        assert await get_thread_participants(None) == []

    async def test_successful_fetch(self):
        from hermes_server.azdo_client import get_thread_participants

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "comments": [
                {"author": {"id": "u1", "displayName": "Dale"}},
                {"author": {"id": "u2", "displayName": "Taiye"}},
                {"content": "no author"},
            ],
        }
        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_resp)

        with (
            patch("hermes_server.azdo_client.settings.AZDO_PAT", "pat"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            authors = await get_thread_participants("http://ado/thread/1")

        assert len(authors) == 2
        assert authors[0]["id"] == "u1"
        assert authors[1]["id"] == "u2"

    async def test_http_error_returns_empty_list(self):
        from hermes_server.azdo_client import get_thread_participants

        mock_http = MagicMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(side_effect=Exception("network error"))

        with (
            patch("hermes_server.azdo_client.settings.AZDO_PAT", "pat"),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            authors = await get_thread_participants("http://ado/thread/1")

        assert authors == []


class TestCleanUrl:
    def test_unescapes_ampersand_entities(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado/project/_git/repo/pullrequest/123?_a=overview&amp;iteration=1"
        assert _clean_url(url) == "http://ado/project/_git/repo/pullrequest/123?_a=overview&iteration=1"

    def test_unescapes_double_encoded_ampersand(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado/project/_git/repo/pullrequest/123?_a=overview&amp;amp;iteration=1"
        assert _clean_url(url) == "http://ado/project/_git/repo/pullrequest/123?_a=overview&iteration=1"

    def test_extract_message_unescapes_html_href(self):
        from hermes_server.formatter import _extract_message

        payload = {
            "message": {
                "text": "PR created",
                "html": '<a href="http://ado/pr/1?foo=bar&amp;baz=qux">View PR</a>',
            },
        }
        text, link = _extract_message(payload)
        assert text == "PR created"
        assert link == "http://ado/pr/1?foo=bar&baz=qux"

    def test_canonicalizes_vsix_build_hub_url(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado:8080/tfs/DefaultCollection/_apps/hub/ms.vss-build-web.run-result-hub?buildId=5678&planId=123"
        assert _clean_url(url) == "http://ado:8080/tfs/DefaultCollection/_build/results?buildId=5678"

    def test_canonicalizes_vsix_release_hub_url(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado:8080/tfs/DefaultCollection/ProjectName/_apps/hub/ms.vss-release-web.hub-explorer?releaseId=987"
        assert _clean_url(url) == "http://ado:8080/tfs/DefaultCollection/ProjectName/_release?releaseId=987"

    def test_canonicalizes_build_api_url(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado:8080/tfs/DefaultCollection/ProjectName/_apis/build/Builds/1234"
        assert _clean_url(url) == "http://ado:8080/tfs/DefaultCollection/ProjectName/_build/results?buildId=1234"

    def test_canonicalizes_git_pr_api_url(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado:8080/tfs/DefaultCollection/ProjectName/_apis/git/repositories/MyRepo/pullRequests/42"
        assert _clean_url(url) == "http://ado:8080/tfs/DefaultCollection/ProjectName/_git/MyRepo/pullrequest/42"

    def test_canonicalizes_wit_api_url(self):
        from hermes_server.formatter import _clean_url

        url = "http://ado:8080/tfs/DefaultCollection/_apis/wit/workItems/99/revisions/2"
        assert _clean_url(url) == "http://ado:8080/tfs/DefaultCollection/_workitems/edit/99"

