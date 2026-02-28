# Hermes Client

Windows toast notification client for the Hermes Azure DevOps notification system.

## Installation

```powershell
pip install hermes
```

## Setup (one-time)

Run the interactive wizard — it connects to ADO with your PAT to look up your
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
  ADO organisation URL: http://ado-server/DefaultCollection
  Personal Access Token: ********************************

  Resolving your ADO identity… ✓
  Name : Alice Smith
  ID   : b3f1a2c4-…

── Network ─────────────────────────────────────────────────
  Local listener port [9000]:
  Detected LAN IP: [http://192.168.1.42:9000/notify](http://192.168.1.42:9000/notify)
  Callback URL: [[http://192.168.1.42:9000/notify](http://192.168.1.42:9000/notify)]:

── Optional ────────────────────────────────────────────────
  Client display name [ALICE-PC]:

✓ Configuration saved to: C:\Users\Alice\AppData\Roaming\Hermes\.env.hermes-client
```

The config file is saved to `%APPDATA%\Hermes\.env.hermes-client` on Windows.

## Register to start at login

```powershell
hermes-client startup install
```

This registers a Windows Task Scheduler task that launches Hermes at login with
no console window. Re-run after upgrading the package.

```powershell
hermes-client startup status   # check it's registered
hermes-client startup remove   # unregister
```

## Start manually

```powershell
hermes-client run
```

## How notification routing works

You receive a notification when:
- You are directly involved (reviewer, assignee, PR author) and you are **not** the one who triggered the event
- Any ADO group you belong to is mentioned in the event
- A broadcast manual notification is sent

You never receive notifications for actions you take yourself.

## Configuration reference

All settings live in `.env.hermes-client`. Run `hermes-client configure` to
regenerate it, or edit it by hand:

| Setting                | Description                                         |
|------------------------|-----------------------------------------------------|
| `SERVER_URL`           | Hermes server URL                                   |
| `CLIENT_NAME`          | Display name for this machine                       |
| `LOCAL_PORT`           | Port the local listener binds to (default: 9000)    |
| `CALLBACK_URL`         | URL the server POSTs notifications to (your LAN IP) |
| `ADO_ORGANIZATION_URL` | Your ADO server collection URL                      |
| `ADO_PAT`              | Personal Access Token (Identity/Profile read)       |
| `ADO_USER_ID`          | Your ADO identity GUID (filled by configure)        |
| `ADO_DISPLAY_NAME`     | Your ADO display name (filled by configure)         |
| `SUBSCRIPTIONS`        | Event types: pr, workitem, pipeline, manual         |

## Development

```powershell
git clone ...
cd hermes
uv sync --extra dev
uv run hermes-client configure
uv run hermes-client run
```