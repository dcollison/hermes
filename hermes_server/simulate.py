"""
Hermes — Fake ADO webhook payloads for local end-to-end testing.

Updated factories ensure that the test user is placed in the correct role
(e.g. Reviewer for new PRs, Author for Merged PRs) to bypass actor suppression
and test identity routing effectively.
"""

# Standard
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(display_name: str, user_id: str) -> dict:
    return {
        "id": user_id,
        "displayName": display_name,
        "uniqueName": f"{display_name.lower().replace(' ', '.')}@corp.local",
        "imageUrl": "",
    }


def _project(name: str = "MyProject") -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "url": "http://ado/MyProject"}


def _repo(name: str = "MyRepo") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "url": "http://ado/MyProject/_git/MyRepo",
        "remoteUrl": "http://ado/MyProject/_git/MyRepo",
    }


# ---------------------------------------------------------------------------
# Pull Request
# ---------------------------------------------------------------------------


def pr_created(user: dict, reviewer: dict = None) -> dict:
    """User is a reviewer on a new PR opened by someone else."""
    pr_id = 42
    author = _user("Alice (Dev)", str(uuid.uuid4()))
    # If the user is passed in, make THEM the reviewer so they see the toast
    return {
        "eventType": "git.pullrequest.created",
        "resource": {
            "pullRequestId": pr_id,
            "title": "Add simulated feature",
            "description": "This is a simulated PR for local testing.",
            "status": "active",
            "repository": _repo(),
            "sourceRefName": "refs/heads/feature/simulate",
            "targetRefName": "refs/heads/main",
            "url": f"http://ado/MyProject/_git/MyRepo/pullrequest/{pr_id}",
            "createdBy": author,
            "reviewers": [user],
            "creationDate": _now(),
        },
        "resourceContainers": {"project": _project()},
    }


def pr_merged(user: dict, merger: dict = None) -> dict:
    """User's PR is merged by someone else."""
    pr_id = 42
    merger = merger or _user("Build Master", str(uuid.uuid4()))
    return {
        "eventType": "git.pullrequest.merged",
        "resource": {
            "pullRequestId": pr_id,
            "title": "Add simulated feature",
            "status": "completed",
            "repository": _repo(),
            "sourceRefName": "refs/heads/feature/simulate",
            "targetRefName": "refs/heads/main",
            "url": f"http://ado/MyProject/_git/MyRepo/pullrequest/{pr_id}",
            "createdBy": user,
            "closedBy": merger,
            "reviewers": [],
            "closedDate": _now(),
        },
        "resourceContainers": {"project": _project()},
    }


def pr_comment(user: dict, commenter: dict = None) -> dict:
    """Someone comments on the user's PR."""
    pr_id = 42
    commenter = commenter or _user("Bob (Reviewer)", str(uuid.uuid4()))
    return {
        "eventType": "ms.vss-code.git-pullrequest-comment-event",
        "resource": {
            "comment": {
                "id": 1,
                "content": "Looks good, but can you add a test for the edge case?",
                "author": commenter,
                "publishedDate": _now(),
            },
            "pullRequest": {
                "pullRequestId": pr_id,
                "title": "Add simulated feature",
                "status": "active",
                "repository": _repo(),
                "sourceRefName": "refs/heads/feature/simulate",
                "targetRefName": "refs/heads/main",
                "url": f"http://ado/MyProject/_git/MyRepo/pullrequest/{pr_id}",
                "createdBy": user,
                "reviewers": [],
            },
        },
        "resourceContainers": {"project": _project()},
    }


# ---------------------------------------------------------------------------
# Work Items
# ---------------------------------------------------------------------------


def workitem_assigned(user: dict) -> dict:
    """A work item is assigned to the user."""
    return {
        "eventType": "workitem.updated",
        "resource": {
            "id": 99,
            "url": "http://ado/MyProject/_workitems/edit/99",
            "fields": {
                "System.WorkItemType": "Task",
                "System.Title": "Investigate the simulated issue",
                "System.State": "Active",
                "System.AssignedTo": user,
                "System.ChangedBy": _user("Scrum Master", str(uuid.uuid4())),
            },
        },
        "resourceContainers": {"project": _project()},
    }


def workitem_created(user: dict) -> dict:
    """A new bug is created and assigned to the user."""
    return {
        "eventType": "workitem.created",
        "resource": {
            "id": 100,
            "url": "http://ado/MyProject/_workitems/edit/100",
            "fields": {
                "System.WorkItemType": "Bug",
                "System.Title": "Simulated bug report",
                "System.State": "New",
                "System.AssignedTo": user,
                "System.ChangedBy": _user("QA Tester", str(uuid.uuid4())),
            },
        },
        "resourceContainers": {"project": _project()},
    }


# ---------------------------------------------------------------------------
# Pipelines / Builds
# ---------------------------------------------------------------------------


def build_succeeded(user: dict) -> dict:
    """A build requested by the user succeeded."""
    return {
        "eventType": "build.complete",
        "resource": {
            "id": 1001,
            "buildNumber": "20260101.1",
            "result": "succeeded",
            "status": "completed",
            "definition": {"name": "CI Pipeline"},
            "requestedFor": user,
            "_links": {
                "web": {"href": "http://ado/MyProject/_build/results?buildId=1001"}
            },
            "startTime": _now(),
            "finishTime": _now(),
        },
        "resourceContainers": {"project": _project()},
    }


def build_failed(user: dict) -> dict:
    """A build requested by the user failed."""
    payload = build_succeeded(user)
    payload["resource"]["result"] = "failed"
    payload["resource"]["buildNumber"] = "20260101.2"
    return payload


def deployment_succeeded(user: dict) -> dict:
    """A deployment requested by the user succeeded."""
    return {
        "eventType": "ms.vss-release.deployment-completed-event",
        "resource": {
            "environment": {"name": "Production", "status": "succeeded"},
            "release": {
                "name": "Release-42",
                "_links": {
                    "web": {
                        "href": "http://ado/MyProject/_releaseProgress?releaseId=42"
                    }
                },
            },
            "deployment": {"requestedFor": user},
        },
        "resourceContainers": {"project": _project()},
    }


def deployment_failed(user: dict) -> dict:
    """A deployment requested by the user failed."""
    payload = deployment_succeeded(user)
    payload["resource"]["environment"]["status"] = "failed"
    return payload


# ---------------------------------------------------------------------------
# Registry — maps CLI event names to factory functions
# ---------------------------------------------------------------------------

# Each entry: (factory_fn, description)
EVENTS: dict[str, tuple] = {
    "pr-created": (pr_created, "New PR opened (you are a reviewer)"),
    "pr-merged": (pr_merged, "Your PR was merged"),
    "pr-comment": (pr_comment, "Someone commented on your PR"),
    "workitem-assigned": (workitem_assigned, "Work item assigned to you"),
    "workitem-created": (workitem_created, "New bug assigned to you"),
    "build-succeeded": (build_succeeded, "Your build passed"),
    "build-failed": (build_failed, "Your build failed"),
    "deployment-succeeded": (deployment_succeeded, "Your deployment succeeded"),
    "deployment-failed": (deployment_failed, "Your deployment failed"),
}
