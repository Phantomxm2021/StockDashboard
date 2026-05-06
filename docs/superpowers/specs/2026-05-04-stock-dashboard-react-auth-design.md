# Stock Dashboard React Auth Design

## Goal

Rebuild the stock dashboard as a React frontend plus Python backend so the page no longer freezes from server-rendering large HTML reports, while adding a local login system and root-only administration features.

## Confirmed Requirements

- Use a full React frontend with a Python FastAPI backend.
- Use `conda activate base` for test, run, and build commands.
- Default UI is dark mode.
- Use SQLite for user storage.
- Initialize a default root account with username `root` and password `admin@root`.
- Do not show root credentials or account-management explanations in the UI.
- Do not allow public registration.
- Only root can create users.
- Only root can access user management, task triggering, and runtime status.
- Non-root users can view dashboard data only.
- Replace raw pool names like `A_pool_重点盯盘` in the UI with polished display names.
- Keep compatibility with the existing report generator and file names.

## Architecture

The backend remains the system of record for reports, task execution, auth, and authorization. React owns all page rendering and requests paginated JSON data from FastAPI instead of embedding report HTML. Existing HTML report routes remain available for compatibility, but the main `/` route serves the React build.

## Backend Components

- `stock_dashboard/config.py`: filesystem and auth settings.
- `stock_dashboard/auth.py`: password hashing, token creation, and token verification.
- `stock_dashboard/users.py`: SQLite schema, root bootstrap, user CRUD, and credential verification.
- `stock_dashboard/reports.py`: CSV/JSON report loading, pool display-name mapping, pagination.
- `stock_dashboard/jobs.py`: protected subprocess task runner wrapper.
- `dashboard_server.py`: FastAPI app, API routes, static frontend serving, and compatibility HTML routes.

## Frontend Components

- `frontend/src/App.tsx`: top-level auth state, routing between login and dashboard.
- `frontend/src/api.ts`: typed API client.
- `frontend/src/LoginPage.tsx`: minimal dark login screen.
- `frontend/src/Dashboard.tsx`: authenticated shell with role-aware navigation.
- `frontend/src/ReportView.tsx`: lazy-loaded report tabs with pagination.
- `frontend/src/AdminViews.tsx`: root-only status, task, and user-management panels.
- `frontend/src/styles.css`: dark-mode visual system.

## Auth Model

Users authenticate with username and password. Passwords are stored as PBKDF2 hashes with per-password salt. The backend issues a signed bearer token stored by the frontend in local storage. Every protected API route validates the token. Root-only routes check `user.is_root` server-side even if the frontend hides those views.

## Data Flow

React loads `/api/me` on startup when a token exists. After login, React fetches report summaries and page data on demand. Report tables are paginated server-side to avoid rendering thousands of rows at once. Display names are applied at the API layer so the UI never needs to show internal pool identifiers.

## Error Handling

Auth failures return `401`; root-only authorization failures return `403`. Missing reports return empty datasets with clear titles. Job execution returns a structured result and records status through the existing `run_job.py` flow. Frontend errors show compact inline states, not browser alerts.

## Testing

Backend tests cover root bootstrap, login, root-only route protection, user creation, and paginated report loading. Frontend build verifies TypeScript and production bundling. Smoke checks run the FastAPI app enough to validate route registration and static files.

## Scope Boundaries

This implementation does not add OAuth, password reset, theme switching, real-time websocket updates, or a full audit log. Those can be added later without changing the core React/backend split.

## Scheduled Docker Runtime

Docker Compose runs two services from the same image. `web` serves the FastAPI and React application on port 8001. `scheduler` runs `python -m stock_dashboard.scheduler`, checks the A-share trading calendar in Beijing time, and runs `after_close` at 15:05 and `morning` at 9:40 only on trading days.
