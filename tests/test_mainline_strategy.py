from __future__ import annotations

import pandas as pd

from stock_dashboard.strategy import MainlineStrategyConfig, MarketContext, build_mainline_candidates


def test_mainline_strategy_prefers_sector_fund_and_catalyst_over_lhb_only() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000001",
                "代码": "000001",
                "名称": "主线股份",
                "最新价": 12.3,
                "涨跌幅": 4.8,
                "成交额": 850_000_000,
                "换手率": 9.0,
                "有换手率数据": True,
                "数据源": "test",
            },
            {
                "code": "000002",
                "代码": "000002",
                "名称": "孤立龙虎",
                "最新价": 9.8,
                "涨跌幅": 5.1,
                "成交额": 900_000_000,
                "换手率": 10.0,
                "有换手率数据": True,
                "数据源": "test",
            },
        ]
    )
    amount_rank_df = quote_df[["code"]].copy()
    gain_rank_df = quote_df[["code"]].copy()
    lhb_df = pd.DataFrame([{"code": "000002"}])
    enrichment_df = pd.DataFrame(
        [
            {
                "code": "000001",
                "主线板块": "机器人",
                "板块强度分": 23,
                "资金流向分": 18,
                "新闻催化分": 8,
            },
            {
                "code": "000002",
                "主线板块": "",
                "板块强度分": 0,
                "资金流向分": 4,
                "新闻催化分": 0,
            },
        ]
    )

    candidates_df, excluded_df = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=amount_rank_df,
        gain_rank_df=gain_rank_df,
        lhb_df=lhb_df,
        enrichment_df=enrichment_df,
    )

    assert excluded_df.empty
    assert candidates_df.iloc[0]["代码"] == "000001"
    assert candidates_df.iloc[0]["买入观察等级"] == "A_核心关注"
    assert candidates_df.iloc[0]["主线板块"] == "机器人"
    assert candidates_df.iloc[0]["主线强势分"] > candidates_df.iloc[1]["主线强势分"]
    assert "龙虎榜信号" not in candidates_df.columns
    assert "成交额榜信号" not in candidates_df.columns
    assert "涨幅榜信号" not in candidates_df.columns
    assert "风险扣分" not in candidates_df.columns
    assert "候选类型" not in candidates_df.columns


def test_mainline_strategy_penalizes_high_position_risk() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000003",
                "代码": "000003",
                "名称": "高位股份",
                "最新价": 18.5,
                "涨跌幅": 9.4,
                "成交额": 1_200_000_000,
                "换手率": 28.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "000003", "板块强度分": 25, "资金流向分": 20, "新闻催化分": 10}]
        ),
    )

    assert candidates_df.iloc[0]["位置风险分"] < 10
    assert candidates_df.iloc[0]["买入观察等级"] == "C_暂缓跟踪"


def test_mainline_strategy_allows_sector_catalyst_core_when_fund_is_moderate() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000004",
                "代码": "000004",
                "名称": "催化股份",
                "最新价": 15.2,
                "涨跌幅": 5.2,
                "成交额": 1_600_000_000,
                "换手率": 8.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "000004", "板块强度分": 18, "资金流向分": 5, "新闻催化分": 8}]
        ),
    )

    assert candidates_df.iloc[0]["买入观察等级"] == "A_核心关注"


def test_mainline_strategy_allows_fund_strength_with_strong_individual_signal() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000005",
                "代码": "000005",
                "名称": "资金股份",
                "最新价": 22.1,
                "涨跌幅": 5.8,
                "成交额": 2_400_000_000,
                "换手率": 12.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "000005", "板块强度分": 0, "资金流向分": 8.0, "新闻催化分": 0}]
        ),
    )

    assert candidates_df.iloc[0]["个股强度分"] >= 18
    assert candidates_df.iloc[0]["买入观察等级"] == "A_核心关注"


def test_mainline_strategy_does_not_allow_weak_fund_path_into_core() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000006",
                "代码": "000006",
                "名称": "弱资股份",
                "最新价": 16.0,
                "涨跌幅": 5.8,
                "成交额": 2_400_000_000,
                "换手率": 12.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "000006", "板块强度分": 0, "资金流向分": 5.5, "新闻催化分": 0}]
        ),
    )

    assert candidates_df.iloc[0]["个股强度分"] >= 18
    assert candidates_df.iloc[0]["买入观察等级"] != "A_核心关注"


def test_mainline_strategy_degrades_to_watch_when_enrichment_sources_fail() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "000007",
                "代码": "000007",
                "名称": "强势缺增强",
                "最新价": 18.0,
                "涨跌幅": 6.2,
                "成交额": 3_000_000_000,
                "换手率": 12.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "000007", "板块强度分": 0, "资金流向分": 0, "新闻催化分": 0}]
        ),
    )

    assert candidates_df.iloc[0]["个股强度分"] >= 18
    assert candidates_df.iloc[0]["主线强势分"] >= 40
    assert candidates_df.iloc[0]["买入观察等级"] == "B_继续观察"


def test_mainline_strategy_excludes_star_market_when_market_is_shrinking() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "688001",
                "代码": "688001",
                "名称": "科创股份",
                "最新价": 30.0,
                "涨跌幅": 4.5,
                "成交额": 1_500_000_000,
                "换手率": 8.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, excluded_df = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "688001", "板块强度分": 20, "资金流向分": 9, "新闻催化分": 8}]
        ),
        market_context=MarketContext(state="shrinking", amount_yi=7600),
    )

    assert candidates_df.empty
    assert "缩量不做科创板" in excluded_df.iloc[0]["排除原因"]


def test_mainline_strategy_boosts_chinext_when_market_is_expanding() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "300001",
                "代码": "300001",
                "名称": "创业股份",
                "最新价": 20.0,
                "涨跌幅": 4.0,
                "成交额": 900_000_000,
                "换手率": 8.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "300001", "板块强度分": 12, "资金流向分": 6, "新闻催化分": 0}]
        ),
        market_context=MarketContext(state="expanding", amount_yi=11000),
    )

    assert candidates_df.iloc[0]["市场环境"] == "放量"
    assert candidates_df.iloc[0]["个股强度分"] >= 22
    assert candidates_df.iloc[0]["买入观察等级"] == "A_核心关注"


def test_star_market_requires_fund_confirmation_when_market_is_expanding() -> None:
    quote_df = pd.DataFrame(
        [
            {
                "code": "688002",
                "代码": "688002",
                "名称": "弹性科创",
                "最新价": 26.0,
                "涨跌幅": 5.0,
                "成交额": 1_200_000_000,
                "换手率": 9.0,
                "有换手率数据": True,
                "数据源": "test",
            }
        ]
    )

    candidates_df, _ = build_mainline_candidates(
        config=MainlineStrategyConfig(),
        quote_df=quote_df,
        amount_rank_df=quote_df[["code"]],
        gain_rank_df=quote_df[["code"]],
        lhb_df=pd.DataFrame(),
        enrichment_df=pd.DataFrame(
            [{"code": "688002", "板块强度分": 18, "资金流向分": 5, "新闻催化分": 8}]
        ),
        market_context=MarketContext(state="expanding", amount_yi=11000),
    )

    assert candidates_df.iloc[0]["买入观察等级"] != "A_核心关注"
