# Standard
import base64
import html
import logging
import os
import re
import tempfile
from importlib import resources

try:
    # Standard
    import winreg
except ImportError:
    winreg = None

# Remote
from win11toast import toast

# Local
from . import __app_id__, __app_name__

logger = logging.getLogger("hermes.client.notifier")

# Maps status_image keys to base bundled PNG filenames
_STATUS_ICONS = {
    "success": "succeeded",
    "succeeded": "succeeded",
    "completed": "succeeded",
    "failure": "failed",
    "failed": "failed",
    "rejected": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "stopped": "cancelled",
    "abandoned": "cancelled",
    "new pr": "pr",
    "pr": "pr",
    "pr completed": "merged",
    "pr merged": "merged",
    "pr comment": "comment",
    "pr updated": "pr",
    "bug": "bug",
    "epic": "epic",
    "feature": "feature",
    "task": "task",
    "user story": "userstory",
    "workitem comment": "comment",
    "manual": "hermes",
    "hermes": "hermes",
    "fallback": "hermes",
}

_BUILD_HUB_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apps/hub/ms\.vss-build-web\.[^?]+\?.*?\bbuildId=(\d+)",
    re.IGNORECASE,
)
_RELEASE_HUB_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apps/hub/ms\.vss-release-web\.[^?]+\?.*?\breleaseId=(\d+)",
    re.IGNORECASE,
)
_BUILD_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/build/builds/(\d+)",
    re.IGNORECASE,
)
_GIT_PR_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/git/repositories/([^/]+)/pullRequests/(\d+)",
    re.IGNORECASE,
)
_WIT_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/wit/workItems/(\d+)",
    re.IGNORECASE,
)
_RELEASE_API_RE = re.compile(
    r"(https?://[^/]+(?:/[^/]+)*?)/_apis/Release/releases/(\d+)",
    re.IGNORECASE,
)


def is_dark_mode() -> bool:
    """Detect if Windows 11 is currently set to dark theme mode.

    :returns: True if dark mode is active or registry lookup fails; False otherwise.
    """
    if not winreg:
        return True
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        # Default to dark if we can't read the registry
        return True


def _get_icon_filename(status_image_key: str | None) -> str:
    """Resolve a status key to a theme-aware icon filename.

    :param status_image_key: Key identifying the notification status icon.
    :returns: Theme-aware PNG filename (defaults to hermes.png).
    """
    key = (status_image_key or "fallback").lower()
    base_name = _STATUS_ICONS.get(key, "hermes")

    if base_name == "hermes":
        return "hermes.png"

    suffix = "dark" if is_dark_mode() else "light"
    return f"{base_name}-{suffix}.png"


def _clean_url(url: str) -> str:
    """Sanitize a notification click URL by unescaping HTML entities and canonicalizing AzDO URLs.

    :param url: Raw URL string.
    :returns: Cleaned URL string.
    """
    if not url:
        return ""
    url = html.unescape(url.strip())
    while "&amp;" in url:
        url = url.replace("&amp;", "&")

    if m := _BUILD_HUB_RE.search(url):
        return f"{m.group(1)}/_build/results?buildId={m.group(2)}"
    if m := _RELEASE_HUB_RE.search(url):
        return f"{m.group(1)}/_release?releaseId={m.group(2)}"
    if m := _BUILD_API_RE.search(url):
        return f"{m.group(1)}/_build/results?buildId={m.group(2)}"
    if m := _GIT_PR_API_RE.search(url):
        return f"{m.group(1)}/_git/{m.group(2)}/pullrequest/{m.group(3)}"

    wit_url = url.split("/revisions/")[0].split("/updates/")[0]
    if m := _WIT_API_RE.search(wit_url):
        return f"{m.group(1)}/_workitems/edit/{m.group(2)}"

    if m := _RELEASE_API_RE.search(url):
        return f"{m.group(1)}/_release?releaseId={m.group(2)}"

    return url


def show_notification(payload: dict[str, object]) -> None:
    """Display a Windows toast notification from a Hermes payload.

    :param payload: Notification dictionary received from the Hermes server.
    """
    heading: str = str(payload.get("heading", __app_name__))
    body: str = str(payload.get("body", ""))
    actor = str(payload.get("actor") or "").strip()
    if (
        payload.get("event_type") == "manual"
        and actor
        and actor != "Hermes"
        and actor not in body
        and actor not in heading
    ):
        body = f"{body}\n— {actor}" if body else f"— {actor}"

    url: str = _clean_url(str(payload.get("url") or ""))
    avatar_b64: str | None = payload.get("avatar_b64")  # type: ignore[assignment]
    raw_status_key = payload.get("status_image")
    status_image_key: str = str(raw_status_key) if raw_status_key else "fallback"

    avatar_path: str | None = _save_b64_image(avatar_b64) if avatar_b64 else None

    icon_filename = _get_icon_filename(status_image_key)
    status_image_path: str | None = (
        _get_bundled_icon(icon_filename) if icon_filename else None
    )

    try:
        _display(heading, body, url, avatar_path, status_image_path)
    finally:
        if avatar_path and os.path.exists(avatar_path):
            try:
                os.unlink(avatar_path)
            except Exception:
                pass


def _display(
    heading: str,
    body: str,
    url: str,
    avatar_path: str | None,
    status_image_path: str | None,
) -> None:
    """Render the toast notification using win11toast.

    :param heading: Notification title.
    :param body: Notification body text.
    :param url: Click-through URL opened when toast is clicked.
    :param avatar_path: Path to the sender avatar image file, or None.
    :param status_image_path: Path to the bundled status icon image file, or None.
    """
    url = _clean_url(url)
    logger.info(f"[TOAST] {heading}: {body}")

    try:
        kwargs: dict = {}

        if avatar_path:
            kwargs["icon"] = avatar_path
        elif status_image_path:
            kwargs["icon"] = status_image_path

        toast(
            heading,
            body,
            on_click=url if url else print,
            app_id=__app_id__,
            **kwargs,
        )
        logger.debug("Toast shown via win11toast")
        return
    except Exception as e:
        logger.debug(f"win11toast failed: {e}")


def _save_b64_image(b64: str) -> str | None:
    """Decode a base64 data URI and write it to a temp file.

    :param b64: Base64 data URI string.
    :returns: The temporary file path, or None if decoding fails.
    """
    try:
        if "," in b64:
            header, data = b64.split(",", 1)
            ext = "jpg" if ("jpeg" in header or "jpg" in header) else "png"
        else:
            data, ext = b64, "png"

        img_bytes = base64.b64decode(data)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
        tmp.write(img_bytes)
        tmp.close()
        return tmp.name
    except Exception as e:
        logger.debug(f"Failed to decode image: {e}")
        return None


def _get_bundled_icon(filename: str | None) -> str | None:
    """Return the filesystem path to a bundled icon, or None if not found.

    :param filename: Base filename of the bundled PNG icon.
    :returns: Absolute path to the icon file, or None if not found.
    """
    if not filename:
        return None
    try:
        ref = resources.files("hermes_client.icons") / filename
        if ref.is_file():
            return str(ref)
    except Exception:
        pass

    return None
