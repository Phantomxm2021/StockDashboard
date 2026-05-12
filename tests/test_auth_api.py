from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dashboard_server import create_app
from stock_dashboard import auth


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            report_dir=tmp_path / "reports",
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "data",
        )
    )


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_root_user_is_bootstrapped_and_can_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    token = login(client, "root", "admin@root")
    response = client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"username": "root", "is_root": True}


def test_login_rejects_bad_password(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "wrong"},
    )

    assert response.status_code == 401


def test_root_can_create_user_and_user_can_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_token = login(client, "root", "admin@root")

    response = client.post(
        "/api/users",
        json={"username": "analyst", "password": "strong-password"},
        headers={"Authorization": f"Bearer {root_token}"},
    )

    assert response.status_code == 201
    assert response.json() == {"username": "analyst", "is_root": False}

    user_token = login(client, "analyst", "strong-password")
    me_response = client.get(
        "/api/me",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert me_response.json() == {"username": "analyst", "is_root": False}


def test_non_root_cannot_create_users_or_read_status_or_run_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_token = login(client, "root", "admin@root")
    client.post(
        "/api/users",
        json={"username": "analyst", "password": "strong-password"},
        headers={"Authorization": f"Bearer {root_token}"},
    )
    user_token = login(client, "analyst", "strong-password")
    user_headers = {"Authorization": f"Bearer {user_token}"}

    create_response = client.post(
        "/api/users",
        json={"username": "blocked", "password": "strong-password"},
        headers=user_headers,
    )
    status_response = client.get("/api/status", headers=user_headers)
    job_response = client.post(
        "/api/jobs/run",
        json={"mode": "after_close"},
        headers=user_headers,
    )

    assert create_response.status_code == 403
    assert status_response.status_code == 403
    assert job_response.status_code == 403


def test_unauthenticated_requests_are_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    me_response = client.get("/api/me")
    users_response = client.post(
        "/api/users",
        json={"username": "analyst", "password": "strong-password"},
    )
    status_response = client.get("/api/status")

    assert me_response.status_code == 401
    assert users_response.status_code == 401
    assert status_response.status_code == 401


def test_root_job_run_returns_job_id_and_status_endpoint(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    root_token = login(client, "root", "admin@root")
    headers = {"Authorization": f"Bearer {root_token}"}

    response = client.post(
        "/api/jobs/run",
        json={"mode": "after_close"},
        headers=headers,
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert response.json()["status"] in {"queued", "running"}

    status_response = client.get(f"/api/jobs/{job_id}", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["job_id"] == job_id
    assert status_response.json()["mode"] == "cn.after_close"
    assert "logs" in status_response.json()


def test_token_stays_valid_for_day_scale_session(monkeypatch) -> None:
    start = 1_700_000_000
    monkeypatch.setattr(auth.time, "time", lambda: start)

    token = auth.create_token("root", "secret")

    monkeypatch.setattr(auth.time, "time", lambda: start + 60 * 60 * 24)

    payload = auth.parse_token(token, "secret")

    assert payload is not None
    assert payload.username == "root"


def test_token_expires_after_ttl_window(monkeypatch) -> None:
    start = 1_700_000_000
    monkeypatch.setattr(auth.time, "time", lambda: start)

    token = auth.create_token("root", "secret")

    monkeypatch.setattr(auth.time, "time", lambda: start + auth.TOKEN_TTL_SECONDS + 1)

    assert auth.parse_token(token, "secret") is None
