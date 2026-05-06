from __future__ import annotations

import pandas as pd

import a_stock_shortlist_akshare_html as a_stock


def test_classify_morning_buy_level_rejects_overheated_gap() -> None:
    row = pd.Series(
        {
            "涨跌幅": 6.8,
            "成交额亿": 8.0,
            "换手率": 6.0,
            "早盘确认分": 20.0,
            "开盘强弱": "高开过热",
            "承接确认": "承接强",
            "早盘形态": "冲高过热",
        }
    )

    assert a_stock.classify_morning_buy_level(row) == "C_不追_高开过多"


def test_classify_morning_buy_level_prefers_tempered_strength_with_support() -> None:
    row = pd.Series(
        {
            "涨跌幅": 2.8,
            "成交额亿": 6.5,
            "换手率": 7.2,
            "早盘确认分": 18.0,
            "开盘强弱": "温和走强",
            "承接确认": "承接强",
            "早盘形态": "延续强势",
        }
    )

    assert a_stock.classify_morning_buy_level(row) == "A_早盘重点确认"


def test_classify_morning_buy_level_keeps_weak_to_strong_in_watch_pool() -> None:
    row = pd.Series(
        {
            "涨跌幅": 0.9,
            "成交额亿": 4.2,
            "换手率": 5.5,
            "早盘确认分": 11.5,
            "开盘强弱": "平开观察",
            "承接确认": "承接一般",
            "早盘形态": "弱转强观察",
        }
    )

    assert a_stock.classify_morning_buy_level(row) == "B_继续观察"

