from __future__ import annotations

import os
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

US_EASTERN_TZ = ZoneInfo("America/New_York")
HK_TZ = ZoneInfo("Asia/Hong_Kong")
ALPACA_BASE_URL = "https://data.alpaca.markets"
US_EXTENDED_REPORT_TYPES = {"pre_market", "after_hours"}
US_ALPACA_CANDIDATE_LIMIT = 200


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
    snapshot_client: Any | None = None,
) -> tuple[Path, Path]:
    if enforce_session:
        _ensure_us_extended_session(report_type, now or datetime.now(US_EASTERN_TZ))
    if report_type in US_EXTENDED_REPORT_TYPES and (ak_module is None or snapshot_client is not None):
        quotes = _fetch_alpaca_us_extended_quotes(ak_module=ak_module, snapshot_client=snapshot_client)
    else:
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


def _fetch_alpaca_us_extended_quotes(
    ak_module: Any | None = None,
    snapshot_client: Any | None = None,
) -> pd.DataFrame:
    api_key_id = os.getenv("ALPACA_API_KEY_ID")
    api_secret_key = os.getenv("ALPACA_API_SECRET_KEY")
    if not api_key_id or not api_secret_key:
        raise RuntimeError(
            "美股盘前/盘后观察需要配置 ALPACA_API_KEY_ID 和 ALPACA_API_SECRET_KEY，"
            "否则无法区分扩展时段行情。"
        )

    if snapshot_client is None:
        import httpx

        snapshot_client = httpx

    base_quotes = _fetch_us_quotes(_load_akshare(ak_module))
    universe = _build_us_alpaca_universe(base_quotes)
    if universe.empty:
        raise RuntimeError("AKShare 美股初筛后没有可供 Alpaca 修正的候选。")

    snapshots = _fetch_alpaca_snapshots(
        universe["alpaca_symbol"].tolist(),
        snapshot_client=snapshot_client,
        api_key_id=api_key_id,
        api_secret_key=api_secret_key,
    )

    rows: list[dict[str, Any]] = []
    for item in universe.to_dict("records"):
        snapshot = snapshots.get(str(item["alpaca_symbol"]))
        if not isinstance(snapshot, dict):
            continue
        quote = _alpaca_snapshot_to_quote(item, snapshot)
        if quote is not None:
            rows.append(quote)

    if not rows:
        raise RuntimeError("Alpaca IEX 没有返回可用的美股扩展时段候选行情。")
    return pd.DataFrame(rows)


def _build_us_alpaca_universe(quotes: pd.DataFrame) -> pd.DataFrame:
    df = _normalize_quote_frame(quotes, market_label="美股")
    df["alpaca_symbol"] = df["code"].map(_to_alpaca_symbol)
    df = df[
        (df["alpaca_symbol"] != "")
        & (df["最新价"] >= 5)
        & (df["成交额"] >= 100_000_000)
        & (df["涨跌幅"] >= 1.0)
    ].copy()
    df = df.sort_values("成交额", ascending=False).drop_duplicates("alpaca_symbol")
    return df.head(US_ALPACA_CANDIDATE_LIMIT)


def _to_alpaca_symbol(code: Any) -> str:
    raw = str(code or "").strip().upper()
    if "." in raw:
        raw = raw.rsplit(".", 1)[-1]
    return raw.replace("-", ".")


def _fetch_alpaca_snapshots(
    symbols: list[str],
    snapshot_client: Any,
    api_key_id: str,
    api_secret_key: str,
) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    base_url = os.getenv("ALPACA_API_BASE_URL", ALPACA_BASE_URL).rstrip("/")
    url = f"{base_url}/v2/stocks/snapshots"
    for batch_start in range(0, len(symbols), 100):
        batch = symbols[batch_start : batch_start + 100]
        response = _alpaca_get(
            snapshot_client,
            url,
            params={"symbols": ",".join(batch), "feed": "iex"},
            api_key_id=api_key_id,
            api_secret_key=api_secret_key,
        )
        payload = response.json()
        batch_snapshots = payload.get("snapshots") if isinstance(payload, dict) else None
        if isinstance(batch_snapshots, dict):
            snapshots.update(batch_snapshots)
            continue
        for symbol in batch:
            if isinstance(payload, dict) and isinstance(payload.get(symbol), dict):
                snapshots[symbol] = payload[symbol]
    return snapshots


def _alpaca_get(
    snapshot_client: Any,
    url: str,
    params: dict[str, str],
    api_key_id: str,
    api_secret_key: str,
) -> Any:
    response = snapshot_client.get(
        url,
        params=params,
        timeout=30,
        headers={
            "Accept": "application/json",
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
            "User-Agent": "stock-dashboard/1.0",
        },
    )
    try:
        response.raise_for_status()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {401, 403}:
            raise RuntimeError(
                "Alpaca 美股 IEX snapshot 授权失败，请检查 ALPACA_API_KEY_ID 和 "
                "ALPACA_API_SECRET_KEY 是否有效。"
            ) from exc
        raise RuntimeError(f"Alpaca 美股 IEX snapshot 请求失败：HTTP {status_code or 'unknown'}") from exc
    return response


def _alpaca_snapshot_to_quote(base_item: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(base_item.get("alpaca_symbol") or "").strip()
    latest_trade = snapshot.get("latestTrade") if isinstance(snapshot.get("latestTrade"), dict) else {}
    minute_bar = snapshot.get("minuteBar") if isinstance(snapshot.get("minuteBar"), dict) else {}
    daily_bar = snapshot.get("dailyBar") if isinstance(snapshot.get("dailyBar"), dict) else {}
    prev_daily_bar = snapshot.get("prevDailyBar") if isinstance(snapshot.get("prevDailyBar"), dict) else {}

    price = _first_number(latest_trade.get("p"), minute_bar.get("c"), daily_bar.get("c"))
    previous_close = _first_number(prev_daily_bar.get("c"))
    change_pct = None
    if price is not None and previous_close not in {None, 0}:
        change_pct = (price - previous_close) / previous_close * 100
    else:
        change_pct = _first_number(base_item.get("涨跌幅"))

    volume = _first_number(daily_bar.get("v"), minute_bar.get("v"), 0) or 0
    amount = None
    if amount is None and price is not None:
        amount = price * volume

    return {
        "code": ticker,
        "名称": str(base_item.get("名称") or ticker),
        "最新价": price or 0,
        "涨跌幅": round(change_pct or 0, 2),
        "成交额": amount or 0,
    }


def _first_number(*values: Any) -> float | None:
    for value in values:
        try:
            if value is None or value == "":
                continue
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


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
