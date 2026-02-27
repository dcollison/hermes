# Standard
import base64
import logging
import os
import tempfile
from importlib import resources

# Remote
from win11toast import toast

# Local
from . import __app_id__, __app_name__

logger = logging.getLogger("hermes.client.notifier")

# Maps status_image keys to bundled PNG filenames
_STATUS_ICONS = {
    "success": "success.png",
    "failure": "failure.png",
    "cancelled": "cancelled.png",
}

# Maps event_type to a small fallback icon (used by winotify when no avatar)
_EVENT_ICONS = {
    "pr": "pr.png",
    "workitem": "workitem.png",
    "pipeline": "pipeline.png",
    "manual": "hermes.png",
}


def show_notification(payload: dict):
    """
    Display a Windows toast notification from a Hermes payload.
    """
    heading = payload.get("heading", __app_name__)
    body = payload.get("body", "")
    url = payload.get("url") or ""
    avatar_b64: str | None = payload.get("avatar_b64")
    status_image_key: str | None = payload.get("status_image")

    avatar_path: str | None = _save_b64_image(avatar_b64) if avatar_b64 else None
    status_image_path: str | None = (
        _get_bundled_icon(_STATUS_ICONS.get(status_image_key, ""))
        if status_image_key
        else None
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
):
    try:
        kwargs: dict = {}

        # Hero image: large banner shown at the top of the toast
        if status_image_path:
            kwargs["hero"] = {"src": status_image_path, "alt": "status"}

        # App logo override: small image in the bottom-left corner
        if avatar_path:
            kwargs["image"] = {"src": avatar_path, "placement": "appLogoOverride"}

        def _on_click(args):
            if url:
                # Standard
                import webbrowser

                webbrowser.open(url)

        toast(
            heading,
            body,
            on_click=_on_click if url else None,
            app_id=__app_id__,
            **kwargs,
        )
        logger.debug("Toast shown via win11toast")
        return
    except Exception as e:
        logger.debug(f"win11toast failed: {e}")

    logger.info(f"[TOAST] {heading}: {body}")


def _save_b64_image(b64: str) -> str | None:
    """
    Decode a base64 data URI and write it to a temp file.
    :returns: The path.
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


def _get_bundled_icon(filename: str) -> str | None:
    """
    Return the filesystem path to a bundled icon, or None if not found.
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
