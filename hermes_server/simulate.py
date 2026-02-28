# Standard
import argparse
import json
import urllib.request
from urllib.error import URLError

DEFAULT_URL = "http://localhost:8000/api/webhooks/ado"
DEFAULT_USER = "simulate-user"

EVENTS = [
    "pr-created",
    "pr-merged",
    "pr-updated",
    "pr-comment",
    "wi-bug",
    "wi-epic",
    "wi-feature",
    "wi-task",
    "wi-story",
    "wi-comment",
    "build-success",
    "build-fail",
    "build-cancel",
    "release-created",
    "release-success",
    "release-fail",
    "release-abandoned",
]


def _send(payload: dict, url: str):
    """Send the simulated webhook payload to the Hermes server."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"✅ Successfully sent to {url} (Status: {resp.status})")
    except URLError as e:
        print(f"❌ Failed to connect to {url}: {e}")


def generate_payload(event: str, target_user: str) -> dict:
    """Generate a fake ADO webhook payload for a given event type."""
    project = {"name": "Simulated Project"}
    resource_containers = {"project": project}

    # -----------------------------------------------------------------------
    # Pull Requests
    # -----------------------------------------------------------------------
    if event.startswith("pr-"):
        resource = {
            "pullRequestId": 1234,
            "title": f"Simulated PR for {event}",
            "repository": {"name": "sim-repo"},
            "sourceRefName": "refs/heads/feature/sim",
            "targetRefName": "refs/heads/main",
            "url": "http://localhost/pr/1234",
            "createdBy": {"id": "author-id", "displayName": "Sim Author"},
            "reviewers": [{"id": target_user, "displayName": "Sim Target User"}],
        }
        if event == "pr-created":
            return {
                "eventType": "git.pullrequest.created",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        elif event == "pr-merged":
            resource["closedBy"] = {"id": "merger-id", "displayName": "Sim Merger"}
            # Make the target user the PR author so they receive the merge notification
            resource["createdBy"] = {"id": target_user, "displayName": "Sim Target User"}
            return {
                "eventType": "git.pullrequest.merged",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        elif event == "pr-updated":
            resource["status"] = "active"
            return {
                "eventType": "git.pullrequest.updated",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        elif event == "pr-comment":
            return {
                "eventType": "ms.vss-code.git-pullrequest-comment-event",
                "resource": {
                    "pullRequest": resource,
                    "comment": {
                        "author": {"id": "commenter-id", "displayName": "Sim Commenter"},
                        "content": "This is a simulated comment.",
                    },
                },
                "resourceContainers": resource_containers,
            }

    # -----------------------------------------------------------------------
    # Work Items
    # -----------------------------------------------------------------------
    elif event.startswith("wi-"):
        wi_type_map = {
            "wi-bug": "Bug",
            "wi-epic": "Epic",
            "wi-feature": "Feature",
            "wi-task": "Task",
            "wi-story": "User Story",
        }
        wi_type = wi_type_map.get(event, "Task")

        fields = {
            "System.WorkItemType": wi_type,
            "System.Title": f"Simulated {wi_type}",
            "System.State": "Active",
            "System.AssignedTo": {"id": target_user, "displayName": "Sim Target User"},
            "System.ChangedBy": {"id": "changer-id", "displayName": "Sim Changer"},
        }

        resource = {
            "id": 5678,
            "fields": fields,
            "url": "http://localhost/_apis/wit/workItems/5678",
        }

        if event == "wi-comment":
            return {
                "eventType": "workitem.commented",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        else:
            return {
                "eventType": "workitem.created",
                "resource": resource,
                "resourceContainers": resource_containers,
            }

    # -----------------------------------------------------------------------
    # Pipelines / Builds
    # -----------------------------------------------------------------------
    elif event.startswith("build-"):
        result_map = {
            "build-success": "succeeded",
            "build-fail": "failed",
            "build-cancel": "canceled",
        }
        resource = {
            "id": 9012,
            "buildNumber": "20260228.1",
            "result": result_map[event],
            "definition": {"name": "Simulated Pipeline"},
            "requestedFor": {"id": target_user, "displayName": "Sim Target User"},
            "_links": {"web": {"href": "http://localhost/build/9012"}},
        }
        return {
            "eventType": "build.complete",
            "resource": resource,
            "resourceContainers": resource_containers,
        }

    # -----------------------------------------------------------------------
    # Releases
    # -----------------------------------------------------------------------
    elif event.startswith("release-"):
        if event == "release-abandoned":
            resource = {
                "name": "Sim-Release-1",
                "modifiedBy": {"id": "abandoner-id", "displayName": "Sim Abandoner"},
                "_links": {"web": {"href": "http://localhost/release/1"}},
            }
            return {
                "eventType": "ms.vss-release.release-abandoned-event",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        elif event == "release-created":
            resource = {
                "name": "Sim-Release-1",
                "releaseDefinition": {"name": "Main release"},
                "createdBy": {"id": "creator-id", "displayName": "Sim Creator"},
                "_links": {"web": {"href": "http://localhost/release/1"}},
            }
            return {
                "eventType": "ms.vss-release.release-created-event",
                "resource": resource,
                "resourceContainers": resource_containers,
            }
        else:
            status_map = {
                "release-success": "succeeded",
                "release-fail": "failed",
            }
            resource = {
                "environment": {"name": "Production", "status": status_map[event]},
                "release": {
                    "name": "Sim-Release-1",
                    "_links": {"web": {"href": "http://localhost/release/1"}},
                },
                "deployment": {
                    "requestedFor": {"id": target_user, "displayName": "Sim Target User"}
                },
            }
            return {
                "eventType": "ms.vss-release.deployment-completed-event",
                "resource": resource,
                "resourceContainers": resource_containers,
            }

    raise ValueError(f"Unknown event type: {event}")


def main():
    parser = argparse.ArgumentParser(description="Simulate ADO webhooks for Hermes")
    parser.add_argument(
        "event",
        choices=EVENTS + ["all"],
        help="The event type to simulate",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Webhook URL (default: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help="User ID to mention so you actually receive the toast (e.g. your email)",
    )

    args = parser.parse_args()

    events_to_run = EVENTS if args.event == "all" else [args.event]

    for ev in events_to_run:
        print(f"--- Simulating {ev} ---")
        payload = generate_payload(ev, args.user)
        _send(payload, args.url)


if __name__ == "__main__":
    main()