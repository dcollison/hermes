#!/usr/bin/env python3
"""simulate_webhook.py — Hermes local ADO webhook simulator

Simulates Azure DevOps webhook payloads and posts them to a local Hermes server.
Useful for testing the server and client routing logic without a real ADO instance.

Usage:
    python simulate_webhook.py list                 # List available events
    python simulate_webhook.py pr_created           # Simulate a PR being created
    python simulate_webhook.py workitem_assigned    # Simulate a bug assignment
    python simulate_webhook.py build_failed         # Simulate a failed build
"""

import argparse
import json
import sys

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required. Run: pip install httpx")
    sys.exit(1)

DEFAULT_SERVER = "http://localhost:8000"
WEBHOOK_ENDPOINT = "/webhooks/ado"

# The dummy ID used in your local client's .env.hermes-client
LOCAL_TESTER_ID = "11111111-1111-1111-1111-111111111111"
LOCAL_TESTER_NAME = "Local Tester"

# Another dummy ID to act as the person who triggered the event
ACTOR_ID = "22222222-2222-2222-2222-222222222222"
ACTOR_NAME = "Alice"

PAYLOADS = {
    "pr_created": {
        "description": "A new Pull Request where you are listed as a reviewer.",
        "payload": {
            "eventType": "git.pullrequest.created",
            "resource": {
                "pullRequestId": 42,
                "title": "Implement shiny new feature",
                "repository": {"name": "WebApp"},
                "sourceRefName": "refs/heads/feature-branch",
                "targetRefName": "refs/heads/main",
                "createdBy": {"id": ACTOR_ID, "displayName": ACTOR_NAME},
                "reviewers": [
                    {"id": LOCAL_TESTER_ID, "displayName": LOCAL_TESTER_NAME}
                ],
                "url": "http://fake-ado/pr/42"
            },
            "resourceContainers": {"project": {"name": "FakeProject"}}
        }
    },
    "pr_merged": {
        "description": "Your Pull Request gets merged by someone else.",
        "payload": {
            "eventType": "git.pullrequest.merged",
            "resource": {
                "pullRequestId": 42,
                "title": "Implement shiny new feature",
                "repository": {"name": "WebApp"},
                "status": "completed",
                "createdBy": {"id": LOCAL_TESTER_ID, "displayName": LOCAL_TESTER_NAME},
                "closedBy": {"id": ACTOR_ID, "displayName": ACTOR_NAME},
                "reviewers": [],
            },
            "resourceContainers": {"project": {"name": "FakeProject"}}
        }
    },
    "workitem_assigned": {
        "description": "A Bug gets assigned to you.",
        "payload": {
            "eventType": "workitem.updated",
            "resource": {
                "id": 404,
                "url": "http://fake-ado/_apis/wit/workItems/404",
                "fields": {
                    "System.WorkItemType": "Bug",
                    "System.Title": "Login button is unresponsive on mobile",
                    "System.State": "Active",
                    "System.AssignedTo": {"id": LOCAL_TESTER_ID, "displayName": LOCAL_TESTER_NAME},
                    "System.ChangedBy": {"id": ACTOR_ID, "displayName": ACTOR_NAME}
                }
            },
            "resourceContainers": {"project": {"name": "FakeProject"}}
        }
    },
    "build_failed": {
        "description": "A build you triggered has failed.",
        "payload": {
            "eventType": "build.complete",
            "resource": {
                "id": 999,
                "buildNumber": "20260227.1",
                "result": "failed",
                "definition": {"name": "Nightly Build"},
                "requestedFor": {"id": LOCAL_TESTER_ID, "displayName": LOCAL_TESTER_NAME},
                "_links": {"web": {"href": "http://fake-ado/build/999"}}
            },
            "resourceContainers": {"project": {"name": "FakeProject"}}
        }
    }
}


def main():
    parser = argparse.ArgumentParser(description="Simulate ADO webhook events for Hermes.")
    parser.add_argument(
        "event",
        choices=list(PAYLOADS.keys()) + ["list"],
        help="The event scenario to simulate, or 'list' to see options."
    )
    parser.add_argument(
        "--server", "-s",
        default=DEFAULT_SERVER,
        help=f"Hermes server URL (default: {DEFAULT_SERVER})"
    )

    args = parser.parse_args()

    if args.event == "list":
        print("Available simulated events:\n")
        for key, data in PAYLOADS.items():
            print(f"  {key:<20} {data['description']}")
        sys.exit(0)

    scenario = PAYLOADS[args.event]
    url = f"{args.server.rstrip('/')}{WEBHOOK_ENDPOINT}"

    print(f"Sending '{args.event}' event to {url} ...")

    try:
        resp = httpx.post(url, json=scenario["payload"], timeout=5.0)
        resp.raise_for_status()
        print(f"✓ Server accepted the webhook (Status: {resp.status_code})")
        print("  Check your screen for the toast notification!")
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Server returned {e.response.status_code}: {e.response.text}",
              file=sys.stderr)
    except Exception as e:
        print(f"ERROR: Could not reach Hermes server at {url}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()