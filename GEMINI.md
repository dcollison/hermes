# Hermes — Project Guidelines & Developer Reference

This document serves as the guide for AI coding assistants working in the Hermes repository.

---

## 1. Project Overview

**Hermes** is an internal notification routing system tailored for **Azure DevOps Server 2020** (on-premises) and Azure DevOps Cloud. It captures Azure DevOps webhooks on a central server, formats event data into structured notifications, filters recipients based on subscriptions and team/group memberships, and delivers notifications directly to developer Windows machines via toast notifications and a local web dashboard.

### Core Components

1. **`hermes_server`** (FastAPI):
   - Runs on a centralized build/infrastructure server (default port `8000`).
   - Endpoint `/webhooks/ado` receives Service Hook payloads from Azure DevOps.
   - Evaluates client subscriptions and team/group mentions (via `ado_client.py` and `dispatcher.py`).
   - Persists client registrations to `data/clients.json` and delivery logs to `data/notifications.log`.
   - Includes webhook event simulator (`hermes-server simulate`).

2. **`hermes_client`** (FastAPI + Windows Toast):
   - Runs on developer machines (default port `9000`).
   - Listens on `POST /notify` to display Windows 11 toast notifications via `win11toast`.
   - Supports background Windows logon startup via Startup folder shortcut (`hermes-client startup install`).

3. **`notify.py`** (`hermes-notify`):
   - Standalone CLI utility for sending manual or CI/CD broadcast notifications to the Hermes server.

4. **`design/`**:
   - C4 architecture diagrams (`context.puml`, `container.puml`, `component.puml`).

---

## 2. Python Coding & Style Guidelines

- **Python Version**: Python 3.11+.
- **Type Annotations**:
  - Use modern built-in generic types (`list`, `dict`, `set`, `tuple`, `type1 | type2`).
  - **Do NOT** import `List`, `Dict`, `Set`, `Tuple`, `Optional`, or `Union` from `typing`.
- **Docstrings**:
  - Use **reStructuredText (rST)** style docstrings (`:param ...:`, `:returns:`, `:raises:`).
  - **Do NOT** use `:type:` or `:rtype:` tags (types are documented in Python type hints).
- **Import Organization**:
  - Managed by `isort` with 3 sections separated by comments:
    ```python
    # Standard
    import json
    import os

    # Remote
    import httpx
    from fastapi import FastAPI

    # Local
    from .config import ClientSettings
    ```
- **Linting & Formatting**:
  - `ruff check .`
  - `isort --check .`

---

## 3. Azure DevOps Server 2020 Quirks & Formatter Rules

- **Service Hooks Version**: 1.0 (5.1-preview).
- **Pull Requests**:
  - **PR Merge Attempted (`git.pullrequest.merged`)**: Must return `None` (suppress background branch merge attempt noise).
  - **PR Completed (`git.pullrequest.updated` with `status: "completed"`)**: In ADO 1.0, completion events arrive as update events. These are converted to `git.pullrequest.completed` with heading `"PR Completed"`, notifying both author and reviewers.
  - **PR Created (`git.pullrequest.created`)**: Notifies assigned reviewers.
  - **PR Updated (`git.pullrequest.updated` with `status: "active"`)**: Notifies reviewers.
  - **PR Comments (`ms.vss-code.git-pullrequest-comment-event`)**: Notifies thread participants and reviewers, excluding commenter.
- **Work Items**:
  - Created, updated, commented, resolved, closed, done.
  - REST URLs (`/_apis/wit/workItems/123`) must be converted to browser edit URLs (`/_workitems/edit/123`), stripping revision suffixes.
- **URL Entity Sanitization**:
  - ADO webhooks include HTML-escaped URLs with entities like `&amp;` in query strings.
  - All URLs extracted from HTML/Markdown must pass through `html.unescape()` and `.replace("&amp;", "&")`.

---

## 4. Verification & Testing

Always verify modifications by running:

```powershell
pytest
ruff check .
isort --check .
```

- All unit tests reside under `tests/server/` and `tests/client/`.
- Maintain 100% test pass rate when modifying formatting, routing, storage, or dispatching logic.

---

## 5. Git & Commit Guidelines

- **Commit Message Preparation**:
  - When completing work or presenting changes, draft a concise and informative git commit message (using imperative mood, e.g. `Fix ...`, `Add ...`, `Update ...`).
  - Provide the suggested commit message and summary of staged files so the user can easily review or run `git commit`.
- **Commit Policy**:
  - Do **not** commit or push changes automatically unless explicitly requested by the user.
