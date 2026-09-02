![image](hermes_client/icons/hermes.png)

# Hermes

> Azure DevOps → Windows Toast Notifications

Hermes is a two-part notification system:

- **Server** — Runs on your build server. Receives Azure DevOps webhooks, fetches user profile images, formats events, and pushes notifications to registered clients.
- **Client** — Runs on each developer's Windows machine. Registers with the server and displays Windows toast notifications.

---

### Data files

Hermes stores all state in the `data/` directory:

| File                              | Contents                                                 |
|-----------------------------------|----------------------------------------------------------|
| `data/clients.json`               | All registered clients (keyed by ID)                     |
| `data/notifications.log`          | Delivery log — one compact JSON object per line (NDJSON) |
| `data/notifications.log.1`        | Most recent rolled file                                  |
| `data/notifications.log.2` … `.3` | Older rolled files                                       |

`clients.json` is written atomically (write-to-temp then rename). `notifications.log` uses Python's built-in `RotatingFileHandler` — when the active log reaches `HERMES_LOG_MAX_BYTES` (default **5 MB**) it is renamed to `.log.1`, the previous `.log.1` becomes `.log.2`, and so on up to `HERMES_LOG_BACKUP_COUNT` (default **3**) kept files. Both are protected by an asyncio lock and survive server restarts.

---

## Quick Start

### Server

1. **Install dependencies**
   ```bash
   pip install hermes[server]
   ```

2. **Configure**
   ```bash
   cp .env.example .env.hermes-server
   # Edit .env.hermes-server with your AzDO server URL and PAT
   ```

3. **Run**
   ```bash
   hermes-server run
   ```
   The server starts on `http://0.0.0.0:8000`. Access the interactive API docs at `http://localhost:8000/docs`.

4. **Register Azure DevOps webhooks** (do this once per event type)

   In AzDO: Project Settings → Service Hooks → Create Subscription → Web Hooks

   Set the URL to: `http://your-build-server:8000/webhooks/azdo`

   **Recommended events to subscribe:**

   | Category   | Event                        |
   |------------|------------------------------|
   | Code       | Pull request created         |
   | Code       | Pull request updated         |
   | Code       | Pull request commented on    |
   | Work Items | Work item created            |
   | Work Items | Work item updated            |
   | Work Items | Work item commented on       |
   | Pipelines  | Build completed              |
   | Release    | Release created              |
   | Release    | Release deployment completed |
   | Release    | Release abandoned            |

   > All use **API version 5.1-preview** in AzDO Server.

   If you want webhook validation, set a shared secret in AzDO and add `AZDO_WEBHOOK_SECRET=your_secret` to `.env.hermes-server`.

---

### Client (Windows)

1. **Install dependencies**
   ```bash
   pip install hermes
   ```

2. **Configure**
   Run the interactive configuration wizard to generate your `.env.hermes-client` file automatically:
   ```bash
   hermes-client configure
   ```

3. **Run**
   ```bash
   hermes-client run
   ```
   The client starts a local server on port 9000 and registers with the Hermes server automatically.

4. **Auto-start on login (recommended)**

   Install the background Startup shortcut to run the client invisibly on Windows logon:
   ```bash
   hermes-client startup install
   ```

---

## Production Deployment (Build Server)

Run the Hermes server as a Windows Service using [NSSM](https://nssm.cc/):

```bash
nssm install Hermes "C:\Python311\Scripts\hermes-server.exe"
nssm set Hermes AppDirectory "C:\hermes"
nssm set Hermes AppStdout "C:\hermes\logs\hermes.log"
nssm set Hermes AppStderr "C:\hermes\logs\hermes-error.log"
nssm start Hermes
```

The JSON files in `data/` persist all client registrations and notification logs across server restarts. Back up this directory periodically if you want to preserve log history.

---

## Client Subscriptions

Clients can subscribe to specific event types so they only receive relevant notifications. 

### Subscription types

| Value      | Events received                                         |
|------------|---------------------------------------------------------|
| `pr`       | Pull request created, updated, completed, commented     |
| `workitem` | Work item created, updated, commented, resolved, closed |
| `pipeline` | Build completed, release created/deployed/abandoned     |
| `manual`   | Manual push notifications from the server               |

Set via `.env.hermes-client` (can be updated by rerunning `hermes-client configure`):
```env
SUBSCRIPTIONS=["pr", "workitem", "manual"]
```

---

## Manual Notifications

### Using the CLI (`hermes-notify`)

`hermes-notify` automatically reads the server URL and your sender identity from your client configuration (`%APPDATA%\Hermes\.env.hermes-client` or `.env`):

```powershell
# Send a broadcast to all clients
hermes-notify "Heads up" "Dev database is restarting in 5 minutes"

# Specify a custom sender identity (defaults to your AzDO display name or username)
hermes-notify "Build Failed" "Main branch pipeline failed" --from "CI Runner"

# Filter recipients by name or project
hermes-notify "Code Review" "PR #42 is ready for review" --filter-name "Dale" --url "http://your-azdo/pr/42"
```

### Using the REST API

```bash
# Send to all clients subscribed to "manual" with sender attribution
curl -X POST http://your-server:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "heading": "Deployment Notice",
    "body": "Prod deployment starts in 10 minutes. Please save your work.",
    "actor": "Dale",
    "url": "http://your-azdo/release/123"
  }'

# Target specific clients by name
curl -X POST http://your-server:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "heading": "Code Review Needed",
    "body": "PR #42 needs your review.",
    "filter_name_contains": "Dale"
  }'

# Target a specific project team
curl -X POST http://your-server:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "heading": "Sprint Planning",
    "body": "Sprint planning starts in 15 minutes.",
    "filter_project": "MyProject"
  }'
```

---

## API Reference

| Endpoint                      | Method | Description                  |
|-------------------------------|--------|------------------------------|
| `/webhooks/azdo`              | POST   | AzDO webhook receiver        |
| `/webhooks/ado`               | POST   | Legacy webhook receiver alias|
| `/clients/register`           | POST   | Register a client            |
| `/clients/`                   | GET    | List all clients             |
| `/clients/{id}`               | DELETE | Unregister a client          |
| `/clients/{id}/subscriptions` | PUT    | Update subscriptions         |
| `/notifications/send`         | POST   | Push a manual notification   |
| `/notifications/logs`         | GET    | View delivery logs           |
| `/health`                     | GET    | Health check                 |
| `/docs`                       | GET    | Swagger UI                   |