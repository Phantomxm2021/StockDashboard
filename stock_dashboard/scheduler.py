from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

from .config import BASE_DIR
from .jobs import run_job


LOGGER = logging.getLogger(__name__)
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
US_EASTERN_TZ = ZoneInfo("America/New_York")


class TradingDayChecker:
    def __init__(self, calendar_loader=None) -> None:
        self._calendar_loader = calendar_loader or ak.tool_trade_date_hist_sina
        self._trade_dates: set[date] | None = None

    def is_trading_day(self, target_date: date) -> bool:
        trade_dates = self._load_trade_dates()
        if trade_dates is not None:
            return target_date in trade_dates
        return target_date.weekday() < 5

    def _load_trade_dates(self) -> set[date] | None:
        if self._trade_dates is not None:
            return self._trade_dates
        try:
            df = self._calendar_loader()
        except Exception as exc:
            LOGGER.warning("Failed to load trading calendar, falling back to weekdays: %s", exc)
            return None

        column = _find_trade_date_column(df)
        if column is None:
            LOGGER.warning("Trading calendar has no trade_date column, falling back to weekdays")
            return None

        dates = pd.to_datetime(df[column], errors="coerce").dropna().dt.date
        self._trade_dates = set(dates)
        return self._trade_dates


@dataclass(frozen=True)
class ScheduledTask:
    market: str
    report_type: str
    run_at: str


STATIC_TASKS = [
    ScheduledTask(market="cn", report_type="after_close", run_at="15:05"),
    ScheduledTask(market="cn", report_type="morning", run_at="09:40"),
    ScheduledTask(market="hk", report_type="after_close", run_at="16:15"),
    ScheduledTask(market="hk", report_type="pre_market", run_at="09:22"),
]


def scheduled_jobs(target_date: date | None = None) -> list[tuple[str, str, str]]:
    beijing_date = target_date or datetime.now(BEIJING_TZ).date()
    tasks = [
        *STATIC_TASKS,
        ScheduledTask(market="us", report_type="after_hours", run_at=_us_after_hours_run_at(beijing_date)),
        ScheduledTask(market="us", report_type="pre_market", run_at=_us_pre_market_run_at(beijing_date)),
    ]
    return [(task.market, task.report_type, task.run_at) for task in tasks]


def run_scheduler_forever() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    checker = TradingDayChecker()
    executed_keys: set[str] = set()
    LOGGER.info("Scheduler started with Asia/Shanghai trading-day checks")

    while True:
        now = datetime.now(BEIJING_TZ)
        today = now.date()
        current_time = now.strftime("%H:%M")
        for task in _tasks_for_date(today):
            key = f"{today.isoformat()}:{task.market}:{task.report_type}"
            if key in executed_keys:
                continue
            if current_time == task.run_at:
                if checker.is_trading_day(today):
                    LOGGER.info("Running scheduled task: %s.%s", task.market, task.report_type)
                    result = run_job(task.market, task.report_type, BASE_DIR)
                    LOGGER.info(
                        "Task %s.%s finished with returncode=%s",
                        task.market,
                        task.report_type,
                        result.returncode,
                    )
                else:
                    LOGGER.info(
                        "Skipping %s.%s because %s is not a trading day",
                        task.market,
                        task.report_type,
                        today.isoformat(),
                    )
                executed_keys.add(key)
        time.sleep(20)


def _find_trade_date_column(df: pd.DataFrame) -> str | None:
    for column in df.columns:
        if str(column) in {"trade_date", "交易日", "date"}:
            return str(column)
    return None


def _tasks_for_date(target_date: date) -> list[ScheduledTask]:
    return [ScheduledTask(market=market, report_type=report_type, run_at=run_at) for market, report_type, run_at in scheduled_jobs(target_date)]


def _us_after_hours_run_at(beijing_date: date) -> str:
    eastern_date = beijing_date - timedelta(days=1)
    eastern_dt = datetime.combine(eastern_date, datetime_time(17, 15), tzinfo=US_EASTERN_TZ)
    return eastern_dt.astimezone(BEIJING_TZ).strftime("%H:%M")


def _us_pre_market_run_at(beijing_date: date) -> str:
    eastern_dt = datetime.combine(beijing_date, datetime_time(9, 0), tzinfo=US_EASTERN_TZ)
    return eastern_dt.astimezone(BEIJING_TZ).strftime("%H:%M")


if __name__ == "__main__":
    run_scheduler_forever()
