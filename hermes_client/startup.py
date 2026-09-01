# Standard
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Local
from .config import _ensure_std_streams

SHORTCUT_NAME = "Hermes Client.lnk"
SHORTCUT_DESCRIPTION = "Hermes — Azure DevOps notification client"
LEGACY_TASK_NAME = "HermesNotificationClient"


def _get_startup_dir() -> Path:
    """Return the Windows user Startup directory path.

    :returns: Path to the user's Startup directory.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return (
        Path.home()
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def _get_shortcut_path() -> Path:
    """Return the full Path to the Hermes Client shortcut in the Startup folder.

    :returns: Path to the .lnk file.
    """
    return _get_startup_dir() / SHORTCUT_NAME


def _resolve_paths() -> tuple[str, str]:
    """Return (pythonw_path, script_path) for use in the startup shortcut.

    uv installs console scripts as .exe wrappers that embed the full path to
    the venv's Python, so we don't need to locate Python separately — we just
    need the script exe itself. We use sys.argv[0] which is always the path
    of the currently-running script, regardless of how uv organised it.

    :returns: Tuple containing (pythonw_executable_path, client_script_path).
    """
    # The running script (hermes-client.exe or hermes-client on Unix)
    script = Path(sys.argv[0]).resolve()

    if sys.platform == "win32":
        if script.suffix.lower() != ".exe":
            if script.with_suffix(".exe").exists():
                script = script.with_suffix(".exe")
            else:
                exe_in_parent = Path(sys.executable).parent / "hermes-client.exe"
                exe_in_scripts = Path(sys.executable).parent / "Scripts" / "hermes-client.exe"
                which_exe = shutil.which("hermes-client.exe") or shutil.which("hermes-client")

                if exe_in_parent.exists():
                    script = exe_in_parent
                elif exe_in_scripts.exists():
                    script = exe_in_scripts
                elif which_exe and which_exe.lower().endswith(".exe"):
                    script = Path(which_exe).resolve()
                else:
                    script = script.with_suffix(".exe")

    # Look for pythonw.exe next to the current interpreter
    pythonw = Path(sys.executable).parent / "pythonw.exe"

    # uv tool installs go into a separate tools venv; the interpreter there
    # may not have a pythonw.exe beside it, but the Scripts/ folder of the
    # *tools* venv always has one at the same level as the script.
    if not pythonw.exists():
        pythonw = script.parent / "pythonw.exe"

    if not pythonw.exists():
        # Last resort — fall back to the console interpreter
        pythonw = Path(sys.executable)

    return str(pythonw), str(script)


def _ps_escape(s: str) -> str:
    """Escape a string for use in a single-quoted PowerShell string literal.

    :param s: Input string.
    :returns: Escaped string enclosed in single quotes.
    """
    return "'" + s.replace("'", "''") + "'"


def _create_shortcut(
    shortcut_path: Path,
    target_exe: str,
    arguments: str,
    working_dir: str,
    description: str,
) -> None:
    """Create a Windows .lnk shortcut using PowerShell and WScript.Shell.

    :param shortcut_path: Destination path for the .lnk shortcut file.
    :param target_exe: Target executable (e.g. pythonw.exe).
    :param arguments: Command line arguments for the target.
    :param working_dir: Initial working directory for the process.
    :param description: Description metadata for the shortcut.
    """
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_escape(str(shortcut_path))}); "
        f"$s.TargetPath = {_ps_escape(target_exe)}; "
        f"$s.Arguments = {_ps_escape(arguments)}; "
        f"$s.WorkingDirectory = {_ps_escape(working_dir)}; "
        f"$s.Description = {_ps_escape(description)}; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        check=True,
    )


def _read_shortcut(shortcut_path: Path) -> dict[str, str] | None:
    """Read target path and arguments from an existing Windows .lnk shortcut.

    :param shortcut_path: Path to the .lnk file.
    :returns: Dictionary with shortcut properties, or None if read fails.
    """
    if not shortcut_path.exists():
        return None
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({_ps_escape(str(shortcut_path))}); "
        "Write-Output $s.TargetPath; "
        "Write-Output $s.Arguments; "
        "Write-Output $s.WorkingDirectory; "
        "Write-Output $s.Description"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return {
            "target_path": lines[0] if len(lines) > 0 else "",
            "arguments": lines[1] if len(lines) > 1 else "",
            "working_directory": lines[2] if len(lines) > 2 else "",
            "description": lines[3] if len(lines) > 3 else "",
        }
    except Exception:
        return None


def _cleanup_legacy_task() -> None:
    """Silently delete any legacy Task Scheduler task from previous Hermes versions."""
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", LEGACY_TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        pass

def install() -> None:
    """Register the Hermes client in the Windows user Startup folder."""
    _ensure_std_streams()
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        sys.exit(1)

    pythonw, script = _resolve_paths()
    shortcut_path = _get_shortcut_path()
    arguments = f'"{script}" run'
    working_dir = str(Path.home())

    try:
        _create_shortcut(
            shortcut_path=shortcut_path,
            target_exe=pythonw,
            arguments=arguments,
            working_dir=working_dir,
            description=SHORTCUT_DESCRIPTION,
        )
        _cleanup_legacy_task()

        print("✓ Startup shortcut installed.")
        print(f"  Location : {shortcut_path}")
        print(f"  Launcher : {pythonw}")
        print(f"  Script   : {script}")
        print()
        print("  Hermes will start automatically the next time you log in.")
        print("  To start it now:  hermes-client run")
        print()
        print("  NOTE: Re-run this command after upgrading hermes-client,")
        print("  as the stored paths will change with a new installation.")
    except Exception as e:
        print(f"ERROR: Could not create startup shortcut:\n{e}", file=sys.stderr)
        sys.exit(1)


def remove() -> None:
    """Remove the Hermes client from the Windows Startup folder."""
    _ensure_std_streams()
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        sys.exit(1)

    shortcut_path = _get_shortcut_path()
    removed = False

    if shortcut_path.exists():
        try:
            shortcut_path.unlink()
            removed = True
        except OSError as e:
            print(f"ERROR: Could not delete startup shortcut:\n{e}", file=sys.stderr)
            sys.exit(1)

    _cleanup_legacy_task()

    if removed:
        print(f"✓ Startup shortcut removed from '{shortcut_path}'.")
    else:
        print("Startup shortcut was not found — nothing to remove.")


def status() -> None:
    """Print whether the startup shortcut exists and its configuration."""
    _ensure_std_streams()
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        return

    shortcut_path = _get_shortcut_path()
    if not shortcut_path.exists():
        print("Startup shortcut is NOT installed.")
    else:
        print("Startup shortcut is installed.\n")
        print(f"  Location : {shortcut_path}")
        info = _read_shortcut(shortcut_path)
        if info:
            if info.get("target_path"):
                print(f"  Launcher : {info['target_path']}")
            if info.get("arguments"):
                print(f"  Arguments: {info['arguments']}")
            if info.get("working_directory"):
                print(f"  WorkDir  : {info['working_directory']}")
