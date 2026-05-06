from pathlib import Path

from stock_dashboard.bootstrap import bootstrap_reports


def test_bootstrap_runs_missing_reports(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type, base_dir))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setenv("STOCK_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr("stock_dashboard.bootstrap.run_job", fake_run_job)

    bootstrap_reports(tmp_path)

    assert ("cn", "after_close", tmp_path) in calls
    assert ("cn", "morning", tmp_path) in calls
    assert ("hk", "after_close", tmp_path) in calls
    assert ("hk", "pre_market", tmp_path) in calls
    assert ("us", "after_hours", tmp_path) in calls
    assert ("us", "pre_market", tmp_path) in calls


def test_bootstrap_skips_existing_reports_by_default(monkeypatch, tmp_path: Path):
    calls = []
    report_dir = tmp_path / "reports"
    for market, filename in [
        ("cn", "latest_after_close.csv"),
        ("cn", "latest_morning.csv"),
        ("hk", "latest_after_close.csv"),
        ("hk", "latest_pre_market.csv"),
        ("us", "latest_after_hours.csv"),
        ("us", "latest_pre_market.csv"),
    ]:
        path = report_dir / market / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type, base_dir))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setenv("STOCK_REPORT_DIR", str(report_dir))
    monkeypatch.delenv("STOCK_BOOTSTRAP_REPORTS", raising=False)
    monkeypatch.setattr("stock_dashboard.bootstrap.run_job", fake_run_job)

    bootstrap_reports(tmp_path)

    assert calls == []


def test_bootstrap_always_runs_existing_reports(monkeypatch, tmp_path: Path):
    calls = []
    path = tmp_path / "reports" / "cn" / "latest_after_close.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ok", encoding="utf-8")

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setenv("STOCK_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("STOCK_BOOTSTRAP_REPORTS", "always")
    monkeypatch.setattr("stock_dashboard.bootstrap.run_job", fake_run_job)

    bootstrap_reports(tmp_path)

    assert ("cn", "after_close") in calls
