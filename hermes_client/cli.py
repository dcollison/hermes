"""
Hermes Client CLI — `hermes-client` console script.

Subcommands
-----------
  hermes-client configure            Resolve ADO identity and write config file
  hermes-client run                  Start the notification listener
  hermes-client startup install      Register as a Windows logon task
  hermes-client startup remove       Remove the Windows logon task
  hermes-client startup status       Check whether the task is registered
"""

# Standard
import argparse
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Remote
import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Local
from . import __version__
from .config import ClientSettings, _find_env_file, default_env_file_path
from .notifier import show_notification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hermes.client")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Hermes Client", version=__version__)


@app.post("/notify")
async def receive_notification(request: Request):
    payload = await request.json()
    logger.info(f"Received: {payload.get('heading', '?')}")
    threading.Thread(target=show_notification, args=(payload,), daemon=True).start()
    return JSONResponse({"status": "ok"})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Hermes Client", "version": __version__}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_with_server(settings: ClientSettings, retries: int = 5):
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


# ---------------------------------------------------------------------------
# `configure` command
# ---------------------------------------------------------------------------


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """
    Prompt the user for input. Shows the default in brackets.
    Masks input for secrets (PATs / passwords).
    """
    hint = f" [{default}]" if default else ""
    prompt_str = f"  {label}{hint}: "
    if secret:
        # Standard
        import getpass

        value = getpass.getpass(prompt_str)
    else:
        value = input(prompt_str).strip()
    return value or default


def _cmd_configure(args: argparse.Namespace):
    """
    Interactive wizard that resolves the user's ADO identity via their PAT
    and writes a complete .env.hermes-client config file.
    """
    # Local
    from .ado import resolve_callback_url, resolve_identity

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
            "ADO display name", settings.ADO_DISPLAY_NAME
        )
    except Exception as e:
        print("✗")
        print(f"\n  ERROR: {e}")
        print("  You can enter the values manually below.")
        settings.ADO_USER_ID = _prompt("ADO user ID (GUID)", settings.ADO_USER_ID)
        settings.ADO_DISPLAY_NAME = _prompt(
            "ADO display name", settings.ADO_DISPLAY_NAME
        )

    # --- Callback URL ---
    print()
    print("── Network ─────────────────────────────────────────────────")
    settings.LOCAL_PORT = int(_prompt("Local listener port", str(settings.LOCAL_PORT)))

    auto_callback = resolve_callback_url(settings.LOCAL_PORT)
    print(f"  Detected LAN IP: {auto_callback}")
    settings.CALLBACK_URL = _prompt(
        "Callback URL (the server will POST here)",
        settings.CALLBACK_URL or auto_callback,
    )

    # --- Optional overrides ---
    print()
    print("── Optional ────────────────────────────────────────────────")
    settings.CLIENT_NAME = _prompt("Client display name", settings.CLIENT_NAME)

    # --- Write ---
    print()
    target = default_env_file_path()
    written = settings.write_env_file(target)
    print(f"✓ Configuration saved to: {written}")
    print()
    print("  Next steps:")
    print("    hermes-client run               — start the client now")
    print("    hermes-client startup install   — register to start at login")
    print()


# ---------------------------------------------------------------------------
# `run` command
# ---------------------------------------------------------------------------


def _resolve_runtime_settings(args: argparse.Namespace) -> ClientSettings:
    """
    Load settings from the env file, apply any CLI overrides, then
    auto-resolve missing CALLBACK_URL / ADO identity if we have a PAT.
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
                    settings.ADO_ORGANIZATION_URL, settings.ADO_PAT
                )
                settings.ADO_USER_ID = settings.ADO_USER_ID or identity["user_id"]
                settings.ADO_DISPLAY_NAME = (
                    settings.ADO_DISPLAY_NAME or identity["display_name"]
                )
                logger.info(
                    f"Identity resolved: {settings.ADO_DISPLAY_NAME} ({settings.ADO_USER_ID})"
                )
            except Exception as e:
                logger.warning(f"Could not resolve ADO identity: {e}")

    if not settings.ADO_USER_ID or not settings.ADO_DISPLAY_NAME:
        logger.warning(
            "ADO identity is not configured — notifications cannot be routed to you. "
            "Run `hermes-client configure` to set this up."
        )

    return settings


def _cmd_run(args: argparse.Namespace):
    settings = _resolve_runtime_settings(args)

    logger.info(
        f"Starting Hermes client '{settings.CLIENT_NAME}' "
        f"on {settings.LOCAL_HOST}:{settings.LOCAL_PORT}"
    )
    logger.info(f"Server       : {settings.SERVER_URL}")
    logger.info(f"Callback URL : {settings.CALLBACK_URL}")
    logger.info(
        f"Identity     : {settings.ADO_DISPLAY_NAME or '(not set)'} "
        f"({settings.ADO_USER_ID or 'none'})"
    )

    def _register():
        time.sleep(2)
        register_with_server(settings)

    threading.Thread(target=_register, daemon=True).start()
    uvicorn.run(
        app,
        host=settings.LOCAL_HOST,
        port=settings.LOCAL_PORT,
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# `startup` command
# ---------------------------------------------------------------------------


def _cmd_startup(args: argparse.Namespace):
    # Local
    from . import startup

    {"install": startup.install, "remove": startup.remove, "status": startup.status}[
        args.startup_command
    ]()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-client",
        description="Hermes — Azure DevOps notification client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"hermes-client {__version__}"
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
        "--ado-user-id", metavar="GUID", help="Override ADO identity GUID"
    )
    run_p.add_argument(
        "--ado-display-name", metavar="NAME", help="Override ADO display name"
    )

    # startup
    startup_p = sub.add_parser("startup", help="Manage Windows startup integration")
    startup_sub = startup_p.add_subparsers(dest="startup_command", metavar="ACTION")
    startup_sub.required = True
    startup_sub.add_parser("install", help="Register as a Windows logon task")
    startup_sub.add_parser("remove", help="Remove the Windows logon task")
    startup_sub.add_parser("status", help="Show whether the task is registered")

    return parser


def main():
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
