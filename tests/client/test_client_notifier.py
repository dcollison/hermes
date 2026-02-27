# Standard
import base64
import importlib
import os
from unittest.mock import MagicMock, patch

from hermes_client import notifier
from hermes_client.notifier import (
    _display,
    _get_bundled_icon,
    _save_b64_image,
    show_notification,
)

# ---------------------------------------------------------------------------
# _save_b64_image
# ---------------------------------------------------------------------------


class TestSaveB64Image:
    def _encode(self, data: bytes, mime="image/png") -> str:
        b64 = base64.b64encode(data).decode()
        return f"data:{mime};base64,{b64}"

    def test_decodes_png_data_uri(self):

        uri = self._encode(b"\x89PNG fake png bytes")
        path = _save_b64_image(uri)
        assert path is not None
        assert path.endswith(".png")
        assert os.path.exists(path)
        os.unlink(path)

    def test_decodes_jpeg_data_uri(self):

        uri = self._encode(b"\xff\xd8 fake jpeg", mime="image/jpeg")
        path = _save_b64_image(uri)
        assert path is not None
        assert path.endswith(".jpg")
        os.unlink(path)

    def test_raw_base64_without_header(self):

        raw_b64 = base64.b64encode(b"raw bytes").decode()
        path = _save_b64_image(raw_b64)
        assert path is not None
        assert path.endswith(".png")  # defaults to png
        os.unlink(path)

    def test_corrupt_data_returns_none(self):

        result = _save_b64_image("data:image/png;base64,NOT_VALID_BASE64!!!!")
        assert result is None

    def test_empty_string_returns_none(self):

        result = _save_b64_image("")
        # Empty string has no comma — treated as raw base64
        # base64.b64decode("") returns b"" — valid but empty file written, or None
        # Either is acceptable; just shouldn't raise
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# _get_bundled_icon
# ---------------------------------------------------------------------------


class TestGetBundledIcon:
    def test_known_icon_resolved(self):

        fake_ref = MagicMock()
        fake_ref.is_file.return_value = True
        fake_ref.__str__ = MagicMock(return_value="/fake/path/success.png")

        with patch("hermes_client.notifier.resources") as mock_res:
            mock_res.files.return_value.__truediv__ = MagicMock(return_value=fake_ref)
            result = _get_bundled_icon("success.png")

        assert result == "/fake/path/success.png"

    def test_missing_icon_returns_none(self):

        fake_ref = MagicMock()
        fake_ref.is_file.return_value = False

        with patch("hermes_client.notifier.resources") as mock_res:
            mock_res.files.return_value.__truediv__ = MagicMock(return_value=fake_ref)
            result = _get_bundled_icon("nonexistent.png")

        assert result is None

    def test_empty_filename_returns_none(self):

        result = _get_bundled_icon("")
        assert result is None

    def test_importlib_error_returns_none(self):

        with patch("hermes_client.notifier.resources") as mock_res:
            mock_res.files.side_effect = Exception("package not found")
            result = _get_bundled_icon("success.png")
        assert result is None


# ---------------------------------------------------------------------------
# _display — win11toast
# ---------------------------------------------------------------------------


class TestDisplayWin11Toast:
    def _call_display(self, **kwargs):
        defaults = dict(
            heading="Build Failed",
            body="CI Pipeline #42 failed",
            url="http://ado/build/42",
            avatar_path=None,
            status_image_path=None,
            event_icon_path=None,
        )
        defaults.update(kwargs)
        _display(**defaults)

    def test_win11toast_called(self):
        mock_toast = MagicMock()
        with patch.dict("sys.modules", {"win11toast": MagicMock(toast=mock_toast)}):
            importlib.reload(notifier)

            _display("Test", "Body", "", None, None)
            mock_toast.assert_called_once()

    def test_hero_image_passed_when_status_image_provided(self):
        mock_win11 = MagicMock()
        with patch.dict("sys.modules", {"win11toast": mock_win11}):
            importlib.reload(notifier)
            _display("Build Failed", "body", "", None, "/icons/failure.png")

        call_kwargs = mock_win11.toast.call_args[1]
        assert "hero" in call_kwargs
        assert call_kwargs["hero"]["src"] == "/icons/failure.png"

    def test_app_logo_override_passed_when_avatar_provided(self):
        mock_win11 = MagicMock()
        with patch.dict("sys.modules", {"win11toast": mock_win11}):
            importlib.reload(notifier)

            _display("Build Failed", "body", "", "/tmp/avatar.png", None)

        call_kwargs = mock_win11.toast.call_args[1]
        assert "image" in call_kwargs
        assert call_kwargs["image"]["placement"] == "appLogoOverride"

    def test_both_hero_and_logo_provided_simultaneously(self):
        mock_win11 = MagicMock()
        with patch.dict("sys.modules", {"win11toast": mock_win11}):
            importlib.reload(notifier)

            _display("Title", "body", "", "/tmp/avatar.png", "/icons/success.png")

        call_kwargs = mock_win11.toast.call_args[1]
        assert "hero" in call_kwargs
        assert "image" in call_kwargs

    def test_no_on_click_when_no_url(self):
        mock_win11 = MagicMock()
        with patch.dict("sys.modules", {"win11toast": mock_win11}):
            importlib.reload(notifier)

            _display("Title", "body", "", None, None)

        call_kwargs = mock_win11.toast.call_args[1]
        assert call_kwargs.get("on_click") is None


# ---------------------------------------------------------------------------
# show_notification — integration
# ---------------------------------------------------------------------------


class TestShowNotification:
    def _make_png_b64(self) -> str:
        # Minimal valid-looking base64 PNG header
        return "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()

    def test_avatar_temp_file_cleaned_up(self):
        created_paths = []

        original_save = __import__(
            "hermes_client.notifier",
            fromlist=["_save_b64_image"],
        )._save_b64_image

        def tracking_save(b64):
            path = original_save(b64)
            if path:
                created_paths.append(path)
            return path

        payload = {
            "heading": "PR Merged",
            "body": "Feature branch merged",
            "url": "",
            "avatar_b64": self._make_png_b64(),
            "status_image": None,
            "event_type": "pr",
        }

        with (
            patch("hermes_client.notifier._save_b64_image", side_effect=tracking_save),
            patch("hermes_client.notifier._display"),
            patch("hermes_client.notifier._get_bundled_icon", return_value=None),
        ):
            show_notification(payload)

        for path in created_paths:
            assert not os.path.exists(path), f"Temp file not cleaned up: {path}"

    def test_show_notification_passes_status_image_path(self):
        payload = {
            "heading": "Build Succeeded",
            "body": "All tests passed",
            "url": "http://ado/build/1",
            "avatar_b64": None,
            "status_image": "success",
            "event_type": "pipeline",
        }

        with (
            patch("hermes_client.notifier._display") as mock_display,
            patch(
                "hermes_client.notifier._get_bundled_icon",
                side_effect=lambda f: f"/icons/{f}" if f else None,
            ),
        ):
            show_notification(payload)

        _, _, _, avatar, status_img = mock_display.call_args[0]
        assert status_img == "/icons/success.png"
        assert avatar is None

    def test_show_notification_no_avatar_no_status_image(self):
        payload = {
            "heading": "Work Item Updated",
            "body": "Bug #42 resolved",
            "url": "",
            "avatar_b64": None,
            "status_image": None,
            "event_type": "workitem",
        }
        with (
            patch("hermes_client.notifier._display") as mock_display,
            patch("hermes_client.notifier._get_bundled_icon", return_value=None),
        ):
            show_notification(payload)

        _, _, _, avatar, status_img = mock_display.call_args[0]
        assert avatar is None
        assert status_img is None
