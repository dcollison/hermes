# Standard
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
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


def is_file_locked(path: Path) -> bool:
    """Check if a file is currently locked and cannot be opened for writing.

    :param path: File path to test.
    :returns: True if file exists and cannot be opened for writing; False otherwise.
    """
    if not path.is_file():
        return False
    try:
        with open(path, "a+b"):
            pass
        return False
    except OSError:
        return True


def _is_current_executable(exe_path: Path) -> bool:
    """Check if the given path corresponds to the currently running script executable.

    :param exe_path: Executable path to test.
    :returns: True if the path matches the running script.
    """
    try:
        script = Path(sys.argv[0]).resolve()
        if script.suffix.lower() != ".exe":
            script = script.with_suffix(".exe")
        return exe_path.resolve() == script
    except Exception:
        return False


def find_hermes_executables() -> list[Path]:
    """Locate all Hermes executable paths associated with the current environment.

    :returns: List of existing executable Paths.
    """
    exec_names = ("hermes-client.exe", "hermes-server.exe", "hermes-notify.exe")
    found: set[Path] = set()

    # 1. From sys.argv[0]
    try:
        script = Path(sys.argv[0]).resolve()
        if script.suffix.lower() == ".exe" and script.is_file():
            found.add(script)
        elif script.with_suffix(".exe").is_file():
            found.add(script.with_suffix(".exe"))
        for name in exec_names:
            sib = (script.parent / name).resolve()
            if sib.is_file():
                found.add(sib)
    except Exception:
        pass

    # 2. From startup._resolve_paths()
    try:
        _, script_path = startup._resolve_paths()
        sp = Path(script_path).resolve()
        if sp.is_file():
            found.add(sp)
            for name in exec_names:
                sib = (sp.parent / name).resolve()
                if sib.is_file():
                    found.add(sib)
    except Exception:
        pass

    # 3. From sys.executable directory and Scripts directory
    try:
        py_dir = Path(sys.executable).parent
        for d in (py_dir, py_dir / "Scripts"):
            if d.is_dir():
                for name in exec_names:
                    p = (d / name).resolve()
                    if p.is_file():
                        found.add(p)
    except Exception:
        pass

    # 4. From PATH (e.g. ~/.local/bin or virtualenv)
    for name in exec_names:
        try:
            which_path = shutil.which(name)
            if which_path:
                p = Path(which_path).resolve()
                if p.is_file():
                    found.add(p)
                    for sib_name in exec_names:
                        sib = (p.parent / sib_name).resolve()
                        if sib.is_file():
                            found.add(sib)
        except Exception:
            pass

    return sorted(found)


def prepare_executables_for_upgrade() -> list[tuple[Path, Path]]:
    """Rename running or locked Hermes executables on Windows so package managers can replace them.

    Renames executables to `<name>.<pid>.old`.

    :returns: List of (original_path, renamed_old_path) tuples.
    """
    if sys.platform != "win32":
        return []

    candidates = find_hermes_executables()
    renamed: list[tuple[Path, Path]] = []

    for exe_path in candidates:
        if _is_current_executable(exe_path) or is_file_locked(exe_path):
            old_path = exe_path.with_name(f"{exe_path.name}.{os.getpid()}.old")
            try:
                if old_path.exists():
                    try:
                        old_path.unlink(missing_ok=True)
                    except OSError:
                        old_path = exe_path.with_name(
                            f"{exe_path.name}.{os.getpid()}.{int(time.time())}.old"
                        )
                exe_path.rename(old_path)
                renamed.append((exe_path, old_path))
            except OSError as e:
                print(f"  Warning: Could not rename {exe_path.name}: {e}")

    return renamed


def restore_executables(renamed: list[tuple[Path, Path]]) -> None:
    """Restore renamed executables back to their original names if an upgrade failed.

    :param renamed: List of (original_path, renamed_old_path) tuples to restore.
    """
    for original, old in renamed:
        if old.exists() and not original.exists():
            try:
                old.rename(original)
            except OSError as e:
                print(f"  Warning: Could not restore {original.name}: {e}")


def schedule_old_executables_cleanup(renamed: list[tuple[Path, Path]]) -> None:
    """Schedule or attempt deletion of renamed .old executable files.

    :param renamed: List of (original_path, renamed_old_path) tuples.
    """
    for _, old in renamed:
        if not old.exists():
            continue
        try:
            old.unlink(missing_ok=True)
            continue
        except OSError:
            pass

        if sys.platform == "win32":
            try:
                cmd = f'cmd.exe /c "ping 127.0.0.1 -n 3 >nul & del /f /q \"{old}\""'
                subprocess.Popen(
                    cmd,
                    shell=True,
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                    close_fds=True,
                )
            except Exception:
                pass


def cleanup_old_executables(directories: list[Path] | None = None) -> None:
    """Attempt to delete any stale .old executable files left by previous upgrades.

    :param directories: Optional list of directories to scan. Defaults to directories
        associated with Hermes executables.
    """
    if directories is None:
        dirs_to_check: set[Path] = set()
        try:
            script_path = Path(sys.argv[0]).resolve()
            dirs_to_check.add(script_path.parent)
        except Exception:
            pass
        try:
            py_dir = Path(sys.executable).parent
            dirs_to_check.add(py_dir)
            if (py_dir / "Scripts").is_dir():
                dirs_to_check.add(py_dir / "Scripts")
        except Exception:
            pass
        try:
            which_client = shutil.which("hermes-client.exe") or shutil.which("hermes-client")
            if which_client:
                dirs_to_check.add(Path(which_client).resolve().parent)
        except Exception:
            pass
    else:
        dirs_to_check = set(directories)

    for d in dirs_to_check:
        if not d.is_dir():
            continue
        try:
            for old_file in d.glob("hermes-*.old*"):
                if old_file.is_file():
                    try:
                        old_file.unlink(missing_ok=True)
                    except OSError:
                        pass
        except Exception:
            pass


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
    cleanup_old_executables()

    was_running, _ = is_client_running(settings.LOCAL_PORT, settings.LOCAL_HOST)

    if was_running:
        print("  Stopping running Hermes client...", end=" ", flush=True)
        stopped = stop_client(settings.LOCAL_PORT, settings.LOCAL_HOST)
        if stopped:
            print("✓")
        else:
            print("WARNING: Could not cleanly stop Hermes client.")

    renamed = prepare_executables_for_upgrade()

    cmd = _detect_upgrade_command(package_name=package_name, extra_args=extra_args)
    print(f"  Running: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"\n  ERROR: Upgrade command exited with code {res.returncode}")
        if renamed:
            restore_executables(renamed)
        if was_running and restart:
            print("  Restarting previous Hermes client instance...")
            start_client()
        return False

    if renamed:
        schedule_old_executables_cleanup(renamed)

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
