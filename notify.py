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

try:
    # Remote
    import httpx
except ImportError:
    print("ERROR: httpx is required.  Run: pip install httpx")
    sys.exit(1)


def _load_dotenv(path: Path = Path(".env")):
    """Tiny .env loader — no dependencies."""
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DEFAULT_SERVER = os.environ.get("HERMES_SERVER_URL", "http://localhost:8000")


def _encode_image(path: str) -> str:
    """Read an image file and return a base64 data URI."""
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "ico": "image/x-icon",
    }.get(ext, "image/png")

    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{data}"


def main():
    parser = argparse.ArgumentParser(
        description="Send a manual notification to all Hermes clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python notify.py "Heads up" "Prod deployment in 5 minutes"
  python notify.py "Build failed" "Pipeline #42 failed on main" --image fail.png
  python notify.py "Done" "Release shipped!" --server http://build-server:8000
        """,
    )

    parser.add_argument("title", help="Notification title")
    parser.add_argument("message", help="Notification body text")
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
        default=DEFAULT_SERVER,
        metavar="URL",
        help=f"Hermes server URL (default: {DEFAULT_SERVER})",
    )
    parser.add_argument(
        "--url",
        "-u",
        default=None,
        metavar="URL",
        help="Optional click-through URL attached to the notification",
    )

    args = parser.parse_args()

    # Build payload
    payload: dict = {
        "heading": args.title,
        "body": args.message,
        "url": args.url,
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
        print(f"✓ {result.get('message', 'Sent')}")
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
