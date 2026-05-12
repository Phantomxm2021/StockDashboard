from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

US_EASTERN_TZ = ZoneInfo("America/New_York")
HK_TZ = ZoneInfo("Asia/Hong_Kong")


OUTPUT_COLUMNS = [
    "code",
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "成交额亿",
    "市场",
    "个股强度分",
    "板块强度分",
    "资金流向分",
    "位置风险分",
    "新闻催化分",
    "主线强势分",
    "买入观察等级",
    "次日动作建议",
]


def build_hk_candidates_from_quotes(quotes: pd.DataFrame, report_type: str) -> pd.DataFrame:
    df = _normalize_quote_frame(quotes, market_label="港股")
    filtered = df[
        (df["最新价"] >= 0.5)
        & (df["成交额"] >= 50_000_000)
        & (df["涨跌幅"] >= 1.0)
    ].copy()
    return _score_candidates(
        filtered,
        market_label="港股",
        report_type=report_type,
        amount_divisor=2_000_000_000,
    )


def build_us_candidates_from_quotes(quotes: pd.DataFrame, report_type: str) -> pd.DataFrame:
    df = _normalize_quote_frame(quotes, market_label="美股")
    filtered = df[
        (df["最新价"] >= 5)
        & (df["成交额"] >= 100_000_000)
        & (df["涨跌幅"] >= 1.0)
    ].copy()
    return _score_candidates(
        filtered,
        market_label="美股",
        report_type=report_type,
        amount_divisor=5_000_000_000,
    )


def run_hk_report(
    report_type: str,
    output_dir: Path,
    ak_module: Any | None = None,
    now: datetime | None = None,
    enforce_session: bool = False,
) -> tuple[Path, Path]:
    if enforce_session:
        _ensure_hk_session(report_type, now or datetime.now(HK_TZ))
    quotes = _fetch_hk_quotes(_load_akshare(ak_module))
    candidates = build_hk_candidates_from_quotes(quotes, report_type=report_type)
    return _write_market_outputs(candidates, output_dir, f"hk_{report_type}")


def run_us_report(
    report_type: str,
    output_dir: Path,
    ak_module: Any | None = None,
    now: datetime | None = None,
    enforce_session: bool = False,
) -> tuple[Path, Path]:
    if enforce_session:
        _ensure_us_extended_session(report_type, now or datetime.now(US_EASTERN_TZ))
    quotes = _fetch_us_quotes(_load_akshare(ak_module))
    candidates = build_us_candidates_from_quotes(quotes, report_type=report_type)
    return _write_market_outputs(candidates, output_dir, f"us_{report_type}")


def _normalize_quote_frame(quotes: pd.DataFrame, market_label: str) -> pd.DataFrame:
    rename_map = {
        "symbol": "code",
        "代码": "code",
        "中文名称": "名称",
        "name": "名称",
        "price": "最新价",
        "change_pct": "涨跌幅",
        "amount": "成交额",
    }
    df = quotes.copy().rename(
        columns={source: target for source, target in rename_map.items() if source in quotes.columns}
    )

    for column in ["code", "名称", "最新价", "涨跌幅", "成交额"]:
        if column not in df.columns:
            df[column] = "" if column in {"code", "名称"} else 0

    df["code"] = df["code"].astype(str).str.strip()
    df["代码"] = df["code"]
    df["名称"] = df["名称"].astype(str).str.strip()
    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce").fillna(0)
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
    df["成交额"] = pd.to_numeric(df["成交额"], errors="coerce").fillna(0)
    df["成交额亿"] = (df["成交额"] / 100_000_000).round(2)
    df["市场"] = market_label
    return df


def _score_candidates(
    df: pd.DataFrame,
    market_label: str,
    report_type: str,
    amount_divisor: float,
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    scored = df.copy()
    amount_score = (scored["成交额"] / amount_divisor).clip(upper=1) * 15
    scored["个股强度分"] = (scored["涨跌幅"].clip(upper=8) * 2.5 + amount_score).round(2)
    scored["板块强度分"] = 0.0
    scored["资金流向分"] = 0.0
    scored["位置风险分"] = scored["涨跌幅"].map(_position_risk_score)
    scored["新闻催化分"] = 0.0
    scored["主线强势分"] = (
        scored["个股强度分"]
        + scored["板块强度分"]
        + scored["资金流向分"]
        + scored["位置风险分"]
        + scored["新闻催化分"]
    ).round(2)
    scored["买入观察等级"] = scored["主线强势分"].map(_watch_level)
    report_label = _report_label(report_type)
    scored["次日动作建议"] = (
        f"{market_label}{report_label}：观察量能延续、价格承接和风险回落。"
    )
    if report_type == "pre_market":
        scored["早盘买入等级"] = scored["买入观察等级"].map(_pre_market_level)
        scored["早盘动作建议"] = scored["次日动作建议"]

    output_columns = OUTPUT_COLUMNS.copy()
    if report_type == "pre_market":
        output_columns.extend(["早盘买入等级", "早盘动作建议"])
    return (
        scored[output_columns]
        .sort_values(["买入观察等级", "主线强势分"], ascending=[True, False])
        .reset_index(drop=True)
    )


def _position_risk_score(change_pct: float) -> int:
    if change_pct >= 12:
        return 8
    if change_pct >= 8:
        return 16
    return 20


def _watch_level(score: float) -> str:
    if score >= 38:
        return "A_核心关注"
    if score >= 28:
        return "B_继续观察"
    return "C_暂缓跟踪"


def _pre_market_level(level: str) -> str:
    if level.startswith("A_"):
        return "A_早盘重点确认"
    if level.startswith("B_"):
        return "B_继续观察"
    return "C_暂缓跟踪"


def _report_label(report_type: str) -> str:
    return {
        "after_close": "收盘观察",
        "pre_market": "盘前观察",
        "after_hours": "盘后观察",
    }.get(report_type, "观察")


def _ensure_us_extended_session(report_type: str, now: datetime) -> None:
    eastern_now = now.astimezone(US_EASTERN_TZ) if now.tzinfo is not None else now.replace(tzinfo=US_EASTERN_TZ)
    current_time = eastern_now.time()
    if report_type == "pre_market":
        if time(4, 0) <= current_time < time(9, 30):
            return
        raise RuntimeError("strict US pre-market session check failed")
    if report_type == "after_hours":
        if time(16, 0) <= current_time < time(20, 0):
            return
        raise RuntimeError("strict US after-hours session check failed")


def _ensure_hk_session(report_type: str, now: datetime) -> None:
    hk_now = now.astimezone(HK_TZ) if now.tzinfo is not None else now.replace(tzinfo=HK_TZ)
    current_time = hk_now.time()
    if report_type == "pre_market":
        if time(9, 20) <= current_time < time(9, 30):
            return
        raise RuntimeError("strict HK pre-market session check failed")
    if report_type == "after_close":
        if time(16, 10) <= current_time < time(18, 0):
            return
        raise RuntimeError("strict HK after-close session check failed")


def _load_akshare(ak_module: Any | None) -> Any:
    if ak_module is not None:
        return ak_module

    import akshare as ak

    return ak


def _fetch_hk_quotes(ak: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for method_name in ("stock_hk_spot_em", "stock_hk_spot"):
        if not hasattr(ak, method_name):
            continue
        try:
            return getattr(ak, method_name)()
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise RuntimeError(f"AKShare 港股实时行情接口调用失败：{last_error}") from last_error
    raise RuntimeError("AKShare 缺少港股实时行情接口")


def _fetch_us_quotes(ak: Any) -> pd.DataFrame:
    last_error: Exception | None = None
    for method_name in ("stock_us_spot_em", "stock_us_spot"):
        if not hasattr(ak, method_name):
            continue
        try:
            return getattr(ak, method_name)()
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise RuntimeError(f"AKShare 美股实时行情接口调用失败：{last_error}") from last_error
    raise RuntimeError("AKShare 缺少美股实时行情接口")


def _write_market_outputs(
    candidates: pd.DataFrame,
    output_dir: Path,
    prefix: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"{prefix}_{stamp}.csv"
    html_path = output_dir / f"{prefix}_{stamp}.html"

    candidates.to_csv(csv_path, index=False)
    candidates.to_html(html_path, index=False)
    return csv_path, html_path
