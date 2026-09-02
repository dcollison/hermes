# Standard
import argparse
import getpass
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

# Remote
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# Local
from . import __version__, process, startup
from .azdo import resolve_callback_url, resolve_identity
from .config import ClientSettings, _ensure_std_streams, default_env_file_path
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
@app.get("/status")
async def health() -> dict[str, object]:
    """Health and status check endpoint for the client notification listener.

    :returns: Dictionary with service status, PID, and client metadata.
    """
    settings: ClientSettings = getattr(app.state, "settings", None) or ClientSettings()
    return {
        "status": "ok",
        "service": "Hermes Client",
        "version": __version__,
        "pid": os.getpid(),
        "name": settings.CLIENT_NAME,
        "server_url": settings.SERVER_URL,
        "azdo_display_name": settings.AZDO_DISPLAY_NAME,
    }


@app.post("/shutdown")
async def shutdown(request: Request) -> JSONResponse:
    """Gracefully shutdown the running client listener process.

    Only accepts shutdown requests originating from localhost.

    :param request: Incoming FastAPI Request.
    :returns: JSONResponse acknowledging shutdown.
    :raises HTTPException: If request is not from localhost.
    """
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=403,
            detail="Shutdown only permitted from localhost",
        )

    def _delayed_shutdown() -> None:
        time.sleep(0.3)
        try:
            os.kill(
                os.getpid(),
                signal.SIGINT if sys.platform == "win32" else signal.SIGTERM,
            )
        except Exception:
            pass
        time.sleep(1.0)
        os._exit(0)

    threading.Thread(target=_delayed_shutdown, daemon=True).start()
    return JSONResponse({"status": "shutting_down", "pid": os.getpid()})


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
        "azdo_user_id": settings.AZDO_USER_ID,
        "ado_user_id": settings.AZDO_USER_ID,
        "display_name": settings.AZDO_DISPLAY_NAME,
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

            # Check if a newer version is deployed on the server
            server_ver = data.get("server_version")
            if server_ver and process.parse_version(str(server_ver)) > process.parse_version(__version__):
                logger.info(
                    f"Newer server version available: v{server_ver} (client is v{__version__})",
                )
                try:
                    show_notification(
                        {
                            "heading": "Hermes Update Available",
                            "body": f"Server is running v{server_ver}. Run 'hermes-client upgrade' to update.",
                            "status_image": "fallback",
                            "event_type": "manual",
                        }
                    )
                except Exception:
                    pass

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
    :param secret: Whether to mask user input for secrets.
    :returns: Entered string value or default.
    """
    hint = f" [{default if not secret else '***'}]" if default else ""
    prompt_str = f"  {label}{hint}: "
    if secret:
        # In environments like Git Bash (mintty) on Windows, sys.stdin is an MSYS pipe
        # rather than a native Windows console character device. getpass.getpass()
        # uses msvcrt.getwch() on Windows which hangs indefinitely if not attached
        # to a real console buffer. Fall back to input() when stdin is not a tty or on error.
        is_tty = hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
        if is_tty:
            try:
                value = getpass.getpass(prompt_str).strip()
            except (OSError, Exception):
                value = input(prompt_str).strip()
        else:
            value = input(prompt_str).strip()
    else:
        value = input(prompt_str).strip()
    return value or default


def _cmd_configure(args: argparse.Namespace) -> None:
    """Interactive wizard that resolves the user's AzDO identity via their PAT
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

    # --- AzDO ---
    print()
    print("── Azure DevOps ────────────────────────────────────────────")
    print("  Your PAT needs at least Read access to Identity and Profile.")
    settings.AZDO_ORGANIZATION_URL = _prompt(
        "AzDO organisation URL (e.g. http://ado-server/DefaultCollection)",
        settings.AZDO_ORGANIZATION_URL,
    )
    settings.AZDO_PAT = _prompt("Personal Access Token", settings.AZDO_PAT, secret=True)

    # --- Resolve identity ---
    print()
    print("  Resolving your AzDO identity…", end=" ", flush=True)
    try:
        identity = resolve_identity(settings.AZDO_ORGANIZATION_URL, settings.AZDO_PAT)
        settings.AZDO_USER_ID = identity["user_id"]
        settings.AZDO_DISPLAY_NAME = identity["display_name"]
        print("✓")
        print(f"  Name : {settings.AZDO_DISPLAY_NAME}")
        print(f"  ID   : {settings.AZDO_USER_ID}")
    except httpx.HTTPStatusError as e:
        print("✗")
        print(f"\n  ERROR: AzDO returned HTTP {e.response.status_code}.")
        if e.response.status_code == 401:
            print("  The PAT may be invalid or expired, or the URL is wrong.")
        print("  You can enter the values manually below.")
        settings.AZDO_USER_ID = _prompt("AzDO user ID (GUID)", settings.AZDO_USER_ID)
        settings.AZDO_DISPLAY_NAME = _prompt(
            "AzDO display name",
            settings.AZDO_DISPLAY_NAME,
        )
    except Exception as e:
        print("✗")
        print(f"\n  ERROR: {e}")
        print("  You can enter the values manually below.")
        settings.AZDO_USER_ID = _prompt("AzDO user ID (GUID)", settings.AZDO_USER_ID)
        settings.AZDO_DISPLAY_NAME = _prompt(
            "AzDO display name",
            settings.AZDO_DISPLAY_NAME,
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
    from .azdo import resolve_callback_url, resolve_identity

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
    if getattr(args, "log_file", None):
        settings.LOG_FILE = args.log_file

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
    settings = _resolve_runtime_settings(args)
    log_level = getattr(args, "log_level", "info")
    log_file = settings.LOG_FILE

    # Ensure streams are configured (redirecting None streams to log file or devnull)
    _ensure_std_streams(log_file)

    if os.name == "nt":
        os.system("")

    # Configure the standard Python logger dynamically
    handlers: list[logging.Handler] = []
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    if log_file and log_file.lower() != "devnull":
        try:
            log_path = Path(log_file).expanduser().resolve()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            if not (hasattr(sys.stderr, "name") and sys.stderr.name == str(log_path)):
                handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Could not open configured log file {log_file}: {e}")

    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers or None,
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
    app.state.settings = settings
    uvicorn.run(
        app,
        host=settings.LOCAL_HOST,
        port=settings.LOCAL_PORT,
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# Process management commands (start, stop, restart, status, upgrade)
# ---------------------------------------------------------------------------


def _cmd_start(args: argparse.Namespace) -> None:
    """Start the Hermes client in the background.

    :param args: Parsed command line arguments.
    """
    settings = ClientSettings()
    running, info = process.is_client_running(settings.LOCAL_PORT, settings.LOCAL_HOST)
    if running:
        pid = info.get("pid", "unknown") if info else "unknown"
        print(f"Hermes client is already running (PID: {pid}).")
        return

    print("Starting Hermes client in the background...", end=" ", flush=True)
    started, info = process.start_client()
    if started:
        print("✓")
        pid = info.get("pid", "unknown") if info else "unknown"
        print(
            f"Hermes client is running on http://127.0.0.1:{settings.LOCAL_PORT} (PID: {pid}).",
        )
    else:
        print("✗")
        print("Could not verify client startup. Run 'hermes-client run' to see error logs.")


def _cmd_stop(args: argparse.Namespace) -> None:
    """Stop the running background Hermes client.

    :param args: Parsed command line arguments.
    """
    settings = ClientSettings()
    running, _ = process.is_client_running(settings.LOCAL_PORT, settings.LOCAL_HOST)
    if not running:
        print("Hermes client is not running.")
        return

    print("Stopping Hermes client...", end=" ", flush=True)
    stopped = process.stop_client(settings.LOCAL_PORT, settings.LOCAL_HOST)
    if stopped:
        print("✓")
        print("Hermes client stopped.")
    else:
        print("✗")
        print("Could not cleanly stop Hermes client.")


def _cmd_restart(args: argparse.Namespace) -> None:
    """Restart the background Hermes client.

    :param args: Parsed command line arguments.
    """
    settings = ClientSettings()
    print("Restarting Hermes client...", end=" ", flush=True)
    started, info = process.restart_client()
    if started:
        print("✓")
        pid = info.get("pid", "unknown") if info else "unknown"
        print(
            f"Hermes client restarted on http://127.0.0.1:{settings.LOCAL_PORT} (PID: {pid}).",
        )
    else:
        print("✗")
        print("Could not restart Hermes client. Check logs or run 'hermes-client run'.")


def _cmd_status(args: argparse.Namespace) -> None:
    """Display runtime status and configuration of the Hermes client.

    :param args: Parsed command line arguments.
    """
    settings = ClientSettings()
    running, info = process.is_client_running(settings.LOCAL_PORT, settings.LOCAL_HOST)

    print()
    print("═" * 50)
    print("  Hermes Client Status")
    print("═" * 50)
    if running and info:
        print(f"  Status       : RUNNING (PID: {info.get('pid', 'unknown')})")
        print(f"  Version      : {info.get('version', __version__)}")
        print(f"  Listener     : http://{settings.LOCAL_HOST}:{settings.LOCAL_PORT}/notify")
        print(f"  Server URL   : {info.get('server_url', settings.SERVER_URL)}")
        print(f"  Display Name : {info.get('azdo_display_name', settings.AZDO_DISPLAY_NAME)}")
    else:
        print("  Status       : STOPPED (not running)")
        print(f"  Version      : {__version__}")
        print(f"  Server URL   : {settings.SERVER_URL}")
        print(f"  Display Name : {settings.AZDO_DISPLAY_NAME or '(not set)'}")

    print()
    startup.status()


def _cmd_upgrade(args: argparse.Namespace) -> None:
    """Perform in-place client upgrade and background restart.

    :param args: Parsed command line arguments.
    """
    print()
    print("═" * 50)
    print("  Hermes Client — Self Upgrade")
    print("═" * 50)
    package = getattr(args, "package", None) or "hermes"
    restart = not getattr(args, "no_restart", False)
    extra = getattr(args, "extra_args", None)
    process.upgrade_client(package_name=package, restart=restart, extra_args=extra)


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
        help="Resolve AzDO identity from a PAT and write the config file",
    )

    # start
    sub.add_parser(
        "start",
        help="Start the Hermes client in the background",
    )

    # stop
    sub.add_parser(
        "stop",
        help="Stop the running background Hermes client",
    )

    # restart
    sub.add_parser(
        "restart",
        help="Restart the background Hermes client",
    )

    # status
    sub.add_parser(
        "status",
        help="Show runtime status and startup configuration",
    )

    # upgrade / update
    upgrade_p = sub.add_parser(
        "upgrade",
        aliases=["update"],
        help="Upgrade Hermes package and restart the background client",
    )
    upgrade_p.add_argument(
        "--package",
        default="hermes",
        help="Package name or specifier to upgrade (default: hermes)",
    )
    upgrade_p.add_argument(
        "--no-restart",
        action="store_true",
        help="Do not restart the client after upgrading",
    )

    # run
    run_p = sub.add_parser("run", help="Start the notification listener (foreground)")
    run_p.add_argument("--server", metavar="URL", help="Hermes server URL")
    run_p.add_argument("--name", metavar="TEXT", help="Client display name")
    run_p.add_argument("--host", metavar="HOST", help="Local listen host")
    run_p.add_argument("--port", metavar="PORT", type=int, help="Local listen port")
    run_p.add_argument("--callback-url", metavar="URL", help="Override callback URL")
    run_p.add_argument(
        "--ado-user-id",
        "--azdo-user-id",
        dest="ado_user_id",
        metavar="GUID",
        help="Override AzDO identity GUID",
    )
    run_p.add_argument(
        "--ado-display-name",
        "--azdo-display-name",
        dest="ado_display_name",
        metavar="NAME",
        help="Override AzDO display name",
    )
    run_p.add_argument(
        "--log-file",
        metavar="FILE",
        help="Log file destination (default: %%APPDATA%%/Hermes/hermes-client.log or devnull)",
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
    _ensure_std_streams()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "configure":
        _cmd_configure(args)
    elif args.command == "start":
        _cmd_start(args)
    elif args.command == "stop":
        _cmd_stop(args)
    elif args.command == "restart":
        _cmd_restart(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command in ("upgrade", "update"):
        _cmd_upgrade(args)
    elif args.command == "run":
        _cmd_run(args)
    elif args.command == "startup":
        _cmd_startup(args)


if __name__ == "__main__":
    main()
