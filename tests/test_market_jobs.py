from pathlib import Path
from time import monotonic, sleep

from fastapi.testclient import TestClient

from dashboard_server import create_app
from stock_dashboard.jobs import JobManager


def wait_for_terminal_job(manager: JobManager, job_id: str, timeout: float = 2.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = manager.get(job_id)
        assert job is not None
        if job.status not in {"queued", "running"}:
            return job
        sleep(0.01)
    job = manager.get(job_id)
    raise AssertionError(f"job did not finish before timeout: {job}")


def test_job_manager_accepts_market_report_type(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type, base_dir))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setattr("stock_dashboard.jobs.run_job", fake_run_job)
    manager = JobManager(tmp_path)

    job = manager.start("hk", "pre_market")
    final = wait_for_terminal_job(manager, job.job_id)
    assert final.market == "hk"
    assert final.report_type == "pre_market"
    assert final.status == "succeeded"
    assert calls[0][:2] == ("hk", "pre_market")


def test_job_manager_marks_background_exceptions_failed(monkeypatch, tmp_path: Path):
    def fake_run_job(market: str, report_type: str, base_dir: Path):
        raise RuntimeError("boom")

    monkeypatch.setattr("stock_dashboard.jobs.run_job", fake_run_job)
    manager = JobManager(tmp_path)

    job = manager.start("hk", "pre_market")
    final = wait_for_terminal_job(manager, job.job_id)

    assert final.status == "failed"
    assert final.returncode == 1
    assert "boom" in final.logs


def test_run_job_api_rejects_invalid_market_report(tmp_path: Path):
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    token = login.json()["access_token"]

    response = client.post(
        "/api/jobs/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"market": "us", "report_type": "morning"},
    )

    assert response.status_code == 400


def test_run_job_api_requires_report_type_or_legacy_mode(tmp_path: Path):
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    token = login.json()["access_token"]

    response = client.post(
        "/api/jobs/run",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "report_type is required"


def test_run_job_api_legacy_mode_returns_market_mode(monkeypatch, tmp_path: Path):
    from stock_dashboard.jobs import JobResult

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setattr("stock_dashboard.jobs.run_job", fake_run_job)
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    token = login.json()["access_token"]

    response = client.post(
        "/api/jobs/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"mode": "after_close"},
    )

    assert response.status_code == 202
    assert response.json()["market"] == "cn"
    assert response.json()["report_type"] == "after_close"
    assert response.json()["mode"] == "cn.after_close"
