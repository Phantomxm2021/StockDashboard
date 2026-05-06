from __future__ import annotations

from datetime import date

import pandas as pd

from stock_dashboard.scheduler import TradingDayChecker


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
