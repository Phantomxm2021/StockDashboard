from __future__ import annotations

from datetime import date
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from stock_dashboard.scheduler import TradingDayChecker, read_scheduler_status, run_scheduler_tick


def test_scheduler_jobs_include_all_markets():
    from stock_dashboard.scheduler import scheduled_jobs

    jobs = scheduled_jobs(date(2026, 5, 5))
    assert ("cn", "after_close", "15:05") in jobs
    assert ("cn", "morning", "09:40") in jobs
    assert ("hk", "after_close", "16:15") in jobs
    assert ("hk", "pre_market", "09:22") in jobs
    assert ("us", "after_hours", "05:15") in jobs
    assert ("us", "pre_market", "21:00") in jobs


def test_scheduler_us_jobs_follow_winter_time():
    from stock_dashboard.scheduler import scheduled_jobs

    jobs = scheduled_jobs(date(2026, 1, 6))
    assert ("us", "after_hours", "06:15") in jobs
    assert ("us", "pre_market", "22:00") in jobs


def test_trading_day_checker_uses_akshare_calendar_when_available() -> None:
    checker = TradingDayChecker(
        calendar_loader=lambda: pd.DataFrame({"trade_date": ["2026-05-04", "2026-05-05"]})
    )

    assert checker.is_trading_day(date(2026, 5, 4)) is True
    assert checker.is_trading_day(date(2026, 5, 6)) is False


def test_trading_day_checker_falls_back_to_weekdays_when_calendar_fails() -> None:
    def fail_loader() -> pd.DataFrame:
        raise RuntimeError("calendar unavailable")

    checker = TradingDayChecker(calendar_loader=fail_loader)

    assert checker.is_trading_day(date(2026, 5, 4)) is True
    assert checker.is_trading_day(date(2026, 5, 9)) is False


def test_scheduler_tick_runs_due_task_and_writes_status(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setenv("STOCK_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr("stock_dashboard.scheduler.run_job", fake_run_job)

    results = run_scheduler_tick(
        datetime(2026, 5, 5, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai")),
        TradingDayChecker(calendar_loader=lambda: pd.DataFrame({"trade_date": ["2026-05-05"]})),
        set(),
    )

    assert calls == [("cn", "morning")]
    assert results[0]["status"] == "succeeded"
    status = read_scheduler_status()
    assert status["current_time"] == "09:40"
    assert status["last_runs"][0]["market"] == "cn"
    assert status["last_runs"][0]["report_type"] == "morning"


def test_scheduler_tick_records_non_trading_day_skip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STOCK_REPORT_DIR", str(tmp_path / "reports"))

    results = run_scheduler_tick(
        datetime(2026, 5, 5, 9, 40, tzinfo=ZoneInfo("Asia/Shanghai")),
        TradingDayChecker(calendar_loader=lambda: pd.DataFrame({"trade_date": ["2026-05-04"]})),
        set(),
    )

    assert results[0]["status"] == "skipped_non_trading_day"
    status = read_scheduler_status()
    assert status["trading_day"] is False
