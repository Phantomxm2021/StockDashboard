from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Callable

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import a_stock_shortlist_akshare_html as a_stock


CACHE_DIR = ROOT_DIR / "reports" / "cn" / "enrichment_cache"


def main() -> None:
    print("== A股数据流诊断 ==")
    print(f"项目目录: {ROOT_DIR}")
    print(f"缓存目录: {CACHE_DIR}")

    quotes = run_step("1. 实时行情", load_quotes)
    if quotes is None or quotes.empty:
        print("\n[STOP] 没有实时行情，也没有可用落盘数据，后续无法诊断。")
        return

    run_step("2. 成交额榜", lambda: diagnose_amount_rank(quotes))
    sector_fund = run_step("3. 板块资金源", diagnose_sector_fund_flow)
    sector = run_step("4. 板块强度", lambda: diagnose_sector_strength(quotes))
    fund = run_step("5. 个股资金流", lambda: diagnose_individual_fund_flow(quotes))
    hot = run_step("6. 热度/新闻催化", lambda: diagnose_hot_rank(quotes))

    print("\n== 汇总 ==")
    print_summary("实时行情", quotes, value_column=None)
    print_summary("板块资金源", sector_fund, value_column="板块资金净流入")
    print_summary("板块强度", sector, value_column="板块强度分")
    print_summary("个股资金流", fund, value_column="资金流向分")
    print_summary("热度/新闻催化", hot, value_column="新闻催化分")


def run_step(name: str, fn: Callable[[], pd.DataFrame | None]) -> pd.DataFrame | None:
    print(f"\n--- {name} ---")
    try:
        result = fn()
        if result is None:
            print("结果: None")
        else:
            print(f"结果行数: {len(result)}")
        return result
    except Exception as exc:
        print("步骤失败:", repr(exc))
        traceback.print_exc()
        return None


def load_quotes() -> pd.DataFrame:
    try:
        quotes = a_stock.get_realtime_quotes()
        print("实时行情来源: 在线接口")
        print_frame(quotes, ["code", "代码", "名称", "最新价", "涨跌幅", "成交额", "数据源"], rows=10)
        return quotes
    except Exception as exc:
        print("实时行情在线接口失败:", repr(exc))
        latest = ROOT_DIR / "reports" / "cn" / "latest_after_close.csv"
        if not latest.exists():
            raise
        quotes = pd.read_csv(latest, dtype={"code": str, "代码": str})
        if "code" not in quotes.columns and "代码" in quotes.columns:
            quotes["code"] = quotes["代码"].apply(a_stock.normalize_code)
        if "名称" not in quotes.columns:
            quotes["名称"] = ""
        print(f"实时行情来源: 落盘文件 {latest}")
        print_frame(quotes, ["code", "代码", "名称", "最新价", "涨跌幅", "成交额亿", "数据源"], rows=10)
        return quotes


def diagnose_amount_rank(quotes: pd.DataFrame) -> pd.DataFrame:
    if "成交额" not in quotes.columns and "成交额亿" in quotes.columns:
        quotes = quotes.copy()
        quotes["成交额"] = pd.to_numeric(quotes["成交额亿"], errors="coerce").fillna(0) * 100_000_000
    amount_rank = a_stock.get_amount_rank_from_quotes(quotes, top_n=100)
    print("成交额榜 top_n: 100")
    print_frame(amount_rank, ["code", "代码", "名称", "最新价", "涨跌幅", "成交额", "成交额亿", "数据源"], rows=20)
    return amount_rank


def diagnose_sector_fund_flow() -> pd.DataFrame:
    fetched = a_stock._fetch_sector_fund_flow()
    if fetched is None:
        print("板块资金源: 全部 provider 失败")
        return pd.DataFrame()

    provider_name, sector_df, name_col, flow_col, change_col = fetched
    print(f"板块资金 provider: {provider_name}")
    print(f"字段识别: name_col={name_col!r}, flow_col={flow_col!r}, change_col={change_col!r}")
    print("原始字段:", list(sector_df.columns))
    ranked = a_stock._rank_sector_fund_flow(sector_df, flow_col=flow_col, change_col=change_col)
    display_cols = [col for col in [name_col, flow_col, change_col, "板块资金净流入", "板块涨跌幅"] if col in ranked.columns]
    print_frame(ranked, display_cols, rows=20)
    return ranked


def diagnose_sector_strength(quotes: pd.DataFrame) -> pd.DataFrame:
    base = quotes[required_columns(quotes, ["code", "名称"])].copy()
    enrichment = a_stock._apply_sector_strength(base, cache_dir=CACHE_DIR)
    nonzero = enrichment[enrichment["板块强度分"] > 0].sort_values(["板块强度分", "code"], ascending=[False, True])
    print_coverage(enrichment, "板块强度分")
    print_frame(nonzero, ["code", "名称", "主线板块", "板块强度分"], rows=40)
    return enrichment


def diagnose_individual_fund_flow(quotes: pd.DataFrame) -> pd.DataFrame:
    base = quotes[required_columns(quotes, ["code", "名称"])].copy()
    enrichment = a_stock._apply_individual_fund_flow(base, cache_dir=CACHE_DIR)
    nonzero = enrichment[enrichment["资金流向分"] > 0].sort_values("资金流向分", ascending=False)
    print_coverage(enrichment, "资金流向分")
    print_frame(nonzero, ["code", "名称", "资金流向分"], rows=40)
    return enrichment


def diagnose_hot_rank(quotes: pd.DataFrame) -> pd.DataFrame:
    base = quotes[required_columns(quotes, ["code", "名称"])].copy()
    enrichment = a_stock._apply_hot_rank(base, cache_dir=CACHE_DIR)
    nonzero = enrichment[enrichment["新闻催化分"] > 0].sort_values("新闻催化分", ascending=False)
    print_coverage(enrichment, "新闻催化分")
    print_frame(nonzero, ["code", "名称", "新闻催化分"], rows=40)
    return enrichment


def required_columns(df: pd.DataFrame, columns: list[str]) -> list[str]:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise KeyError(f"缺少必要字段: {missing}; 当前字段: {list(df.columns)}")
    return columns


def print_coverage(df: pd.DataFrame, column: str) -> None:
    if column not in df.columns:
        print(f"{column}: 字段不存在")
        return
    values = pd.to_numeric(df[column], errors="coerce").fillna(0)
    print(f"{column}: 非零 {int((values > 0).sum())}/{len(df)}, max={values.max():.4f}, mean={values.mean():.4f}")


def print_summary(name: str, df: pd.DataFrame | None, value_column: str | None) -> None:
    if df is None:
        print(f"{name}: FAILED")
        return
    if value_column is None:
        print(f"{name}: rows={len(df)}")
        return
    if value_column not in df.columns:
        print(f"{name}: rows={len(df)}, {value_column}=MISSING")
        return
    values = pd.to_numeric(df[value_column], errors="coerce").fillna(0)
    print(f"{name}: rows={len(df)}, {value_column}非零={int((values > 0).sum())}, max={values.max():.4f}")


def print_frame(df: pd.DataFrame, columns: list[str], rows: int) -> None:
    if df is None or df.empty:
        print("(empty)")
        return
    available = [column for column in columns if column in df.columns]
    if not available:
        print("(no requested columns)")
        print("columns:", list(df.columns))
        return
    print(df[available].head(rows).to_string(index=False))


if __name__ == "__main__":
    main()
