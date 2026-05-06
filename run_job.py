from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from stock_dashboard.market_strategies import run_hk_report, run_us_report
from stock_dashboard.markets import ReportTypeDefinition, get_market_definition


BASE_DIR = Path(__file__).resolve().parent

SCRIPT_PATH = Path(
    os.getenv(
        "STOCK_REPORT_SCRIPT",
        BASE_DIR / "a_stock_shortlist_akshare_html.py",
    )
)

OUTPUT_DIR = Path(os.getenv("STOCK_OUTPUT_DIR", BASE_DIR / "output"))
REPORT_DIR = Path(os.getenv("STOCK_REPORT_DIR", BASE_DIR / "reports"))
LOG_DIR = Path(os.getenv("STOCK_LOG_DIR", BASE_DIR / "logs"))

TIMEZONE = ZoneInfo(os.getenv("STOCK_TZ", "Asia/Shanghai"))


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def now_str() -> str:
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def is_weekend() -> bool:
    """
    简单跳过周末。
    注意：这里没有处理中国法定节假日。
    """
    now = datetime.now(TIMEZONE)
    return now.weekday() >= 5


def run_subprocess(args: list[str]) -> None:
    print(f"[{now_str()}] RUN:", " ".join(args))

    result = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    print(result.stdout)

    if result.returncode != 0:
        raise RuntimeError(
            f"命令执行失败，returncode={result.returncode}\n{result.stdout}"
        )


def find_latest(pattern: str) -> Path | None:
    files = sorted(
        OUTPUT_DIR.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def update_status(data: dict, report_dir: Path = REPORT_DIR) -> None:
    status_path = report_dir / "status.json"
    report_dir.mkdir(parents=True, exist_ok=True)

    old_data = {}
    if status_path.exists():
        try:
            old_data = json.loads(status_path.read_text(encoding="utf-8"))
        except Exception:
            old_data = {}

    old_data.update(data)
    old_data["updated_at"] = now_str()

    status_path.write_text(
        json.dumps(old_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def copy_file(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
    print(f"[COPY] {src} -> {dst}")


def run_after_close(force: bool = False, report_dir: Path = REPORT_DIR) -> None:
    ensure_dirs()

    if is_weekend() and not force:
        print(f"[{now_str()}] 周末，跳过 after_close。")
        update_status({
            "last_after_close_status": "skipped_weekend",
            "last_after_close_time": now_str(),
        }, report_dir=report_dir)
        return

    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"找不到选股脚本：{SCRIPT_PATH}")

    run_subprocess([
        sys.executable,
        str(SCRIPT_PATH),
        "--mode",
        "after_close",
        "--output-dir",
        str(OUTPUT_DIR),
    ])

    latest_html = find_latest("candidates_*.html")
    latest_csv = find_latest("candidates_*.csv")

    if latest_html is None:
        raise FileNotFoundError("after_close 执行后没有找到 candidates_*.html")

    if latest_csv is None:
        raise FileNotFoundError("after_close 执行后没有找到 candidates_*.csv")

    latest_html_report = report_dir / "latest_after_close.html"
    latest_csv_report = report_dir / "latest_candidates.csv"

    copy_file(latest_html, latest_html_report)
    copy_file(latest_csv, latest_csv_report)
    copy_file(latest_csv, report_dir / "latest_after_close.csv")

    update_status({
        "last_after_close_status": "ok",
        "last_after_close_time": now_str(),
        "latest_after_close_html": str(latest_html_report),
        "latest_candidates_csv": str(latest_csv_report),
    }, report_dir=report_dir)


def run_morning(force: bool = False, report_dir: Path = REPORT_DIR) -> None:
    ensure_dirs()

    if is_weekend() and not force:
        print(f"[{now_str()}] 周末，跳过 morning。")
        update_status({
            "last_morning_status": "skipped_weekend",
            "last_morning_time": now_str(),
        }, report_dir=report_dir)
        return

    if not SCRIPT_PATH.exists():
        raise FileNotFoundError(f"找不到选股脚本：{SCRIPT_PATH}")

    candidates_csv = find_candidates_csv(report_dir)
    if candidates_csv is None:
        print(f"[{now_str()}] 未找到 A股收盘候选池，先自动补跑 after_close。")
        run_after_close(force=True, report_dir=report_dir)
        candidates_csv = find_candidates_csv(report_dir)

    if candidates_csv is None:
        raise FileNotFoundError("没有找到 A股 candidates CSV，自动补跑 after_close 后仍未生成。")

    run_subprocess([
        sys.executable,
        str(SCRIPT_PATH),
        "--mode",
        "morning",
        "--yesterday-file",
        str(candidates_csv),
        "--output-dir",
        str(OUTPUT_DIR),
    ])

    latest_html = find_latest("morning_confirm_*.html")
    latest_csv = find_latest("morning_confirm_*.csv")

    if latest_html is None:
        raise FileNotFoundError("morning 执行后没有找到 morning_confirm_*.html")
    if latest_csv is None:
        raise FileNotFoundError("morning 执行后没有找到 morning_confirm_*.csv")

    latest_morning_report = report_dir / "latest_morning.html"
    latest_morning_csv_report = report_dir / "latest_morning.csv"
    copy_file(latest_html, latest_morning_report)
    copy_file(latest_csv, latest_morning_csv_report)

    update_status({
        "last_morning_status": "ok",
        "last_morning_time": now_str(),
        "latest_morning_html": str(latest_morning_report),
        "latest_morning_csv": str(latest_morning_csv_report),
    }, report_dir=report_dir)


def find_candidates_csv(report_dir: Path) -> Path | None:
    candidates = [
        report_dir / "latest_candidates.csv",
        report_dir / "latest_after_close.csv",
    ]
    if report_dir != REPORT_DIR:
        candidates.extend(
            [
                REPORT_DIR / "latest_candidates.csv",
                REPORT_DIR / "latest_after_close.csv",
                REPORT_DIR / "cn" / "latest_candidates.csv",
                REPORT_DIR / "cn" / "latest_after_close.csv",
            ]
        )

    for path in candidates:
        if path.exists():
            return path
    return find_latest("candidates_*.csv")


def run_report(market: str, report_type: str, force: bool = False) -> None:
    if market == "cn":
        market_report_dir = REPORT_DIR / market
        market_report_dir.mkdir(parents=True, exist_ok=True)
        if report_type == "after_close":
            run_after_close(force=force, report_dir=market_report_dir)
            return
        if report_type == "morning":
            run_morning(force=force, report_dir=market_report_dir)
            return
    if market in {"hk", "us"}:
        ensure_dirs()
        market_def = get_market_definition(market)
        report_def = _get_report_definition(market_def.reports, report_type)
        market_report_dir = REPORT_DIR / market
        market_report_dir.mkdir(parents=True, exist_ok=True)

        if is_weekend() and not force:
            print(f"[{now_str()}] 周末，跳过 {market}.{report_type}。")
            update_status({
                "status": "skipped_weekend",
                "market": market,
                "report_type": report_type,
                "time": now_str(),
            }, report_dir=market_report_dir)
            return

        csv_path, html_path = (
            run_hk_report(report_type, OUTPUT_DIR)
            if market == "hk"
            else run_us_report(report_type, OUTPUT_DIR)
        )

        latest_csv = market_report_dir / report_def.latest_csv
        copy_file(csv_path, latest_csv)

        latest_html = None
        if report_def.latest_html is not None:
            latest_html = market_report_dir / report_def.latest_html
            copy_file(html_path, latest_html)

        status_data = {
            "status": "ok",
            "market": market,
            "report_type": report_type,
            "time": now_str(),
            "latest_csv": str(latest_csv),
        }
        if latest_html is not None:
            status_data["latest_html"] = str(latest_html)
        update_status(status_data, report_dir=market_report_dir)
        return
    raise RuntimeError(f"unsupported market report: {market}.{report_type}")


def _get_report_definition(
    reports: tuple[ReportTypeDefinition, ...],
    report_type: str,
) -> ReportTypeDefinition:
    for report in reports:
        if report.id == report_type:
            return report
    raise RuntimeError(f"unsupported report type: {report_type}")


def main() -> None:
    parser = argparse.ArgumentParser(description="股票看板定时任务入口")

    parser.add_argument(
        "--market",
        choices=["cn", "hk", "us"],
        default="cn",
    )

    parser.add_argument("--report-type")

    parser.add_argument(
        "--mode",
        choices=["after_close", "morning"],
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="强制运行，周末也不跳过",
    )

    args = parser.parse_args()

    report_type = args.report_type
    if report_type is None and args.mode is not None:
        report_type = "after_close" if args.mode == "after_close" else "morning"
    if report_type is None:
        parser.error("--report-type is required unless --mode is used")

    run_report(args.market, report_type, force=args.force)


if __name__ == "__main__":
    main()
