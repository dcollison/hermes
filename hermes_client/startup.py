# Standard
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

TASK_NAME = "HermesNotificationClient"
TASK_DESCRIPTION = "Hermes — Azure DevOps notification client"


def _resolve_paths() -> tuple[str, str]:
    """Return (pythonw_path, script_path) for use in the Task Scheduler command.

    uv installs console scripts as .exe wrappers that embed the full path to
    the venv's Python, so we don't need to locate Python separately — we just
    need the script exe itself.  We use sys.argv[0] which is always the path
    of the currently-running script, regardless of how uv organised it.

    The Task Scheduler entry runs:
        pythonw.exe  <script>.exe

    :returns: Tuple containing (pythonw_executable_path, client_script_path).
    """
    # The running script (hermes-client.exe or hermes-client on Unix)
    script = Path(sys.argv[0]).resolve()

    # Look for pythonw.exe next to the current interpreter
    pythonw = Path(sys.executable).parent / "pythonw.exe"

    # uv tool installs go into a separate tools venv; the interpreter there
    # may not have a pythonw.exe beside it, but the Scripts/ folder of the
    # *tools* venv always has one at the same level as the script.
    if not pythonw.exists():
        pythonw = script.parent / "pythonw.exe"

    if not pythonw.exists():
        # Last resort — fall back to the console interpreter (will flash a window)
        pythonw = Path(sys.executable)

    return str(pythonw), str(script)


def _build_task_xml(pythonw: str, script: str) -> str:
    """Generate a Task Scheduler XML definition.

    :param pythonw: Absolute path to the pythonw.exe launcher.
    :param script: Absolute path to the hermes-client executable script.
    :returns: XML configuration string for Task Scheduler.
    """
    username = f"{os.environ.get('USERDOMAIN', '.')}\\{os.environ.get('USERNAME', '')}"

    return textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.4"
              xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>{TASK_DESCRIPTION}</Description>
          </RegistrationInfo>
          <Triggers>
            <LogonTrigger>
              <Enabled>true</Enabled>
              <UserId>{username}</UserId>
            </LogonTrigger>
          </Triggers>
          <Principals>
            <Principal id="Author">
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>LeastPrivilege</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
            <Priority>7</Priority>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>{pythonw}</Command>
              <Arguments>"{script}" run</Arguments>
            </Exec>
          </Actions>
        </Task>
    """)


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command capturing textual output.

    :param args: Command line argument tokens.
    :param check: Whether to raise CalledProcessError on non-zero exit code.
    :returns: CompletedProcess instance containing captured output.
    """
    return subprocess.run(args, capture_output=True, text=True, check=check)


def install() -> None:
    """Register the Hermes client as a Task Scheduler logon task."""
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        sys.exit(1)

    pythonw, script = _resolve_paths()
    xml = _build_task_xml(pythonw, script)

    # schtasks /Create /XML requires a file path, not stdin
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".xml",
        delete=False,
        encoding="utf-16",
    ) as f:
        f.write(xml)
        xml_path = f.name

    try:
        _run("schtasks", "/Delete", "/TN", TASK_NAME, "/F", check=False)
        _run("schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_path)
        print(f"✓ Startup task '{TASK_NAME}' installed.")
        print(f"  Launcher : {pythonw}")
        print(f"  Script   : {script}")
        print()
        print("  Hermes will start automatically the next time you log in.")
        print("  To start it now:  hermes-client run")
        print()
        print("  NOTE: Re-run this command after upgrading hermes-client,")
        print("  as the stored paths will change with a new installation.")
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Could not create scheduled task:\n{e.stderr}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass


def remove() -> None:
    """Remove the Hermes client startup task."""
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        sys.exit(1)

    result = _run("schtasks", "/Delete", "/TN", TASK_NAME, "/F", check=False)
    if result.returncode == 0:
        print(f"✓ Startup task '{TASK_NAME}' removed.")
    else:
        print(f"Task '{TASK_NAME}' was not found — nothing to remove.")


def status() -> None:
    """Print whether the startup task exists and is enabled."""
    if sys.platform != "win32":
        print("Startup integration is only supported on Windows.")
        return

    result = _run("schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST", check=False)
    if result.returncode != 0:
        print(f"Startup task '{TASK_NAME}' is NOT installed.")
    else:
        print(f"Startup task '{TASK_NAME}' is installed.\n")
        for line in result.stdout.splitlines():
            if any(k in line for k in ("Task Name", "Status", "Next Run", "Last Run")):
                print(f"  {line}")
