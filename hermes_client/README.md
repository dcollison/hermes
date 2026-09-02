# Hermes Client

Windows toast notification client for the Hermes Azure DevOps notification system.

## Installation

```powershell
pip install hermes
```

## Setup (one-time)

Run the interactive wizard — it connects to AzDO with your PAT to look up your
user ID and display name, detects your LAN IP for the callback URL, and writes
everything to a config file:

```powershell
hermes-client configure
```

Example session:

```text
══════════════════════════════════════════════════════════
  Hermes Client — Configuration Wizard
══════════════════════════════════════════════════════════

── Hermes Server ──────────────────────────────────────────
  Hermes server URL [http://localhost:8000]: http://build-server:8000

── Azure DevOps ────────────────────────────────────────────
  AzDO organisation URL: http://ado-server/DefaultCollection
  Personal Access Token: ********************************

  Resolving your AzDO identity… ✓
  Name : Dale
  ID   : b3f1a2c4-…

── Network ─────────────────────────────────────────────────
  Local listener port [9000]:
  Detected LAN IP: [http://192.168.1.42:9000/notify](http://192.168.1.42:9000/notify)
  Callback URL: [[http://192.168.1.42:9000/notify](http://192.168.1.42:9000/notify)]:

── Optional ────────────────────────────────────────────────
  Client display name [DALE-PC]:

✓ Configuration saved to: C:\Users\Dale\AppData\Roaming\Hermes\.env.hermes-client
```

The config file is saved to `%APPDATA%\Hermes\.env.hermes-client` on Windows.

## Running Hermes Client

### Background mode (recommended)

Start, stop, restart, or inspect Hermes running in the background without needing an open terminal:

```powershell
hermes-client start     # Start in the background
hermes-client status    # Show running status, PID, and version
hermes-client stop      # Stop the background client
hermes-client restart   # Restart the background client
```

### Upgrading Hermes

To upgrade to the latest version, run the self-upgrade command. It stops the active client, upgrades the package via `uv` or `pip`, and automatically restarts in the background:

```powershell
hermes-client upgrade
```

### Foreground / Debug mode

```powershell
hermes-client run       # Run in the foreground with live console logs
```

## Register to start at login

```powershell
hermes-client startup install
```

This creates a shortcut in your Windows Startup folder that launches Hermes at login with
no console window.

```powershell
hermes-client startup status   # check it's registered
hermes-client startup remove   # unregister
```

## How notification routing works

You receive a notification when:
- You are directly involved (reviewer, assignee, PR author) and you are **not** the one who triggered the event
- Any AzDO group you belong to is mentioned in the event
- A broadcast manual notification is sent

You never receive notifications for actions you take yourself.

## Configuration reference

All settings live in `.env.hermes-client`. Run `hermes-client configure` to
regenerate it, or edit it by hand:

| Setting                 | Description                                         |
|-------------------------|-----------------------------------------------------|
| `SERVER_URL`            | Hermes server URL                                   |
| `CLIENT_NAME`           | Display name for this machine                       |
| `LOCAL_PORT`            | Port the local listener binds to (default: 9000)    |
| `CALLBACK_URL`          | URL the server POSTs notifications to (your LAN IP) |
| `AZDO_ORGANIZATION_URL` | Your AzDO server collection URL                     |
| `AZDO_PAT`              | Personal Access Token (Identity/Profile read)       |
| `AZDO_USER_ID`          | Your AzDO identity GUID (filled by configure)       |
| `AZDO_DISPLAY_NAME`     | Your AzDO display name (filled by configure)        |
| `SUBSCRIPTIONS`         | Event types: pr, workitem, pipeline, manual         |

## Development

```powershell
git clone ...
cd hermes
uv sync --extra dev
uv run hermes-client configure
uv run hermes-client run
```