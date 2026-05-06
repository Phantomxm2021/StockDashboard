# Stock Dashboard React Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a React + FastAPI stock dashboard with SQLite-backed login, root-only administration, and paginated report APIs.

**Architecture:** FastAPI owns auth, SQLite user persistence, report loading, task execution, and static frontend serving. React owns UI rendering and lazily requests JSON data so large report tables do not freeze the browser.

**Tech Stack:** Python 3, FastAPI, SQLite, pandas, pytest, React, TypeScript, Vite.

---

## File Structure

- Create `stock_dashboard/config.py` for paths and auth settings.
- Create `stock_dashboard/auth.py` for password hashing and signed bearer tokens.
- Create `stock_dashboard/users.py` for SQLite user persistence and root bootstrap.
- Create `stock_dashboard/reports.py` for report loading, pool display names, and pagination.
- Create `stock_dashboard/jobs.py` for root-only task execution wrappers.
- Modify `dashboard_server.py` to expose JSON APIs and serve the React build.
- Create `tests/test_auth_api.py` for authentication and authorization behavior.
- Create `tests/test_reports_api.py` for paginated report behavior.
- Create `frontend/` Vite React app files for UI implementation.

## Tasks

### Task 1: Backend Auth And User Storage

- [ ] Write failing tests for root bootstrap, login, `/api/me`, root-only user creation, and non-root denial in `tests/test_auth_api.py`.
- [ ] Run `conda activate base && pytest tests/test_auth_api.py -q` and verify tests fail because modules/routes are missing.
- [ ] Create `stock_dashboard/config.py`, `stock_dashboard/auth.py`, and `stock_dashboard/users.py`.
- [ ] Modify `dashboard_server.py` to expose `/api/auth/login`, `/api/me`, and `/api/users`.
- [ ] Run `conda activate base && pytest tests/test_auth_api.py -q` and verify tests pass.

### Task 2: Report API And Display Names

- [ ] Write failing tests in `tests/test_reports_api.py` for `/api/reports/after-close`, polished pool names, pagination, and missing-file empty results.
- [ ] Run `conda activate base && pytest tests/test_reports_api.py -q` and verify tests fail because report API is missing.
- [ ] Create `stock_dashboard/reports.py`.
- [ ] Modify `dashboard_server.py` to expose `/api/reports/after-close` and `/api/reports/morning`.
- [ ] Run `conda activate base && pytest tests/test_reports_api.py -q` and verify tests pass.

### Task 3: Root-Only Status And Jobs

- [ ] Extend auth tests for `/api/status` and `/api/jobs/run` root-only access.
- [ ] Run `conda activate base && pytest tests/test_auth_api.py -q` and verify the new tests fail.
- [ ] Create `stock_dashboard/jobs.py`.
- [ ] Modify `dashboard_server.py` so `/api/status` and `/api/jobs/run` require root.
- [ ] Run `conda activate base && pytest tests/test_auth_api.py -q` and verify tests pass.

### Task 4: React Frontend

- [ ] Create `frontend/package.json`, `frontend/index.html`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, and `frontend/src/*`.
- [ ] Implement minimal login UI with no registration or root credential hints.
- [ ] Implement dark dashboard shell with role-aware navigation.
- [ ] Implement paginated report tables using display names: `核心关注`, `继续观察`, `暂缓跟踪`, `全部候选`, `排除记录`.
- [ ] Implement root-only panels for strategy status, task center, and user management.
- [ ] Run `npm install` if dependencies are missing, then `npm run build` from `frontend/`.

### Task 5: Integration And Verification

- [ ] Modify `requirements.txt` for backend test/runtime dependencies.
- [ ] Run backend tests with `conda activate base && pytest -q`.
- [ ] Run frontend build with `npm run build` from `frontend/`.
- [ ] Start FastAPI with `conda activate base && uvicorn dashboard_server:app --host 127.0.0.1 --port 8001`.
- [ ] Open the app in the in-app browser and verify login page renders without credential/registration explanatory text.
- [ ] Verify root-only navigation appears for root and API denies unauthenticated access.
