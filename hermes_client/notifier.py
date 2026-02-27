"""
Hermes Client — Toast notification display.

Tries toast backends in order:
  1. win11toast  (Windows 11, recommended)
  2. winotify    (Windows 10/11 fallback)
  3. plyer       (cross-platform dev fallback)

Notification payload fields used here:
  heading      str   — Toast title
  body         str   — Toast body text
  url          str   — Optional click-through URL
  avatar_b64   str   — Optional base64 data URI; shown as the app logo (small, round)
  status_image str   — Optional key: "success" | "failure" | "cancelled"
                       Shown as a large hero banner image at the top of the toast
  event_type   str   — pr / workitem / pipeline / manual
"""

import base64
import logging
import os
import tempfile
from importlib import resources
from typing import Optional

from . import __app_name__, __app_id__

logger = logging.getLogger("hermes.client.notifier")

# Maps status_image keys to bundled PNG filenames
_STATUS_ICONS = {
    "success":   "success.png",
    "failure":   "failure.png",
    "cancelled": "cancelled.png",
}

# Maps event_type to a small fallback icon (used by winotify when no avatar)
_EVENT_ICONS = {
    "pr":       "pr.png",
    "workitem": "workitem.png",
    "pipeline": "pipeline.png",
    "manual":   "hermes.png",
}


def show_notification(payload: dict):
    """Display a Windows toast notification from a Hermes payload."""
    heading = payload.get("heading", __app_name__)
    body = payload.get("body", "")
    url = payload.get("url") or ""
    avatar_b64: Optional[str] = payload.get("avatar_b64")
    status_image_key: Optional[str] = payload.get("status_image")
    event_type: str = payload.get("event_type", "")

    avatar_path: Optional[str] = _save_b64_image(avatar_b64) if avatar_b64 else None
    status_image_path: Optional[str] = _get_bundled_icon(
        _STATUS_ICONS.get(status_image_key, "")
    ) if status_image_key else None
    event_icon_path: Optional[str] = _get_bundled_icon(_EVENT_ICONS.get(event_type, "hermes.png"))

    try:
        _display(heading, body, url, avatar_path, status_image_path, event_icon_path)
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
    avatar_path: Optional[str],      # small round logo (app logo override)
    status_image_path: Optional[str], # large hero banner
    event_icon_path: Optional[str],   # fallback icon for winotify
):
    # --- win11toast ---
    try:
        from win11toast import toast

        kwargs: dict = {}

        # Hero image: large banner shown at the top of the toast
        if status_image_path:
            kwargs["hero"] = {"src": status_image_path, "alt": "status"}

        # App logo override: small image in the bottom-left corner
        if avatar_path:
            kwargs["image"] = {"src": avatar_path, "placement": "appLogoOverride"}

        def _on_click(args):
            if url:
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
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"win11toast failed: {e}")

    # --- winotify ---
    # winotify doesn't support hero images; use the status icon as the toast icon
    # so the result is still visually distinct.
    try:
        from winotify import Notification, audio

        icon = status_image_path or avatar_path or event_icon_path or ""
        notif = Notification(
            app_id=__app_name__,
            title=heading,
            msg=body,
            duration="short",
            icon=icon,
        )
        if url:
            notif.add_actions(label="Open", launch=url)
        notif.set_audio(audio.Default, loop=False)
        notif.show()
        logger.debug("Toast shown via winotify")
        return
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"winotify failed: {e}")

    # --- plyer ---
    try:
        from plyer import notification as plyer_notification
        plyer_notification.notify(
            title=heading,
            message=body,
            app_name=__app_name__,
            timeout=8,
        )
        logger.debug("Notification shown via plyer")
        return
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"plyer failed: {e}")

    logger.info(f"[TOAST] {heading}: {body}")


def _save_b64_image(b64: str) -> Optional[str]:
    """Decode a base64 data URI and write it to a temp file. Returns the path."""
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


def _get_bundled_icon(filename: str) -> Optional[str]:
    """Return the filesystem path to a bundled icon, or None if not found."""
    if not filename:
        return None
    try:
        ref = resources.files("hermes_client.icons") / filename
        if ref.is_file():
            return str(ref)
    except Exception:
        pass
    return None
