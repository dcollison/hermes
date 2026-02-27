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
   cd hermes
   pip install -r requirements-server.txt
   ```

2. **Configure**
   ```bash
   cp .env.example .env
   # Edit .env with your ADO server URL and PAT
   ```

3. **Run**
   ```bash
   python run_server.py
   ```
   The server starts on `http://0.0.0.0:8000`. Access the interactive API docs at `http://localhost:8000/docs`.

4. **Register Azure DevOps webhooks** (do this once per event type)

   In ADO: Project Settings → Service Hooks → Create Subscription → Web Hooks

   Set the URL to: `http://your-build-server:8000/webhooks/ado`

   **Recommended events to subscribe:**

   | Category   | Event                        |
   |------------|------------------------------|
   | Code       | Pull request created         |
   | Code       | Pull request updated         |
   | Code       | Pull request merge attempted |
   | Code       | Pull request commented on    |
   | Work Items | Work item created            |
   | Work Items | Work item updated            |
   | Work Items | Work item commented on       |
   | Pipelines  | Build completed              |
   | Release    | Release created              |
   | Release    | Release deployment completed |
   | Release    | Release abandoned            |

   > All use **API version 5.1-preview** in ADO Server.

   If you want webhook validation, set a shared secret in ADO and add `ADO_WEBHOOK_SECRET=your_secret` to `.env`.

---

### Client (Windows)

1. **Install dependencies**
   ```bash
   pip install -r requirements-client.txt
   ```

2. **Configure**
   ```bash
   cp .env.client.example .env.client
   # Edit .env.client — especially CALLBACK_URL with your actual LAN IP
   ```

3. **Run**
   ```bash
   python run_client.py
   ```
   The client starts a local server on port 9000 and registers with the Hermes server automatically.

4. **Auto-start on login (recommended)**

   Create a shortcut in your Windows Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`) pointing to:
   ```
   Target: C:\Python311\pythonw.exe C:\hermes\run_client.py
   Start in: C:\hermes
   ```
   Using `pythonw.exe` hides the console window.

---

## Production Deployment (Build Server)

Run the Hermes server as a Windows Service using [NSSM](https://nssm.cc/):

```bash
nssm install Hermes "C:\Python311\python.exe" "C:\hermes\run_server.py"
nssm set Hermes AppDirectory "C:\hermes"
nssm set Hermes AppStdout "C:\hermes\logs\hermes.log"
nssm set Hermes AppStderr "C:\hermes\logs\hermes-error.log"
nssm start Hermes
```

The JSON files in `data/` persist all client registrations and notification logs across server restarts. Back up this directory periodically if you want to preserve log history.

---

## Client Subscriptions & Filters

Clients can subscribe to specific event types and apply filters so they only receive relevant notifications.

### Subscription types

| Value      | Events received                                         |
|------------|---------------------------------------------------------|
| `pr`       | Pull request created, updated, merged, commented        |
| `workitem` | Work item created, updated, commented, resolved, closed |
| `pipeline` | Build completed, release created/deployed/abandoned     |
| `manual`   | Manual push notifications from the server               |
| `all`      | Everything                                              |

### Filters (applied server-side)

```json
{"project": "MyProject"}
{"assigned_to": "jane.doe@company.com"}
{"actor": "john.doe"}
{"project": "MyProject", "assigned_to": "jane.doe@company.com"}
```

Set via `.env.client`:
```env
SUBSCRIPTIONS=["pr", "workitem", "manual"]
FILTERS={"project": "MyProject"}
```

---

## Manual Notifications

Push a custom notification to all or specific clients via the API:

```bash
# Send to all clients subscribed to "manual"
curl -X POST http://your-server:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "heading": "Deployment Notice",
    "body": "Prod deployment starts in 10 minutes. Please save your work.",
    "url": "http://your-ado/release/123"
  }'

# Target specific clients by name
curl -X POST http://your-server:8000/notifications/send \
  -H "Content-Type: application/json" \
  -d '{
    "heading": "Code Review Needed",
    "body": "PR #42 needs your review.",
    "filter_name_contains": "Alice"
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
| `/webhooks/ado`               | POST   | ADO webhook receiver         |
| `/clients/register`           | POST   | Register a client            |
| `/clients/`                   | GET    | List all clients             |
| `/clients/{id}`               | DELETE | Unregister a client          |
| `/clients/{id}/subscriptions` | PUT    | Update subscriptions/filters |
| `/notifications/send`         | POST   | Push a manual notification   |
| `/notifications/logs`         | GET    | View delivery logs           |
| `/health`                     | GET    | Health check                 |
| `/docs`                       | GET    | Swagger UI                   |

---
