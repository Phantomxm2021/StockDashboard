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
        "stock_board_concept_cons_em",
        "stock_sector_detail",
        "stock_classify_sina",
        "stock_individual_fund_flow_rank",
        "stock_individual_fund_flow",
        "stock_main_fund_flow",
        "stock_fund_flow_individual",
        "stock_hot_rank_em",
        "stock_hot_rank_latest_em",
        "stock_hot_rank_detail_realtime_em",
        "stock_hot_follow_xq",
        "stock_hot_tweet_xq",
        "stock_hot_deal_xq",
        "stock_hot_search_baidu",
        "stock_lhb_detail_daily_sina",
        "stock_lhb_detail_em",
        "stock_lhb_stock_statistic_em",
        "stock_lhb_ggtj_sina",
        "stock_lhb_jgzz_sina",
    ]:
        monkeypatch.setattr(a_stock.ak, provider_name, unavailable, raising=False)


def test_individual_fund_flow_falls_back_to_last_successful_cache(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_individual",
        lambda symbol="即时": pd.DataFrame(
            [
                {"股票代码": "000001", "净额": 100},
                {"股票代码": "000002", "净额": 50},
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
        "stock_fund_flow_individual",
        raise_connection_error,
        raising=False,
    )
    second = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert second.loc[second["code"] == "000001", "资金流向分"].iloc[0] == 16
    assert second.loc[second["code"] == "000002", "资金流向分"].iloc[0] == 8


def test_individual_fund_flow_leaves_zero_when_ths_provider_fails_without_cache(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    def raise_connection_error(symbol="即时") -> pd.DataFrame:
        raise ConnectionError("simulated ths failure")

    monkeypatch.setattr(a_stock.ak, "stock_fund_flow_individual", raise_connection_error, raising=False)

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment["资金流向分"].eq(0).all()


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


def test_hot_rank_uses_xueqiu_secondary_provider_when_primary_fails(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001"}, {"code": "000002"}])

    def raise_connection_error(symbol="最热门") -> pd.DataFrame:
        raise ConnectionError("simulated hot rank failure")

    monkeypatch.setattr(a_stock.ak, "stock_hot_follow_xq", raise_connection_error, raising=False)
    monkeypatch.setattr(
        a_stock.ak,
        "stock_hot_tweet_xq",
        lambda symbol="最热门": pd.DataFrame(
            [
                {"代码": "000001", "排名": 1},
                {"代码": "000002", "排名": 100},
            ]
        ),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "新闻催化分"].iloc[0] == 10
    assert enrichment.loc[enrichment["code"] == "000002", "新闻催化分"].iloc[0] == 0


def test_hot_rank_can_be_called_directly_without_existing_score_column(monkeypatch, tmp_path) -> None:
    base = pd.DataFrame([{"code": "000001", "名称": "热度股份"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_hot_follow_xq",
        lambda symbol="最热门": pd.DataFrame([{"代码": "000001", "排名": 1}]),
        raising=False,
    )

    enrichment = a_stock._apply_hot_rank(base, cache_dir=tmp_path)

    assert enrichment.loc[0, "新闻催化分"] == 10


def test_lhb_today_uses_sina_statistic_when_daily_detail_fails(monkeypatch) -> None:
    def fail_sina(date: str) -> pd.DataFrame:
        raise ConnectionError("sina lhb failed")

    monkeypatch.setattr(a_stock.ak, "stock_lhb_detail_daily_sina", fail_sina, raising=False)
    monkeypatch.setattr(
        a_stock.ak,
        "stock_lhb_ggtj_sina",
        lambda symbol="5": pd.DataFrame([{"股票代码": "000001", "名称": "龙虎股份"}]),
        raising=False,
    )

    lhb = a_stock.get_lhb_today()

    assert lhb["code"].tolist() == ["000001"]


def test_sector_strength_does_not_use_stock_name_keyword_as_constituent_fallback(monkeypatch, tmp_path) -> None:
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

    assert enrichment["主线板块"].fillna("").eq("").all()
    assert enrichment["板块强度分"].eq(0).all()


def test_sector_strength_limits_each_sector_to_top_100_constituents(monkeypatch, tmp_path) -> None:
    codes = [f"{index:06d}" for index in range(1, 151)]
    quote_df = pd.DataFrame([{"code": code} for code in codes])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "科技", "净流入": "20亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_spot",
        lambda indicator="新浪行业": pd.DataFrame([{"label": "gn_kj", "板块": "科技"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_detail",
        lambda sector: pd.DataFrame([{"symbol": code} for code in codes]),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert int((enrichment["板块强度分"] > 0).sum()) == 100
    assert enrichment.loc[enrichment["code"] == "000100", "板块强度分"].iloc[0] > 0
    assert enrichment.loc[enrichment["code"] == "000101", "板块强度分"].iloc[0] == 0


def test_sector_strength_uses_cache_when_fresh_mapping_is_too_sparse(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame(
        [
            {"code": "000001", "名称": "科技股份"},
            {"code": "000002", "名称": "缓存股份"},
        ]
    )
    cache_path = tmp_path / "sector_strength.csv"
    pd.DataFrame(
        [{"code": "000002", "主线板块": "缓存板块", "板块强度分": 22}]
    ).to_csv(cache_path, index=False)

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "科技", "净流入": "20亿"}]),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000002", "主线板块"].iloc[0] == "缓存板块"
    assert enrichment.loc[enrichment["code"] == "000002", "板块强度分"].iloc[0] == 22


def test_sector_strength_replaces_smaller_stale_cache_with_fresher_sparse_mapping(monkeypatch, tmp_path) -> None:
    codes = [f"{index:06d}" for index in range(1, 89)]
    quote_df = pd.DataFrame([{"code": code} for code in codes])
    cache_path = tmp_path / "sector_strength.csv"
    pd.DataFrame(
        [
            {"code": f"{index:06d}", "主线板块": "旧缓存", "板块强度分": 18}
            for index in range(1, 30)
        ]
    ).to_csv(cache_path, index=False)

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "新浪映射", "净流入": "20亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_spot",
        lambda indicator="新浪行业": pd.DataFrame([{"label": "gn_xx", "板块": "新浪映射"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_detail",
        lambda sector: pd.DataFrame([{"symbol": code} for code in codes]),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert int((enrichment["板块强度分"] > 0).sum()) == 88
    assert enrichment["主线板块"].eq("新浪映射").all()


def test_sector_strength_uses_sina_sector_detail_without_eastmoney(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001", "名称": "可靠股份"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "科技", "净流入": "20亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_spot",
        lambda indicator="新浪行业": pd.DataFrame(
            [{"label": "gn_kj", "板块": "科技", "涨跌幅": 5.0}]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_detail",
        lambda sector: pd.DataFrame([{"symbol": "sz000001", "name": "可靠股份"}]),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[0, "主线板块"] == "科技"
    assert enrichment.loc[0, "板块强度分"] == 25


def test_sector_strength_uses_classify_mapping_when_sector_detail_is_missing(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001", "名称": "软件龙头"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "软件开发", "净流入": "20亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_spot",
        lambda indicator="新浪行业": pd.DataFrame([{"label": "gn_soft", "板块": "软件开发"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_detail",
        lambda sector: pd.DataFrame(),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_classify_sina",
        lambda symbol="申万行业": pd.DataFrame(
            [{"symbol": "000001", "name": "软件龙头", "class": "软件开发"}]
        ),
        raising=False,
    )
    a_stock._SINA_CLASSIFY_CACHE.clear()

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[0, "主线板块"] == "软件开发"
    assert enrichment.loc[0, "板块强度分"] == 25


def test_sector_strength_prioritizes_concept_flow_before_industry(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame(
        [
            {"code": "000001", "名称": "半导体一号"},
            {"code": "000002", "名称": "算力芯片"},
            {"code": "000003", "名称": "电力龙头"},
        ]
    )

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_industry",
        lambda symbol="即时": pd.DataFrame([{"行业": "电力", "净额": "20亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_concept",
        lambda symbol="即时": pd.DataFrame(
            [
                {"行业": "半导体", "净额": "80亿"},
                {"行业": "国产算力芯片", "净额": "60亿"},
            ]
        ),
        raising=False,
    )

    def fake_constituents(sector_name: str, sector_label: str | None = None) -> pd.DataFrame | None:
        mapping = {
            "半导体": pd.DataFrame([{"代码": "000001"}]),
            "国产算力芯片": pd.DataFrame([{"代码": "000002"}]),
            "电力": pd.DataFrame([{"代码": "000003"}]),
        }
        return mapping.get(sector_name)

    monkeypatch.setattr(a_stock, "_fetch_sector_constituents", fake_constituents)

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[enrichment["code"] == "000001", "主线板块"].iloc[0] == "半导体"
    assert enrichment.loc[enrichment["code"] == "000002", "主线板块"].iloc[0] == "国产算力芯片"


def test_sector_strength_uses_eastmoney_concept_constituents_as_secondary_fallback(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001", "名称": "半导体一号"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_concept",
        lambda symbol="即时": pd.DataFrame([{"行业": "半导体", "净额": "80亿"}]),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_spot",
        lambda indicator="新浪行业": pd.DataFrame(),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_sector_detail",
        lambda sector: pd.DataFrame(),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_board_concept_cons_em",
        lambda symbol: pd.DataFrame([{"代码": "000001"}]) if symbol == "半导体" else pd.DataFrame(),
        raising=False,
    )

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[0, "主线板块"] == "半导体"
    assert enrichment.loc[0, "板块强度分"] == 25


def test_sector_strength_skips_generic_capital_flow_concepts(monkeypatch, tmp_path) -> None:
    quote_df = pd.DataFrame([{"code": "000001", "名称": "半导体一号"}])

    monkeypatch.setattr(
        a_stock.ak,
        "stock_fund_flow_concept",
        lambda symbol="即时": pd.DataFrame(
            [
                {"行业": "融资融券", "净额": "120亿"},
                {"行业": "半导体", "净额": "80亿"},
            ]
        ),
        raising=False,
    )
    monkeypatch.setattr(
        a_stock.ak,
        "stock_board_concept_cons_em",
        lambda symbol: pd.DataFrame([{"代码": "000001"}]) if symbol == "半导体" else pd.DataFrame(),
        raising=False,
    )
    monkeypatch.setattr(a_stock.ak, "stock_sector_detail", lambda sector: pd.DataFrame(), raising=False)

    enrichment = a_stock.build_mainline_enrichment(quote_df, cache_dir=tmp_path)

    assert enrichment.loc[0, "主线板块"] == "半导体"
