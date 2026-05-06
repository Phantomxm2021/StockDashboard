"""
A股主线强势观察池生成器 - AKShare + HTML 看板完整版

功能：
1. 使用 AKShare 获取 A 股实时行情
2. sina 优先，eastmoney 备用
3. 结合成交额、涨幅、板块强度、资金流向、位置风险、新闻催化评分
4. 收盘后 after_close：
   - 输出 candidates_YYYYMMDD.html
   - 输出 candidates_YYYYMMDD.csv
5. 次日早盘 morning：
   - 读取 candidates_YYYYMMDD.csv
   - 输出 morning_confirm_YYYYMMDD.html
   - 输出 morning_confirm_YYYYMMDD.csv
6. 自动分池：
   - A_pool_核心关注
   - B_pool_继续观察
   - C_pool_暂缓跟踪
   - excluded_排除原因
7. 自动打标：
   - 主线强势分
   - 买入观察等级
   - 排除原因
   - 次日动作建议
   - 早盘买入等级
   - 早盘动作建议

运行：
python a_stock_shortlist_akshare_html.py --mode after_close

次日早盘：
python a_stock_shortlist_akshare_html.py --mode morning --yesterday-file output/candidates_20260502.csv

诊断：
python a_stock_shortlist_akshare_html.py --mode diagnose

注意：
本代码仅用于数据整理和量化研究，不构成投资建议。
"""

from __future__ import annotations

import os
import time
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Set, Callable, Tuple, Dict

import pandas as pd
import akshare as ak

from stock_dashboard.strategy import (
    MainlineStrategyConfig,
    MarketContext,
    build_mainline_candidates,
    config_to_df,
    is_bj_stock,
    normalize_code,
)


# ============================================================
# 策略配置
# ============================================================

@dataclass
class StrategyConfig(MainlineStrategyConfig):
    morning_min_change_pct: float = -3.0
    morning_max_change_pct: float = 7.0
    morning_min_amount: float = 50_000_000


# ============================================================
# 通用工具
# ============================================================

def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def safe_money_numeric(series: pd.Series) -> pd.Series:
    text = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
    )
    multiplier = pd.Series(1.0, index=series.index)
    multiplier = multiplier.mask(text.str.contains("亿", na=False), 100_000_000.0)
    multiplier = multiplier.mask(text.str.contains("万", na=False), 10_000.0)
    numeric_text = text.str.replace("亿", "", regex=False).str.replace("万", "", regex=False)
    numeric_text = numeric_text.str.replace("--", "", regex=False)
    return pd.to_numeric(numeric_text, errors="coerce") * multiplier


def find_col(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
    for col in df.columns:
        col_str = str(col).strip()
        for kw in keywords:
            if kw in col_str:
                return col
    return None


def ensure_output_dir(output_dir: str) -> str:
    abs_dir = os.path.abspath(output_dir)
    os.makedirs(abs_dir, exist_ok=True)
    return abs_dir


def print_df_info(name: str, df: pd.DataFrame, max_rows: int = 5) -> None:
    print(f"\n[{name}] rows={len(df)}")
    if len(df) > 0:
        print("columns:", list(df.columns))
        print(df.head(max_rows).to_string(index=False))


# ============================================================
# AKShare 实时行情源
# ============================================================

def build_realtime_providers() -> List[Tuple[str, Callable[[], pd.DataFrame]]]:
    """
    当前优先级：
    1. sina：当前环境更稳定
    2. eastmoney：备用
    3. tencent：如果当前 AKShare 版本存在，作为备用
    """
    providers: List[Tuple[str, Callable[[], pd.DataFrame]]] = []

    if hasattr(ak, "stock_zh_a_spot"):
        providers.append(("sina", getattr(ak, "stock_zh_a_spot")))

    if hasattr(ak, "stock_zh_a_spot_em"):
        providers.append(("eastmoney", getattr(ak, "stock_zh_a_spot_em")))

    if hasattr(ak, "stock_zh_a_spot_tx"):
        providers.append(("tencent", getattr(ak, "stock_zh_a_spot_tx")))

    return providers


def standardize_realtime_quotes(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """
    统一不同 AKShare 实时行情接口字段。

    输出字段至少包含：
    code, 代码, 名称, 最新价, 涨跌幅, 成交额, 换手率, 有换手率数据, 数据源
    """
    if df is None or len(df) == 0:
        raise RuntimeError(f"{source} 返回空数据")

    df = df.copy()
    rename_map = {}

    for col in df.columns:
        col_str = str(col).strip()

        if col_str in ["代码", "symbol", "股票代码", "证券代码"]:
            rename_map[col] = "代码"
        elif col_str in ["名称", "name", "股票名称", "证券简称"]:
            rename_map[col] = "名称"
        elif col_str in ["最新价", "最新", "现价", "trade", "price", "当前价"]:
            rename_map[col] = "最新价"
        elif col_str in ["涨跌幅", "涨幅", "changepercent", "涨跌幅度"]:
            rename_map[col] = "涨跌幅"
        elif col_str in ["成交额", "amount", "成交金额"]:
            rename_map[col] = "成交额"
        elif col_str in ["换手率", "turnoverratio", "换手"]:
            rename_map[col] = "换手率"

    df = df.rename(columns=rename_map)

    required_cols = ["代码", "名称", "最新价", "涨跌幅", "成交额"]
    missing = [col for col in required_cols if col not in df.columns]

    if missing:
        raise RuntimeError(
            f"{source} 缺少必要字段：{missing}\n"
            f"当前字段：{df.columns.tolist()}"
        )

    if "换手率" not in df.columns:
        df["换手率"] = pd.NA
        df["有换手率数据"] = False
    else:
        df["有换手率数据"] = True

    df["code"] = df["代码"].apply(normalize_code)
    df["代码"] = df["code"]

    df["最新价"] = safe_numeric(df["最新价"])
    df["涨跌幅"] = safe_numeric(df["涨跌幅"])
    df["成交额"] = safe_numeric(df["成交额"])
    df["换手率"] = safe_numeric(df["换手率"])

    df["数据源"] = source

    df = df[df["code"].str.len() == 6].copy()
    df = df.dropna(subset=["最新价", "涨跌幅", "成交额"])

    first_cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额",
        "换手率", "有换手率数据", "数据源"
    ]
    other_cols = [c for c in df.columns if c not in first_cols]
    df = df[first_cols + other_cols]

    return df


def get_realtime_quotes() -> pd.DataFrame:
    """
    获取实时行情，带重试和 fallback。
    """
    providers = build_realtime_providers()

    if not providers:
        raise RuntimeError(
            "当前 AKShare 版本没有可用的 A 股实时行情接口。"
            "建议执行：pip install akshare --upgrade"
        )

    errors: List[str] = []

    print("[行情] 当前可用数据源：", [name for name, _ in providers])

    for source, func in providers:
        for retry_index in range(3):
            try:
                print(f"[行情] 尝试数据源：{source}，第 {retry_index + 1} 次")

                raw_df = func()
                df = standardize_realtime_quotes(raw_df, source=source)

                if len(df) == 0:
                    raise RuntimeError(f"{source} 标准化后为空")

                print(f"[行情] 使用数据源：{source}，rows={len(df)}")
                return df

            except Exception as e:
                error_msg = f"{source} 第 {retry_index + 1} 次失败：{repr(e)}"
                print("[WARN]", error_msg)
                errors.append(error_msg)
                time.sleep(1.5 * (retry_index + 1))

    raise RuntimeError(
        "所有实时行情数据源都失败：\n" + "\n".join(errors[-20:])
    )


def get_lhb_today() -> pd.DataFrame:
    """
    获取龙虎榜每日详情。
    """
    if not hasattr(ak, "stock_lhb_detail_daily_sina"):
        print("[WARN] 当前 AKShare 版本没有 stock_lhb_detail_daily_sina")
        return pd.DataFrame(columns=["code", "代码"])

    try:
        df = ak.stock_lhb_detail_daily_sina()
    except Exception as e:
        print(f"[WARN] 龙虎榜获取失败：{repr(e)}")
        return pd.DataFrame(columns=["code", "代码"])

    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["code", "代码"])

    df = df.copy()
    code_col = find_col(df, ["代码", "股票代码", "symbol", "code"])

    if code_col is None:
        print(f"[WARN] 龙虎榜未找到股票代码字段，当前字段：{df.columns.tolist()}")
        return pd.DataFrame(columns=["code", "代码"])

    df["code"] = df[code_col].apply(normalize_code)
    df["代码"] = df["code"]
    df = df[df["code"].str.len() == 6].copy()

    first_cols = ["code", "代码"]
    other_cols = [c for c in df.columns if c not in first_cols]
    return df[first_cols + other_cols]


# ============================================================
# 榜单生成
# ============================================================

def get_amount_rank_from_quotes(quote_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    df = quote_df.copy()
    df = df.sort_values("成交额", ascending=False)

    cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额",
        "换手率", "有换手率数据", "数据源"
    ]
    cols = [c for c in cols if c in df.columns]
    return df.head(top_n)[cols].copy()


def get_gain_rank_from_quotes(quote_df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    df = quote_df.copy()
    df = df.sort_values("涨跌幅", ascending=False)

    cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额",
        "换手率", "有换手率数据", "数据源"
    ]
    cols = [c for c in cols if c in df.columns]
    return df.head(top_n)[cols].copy()


# ============================================================
# 主线强势增强数据
# ============================================================

DEFAULT_ENRICHMENT_CACHE_DIR = Path("reports/cn/enrichment_cache")


def _resolve_enrichment_cache_dir(cache_dir: str | os.PathLike[str] | None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    return Path(os.getenv("STOCK_ENRICHMENT_CACHE_DIR", str(DEFAULT_ENRICHMENT_CACHE_DIR)))


def _enrichment_cache_path(cache_dir: str | os.PathLike[str] | None, name: str) -> Path:
    return _resolve_enrichment_cache_dir(cache_dir) / f"{name}.csv"


def _read_enrichment_cache(
    cache_dir: str | os.PathLike[str] | None,
    name: str,
    columns: list[str],
) -> pd.DataFrame:
    path = _enrichment_cache_path(cache_dir, name)
    if not path.exists():
        print(f"[CACHE] {name} 无可用缓存：{path}")
        return pd.DataFrame(columns=columns)
    try:
        cached = pd.read_csv(path, dtype={"code": str})
    except Exception as e:
        print(f"[WARN] {name} 缓存读取失败：{repr(e)}")
        return pd.DataFrame(columns=columns)
    missing = [column for column in columns if column not in cached.columns]
    if missing:
        print(f"[WARN] {name} 缓存字段缺失：{missing}")
        return pd.DataFrame(columns=columns)
    print(f"[CACHE] {name} 使用上次成功缓存：{path} rows={len(cached)}")
    return cached[columns].copy()


def _write_enrichment_cache(
    cache_dir: str | os.PathLike[str] | None,
    name: str,
    df: pd.DataFrame,
    columns: list[str],
) -> None:
    if df.empty:
        return
    path = _enrichment_cache_path(cache_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df[columns].drop_duplicates("code", keep="first").to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[CACHE] {name} 已更新缓存：{path} rows={len(df)}")


def _merge_enrichment_values(
    base: pd.DataFrame,
    values: pd.DataFrame,
    value_columns: list[str],
) -> pd.DataFrame:
    if values.empty:
        return base
    merged = base.merge(values[["code", *value_columns]], on="code", how="left", suffixes=("", "_cached"))
    for column in value_columns:
        cached_column = f"{column}_cached"
        if cached_column in merged.columns:
            if column == "主线板块":
                merged[column] = merged[cached_column].fillna(merged[column])
            else:
                merged[column] = merged[cached_column].fillna(merged[column])
            merged = merged.drop(columns=[cached_column])
    return merged


def _call_ak_provider(name: str, kwargs: dict | None = None) -> pd.DataFrame:
    if not hasattr(ak, name):
        raise AttributeError(f"AKShare provider not found: {name}")
    fn = getattr(ak, name)
    try:
        result = fn(**(kwargs or {}))
    except TypeError:
        result = fn()
    if result is None or result.empty:
        raise ValueError(f"{name} returned empty data")
    print(f"[ENRICH] provider={name} status=success rows={len(result)}")
    return result


def _try_ak_providers(providers: list[tuple[str, dict | None]], label: str) -> tuple[str, pd.DataFrame] | None:
    for name, kwargs in providers:
        try:
            return name, _call_ak_provider(name, kwargs)
        except Exception as e:
            print(f"[WARN] {label} provider={name} failed: {repr(e)}")
    return None


def build_mainline_enrichment(
    quote_df: pd.DataFrame,
    cache_dir: str | os.PathLike[str] | None = None,
) -> pd.DataFrame:
    """
    尽量用 AKShare 补充主线强度数据。
    数据源波动较大，失败时优先回退到最近一次成功缓存，不阻断基础观察池生成。
    """
    base_columns = ["code"]
    if "名称" in quote_df.columns:
        base_columns.append("名称")
    base = quote_df[base_columns].copy()
    base["主线板块"] = ""
    base["板块强度分"] = 0.0
    base["资金流向分"] = 0.0
    base["新闻催化分"] = 0.0

    base = _apply_sector_strength(base, cache_dir=cache_dir)
    base = _apply_individual_fund_flow(base, cache_dir=cache_dir)
    base = _apply_hot_rank(base, cache_dir=cache_dir)
    return base


def build_market_context(quote_df: pd.DataFrame) -> MarketContext:
    amount_yi = float(pd.to_numeric(quote_df.get("成交额", pd.Series(dtype=float)), errors="coerce").fillna(0).sum() / 100_000_000)
    if amount_yi < 8000:
        state = "shrinking"
    elif amount_yi > 10000:
        state = "expanding"
    else:
        state = "normal"
    return MarketContext(state=state, amount_yi=round(amount_yi, 2))


def _apply_sector_strength(base: pd.DataFrame, cache_dir: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    columns = ["code", "主线板块", "板块强度分"]
    fetched = _try_ak_providers(
        [
            ("stock_sector_fund_flow_rank", {"indicator": "今日", "sector_type": "行业资金流"}),
            ("stock_fund_flow_industry", {"symbol": "即时"}),
            ("stock_fund_flow_concept", {"symbol": "即时"}),
            ("stock_sector_spot", {"indicator": "新浪行业"}),
        ],
        "行业板块资金流",
    )

    if fetched is None:
        cached = _read_enrichment_cache(cache_dir, "sector_strength", columns)
        return _merge_enrichment_values(base, cached, ["主线板块", "板块强度分"])

    provider_name, sector_df = fetched
    name_col = find_col(sector_df, ["名称", "行业", "板块"])
    flow_col = find_col(sector_df, ["主力净流入", "净流入", "资金净流入", "净额"])
    change_col = find_col(sector_df, ["涨跌幅", "涨幅"])
    if name_col is None:
        cached = _read_enrichment_cache(cache_dir, "sector_strength", columns)
        return _merge_enrichment_values(base, cached, ["主线板块", "板块强度分"])

    sector = sector_df.copy()
    if flow_col is not None:
        sector["板块资金净流入"] = safe_money_numeric(sector[flow_col]).fillna(0)
        sector = sector.sort_values("板块资金净流入", ascending=False)
    elif change_col is not None:
        sector["板块涨跌幅"] = safe_numeric(sector[change_col]).fillna(0)
        sector = sector.sort_values("板块涨跌幅", ascending=False)
    top_sectors = [str(value) for value in sector[name_col].head(10).tolist() if str(value).strip()]

    mappings: list[pd.DataFrame] = []
    if hasattr(ak, "stock_board_industry_cons_em"):
        for index, sector_name in enumerate(top_sectors):
            try:
                cons_df = ak.stock_board_industry_cons_em(symbol=sector_name)
            except Exception as e:
                print(f"[WARN] 行业成分获取失败：{sector_name} {repr(e)}")
                continue
            code_col = find_col(cons_df, ["代码", "股票代码", "code"])
            if code_col is None:
                continue
            score = max(25 - index * 2.5, 5)
            mapping = cons_df[[code_col]].copy()
            mapping["code"] = mapping[code_col].apply(normalize_code)
            mapping["主线板块"] = sector_name
            mapping["板块强度分"] = score
            mappings.append(mapping[["code", "主线板块", "板块强度分"]])

    if not mappings and "名称" in base.columns:
        for index, sector_name in enumerate(top_sectors):
            matched = base[base["名称"].astype(str).str.contains(sector_name, na=False, regex=False)][["code"]].copy()
            if matched.empty:
                continue
            matched["主线板块"] = sector_name
            matched["板块强度分"] = max(18 - index * 2, 4)
            mappings.append(matched[["code", "主线板块", "板块强度分"]])

    if not mappings:
        print(f"[WARN] 行业板块 provider={provider_name} 未匹配到候选股")
        cached = _read_enrichment_cache(cache_dir, "sector_strength", columns)
        return _merge_enrichment_values(base, cached, ["主线板块", "板块强度分"])

    sector_map = (
        pd.concat(mappings, ignore_index=True)
        .sort_values("板块强度分", ascending=False)
        .drop_duplicates("code", keep="first")
    )
    _write_enrichment_cache(cache_dir, "sector_strength", sector_map, columns)
    return (
        base.drop(columns=["主线板块", "板块强度分"], errors="ignore")
        .merge(sector_map, on="code", how="left")
        .assign(
            主线板块=lambda df: df["主线板块"].fillna(""),
            板块强度分=lambda df: df["板块强度分"].fillna(0.0),
        )
    )


def _apply_individual_fund_flow(base: pd.DataFrame, cache_dir: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    columns = ["code", "资金流向分"]
    providers = [
        ("stock_individual_fund_flow_rank", {"indicator": "今日"}),
        ("stock_main_fund_flow", {"symbol": "全部股票"}),
        ("stock_fund_flow_individual", {"symbol": "即时"}),
    ]

    for provider_name, kwargs in providers:
        try:
            flow_df = _call_ak_provider(provider_name, kwargs)
        except Exception as e:
            print(f"[WARN] 个股资金流向 provider={provider_name} failed: {repr(e)}")
            continue

        code_col = find_col(flow_df, ["代码", "股票代码", "code"])
        flow_col = find_col(flow_df, ["主力净流入", "净流入", "资金净流入", "净额"])
        if code_col is None or flow_col is None:
            print(f"[WARN] 个股资金流向 provider={provider_name} 字段无法识别 columns={list(flow_df.columns)}")
            continue

        flow = flow_df[[code_col, flow_col]].copy()
        flow["code"] = flow[code_col].apply(normalize_code)
        flow["资金净流入"] = safe_money_numeric(flow[flow_col])
        flow = flow.dropna(subset=["资金净流入"])
        flow = flow.sort_values("资金净流入", ascending=False).drop_duplicates("code", keep="first")
        if flow.empty:
            print(f"[WARN] 个股资金流向 provider={provider_name} 无有效净流入数据")
            continue

        positive = flow["资金净流入"].clip(lower=0)
        max_value = positive.max()
        if pd.isna(max_value) or max_value <= 0:
            print(f"[WARN] 个股资金流向 provider={provider_name} 正向净流入为空")
            continue
        flow["资金流向分"] = (positive / max_value * 16).clip(upper=16)
        _write_enrichment_cache(cache_dir, "individual_fund_flow", flow, columns)
        return base.merge(flow[["code", "资金流向分"]], on="code", how="left", suffixes=("", "_fund")).assign(
            资金流向分=lambda df: df["资金流向分_fund"].fillna(df["资金流向分"])
        ).drop(columns=["资金流向分_fund"])

    cached = _read_enrichment_cache(cache_dir, "individual_fund_flow", columns)
    return _merge_enrichment_values(base, cached, ["资金流向分"])


def _apply_hot_rank(base: pd.DataFrame, cache_dir: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    columns = ["code", "新闻催化分"]
    providers = [
        ("stock_hot_rank_em", None),
        ("stock_hot_rank_latest_em", None),
        ("stock_hot_rank_detail_realtime_em", None),
    ]

    for provider_name, kwargs in providers:
        try:
            hot_df = _call_ak_provider(provider_name, kwargs)
        except Exception as e:
            print(f"[WARN] 热度/新闻催化 provider={provider_name} failed: {repr(e)}")
            continue

        code_col = find_col(hot_df, ["代码", "股票代码", "code"])
        rank_col = find_col(hot_df, ["排名", "排行", "当前排名"])
        if code_col is None or rank_col is None:
            print(f"[WARN] 热度/新闻催化 provider={provider_name} 字段无法识别 columns={list(hot_df.columns)}")
            continue

        hot = hot_df[[code_col, rank_col]].copy()
        hot["code"] = hot[code_col].apply(normalize_code)
        hot["热度排名"] = safe_numeric(hot[rank_col])
        hot = hot.dropna(subset=["热度排名"])
        if hot.empty:
            print(f"[WARN] 热度/新闻催化 provider={provider_name} 无有效排名数据")
            continue
        hot["新闻催化分"] = (10 - (hot["热度排名"].clip(lower=1, upper=100) - 1) / 99 * 10).clip(lower=0, upper=10)
        _write_enrichment_cache(cache_dir, "hot_rank", hot, columns)
        return base.merge(hot[["code", "新闻催化分"]], on="code", how="left", suffixes=("", "_hot")).assign(
            新闻催化分=lambda df: df["新闻催化分_hot"].fillna(df["新闻催化分"])
        ).drop(columns=["新闻催化分_hot"])

    cached = _read_enrichment_cache(cache_dir, "hot_rank", columns)
    return _merge_enrichment_values(base, cached, ["新闻催化分"])


def classify_morning_buy_level(row: pd.Series) -> str:
    change_pct = row.get("涨跌幅", 0)
    amount_yi = row.get("成交额亿", 0)
    score = row.get("早盘确认分", 0)

    if change_pct > 7:
        return "C_不追_高开过多"

    if change_pct < -3:
        return "C_放弃_明显走弱"

    if amount_yi < 0.5:
        return "C_放弃_成交不足"

    if 0 <= change_pct <= 5 and score >= 8:
        return "A_早盘重点确认"

    if -1 <= change_pct <= 6 and score >= 5:
        return "B_继续观察"

    return "C_暂不考虑"


# ============================================================
# 核心策略
# ============================================================

def build_after_close_candidates(
    config: StrategyConfig,
    quote_df: pd.DataFrame,
    amount_rank_df: pd.DataFrame,
    gain_rank_df: pd.DataFrame,
    lhb_df: pd.DataFrame,
    enrichment_df: pd.DataFrame | None = None,
    market_context: MarketContext | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    candidates_df, excluded_df = build_mainline_candidates(
        config=config,
        quote_df=quote_df,
        amount_rank_df=amount_rank_df,
        gain_rank_df=gain_rank_df,
        lhb_df=lhb_df,
        enrichment_df=enrichment_df,
        market_context=market_context,
    )
    print(f"\n[筛选] 原始股票数：{len(quote_df)}")
    print(f"[筛选] candidates：{len(candidates_df)}")
    print(f"[筛选] excluded：{len(excluded_df)}")
    return candidates_df, excluded_df


def split_candidate_pools(candidates_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if candidates_df is None or len(candidates_df) == 0:
        empty = pd.DataFrame()
        return {
            "A_pool_核心关注": empty,
            "B_pool_继续观察": empty,
            "C_pool_暂缓跟踪": empty,
        }

    a_pool = candidates_df[candidates_df["买入观察等级"] == "A_核心关注"].copy()
    b_pool = candidates_df[candidates_df["买入观察等级"] == "B_继续观察"].copy()
    c_pool = candidates_df[candidates_df["买入观察等级"] == "C_暂缓跟踪"].copy()

    if "主线强势分" in a_pool.columns:
        a_pool = a_pool.sort_values("主线强势分", ascending=False)
    if "主线强势分" in b_pool.columns:
        b_pool = b_pool.sort_values("主线强势分", ascending=False)
    if "主线强势分" in c_pool.columns:
        c_pool = c_pool.sort_values("主线强势分", ascending=False)

    return {
        "A_pool_核心关注": a_pool,
        "B_pool_继续观察": b_pool,
        "C_pool_暂缓跟踪": c_pool,
    }


# ============================================================
# 早盘确认
# ============================================================

def morning_confirm(
    yesterday_candidates_path: str,
    config: StrategyConfig,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    morning 只读取 after_close 生成的 CSV。
    HTML 只负责展示，不负责反读。
    """
    if not os.path.exists(yesterday_candidates_path):
        raise FileNotFoundError(f"文件不存在：{yesterday_candidates_path}")

    if not yesterday_candidates_path.endswith(".csv"):
        raise RuntimeError(
            "morning 模式请传入 after_close 生成的 CSV 文件，"
            "例如：output/candidates_20260502.csv。不要传 HTML。"
        )

    yesterday_df = pd.read_csv(
        yesterday_candidates_path,
        dtype={"code": str, "代码": str},
    )

    if "code" not in yesterday_df.columns:
        raise RuntimeError("昨日候选池 CSV 缺少 code 字段")

    # 优先读取昨日 A 池；如果没有 A 池，就退回读取全部候选
    if "买入观察等级" in yesterday_df.columns:
        a_df = yesterday_df[yesterday_df["买入观察等级"].astype(str).str.startswith("A_")].copy()
        if len(a_df) > 0:
            yesterday_df = a_df

    yesterday_codes = set(yesterday_df["code"].astype(str).apply(normalize_code))

    quote_df = get_realtime_quotes()
    df = quote_df[quote_df["code"].isin(yesterday_codes)].copy()

    if len(df) == 0:
        return pd.DataFrame(), quote_df

    before_count = len(df)

    df = df[
        (df["涨跌幅"] >= config.morning_min_change_pct) &
        (df["涨跌幅"] <= config.morning_max_change_pct) &
        (df["成交额"] >= config.morning_min_amount)
    ].copy()

    print(f"\n[早盘确认] 过滤前：{before_count}，过滤后：{len(df)}")

    if len(df) == 0:
        return pd.DataFrame(), quote_df

    df["成交额亿"] = df["成交额"] / 100_000_000

    has_real_turnover = (
        "有换手率数据" in df.columns
        and df["有换手率数据"].fillna(False).any()
    )

    if has_real_turnover:
        turnover_score = df["换手率"].fillna(0) * 1.2
    else:
        turnover_score = 0

    df["早盘确认分"] = (
        df["涨跌幅"] * 2.0 +
        turnover_score +
        df["成交额亿"].clip(upper=30)
    )

    df["早盘买入等级"] = df.apply(classify_morning_buy_level, axis=1)

    df["早盘动作建议"] = df["早盘买入等级"].map({
        "A_早盘重点确认": "重点看分时承接：不高开过热，回踩不破均线再考虑",
        "B_继续观察": "继续观察：等待板块和个股进一步确认",
        "C_不追_高开过多": "不追：高开过多，T+1风险较大",
        "C_放弃_明显走弱": "放弃：明显走弱",
        "C_放弃_成交不足": "放弃：成交不足",
        "C_暂不考虑": "暂不考虑",
    }).fillna("暂不考虑")

    df = df.sort_values(["早盘买入等级", "早盘确认分"], ascending=[True, False])

    keep_cols = [
        "code", "代码", "名称", "最新价", "涨跌幅", "成交额亿",
        "换手率", "有换手率数据",
        "早盘确认分", "早盘买入等级", "早盘动作建议",
        "数据源",
    ]
    keep_cols = [col for col in keep_cols if col in df.columns]

    return df[keep_cols].copy(), quote_df


def split_morning_pools(confirm_df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    if confirm_df is None or len(confirm_df) == 0:
        empty = pd.DataFrame()
        return {
            "A_morning_重点确认": empty,
            "B_morning_继续观察": empty,
            "C_morning_暂不考虑": empty,
        }

    return {
        "A_morning_重点确认": confirm_df[confirm_df["早盘买入等级"] == "A_早盘重点确认"].copy(),
        "B_morning_继续观察": confirm_df[confirm_df["早盘买入等级"] == "B_继续观察"].copy(),
        "C_morning_暂不考虑": confirm_df[confirm_df["早盘买入等级"].astype(str).str.startswith("C_")].copy(),
    }


# ============================================================
# HTML 输出
# ============================================================

def add_html_tags(df: pd.DataFrame) -> pd.DataFrame:
    """
    给等级字段加 HTML 标签。
    """
    if df is None or len(df) == 0:
        return df

    out = df.copy()

    def tag_level(value: object) -> str:
        text = str(value)

        if text.startswith("A_"):
            return f'<span class="tag tag-a">{text}</span>'

        if text.startswith("B_"):
            return f'<span class="tag tag-b">{text}</span>'

        if text.startswith("C_"):
            return f'<span class="tag tag-c">{text}</span>'

        if text.startswith("X_"):
            return f'<span class="tag tag-x">{text}</span>'

        return text

    for col in ["买入观察等级", "早盘买入等级"]:
        if col in out.columns:
            out[col] = out[col].apply(tag_level)

    return out


def dataframe_to_html_table(df: pd.DataFrame, title: str) -> str:
    """
    把 DataFrame 转成 HTML 表格。
    """
    if df is None or len(df) == 0:
        return f"""
        <section class="card">
            <h2>{title}</h2>
            <p class="empty">暂无数据</p>
        </section>
        """

    safe_df = df.copy()

    for col in ["code", "代码"]:
        if col in safe_df.columns:
            safe_df[col] = safe_df[col].astype(str).apply(normalize_code)

    table_html = safe_df.to_html(
        index=False,
        escape=False,
        classes="data-table",
        border=0
    )

    return f"""
    <section class="card">
        <div class="section-header">
            <h2>{title}</h2>
            <span class="count">{len(safe_df)} 条</span>
        </div>
        <div class="table-wrap">
            {table_html}
        </div>
    </section>
    """


def build_html_report(
    title: str,
    subtitle: str,
    sections: Dict[str, pd.DataFrame],
) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    section_html = "\n".join([
        dataframe_to_html_table(df, name)
        for name, df in sections.items()
    ])

    return f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
    <style>
        :root {{
            --bg: #f5f7fb;
            --card: rgba(255, 255, 255, 0.88);
            --text: #111827;
            --muted: #6b7280;
            --border: rgba(17, 24, 39, 0.08);
            --green: #16a34a;
            --blue: #2563eb;
            --orange: #ea580c;
            --red: #dc2626;
            --shadow: 0 16px 40px rgba(15, 23, 42, 0.08);
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                         "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
            background:
                radial-gradient(circle at top left, rgba(59, 130, 246, 0.14), transparent 36%),
                radial-gradient(circle at top right, rgba(34, 197, 94, 0.12), transparent 32%),
                var(--bg);
            color: var(--text);
        }}

        .page {{
            max-width: 1440px;
            margin: 0 auto;
            padding: 32px;
        }}

        .hero {{
            margin-bottom: 28px;
            padding: 28px 30px;
            border: 1px solid var(--border);
            border-radius: 28px;
            background: rgba(255, 255, 255, 0.72);
            box-shadow: var(--shadow);
            backdrop-filter: blur(20px);
        }}

        .hero h1 {{
            margin: 0 0 8px;
            font-size: 32px;
            letter-spacing: -0.03em;
        }}

        .hero p {{
            margin: 4px 0;
            color: var(--muted);
            font-size: 15px;
        }}

        .tips {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}

        .tip {{
            padding: 16px;
            border-radius: 20px;
            background: rgba(255,255,255,0.72);
            border: 1px solid var(--border);
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
        }}

        .tip strong {{
            display: block;
            margin-bottom: 6px;
            font-size: 15px;
        }}

        .tip span {{
            color: var(--muted);
            font-size: 13px;
            line-height: 1.5;
        }}

        .card {{
            margin-bottom: 26px;
            padding: 22px;
            border-radius: 24px;
            background: var(--card);
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            backdrop-filter: blur(20px);
        }}

        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }}

        h2 {{
            margin: 0;
            font-size: 20px;
            letter-spacing: -0.02em;
        }}

        .count {{
            color: var(--muted);
            font-size: 13px;
            background: rgba(17, 24, 39, 0.05);
            padding: 5px 10px;
            border-radius: 999px;
        }}

        .table-wrap {{
            overflow-x: auto;
            border-radius: 16px;
            border: 1px solid var(--border);
            max-height: 720px;
        }}

        table.data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            background: white;
        }}

        table.data-table thead th {{
            position: sticky;
            top: 0;
            z-index: 1;
            background: #f9fafb;
            color: #374151;
            text-align: left;
            padding: 11px 10px;
            border-bottom: 1px solid var(--border);
            white-space: nowrap;
            font-weight: 700;
        }}

        table.data-table tbody td {{
            padding: 10px;
            border-bottom: 1px solid rgba(17, 24, 39, 0.06);
            white-space: nowrap;
            vertical-align: top;
        }}

        table.data-table tbody tr:hover {{
            background: #f8fafc;
        }}

        .empty {{
            color: var(--muted);
            margin: 8px 0 0;
        }}

        .tag {{
            display: inline-block;
            padding: 4px 9px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 700;
        }}

        .tag-a {{
            background: rgba(22, 163, 74, 0.12);
            color: var(--green);
        }}

        .tag-b {{
            background: rgba(37, 99, 235, 0.12);
            color: var(--blue);
        }}

        .tag-c {{
            background: rgba(234, 88, 12, 0.12);
            color: var(--orange);
        }}

        .tag-x {{
            background: rgba(220, 38, 38, 0.12);
            color: var(--red);
        }}

        .footer {{
            color: var(--muted);
            font-size: 12px;
            text-align: center;
            margin-top: 24px;
            padding-bottom: 20px;
        }}

        @media (max-width: 900px) {{
            .page {{
                padding: 18px;
            }}

            .tips {{
                grid-template-columns: 1fr;
            }}

            .hero h1 {{
                font-size: 26px;
            }}
        }}
    </style>
</head>
<body>
    <main class="page">
        <header class="hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
            <p>生成时间：{generated_at}</p>
        </header>

        <section class="tips">
            <div class="tip">
                <strong>A 池</strong>
                <span>重点盯盘，不代表直接买。次日需要看竞价、板块和分时承接。</span>
            </div>
            <div class="tip">
                <strong>B 池</strong>
                <span>继续观察，只有次日强于预期或板块继续走强时才升级。</span>
            </div>
            <div class="tip">
                <strong>C 池</strong>
                <span>暂不考虑，通常是信号不足、过热或风险较高。</span>
            </div>
            <div class="tip">
                <strong>Morning</strong>
                <span>建议次日 9:35 - 10:00 运行，用于开盘后确认。</span>
            </div>
        </section>

        {section_html}

        <div class="footer">
            本页面仅用于数据整理和量化研究，不构成投资建议。
        </div>
    </main>
</body>
</html>
"""


def write_html_report(
    output_path: str,
    title: str,
    subtitle: str,
    sections: Dict[str, pd.DataFrame],
) -> None:
    output_path = os.path.abspath(output_path)

    html_sections = {
        name: add_html_tags(df)
        for name, df in sections.items()
    }

    html = build_html_report(
        title=title,
        subtitle=subtitle,
        sections=html_sections,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n[HTML] 已写入：{output_path}")


# ============================================================
# 诊断
# ============================================================

def diagnose_realtime_sources() -> None:
    providers = build_realtime_providers()

    print("\n当前 AKShare 版本：")
    try:
        print(ak.__version__)
    except Exception:
        print("无法读取 ak.__version__")

    print("\n当前检测到的实时行情接口：")
    print([name for name, _ in providers] if providers else "没有检测到可用接口")

    for source, func in providers:
        print("\n" + "=" * 80)
        print(f"诊断数据源：{source}")
        print("=" * 80)

        try:
            df = func()
            print(f"rows={len(df)}")
            print("columns:")
            print(df.columns.tolist())
            print("\nhead:")
            print(df.head(5).to_string(index=False))

            try:
                std_df = standardize_realtime_quotes(df, source=source)
                print("\n标准化成功：")
                print(std_df.head(5).to_string(index=False))
            except Exception as std_error:
                print("\n标准化失败：")
                print(repr(std_error))

        except Exception as e:
            print("获取失败：")
            print(repr(e))


def diagnose_all_functions() -> None:
    names = dir(ak)
    keywords = ["stock_zh_a_spot", "stock_zh_a", "spot"]

    matched = []
    for name in names:
        for kw in keywords:
            if kw in name:
                matched.append(name)
                break

    matched = sorted(set(matched))

    print("\n当前 AKShare 中疑似行情相关函数：")
    for name in matched:
        print(name)


# ============================================================
# 运行入口
# ============================================================

def run_after_close(output_dir: str = "output") -> pd.DataFrame:
    output_dir = ensure_output_dir(output_dir)
    config = StrategyConfig()

    print("[1/5] 获取 A 股实时行情...")
    quote_df = get_realtime_quotes()
    print_df_info("实时行情", quote_df)

    print("\n[2/5] 生成成交额榜...")
    amount_rank_df = get_amount_rank_from_quotes(quote_df, config.amount_top_n)
    print_df_info("成交额榜", amount_rank_df)

    print("\n[3/5] 生成涨幅榜 + 获取龙虎榜补充信号...")
    gain_rank_df = get_gain_rank_from_quotes(quote_df, config.gain_top_n)
    print_df_info("涨幅榜", gain_rank_df)

    lhb_df = get_lhb_today()
    print_df_info("龙虎榜", lhb_df)

    market_context = build_market_context(quote_df)
    print(f"\n[市场环境] {market_context.label}，全市场成交额约 {market_context.amount_yi:.0f} 亿")

    print("\n[4/5] 获取主线增强数据：板块强度 + 资金流向 + 新闻热度...")
    enrichment_df = build_mainline_enrichment(quote_df)
    print_df_info("主线增强数据", enrichment_df)

    print("\n[5/5] 生成主线强势观察池并自动打标...")
    candidates_df, excluded_df = build_after_close_candidates(
        config=config,
        quote_df=quote_df,
        amount_rank_df=amount_rank_df,
        gain_rank_df=gain_rank_df,
        lhb_df=lhb_df,
        enrichment_df=enrichment_df,
        market_context=market_context,
    )

    pools = split_candidate_pools(candidates_df)

    print_df_info("A_pool_核心关注", pools["A_pool_核心关注"], max_rows=20)
    print_df_info("B_pool_继续观察", pools["B_pool_继续观察"], max_rows=20)
    print_df_info("C_pool_暂缓跟踪", pools["C_pool_暂缓跟踪"], max_rows=20)

    today = datetime.now().strftime("%Y%m%d")

    # CSV 给 morning 模式读取
    csv_path = os.path.join(output_dir, f"candidates_{today}.csv")
    candidates_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print("\n[CSV] 已写入：")
    print(os.path.abspath(csv_path))

    # HTML 给你直接浏览
    html_path = os.path.join(output_dir, f"candidates_{today}.html")

    sections = {
        "A_pool_核心关注": pools["A_pool_核心关注"],
        "B_pool_继续观察": pools["B_pool_继续观察"],
        "C_pool_暂缓跟踪": pools["C_pool_暂缓跟踪"],
        "candidates_all_全部候选": candidates_df,
        "excluded_排除原因": excluded_df,
        "amount_rank_成交额榜": amount_rank_df,
        "gain_rank_涨幅榜": gain_rank_df,
        "config_参数": config_to_df(config),
    }

    write_html_report(
        output_path=html_path,
        title="A股主线强势观察池",
        subtitle="收盘后观察池：结合个股强度、板块强度、资金流向、位置风险与新闻催化。",
        sections=sections,
    )

    print("\n请打开这个 HTML 文件：")
    print(os.path.abspath(html_path))

    print("\n次日 morning 请传入这个 CSV 文件：")
    print(os.path.abspath(csv_path))

    return candidates_df


def run_morning_confirm(yesterday_file: str, output_dir: str = "output") -> pd.DataFrame:
    output_dir = ensure_output_dir(output_dir)
    config = StrategyConfig()

    confirm_df, quote_df = morning_confirm(yesterday_file, config)
    morning_pools = split_morning_pools(confirm_df)

    print_df_info("A_morning_重点确认", morning_pools["A_morning_重点确认"], max_rows=20)
    print_df_info("B_morning_继续观察", morning_pools["B_morning_继续观察"], max_rows=20)
    print_df_info("C_morning_暂不考虑", morning_pools["C_morning_暂不考虑"], max_rows=20)

    today = datetime.now().strftime("%Y%m%d")
    html_path = os.path.join(output_dir, f"morning_confirm_{today}.html")
    csv_path = os.path.join(output_dir, f"morning_confirm_{today}.csv")

    confirm_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    sections = {
        "A_morning_重点确认": morning_pools["A_morning_重点确认"],
        "B_morning_继续观察": morning_pools["B_morning_继续观察"],
        "C_morning_暂不考虑": morning_pools["C_morning_暂不考虑"],
        "morning_confirm_all_全部早盘确认": confirm_df,
        "config_参数": config_to_df(config),
    }

    write_html_report(
        output_path=html_path,
        title="A股早盘确认池",
        subtitle="建议次日 9:35 - 10:00 运行，用于确认昨日观察池中哪些股票仍然强势。",
        sections=sections,
    )

    print("\n请打开这个 HTML 文件：")
    print(os.path.abspath(html_path))

    print("\n早盘确认 CSV：")
    print(os.path.abspath(csv_path))

    return confirm_df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A股 T+1 短线观察池生成器 - AKShare + HTML 看板完整版"
    )

    parser.add_argument(
        "--mode",
        choices=[
            "after_close",
            "morning",
            "diagnose",
            "diagnose_functions",
        ],
        default="after_close",
        help=(
            "after_close=收盘后生成观察池；"
            "morning=次日早盘确认；"
            "diagnose=诊断实时行情源；"
            "diagnose_functions=打印 AKShare 行情相关函数"
        ),
    )

    parser.add_argument(
        "--yesterday-file",
        type=str,
        default="",
        help="morning 模式需要传入 after_close 生成的 candidates_xxx.csv",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="输出目录",
    )

    args = parser.parse_args()

    if args.mode == "after_close":
        run_after_close(output_dir=args.output_dir)

    elif args.mode == "morning":
        if not args.yesterday_file:
            raise RuntimeError(
                "morning 模式需要传入 --yesterday-file，例如："
                "output/candidates_20260502.csv"
            )

        run_morning_confirm(
            yesterday_file=args.yesterday_file,
            output_dir=args.output_dir,
        )

    elif args.mode == "diagnose":
        diagnose_realtime_sources()

    elif args.mode == "diagnose_functions":
        diagnose_all_functions()


if __name__ == "__main__":
    main()
