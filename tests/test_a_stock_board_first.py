from __future__ import annotations

import pandas as pd

import a_stock_shortlist_akshare_html as a_stock


def test_restrict_quotes_to_mainline_universe_keeps_only_board_mapped_codes() -> None:
    quote_df = pd.DataFrame(
        [
            {"code": "000001", "名称": "主线一"},
            {"code": "000002", "名称": "非主线"},
            {"code": "000003", "名称": "主线二"},
        ]
    )
    enrichment_df = pd.DataFrame(
        [
            {"code": "000001", "主线板块": "电池", "板块强度分": 25},
            {"code": "000002", "主线板块": "", "板块强度分": 0},
            {"code": "000003", "主线板块": "电力", "板块强度分": 17.5},
        ]
    )

    filtered = a_stock.restrict_quotes_to_mainline_universe(quote_df, enrichment_df)

    assert filtered["code"].tolist() == ["000001", "000003"]


def test_restrict_quotes_to_mainline_universe_returns_empty_when_no_strong_board_match() -> None:
    quote_df = pd.DataFrame(
        [
            {"code": "000001", "名称": "主线一"},
            {"code": "000002", "名称": "非主线"},
        ]
    )
    enrichment_df = pd.DataFrame(
        [
            {"code": "000001", "主线板块": "", "板块强度分": 0},
            {"code": "000002", "主线板块": "", "板块强度分": 0},
        ]
    )

    filtered = a_stock.restrict_quotes_to_mainline_universe(quote_df, enrichment_df)

    assert filtered.empty
