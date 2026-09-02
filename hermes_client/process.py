# Standard
import re
import shutil
import subprocess
import sys
import time
from typing import Any

# Remote
import httpx

# Local
from . import startup
from .config import ClientSettings
from .notifier import show_notification


def parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string (e.g. '2.0.0.dev17', '2.0.1') into a comparable tuple of integers.

    :param v: Version string to parse.
    :returns: Tuple of integer components extracted from version string.
    """
    nums = [int(p) for p in re.findall(r"\d+", v)]
    return tuple(nums) if nums else (0,)


def is_client_running(
    port: int = 9000,
    host: str = "127.0.0.1",
    timeout: float = 1.0,
) -> tuple[bool, dict[str, Any] | None]:
    """Check if a local Hermes client listener is currently active on the given port.

    :param port: Local listener port to check.
    :param host: Local listener host address.
    :param timeout: HTTP request timeout in seconds.
    :returns: Tuple of (is_running, status_dict_or_None).
    """
    check_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        resp = httpx.get(f"http://{check_host}:{port}/health", timeout=timeout)
        if resp.status_code == 200:
            return True, resp.json()
    except Exception:
        pass
    return False, None


def stop_client(
    port: int = 9000,
    host: str = "127.0.0.1",
    timeout: float = 5.0,
) -> bool:
    """Send a shutdown request to the running local Hermes client and wait for it to exit.

    :param port: Local listener port of the client.
    :param host: Local listener host address.
    :param timeout: Maximum seconds to wait for shutdown confirmation.
    :returns: True if client stopped successfully; False if still running.
    """
    running, _ = is_client_running(port, host, timeout=1.0)
    if not running:
        return True

    check_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        httpx.post(f"http://{check_host}:{port}/shutdown", timeout=2.0)
    except Exception:
        pass

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.3)
        running, _ = is_client_running(port, host, timeout=0.5)
        if not running:
            return True

    return False


def start_client(
    args: list[str] | None = None,
    wait_seconds: float = 5.0,
) -> tuple[bool, dict[str, Any] | None]:
    """Launch hermes-client in the background and wait until it is ready.

    :param args: Optional additional CLI arguments to pass to 'run'.
    :param wait_seconds: Maximum seconds to wait for listener readiness.
    :returns: Tuple of (success, status_info_or_None).
    """
    pythonw, script = startup._resolve_paths()
    cmd = [pythonw, script, "run", *(args or [])]

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation_flags |= subprocess.CREATE_NO_WINDOW
        kwargs["creationflags"] = creation_flags
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(cmd, **kwargs)
    except Exception:
        return False, None

    settings = ClientSettings()
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(0.3)
        running, info = is_client_running(
            settings.LOCAL_PORT,
            settings.LOCAL_HOST,
            timeout=0.5,
        )
        if running:
            return True, info

    return False, None


def restart_client(
    args: list[str] | None = None,
    timeout: float = 5.0,
) -> tuple[bool, dict[str, Any] | None]:
    """Stop any running Hermes client and start a fresh instance in the background.

    :param args: Optional CLI arguments for the new instance.
    :param timeout: Timeout for stop and start operations.
    :returns: Tuple of (success, status_info_or_None).
    """
    settings = ClientSettings()
    stop_client(settings.LOCAL_PORT, settings.LOCAL_HOST, timeout=timeout)
    return start_client(args, wait_seconds=timeout)


def _detect_upgrade_command(
    package_name: str = "hermes",
    extra_args: list[str] | None = None,
) -> list[str]:
    """Determine the optimal upgrade command targeting the active Python environment.

    Detects if running as a standalone uv tool, inside a virtual environment with uv,
    or using standard pip.

    :param package_name: Package name or specifier to upgrade.
    :param extra_args: Additional command-line flags.
    :returns: Command list suitable for subprocess execution.
    """
    python_exe = sys.executable
    is_uv_tool = "uv/tools" in python_exe.replace("\\", "/").lower() or "uv\\tools" in python_exe.lower()

    if shutil.which("uv"):
        if is_uv_tool:
            return ["uv", "tool", "upgrade", package_name, *(extra_args or [])]
        # Target the exact virtual environment or Python interpreter of the running client
        return [
            "uv",
            "pip",
            "install",
            "--python",
            python_exe,
            "--upgrade",
            package_name,
            *(extra_args or []),
        ]

    return [
        python_exe,
        "-m",
        "pip",
        "install",
        "--upgrade",
        package_name,
        *(extra_args or []),
    ]


def upgrade_client(
    package_name: str = "hermes",
    restart: bool = True,
    extra_args: list[str] | None = None,
) -> bool:
    """Perform in-place self-upgrade of hermes, managing running processes.

    :param package_name: Package name/specifier to upgrade.
    :param restart: Whether to restart the client in the background after upgrading.
    :param extra_args: Additional arguments passed to pip/uv.
    :returns: True if upgrade succeeded; False otherwise.
    """
    settings = ClientSettings()
    was_running, _ = is_client_running(settings.LOCAL_PORT, settings.LOCAL_HOST)

    if was_running:
        print("  Stopping running Hermes client...", end=" ", flush=True)
        stopped = stop_client(settings.LOCAL_PORT, settings.LOCAL_HOST)
        if stopped:
            print("✓")
        else:
            print("WARNING: Could not cleanly stop Hermes client.")

    cmd = _detect_upgrade_command(package_name=package_name, extra_args=extra_args)
    print(f"  Running: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"\n  ERROR: Upgrade command exited with code {res.returncode}")
        if was_running and restart:
            print("  Restarting previous Hermes client instance...")
            start_client()
        return False

    print("\n✓ Hermes upgrade completed successfully.")

    if restart and (was_running or restart):
        print("  Starting Hermes client in background...", end=" ", flush=True)
        started, info = start_client()
        if started:
            print("✓")
            pid = info.get("pid", "unknown") if info else "unknown"
            print(f"  Hermes is running (PID: {pid})")
            try:
                show_notification(
                    {
                        "heading": "Hermes Upgraded",
                        "body": "Hermes client has been updated to the latest version.",
                        "status_image": "success",
                        "event_type": "manual",
                    }
                )
            except Exception:
                pass
        else:
            print("Note: Could not confirm background start. Run 'hermes-client start' to start.")

    return True
