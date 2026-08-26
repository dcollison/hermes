# Standard
import argparse
import getpass
import logging
import os
import sys
import threading
import time

# Remote
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Local
from . import __version__, startup
from .ado import resolve_callback_url, resolve_identity
from .config import ClientSettings, default_env_file_path
from .notifier import show_notification

logger = logging.getLogger("hermes.client")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Hermes Client", version=__version__)


@app.post("/notify")
async def receive_notification(request: Request) -> JSONResponse:
    """Receive an incoming notification payload and trigger desktop toast display.

    :param request: Incoming FastAPI Request containing the notification JSON.
    :returns: JSONResponse acknowledging notification receipt.
    """
    payload = await request.json()
    logger.info(f"Received: {payload.get('heading', '?')}")
    threading.Thread(target=show_notification, args=(payload,), daemon=True).start()
    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for the client notification listener.

    :returns: Dictionary with service status and client version.
    """
    return {"status": "ok", "service": "Hermes Client", "version": __version__}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_with_server(
    settings: ClientSettings,
    retries: int = 5,
) -> dict[str, object] | None:
    """Register this client instance with the Hermes server.

    :param settings: Configured client settings.
    :param retries: Number of connection attempts before failing.
    :returns: Server registration response dictionary, or None if unreachable.
    """
    payload = {
        "name": settings.CLIENT_NAME,
        "callback_url": settings.CALLBACK_URL,
        "ado_user_id": settings.ADO_USER_ID,
        "display_name": settings.ADO_DISPLAY_NAME,
        "subscriptions": settings.SUBSCRIPTIONS,
    }
    for attempt in range(1, retries + 1):
        try:
            resp = httpx.post(
                f"{settings.SERVER_URL.rstrip('/')}/clients/register",
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"Registered with Hermes server (ID: {data.get('id')})")
            return data
        except Exception as e:
            logger.warning(f"Registration attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    logger.error("Could not register with Hermes server. Notifications may not arrive.")
    return None


# ---------------------------------------------------------------------------
# `configure` command
# ---------------------------------------------------------------------------


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Prompt the user for terminal input with an optional default value.

    :param label: Text prompt label to display.
    :param default: Default string value used if input is blank.
    :param secret: Whether to mask user input via getpass for secrets.
    :returns: Entered string value or default.
    """
    hint = f" [{default if not secret else '***'}]" if default else ""
    prompt_str = f"  {label}{hint}: "
    if secret:
        value = getpass.getpass(prompt_str).strip()
    else:
        value = input(prompt_str).strip()
    return value or default


def _cmd_configure(args: argparse.Namespace) -> None:
    """Interactive wizard that resolves the user's ADO identity via their PAT
    and writes a complete .env.hermes-client config file.

    :param args: Parsed command line arguments.
    """
    # Load whatever exists already so we can offer it as defaults
    settings = ClientSettings()

    print()
    print("═" * 58)
    print("  Hermes Client — Configuration Wizard")
    print("═" * 58)
    print()
    print("Press Enter to accept the value shown in [brackets].")
    print()

    # --- Hermes server ---
    print("── Hermes Server ──────────────────────────────────────────")
    settings.SERVER_URL = _prompt("Hermes server URL", settings.SERVER_URL)

    # --- ADO ---
    print()
    print("── Azure DevOps ────────────────────────────────────────────")
    print("  Your PAT needs at least Read access to Identity and Profile.")
    settings.ADO_ORGANIZATION_URL = _prompt(
        "ADO organisation URL (e.g. http://ado-server/DefaultCollection)",
        settings.ADO_ORGANIZATION_URL,
    )
    settings.ADO_PAT = _prompt("Personal Access Token", settings.ADO_PAT, secret=True)

    # --- Resolve identity ---
    print()
    print("  Resolving your ADO identity…", end=" ", flush=True)
    try:
        identity = resolve_identity(settings.ADO_ORGANIZATION_URL, settings.ADO_PAT)
        settings.ADO_USER_ID = identity["user_id"]
        settings.ADO_DISPLAY_NAME = identity["display_name"]
        print("✓")
        print(f"  Name : {settings.ADO_DISPLAY_NAME}")
        print(f"  ID   : {settings.ADO_USER_ID}")
    except httpx.HTTPStatusError as e:
        print("✗")
        print(f"\n  ERROR: ADO returned HTTP {e.response.status_code}.")
        if e.response.status_code == 401:
            print("  The PAT may be invalid or expired, or the URL is wrong.")
        print("  You can enter the values manually below.")
        settings.ADO_USER_ID = _prompt("ADO user ID (GUID)", settings.ADO_USER_ID)
        settings.ADO_DISPLAY_NAME = _prompt(
            "ADO display name",
            settings.ADO_DISPLAY_NAME,
        )
    except Exception as e:
        print("✗")
        print(f"\n  ERROR: {e}")
        print("  You can enter the values manually below.")
        settings.ADO_USER_ID = _prompt("ADO user ID (GUID)", settings.ADO_USER_ID)
        settings.ADO_DISPLAY_NAME = _prompt(
            "ADO display name",
            settings.ADO_DISPLAY_NAME,
        )

    # --- Callback URL ---
    print()
    print("── Network ─────────────────────────────────────────────────")
    settings.LOCAL_PORT = int(_prompt("Local listener port", str(settings.LOCAL_PORT)))

    auto_callback = resolve_callback_url(settings.LOCAL_PORT)
    print(f"  Detected LAN IP: {auto_callback}")
    settings.CALLBACK_URL = _prompt(
        "Callback URL (the server will POST here)",
        auto_callback or settings.CALLBACK_URL,
    )

    # --- Optional overrides ---
    print()
    print("── Optional ────────────────────────────────────────────────")
    settings.CLIENT_NAME = _prompt("Client display name", settings.CLIENT_NAME)

    # --- Write ---
    print()
    target = default_env_file_path()
    written = settings.write_env_file(target)
    print(f"  Configuration saved to: {written}")
    print()
    print("  Next steps:")
    print("    hermes-client run               — start the client now")
    print("    hermes-client startup install   — register to start at login")
    print()


# ---------------------------------------------------------------------------
# `run` command
# ---------------------------------------------------------------------------


def _resolve_runtime_settings(args: argparse.Namespace) -> ClientSettings:
    """Load settings from the env file, apply CLI overrides, and auto-resolve missing values.

    :param args: Parsed command line arguments.
    :returns: Populated ClientSettings instance.
    """
    # Local
    from .ado import resolve_callback_url, resolve_identity

    settings = ClientSettings()

    # CLI overrides
    if getattr(args, "server", None):
        settings.SERVER_URL = args.server
    if getattr(args, "name", None):
        settings.CLIENT_NAME = args.name
    if getattr(args, "host", None):
        settings.LOCAL_HOST = args.host
    if getattr(args, "port", None):
        settings.LOCAL_PORT = args.port
    if getattr(args, "callback_url", None):
        settings.CALLBACK_URL = args.callback_url
    if getattr(args, "ado_user_id", None):
        settings.ADO_USER_ID = args.ado_user_id
    if getattr(args, "ado_display_name", None):
        settings.ADO_DISPLAY_NAME = args.ado_display_name

    # Auto-resolve callback URL if still blank
    if not settings.CALLBACK_URL:
        settings.CALLBACK_URL = resolve_callback_url(settings.LOCAL_PORT)
        logger.info(f"Callback URL auto-detected: {settings.CALLBACK_URL}")

    # Auto-resolve identity from PAT if user/name still missing
    if settings.ADO_ORGANIZATION_URL and settings.ADO_PAT:
        if not settings.ADO_USER_ID or not settings.ADO_DISPLAY_NAME:
            try:
                logger.info("Resolving ADO identity from PAT…")
                identity = resolve_identity(
                    settings.ADO_ORGANIZATION_URL,
                    settings.ADO_PAT,
                )
                settings.ADO_USER_ID = settings.ADO_USER_ID or identity["user_id"]
                settings.ADO_DISPLAY_NAME = (
                    settings.ADO_DISPLAY_NAME or identity["display_name"]
                )
                logger.info(
                    f"Identity resolved: {settings.ADO_DISPLAY_NAME} ({settings.ADO_USER_ID})",
                )
            except Exception as e:
                logger.warning(f"Could not resolve ADO identity: {e}")

    if not settings.ADO_USER_ID or not settings.ADO_DISPLAY_NAME:
        logger.warning(
            "ADO identity is not configured — notifications cannot be routed to you. "
            "Run `hermes-client configure` to set this up.",
        )

    return settings


def _cmd_run(args: argparse.Namespace) -> None:
    """Start the client listener web server and register with Hermes server.

    :param args: Parsed command line arguments.
    """
    if os.name == "nt":
        os.system("")

    settings = _resolve_runtime_settings(args)
    log_level = getattr(args, "log_level", "info")

    # Configure the standard Python logger dynamically
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )

    logger.info(
        f"Starting Hermes client '{settings.CLIENT_NAME}' "
        f"on {settings.LOCAL_HOST}:{settings.LOCAL_PORT}",
    )
    logger.info(f"Server       : {settings.SERVER_URL}")
    logger.info(f"Callback URL : {settings.CALLBACK_URL}")
    logger.info(
        f"Identity     : {settings.ADO_DISPLAY_NAME or '(not set)'} "
        f"({settings.ADO_USER_ID or 'none'})",
    )

    def _heartbeat_loop():
        time.sleep(2)
        reg_result = register_with_server(settings)
        if reg_result:
            display_user = settings.ADO_DISPLAY_NAME or settings.CLIENT_NAME
            show_notification(
                {
                    "heading": "Hermes Connected",
                    "body": f"Listening for notifications as {display_user}",
                    "status_image": "hermes",
                    "url": settings.SERVER_URL,
                },
            )
        else:
            show_notification(
                {
                    "heading": "Hermes Client Started",
                    "body": f"Retrying connection to {settings.SERVER_URL} in background",
                    "status_image": "failure",
                    "url": settings.SERVER_URL,
                },
            )

        while True:
            time.sleep(900)
            try:
                fresh_callback = resolve_callback_url(settings.LOCAL_PORT)
                if fresh_callback != settings.CALLBACK_URL:
                    settings.CALLBACK_URL = fresh_callback
                    logger.info(f"Updated callback URL after IP change: {fresh_callback}")
                register_with_server(settings, retries=2)
            except Exception as e:
                logger.debug(f"Periodic heartbeat failed: {e}")

    threading.Thread(target=_heartbeat_loop, daemon=True).start()
    uvicorn.run(
        app,
        host=settings.LOCAL_HOST,
        port=settings.LOCAL_PORT,
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# `startup` command
# ---------------------------------------------------------------------------


def _cmd_startup(args: argparse.Namespace) -> None:
    """Execute startup subcommands (install, remove, status).

    :param args: Parsed command line arguments.
    """
    {"install": startup.install, "remove": startup.remove, "status": startup.status}[
        args.startup_command
    ]()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Construct and return the client CLI argument parser.

    :returns: Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="hermes-client",
        description="Hermes — Azure DevOps notification client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hermes-client {__version__}",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # configure
    sub.add_parser(
        "configure",
        help="Resolve ADO identity from a PAT and write the config file",
    )

    # run
    run_p = sub.add_parser("run", help="Start the notification listener")
    run_p.add_argument("--server", metavar="URL", help="Hermes server URL")
    run_p.add_argument("--name", metavar="TEXT", help="Client display name")
    run_p.add_argument("--host", metavar="HOST", help="Local listen host")
    run_p.add_argument("--port", metavar="PORT", type=int, help="Local listen port")
    run_p.add_argument("--callback-url", metavar="URL", help="Override callback URL")
    run_p.add_argument(
        "--ado-user-id",
        metavar="GUID",
        help="Override ADO identity GUID",
    )
    run_p.add_argument(
        "--ado-display-name",
        metavar="NAME",
        help="Override ADO display name",
    )
    run_p.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Console log level (default: info)",
    )

    # startup
    startup_p = sub.add_parser("startup", help="Manage Windows startup integration")
    startup_sub = startup_p.add_subparsers(dest="startup_command", metavar="ACTION")
    startup_sub.required = True
    startup_sub.add_parser("install", help="Register as a Windows logon startup shortcut")
    startup_sub.add_parser("remove", help="Remove the Windows logon startup shortcut")
    startup_sub.add_parser("status", help="Show whether startup integration is installed")

    return parser


def main() -> None:
    """Main entrypoint for the hermes-client CLI."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "configure":
        _cmd_configure(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "startup":
        _cmd_startup(args)


if __name__ == "__main__":
    main()
