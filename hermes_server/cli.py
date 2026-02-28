"""
Hermes Server CLI — `hermes-server` console script.

Subcommands
-----------
  hermes-server run                  Start the webhook receiver and notification dispatcher
  hermes-server simulate             Fire a fake ADO webhook at a running server

Run options (all also readable from .env.hermes-server):
  --host HOST       Bind host            (default: 0.0.0.0)
  --port PORT       Bind port            (default: 8000)
  --reload          Enable auto-reload   (development only)
  --log-level LVL   Uvicorn log level    (default: info)

Simulate options:
  --server URL      Server to send the fake webhook to  (default: http://localhost:8000)
  --event NAME      Event type to simulate              (default: interactive menu)
  --user NAME       Display name of the acting user     (default: Your Name)
  --user-id GUID    ADO user ID of the acting user      (default: a random GUID)
  --list            Print all available event names and exit
"""

# Standard
import argparse
import sys

# Remote
import uvicorn

# Local
from . import __version__

# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _build_run_parser(sub):
    run_p = sub.add_parser("run", help="Start the server")
    run_p.add_argument(
        "--host", default=None, metavar="HOST", help="Bind host (default: 0.0.0.0)"
    )
    run_p.add_argument(
        "--port",
        default=None,
        type=int,
        metavar="PORT",
        help="Bind port (default: 8000)",
    )
    run_p.add_argument(
        "--reload", action="store_true", help="Enable auto-reload (development only)"
    )
    run_p.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        choices=["critical", "error", "warning", "info", "debug", "trace"],
        help="Uvicorn log level (default: info)",
    )


def _cmd_run(args: argparse.Namespace):
    # Local
    from .config import settings

    host = args.host or settings.HOST
    port = args.port or settings.PORT
    log_level = args.log_level or "info"
    uvicorn.run(
        "hermes_server.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=log_level,
        access_log=True,
    )


# ---------------------------------------------------------------------------
# simulate
# ---------------------------------------------------------------------------


def _build_simulate_parser(sub):
    sim_p = sub.add_parser(
        "simulate",
        help="Fire a fake ADO webhook at a running server for local testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Sends a realistic fake ADO webhook payload to a running Hermes server.\n"
            "Use this to test the full stack — formatting, dispatch, and client toasts —\n"
            "without needing a real Azure DevOps instance.\n\n"
            "The --user-id must match the ADO user ID of a registered client so that\n"
            "the dispatcher's mention-matching routes the notification to that client.\n\n"
            "Run `hermes-server simulate --list` to see all available event types."
        ),
    )
    sim_p.add_argument(
        "--server",
        default="http://localhost:8000",
        metavar="URL",
        help="Hermes server URL (default: http://localhost:8000)",
    )
    sim_p.add_argument(
        "--event",
        default=None,
        metavar="NAME",
        help="Event type to simulate (omit for interactive menu)",
    )
    sim_p.add_argument(
        "--user",
        default="Test User",
        metavar="NAME",
        help="Display name of the acting user (default: 'Test User')",
    )
    sim_p.add_argument(
        "--user-id",
        default=None,
        metavar="GUID",
        help="ADO user ID — must match a registered client to trigger routing",
    )
    sim_p.add_argument(
        "--list", action="store_true", help="List all available event names and exit"
    )


def _cmd_simulate(args: argparse.Namespace):
    # Standard
    import uuid

    # Remote
    import httpx

    # Local
    from .simulate import EVENTS

    if args.list:
        print("\nAvailable events:\n")
        for name, (_, description) in EVENTS.items():
            print(f"  {name:<26}  {description}")
        print()
        return

    # Resolve event name — interactive menu if not supplied
    event_name = args.event
    if not event_name:
        names = list(EVENTS.keys())
        print("\nChoose an event to simulate:\n")
        for i, (name, (_, description)) in enumerate(EVENTS.items(), 1):
            print(f"  {i:>2}.  {name:<26}  {description}")
        print()
        while True:
            raw = input("  Enter number or event name: ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(names):
                event_name = names[int(raw) - 1]
                break
            elif raw in EVENTS:
                event_name = raw
                break
            print(f"  Invalid choice — enter a number 1–{len(names)} or an event name.")

    if event_name not in EVENTS:
        print(f"Unknown event '{event_name}'. Run --list to see available events.")
        sys.exit(1)

    factory, description = EVENTS[event_name]
    user_id = args.user_id or str(uuid.uuid4())
    user = {
        "id": user_id,
        "displayName": args.user,
        "uniqueName": f"{args.user.lower().replace(' ', '.')}@corp.local",
    }

    if not args.user_id:
        print(
            f"\n   No --user-id supplied. Using random ID: {user_id}\n"
            f"     This notification will broadcast to all subscribed clients\n"
            f"     rather than routing by mention. To test mention routing,\n"
            f"     pass the ADO user ID of your registered client.\n"
        )

    payload = factory(user)
    url = f"{args.server.rstrip('/')}/webhooks/ado"

    print(f"\n  Simulating : {event_name}")
    print(f"  User       : {args.user} ({user_id})")
    print(f"  Sending to : {url}")
    print()

    try:
        resp = httpx.post(url, json=payload, timeout=10.0)
        if resp.status_code == 200:
            print(f"     Server accepted the webhook ({resp.status_code})")
            print(f"     Response: {resp.json()}")
        else:
            print(f"     Server returned {resp.status_code}: {resp.text}")
    except httpx.ConnectError:
        print(f"     Could not connect to {url}")
        print(f"     Is the server running?  hermes-server run")
        sys.exit(1)
    except Exception as e:
        print(f"     Request failed: {e}")
        sys.exit(1)

    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-server",
        description="Hermes — Azure DevOps webhook receiver and notification dispatcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"hermes-server {__version__}"
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    _build_run_parser(sub)
    _build_simulate_parser(sub)

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "simulate":
        _cmd_simulate(args)


if __name__ == "__main__":
    main()
