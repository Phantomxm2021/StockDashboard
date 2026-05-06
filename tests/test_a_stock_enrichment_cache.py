from __future__ import annotations

import pandas as pd
import pytest

import a_stock_shortlist_akshare_html as a_stock


@pytest.fixture(autouse=True)
def disable_external_enrichment_providers(monkeypatch) -> None:
    def unavailable(*args, **kwargs) -> pd.DataFrame:
        raise ConnectionError("disabled in test")

    for provider_name in [
        "stock_sector_fund_flow_rank",
        "stock_fund_flow_industry",
        "stock_fund_flow_concept",
        "stock_sector_spot",
        "stock_board_industry_cons_em",
        "stock_individual_fund_flow_rank",
        "stock_individual_fund_flow",
        "stock_main_fund_flow",
        "stock_fund_flow_individual",
        "stock_hot_rank_em",
        "stock_hot_rank_latest_em",
        "stock_hot_rank_detail_realtime_em",
    ]:
        monkeypatch.setattr(a_stock.ak, provider_name, unavailable, raising=False)


def test_individual_fund_flow_falls_back_to_last_successful_cache(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_individual_fund_flow_rank",
        lambda indicator="今日": pd.DataFrame(
            [
                {"代码": "000001", "主力净流入": 100},
                {"代码": "000002", "主力净流入": 50},
            ]
        ),
        raising=False,
    )
    first = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)
    assert first.loc[first["code"] == "000001", "资金流向分"].iloc[0] == 16

    def raise_connection_error(indicator="今日") -> pd.DataFrame:
        raise ConnectionError("simulated upstream failure")

    monkeypatch.setattr(
        a_stock.ak,
        "stock_individual_fund_flow_rank",
        raise_connection_error,
        raising=False,
    )
    second = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert second.loc[second["code"] == "000001", "资金流向分"].iloc[0] == 16
    assert second.loc[second["code"] == "000002", "资金流向分"].iloc[0] == 8


def test_individual_fund_flow_uses_secondary_provider_when_rank_fails(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    def raise_connection_error(indicator="今日") -> pd.DataFrame:
        raise ConnectionError("simulated rank failure")

    monkeypatch.setattr(a_stock.ak, "stock_individual_fund_flow_rank", raise_connection_error, raising=False)
    monkeypatch.setattr(
        a_stock.ak,
        "stock_main_fund_flow",
        lambda symbol="全部股票": pd.DataFrame(
            [
                {"股票代码": "000001", "净流入": 200},
                {"股票代码": "000002", "净流入": 100},
            ]
        ),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "资金流向分"].iloc[0] == 16
    assert enrichment.loc[enrichment["code"] == "000002", "资金流向分"].iloc[0] == 8


def test_individual_fund_flow_parses_chinese_money_units(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_individual",
        lambda symbol="即时": pd.DataFrame(
            [
                {"股票代码": "000001", "净额": "2亿"},
                {"股票代码": "000002", "净额": "5000万"},
            ]
        ),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "资金流向分"].iloc[0] == 16
    assert enrichment.loc[enrichment["code"] == "000002", "资金流向分"].iloc[0] == 4


def test_individual_fund_flow_can_be_called_directly_without_existing_score_column(monkeypatch, tmp_path) -> None:
    base = pd.DataFrame([{"code": "000001", "名称": "资金股份"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_individual",
        lambda symbol="即时": pd.DataFrame([{"股票代码": "000001", "净额": "1亿"}]),
        raising=False,
    )

    enrichment = a_stock._apply_individual_fund_flow(base, cache_dir=tmp_path)

    assert enrichment.loc[0, "资金流向分"] == 16


def test_hot_rank_uses_latest_provider_when_primary_fails(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    def raise_connection_error() -> pd.DataFrame:
        raise ConnectionError("simulated hot rank failure")

    monkeypatch.setattr(a_stock.ak, "stock_hot_rank_em", raise_connection_error, raising=False)
    monkeypatch.setattr(
        a_stock.ak,
        "stock_hot_rank_latest_em",
        lambda: pd.DataFrame(
            [
                {"代码": "000001", "当前排名": 1},
                {"代码": "000002", "当前排名": 100},
            ]
        ),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "新闻催化分"].iloc[0] == 10
    assert enrichment.loc[enrichment["code"] == "000002", "新闻催化分"].iloc[0] == 0


def test_sector_strength_uses_industry_fund_flow_fallback_without_constituents(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame(
        [
            {"code": "000001", "名称": "强势科技"},
            {"code": "000002", "名称": "普通制造"},
        ]
    )

    def raise_connection_error(indicator="今日", sector_type="行业资金流") -> pd.DataFrame:
        raise ConnectionError("simulated sector rank failure")

    monkeypatch.setattr(a_stock.ak, "stock_sector_fund_flow_rank", raise_connection_error, raising=False)
    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame(
            [
                {"行业": "科技", "涨跌幅": 6.0, "净流入": 300},
                {"行业": "制造", "涨跌幅": 1.0, "净流入": 50},
            ]
        ),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "主线板块"].iloc[0] == "科技"
    assert enrichment.loc[enrichment["code"] == "000001", "板块强度分"].iloc[0] > 0


def test_sector_strength_limits_each_sector_to_top_100_constituents(monkeypatch, tmp_path) -> None:
    codes = [f"{index:06d}" for index in range(1, 151)]
    quote_df = pd.DataFrame([{"code": code} for code in codes])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_fund_flow_rank",
        lambda indicator="今日", sector_type="行业资金流": pd.DataFrame(
            [{"行业": "科技", "净额": "20亿"}]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_board_industry_cons_em",
        lambda symbol: pd.DataFrame([{"代码": code} for code in codes]),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert int((enrichment["板块强度分"] > 0).sum()) == 100
    assert enrichment.loc[enrichment["code"] == "000100", "板块强度分"].iloc[0] > 0
    assert enrichment.loc[enrichment["code"] == "000101", "板块强度分"].iloc[0] == 0
