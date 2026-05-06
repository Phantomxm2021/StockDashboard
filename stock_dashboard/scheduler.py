from __future__ import annotations

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
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
    write_scheduler_status(
        {
            "status": "running",
            "started_at": _now_str(),
            "timezone": "Asia/Shanghai",
            "today_jobs": _scheduled_job_dicts(datetime.now(BEIJING_TZ).date()),
        }
    )

    while True:
        run_scheduler_tick(datetime.now(BEIJING_TZ), checker, executed_keys)
        time.sleep(20)


def run_scheduler_tick(
    now: datetime,
    checker: TradingDayChecker,
    executed_keys: set[str],
    *,
    force_trading_day: bool | None = None,
) -> list[dict[str, object]]:
    current = now.astimezone(BEIJING_TZ) if now.tzinfo is not None else now.replace(tzinfo=BEIJING_TZ)
    today = current.date()
    current_time = current.strftime("%H:%M")
    due_results: list[dict[str, object]] = []
    trading_day = checker.is_trading_day(today) if force_trading_day is None else force_trading_day

    for task in _tasks_for_date(today):
        key = _task_key(today, task)
        if key in executed_keys or current_time != task.run_at:
            continue
        if trading_day:
            LOGGER.info("Running scheduled task: %s.%s", task.market, task.report_type)
            result = run_job(task.market, task.report_type, BASE_DIR)
            entry = {
                "key": key,
                "market": task.market,
                "report_type": task.report_type,
                "run_at": task.run_at,
                "triggered_at": _now_str(current),
                "status": "succeeded" if result.returncode == 0 else "failed",
                "returncode": result.returncode,
                "output_tail": result.output[-4000:],
            }
            LOGGER.info("Task %s.%s finished with returncode=%s", task.market, task.report_type, result.returncode)
        else:
            entry = {
                "key": key,
                "market": task.market,
                "report_type": task.report_type,
                "run_at": task.run_at,
                "triggered_at": _now_str(current),
                "status": "skipped_non_trading_day",
                "returncode": None,
                "output_tail": "",
            }
            LOGGER.info("Skipping %s.%s because %s is not a trading day", task.market, task.report_type, today.isoformat())
        executed_keys.add(key)
        due_results.append(entry)

    write_scheduler_status(
        {
            "status": "running",
            "heartbeat_at": _now_str(current),
            "timezone": "Asia/Shanghai",
            "current_time": current_time,
            "trading_day": trading_day,
            "today_jobs": _scheduled_job_dicts(today),
            "due_results": due_results,
        }
    )
    return due_results


def _find_trade_date_column(df: pd.DataFrame) -> str | None:
    for column in df.columns:
        if str(column) in {"trade_date", "交易日", "date"}:
            return str(column)
    return None


def _tasks_for_date(target_date: date) -> list[ScheduledTask]:
    return [ScheduledTask(market=market, report_type=report_type, run_at=run_at) for market, report_type, run_at in scheduled_jobs(target_date)]


def write_scheduler_status(data: dict[str, object]) -> None:
    path = _scheduler_status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old_data: dict[str, object] = {}
    if path.exists():
        try:
            old_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            old_data = {}
    if "due_results" in data and data["due_results"]:
        old_runs = old_data.get("last_runs")
        last_runs = old_runs if isinstance(old_runs, list) else []
        data["last_runs"] = [*data["due_results"], *last_runs][:30]
    elif "last_runs" not in data and isinstance(old_data.get("last_runs"), list):
        data["last_runs"] = old_data["last_runs"]
    old_data.update(data)
    old_data["updated_at"] = _now_str()
    path.write_text(json.dumps(old_data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_scheduler_status() -> dict[str, object]:
    path = _scheduler_status_path()
    if not path.exists():
        return {
            "status": "empty",
            "message": "scheduler 还没有写入状态；请确认 scheduler 容器是否运行",
            "today_jobs": _scheduled_job_dicts(datetime.now(BEIJING_TZ).date()),
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "error", "message": f"scheduler_status.json 读取失败：{exc}"}


def _scheduler_status_path() -> Path:
    return Path(os.getenv("STOCK_REPORT_DIR", BASE_DIR / "reports")) / "scheduler_status.json"


def _scheduled_job_dicts(target_date: date) -> list[dict[str, str]]:
    return [
        {"market": market, "report_type": report_type, "run_at": run_at}
        for market, report_type, run_at in scheduled_jobs(target_date)
    ]


def _task_key(target_date: date, task: ScheduledTask) -> str:
    return f"{target_date.isoformat()}:{task.market}:{task.report_type}"


def _now_str(value: datetime | None = None) -> str:
    current = value or datetime.now(BEIJING_TZ)
    current = current.astimezone(BEIJING_TZ) if current.tzinfo is not None else current.replace(tzinfo=BEIJING_TZ)
    return current.isoformat(timespec="seconds")


def _us_after_hours_run_at(beijing_date: date) -> str:
    eastern_date = beijing_date - timedelta(days=1)
    eastern_dt = datetime.combine(eastern_date, datetime_time(17, 15), tzinfo=US_EASTERN_TZ)
    return eastern_dt.astimezone(BEIJING_TZ).strftime("%H:%M")


def _us_pre_market_run_at(beijing_date: date) -> str:
    eastern_dt = datetime.combine(beijing_date, datetime_time(9, 0), tzinfo=US_EASTERN_TZ)
    return eastern_dt.astimezone(BEIJING_TZ).strftime("%H:%M")


def main() -> None:
    parser = argparse.ArgumentParser(description="股票看板自动任务调度器")
    parser.add_argument("--once", action="store_true", help="只检查并执行一次当前命中的任务")
    parser.add_argument("--at", help="指定北京时间 HH:MM，用于测试某个定时点")
    parser.add_argument("--date", help="指定北京时间日期 YYYY-MM-DD，用于测试")
    parser.add_argument("--force-trading-day", action="store_true", help="测试时强制按交易日执行")
    args = parser.parse_args()

    if not args.once:
        run_scheduler_forever()
        return

    target_date = date.fromisoformat(args.date) if args.date else datetime.now(BEIJING_TZ).date()
    if args.at:
        hour, minute = [int(part) for part in args.at.split(":", 1)]
        now = datetime.combine(target_date, datetime_time(hour, minute), tzinfo=BEIJING_TZ)
    else:
        now = datetime.now(BEIJING_TZ)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    results = run_scheduler_tick(
        now,
        TradingDayChecker(),
        set(),
        force_trading_day=True if args.force_trading_day else None,
    )
    print(json.dumps({"checked_at": _now_str(now), "due_results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
