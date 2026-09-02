#!/usr/bin/env python3
"""notify.py — Hermes manual notification sender

Send a toast notification to all Hermes clients from the command line.

Usage:
    python notify.py "Title" "Message body"
    python notify.py "Heads up" "Deployment starts in 5 minutes" --image alert.png
    python notify.py "Done" "Build passed" --server http://build-server:8000

The server URL can also be set via the HERMES_SERVER_URL environment variable
or in a local .env file.
"""

# Standard
import argparse
import base64
import os
import sys
from pathlib import Path

__version__ = "2.0.0.dev17"



try:
    # Remote
    import httpx
except ImportError:
    print("ERROR: httpx is required.  Run: pip install httpx")
    sys.exit(1)


def _find_config_file() -> Path | None:
    """Search for Hermes configuration files in standard locations.

    Search order:
      1. ./.env.hermes-client
      2. ./.env
      3. ~/.env.hermes-client
      4. %APPDATA%/Hermes/.env.hermes-client (Windows)

    :returns: The first matching Path found, or None.
    """
    candidates = [
        Path.cwd() / ".env.hermes-client",
        Path.cwd() / ".env",
        Path.home() / ".env.hermes-client",
    ]
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Hermes" / ".env.hermes-client")

    for path in candidates:
        if path.exists():
            return path
    return None


def _load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Load key-value pairs from a config file.

    :param path: Optional Path to the config file. Searches standard locations if None.
    :returns: Dictionary of key-value pairs read from the file.
    """
    target = path or _find_config_file()
    config: dict[str, str] = {}
    if not target or not target.exists():
        return config

    try:
        with target.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                k = key.strip()
                v = value.strip().strip('"').strip("'")
                config[k] = v
    except Exception:
        pass
    return config


def _resolve_default_server(config: dict[str, str] | None = None) -> str:
    """Resolve the default Hermes server URL from environment or configuration.

    :param config: Optional loaded configuration dictionary.
    :returns: Hermes server URL.
    """
    cfg = config if config is not None else _load_dotenv()
    return (
        os.environ.get("HERMES_SERVER_URL")
        or os.environ.get("SERVER_URL")
        or cfg.get("HERMES_SERVER_URL")
        or cfg.get("SERVER_URL")
        or "http://localhost:8000"
    )


def _resolve_default_sender(config: dict[str, str] | None = None) -> str | None:
    """Resolve the default sender identity for manual notifications.

    :param config: Optional loaded configuration dictionary.
    :returns: Sender identity string or None.
    """
    cfg = config if config is not None else _load_dotenv()
    sender = (
        os.environ.get("HERMES_NOTIFY_FROM")
        or os.environ.get("AZDO_DISPLAY_NAME")
        or os.environ.get("ADO_DISPLAY_NAME")
        or cfg.get("AZDO_DISPLAY_NAME")
        or cfg.get("ADO_DISPLAY_NAME")
        or os.environ.get("CLIENT_NAME")
        or cfg.get("CLIENT_NAME")
        or os.environ.get("USERNAME")
        or os.environ.get("USER")
    )
    return sender.strip() if sender else None


DEFAULT_SERVER = _resolve_default_server()
DEFAULT_SENDER = _resolve_default_sender()


def _encode_image(path: str | Path) -> str:
    """Read an image file and return a base64 data URI.

    :param path: Filesystem path to the image file.
    :returns: Base64 data URI string with appropriate MIME type.
    """
    path_str = str(path)
    ext = os.path.splitext(path_str)[1].lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "ico": "image/x-icon",
    }.get(ext, "image/png")

    with open(path_str, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def main() -> None:
    """Main CLI entrypoint for sending manual notifications."""
    default_server = _resolve_default_server()
    default_sender = _resolve_default_sender()

    parser = argparse.ArgumentParser(
        description="Send a manual notification to all Hermes clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  hermes-notify "Heads up" "Prod deployment in 5 minutes"
  hermes-notify "Build failed" "Pipeline #42 failed on main" --from "CI Runner"
  hermes-notify "Done" "Release shipped!" --server http://build-server:8000
        """,
    )

    parser.add_argument("title", help="Notification title")
    parser.add_argument("message", help="Notification body text")
    parser.add_argument(
        "--from",
        "--sender",
        "-F",
        dest="sender",
        default=default_sender,
        metavar="SENDER",
        help=f"Sender name attached to the notification (default: {default_sender or 'Hermes'})",
    )
    parser.add_argument(
        "--image",
        "-i",
        metavar="FILE",
        type=Path,
        help="Optional image file to include (PNG, JPG, etc.)",
    )
    parser.add_argument(
        "--server",
        "-s",
        default=default_server,
        metavar="URL",
        help=f"Hermes server URL (default: {default_server})",
    )
    parser.add_argument(
        "--url",
        "-u",
        default=None,
        metavar="URL",
        help="Optional click-through URL attached to the notification",
    )
    parser.add_argument(
        "--filter-name",
        "-f",
        default=None,
        metavar="NAME",
        help="Filter target clients by name substring (e.g. Dale)",
    )
    parser.add_argument(
        "--project",
        "-p",
        default=None,
        metavar="PROJECT",
        help="Optional project name tag for the notification",
    )

    args = parser.parse_args()

    # Build payload
    payload: dict = {
        "heading": args.title,
        "body": args.message,
        "url": args.url,
        "filter_name_contains": args.filter_name,
        "filter_project": args.project,
        "actor": args.sender,
    }

    if args.image:
        if not args.image.is_file():
            print(f"ERROR: Image file not found: {args.image}", file=sys.stderr)
            sys.exit(1)
        try:
            payload["avatar_b64"] = _encode_image(args.image)
            print(f"Image attached: {args.image}")
        except Exception as e:
            print(
                f"WARNING: Could not read image ({e}) — sending without it.",
                file=sys.stderr,
            )

    # Send
    endpoint = f"{args.server.rstrip('/')}/notifications/send"
    print(f"Sending to {endpoint} ...")

    try:
        resp = httpx.post(endpoint, json=payload, timeout=10.0)
        resp.raise_for_status()
        result = resp.json()
        print(result.get("message", "Sent"))
    except httpx.HTTPStatusError as e:
        print(
            f"ERROR: Server returned {e.response.status_code}: {e.response.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"ERROR: Could not reach Hermes server at {args.server}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
