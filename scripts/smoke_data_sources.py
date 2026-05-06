from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import a_stock_shortlist_akshare_html as a_stock


def main() -> None:
    print("== A股数据源 smoke test ==")

    print("\n[1/3] 实时行情 + 成交额榜")
    try:
        quotes = a_stock.get_realtime_quotes()
        amount_rank = a_stock.get_amount_rank_from_quotes(quotes, top_n=20)
        print_frame(
            amount_rank,
            ["代码", "名称", "最新价", "涨跌幅", "成交额", "数据源"],
            rows=20,
        )
    except Exception as exc:
        print("实时行情获取失败，改用最近一次落盘数据继续测试增强源。")
        print("ERROR:", repr(exc))
        quotes = load_latest_quotes()

    print("\n[2/4] 板块资金源")
    fetched = a_stock._fetch_sector_fund_flow()
    if fetched is None:
        print("板块资金源: 全部 provider 失败")
    else:
        provider_name, sector_df, name_col, flow_col, change_col = fetched
        print(f"板块资金 provider: {provider_name}")
        print(f"字段识别: name_col={name_col!r}, flow_col={flow_col!r}, change_col={change_col!r}")
        ranked_sector = a_stock._rank_sector_fund_flow(sector_df, flow_col=flow_col, change_col=change_col)
        display_cols = [col for col in [name_col, flow_col, change_col, "板块资金净流入", "板块涨跌幅"] if col in ranked_sector.columns]
        print_frame(ranked_sector, display_cols, rows=20)

    print("\n[3/4] 板块强度")
    sector_enrichment = a_stock._apply_sector_strength(
        quotes[["code", "名称"]].copy(),
        cache_dir=ROOT_DIR / "reports" / "cn" / "enrichment_cache",
    )
    sector_rows = (
        sector_enrichment[sector_enrichment["板块强度分"] > 0]
        .sort_values(["板块强度分", "code"], ascending=[False, True])
        .head(30)
    )
    print_frame(sector_rows, ["code", "名称", "主线板块", "板块强度分"], rows=30)
    print("板块强度非零数量:", int((sector_enrichment["板块强度分"] > 0).sum()))

    print("\n[4/4] 个股资金流")
    fund_enrichment = a_stock._apply_individual_fund_flow(
        quotes[["code", "名称"]].copy(),
        cache_dir=ROOT_DIR / "reports" / "cn" / "enrichment_cache",
    )
    fund_rows = (
        fund_enrichment[fund_enrichment["资金流向分"] > 0]
        .sort_values("资金流向分", ascending=False)
        .head(30)
    )
    print_frame(fund_rows, ["code", "名称", "资金流向分"], rows=30)
    print("资金流向非零数量:", int((fund_enrichment["资金流向分"] > 0).sum()))


def load_latest_quotes() -> pd.DataFrame:
    path = ROOT_DIR / "reports" / "cn" / "latest_after_close.csv"
    if not path.exists():
        raise FileNotFoundError(f"没有可用落盘数据：{path}")
    df = pd.read_csv(path, dtype={"code": str, "代码": str})
    if "code" not in df.columns and "代码" in df.columns:
        df["code"] = df["代码"].apply(a_stock.normalize_code)
    if "名称" not in df.columns:
        df["名称"] = ""
    print(f"使用落盘数据：{path} rows={len(df)}")
    return df


def print_frame(df: pd.DataFrame, columns: list[str], rows: int) -> None:
    available = [column for column in columns if column in df.columns]
    if df.empty or not available:
        print("(empty)")
        return
    print(df[available].head(rows).to_string(index=False))


if __name__ == "__main__":
    main()
