from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from stock_dashboard.markets import ReportTypeDefinition, get_market_definition


AFTER_CLOSE_POOLS = [
    ("core", "核心关注", "买入观察等级", ("A_", "核心关注")),
    ("watch", "继续观察", "买入观察等级", ("B_", "继续观察")),
    ("defer", "暂缓跟踪", "买入观察等级", ("C_", "暂缓跟踪")),
    ("all", "全部候选", None, None),
]

MORNING_POOLS = [
    ("core", "核心关注", "早盘买入等级", ("A_早盘重点确认", "早盘重点确认")),
    ("watch", "继续观察", "早盘买入等级", ("B_继续观察", "继续观察")),
    ("defer", "暂缓跟踪", "早盘买入等级", ("C_", "暂不考虑", "不追", "放弃")),
    ("all", "全部候选", None, None),
]

HIDDEN_COLUMNS = {
    "code",
    "换手率",
    "有换手率数据",
    "龙虎榜信号",
    "风险扣分",
    "排除原因",
    "数据源",
}


@dataclass(frozen=True)
class ReportQuery:
    report_type: str
    pool: str
    page: int
    page_size: int
    market: str = "cn"


def read_status(report_dir: Path, market: str = "cn") -> dict[str, Any]:
    market_def = get_market_definition(market)
    path = report_dir / market_def.id / "status.json"
    if market_def.id == "cn" and not path.exists():
        path = report_dir / "status.json"
    if not path.exists():
        return {
            "status": "empty",
            "message": "还没有运行过定时任务",
            "market": market_def.id,
            "market_name": market_def.name,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "error",
            "message": f"status.json 读取失败：{exc}",
            "market": market_def.id,
            "market_name": market_def.name,
        }


def build_report_payload(report_dir: Path, query: ReportQuery) -> dict[str, Any]:
    market = get_market_definition(query.market)
    report_type = _normalize_report_type(query.report_type)
    report_def = _get_report_definition(market.reports, report_type)
    csv_path = _report_csv_path(report_dir, market.id, report_def)
    pool_defs = MORNING_POOLS if report_type in {"morning", "pre_market"} else AFTER_CLOSE_POOLS

    df = _read_csv(csv_path)
    pools = [_pool_summary(df, definition) for definition in pool_defs]
    active_pool = query.pool if any(item["key"] == query.pool for item in pools) else "core"
    active_df = _filter_pool(df, pool_defs, active_pool)
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), 200)
    total = len(active_df)
    total_pages = max(math.ceil(total / page_size), 1)
    start = (page - 1) * page_size
    end = start + page_size
    page_df = _format_display_values(_visible_columns(active_df.iloc[start:end].copy()))

    return {
        "market": market.id,
        "market_name": market.name,
        "report_type": report_type,
        "active_pool": active_pool,
        "pools": pools,
        "columns": [str(col) for col in page_df.columns],
        "rows": _records(page_df),
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
        },
    }


def _normalize_report_type(report_type: str) -> str:
    return report_type.replace("-", "_")


def _get_report_definition(
    reports: tuple[ReportTypeDefinition, ...],
    report_type: str,
) -> ReportTypeDefinition:
    for report in reports:
        if report.id == report_type:
            return report
    raise ValueError(f"unknown report_type: {report_type}")


def _report_csv_path(report_dir: Path, market_id: str, report_def: ReportTypeDefinition) -> Path:
    path = report_dir / market_id / report_def.latest_csv
    if market_id == "cn" and not path.exists():
        if report_def.id == "after_close":
            return report_dir / "latest_candidates.csv"
        if report_def.id == "morning":
            return report_dir / "latest_morning.csv"
    return path


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"code": str, "代码": str}).fillna("")


def _pool_summary(
    df: pd.DataFrame,
    definition: tuple[str, str, str | None, tuple[str, ...] | None],
) -> dict[str, object]:
    key, title, _, _ = definition
    return {"key": key, "title": title, "count": len(_filter_pool_from_definition(df, definition))}


def _filter_pool(
    df: pd.DataFrame,
    pool_defs: list[tuple[str, str, str | None, tuple[str, ...] | None]],
    pool_key: str,
) -> pd.DataFrame:
    for definition in pool_defs:
        if definition[0] == pool_key:
            return _filter_pool_from_definition(df, definition)
    return pd.DataFrame()


def _filter_pool_from_definition(
    df: pd.DataFrame,
    definition: tuple[str, str, str | None, tuple[str, ...] | None],
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    _, _, column, prefix = definition
    if column is None or prefix is None:
        return df.copy()
    if column not in df.columns:
        return pd.DataFrame(columns=df.columns)
    raw_values = df[column].astype(str)
    display_values = raw_values.map(_strip_level_prefix)
    mask = pd.Series(False, index=df.index)
    for item in prefix:
        normalized_item = _strip_level_prefix(item)
        mask = mask | raw_values.str.startswith(item) | display_values.str.startswith(normalized_item)
    return df[mask].copy()


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    records = df.to_dict(orient="records")
    return [{str(key): value for key, value in row.items()} for row in records]


def _visible_columns(df: pd.DataFrame) -> pd.DataFrame:
    keep_columns = [column for column in df.columns if str(column) not in HIDDEN_COLUMNS]
    return df[keep_columns].copy()


def _format_display_values(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    for column in ["买入观察等级", "早盘买入等级"]:
        if column in out.columns:
            out[column] = out[column].astype(str).map(_strip_level_prefix)
    return out


def _strip_level_prefix(value: str) -> str:
    if len(value) >= 3 and value[1] == "_" and value[0] in {"A", "B", "C"}:
        return value[2:]
    return value
