from stock_dashboard.markets import (
    get_default_report_type,
    get_market_definition,
    list_market_payloads,
    validate_market_report,
)


def test_market_payloads_expose_dropdown_and_role_aware_menus():
    payloads = list_market_payloads()

    assert [item["id"] for item in payloads] == ["cn", "hk", "us"]
    assert [item["name"] for item in payloads] == ["A股市场", "港股市场", "美股市场"]
    assert [item["default_report_type"] for item in payloads] == [
        "after_close",
        "after_close",
        "after_hours",
    ]
    assert [item["title"] for item in payloads[0]["reports"]] == ["收盘观察", "早盘确认"]
    assert [item["title"] for item in payloads[1]["reports"]] == ["收盘观察", "盘前观察"]
    assert [item["title"] for item in payloads[2]["reports"]] == ["盘后观察", "盘前观察"]


def test_market_report_validation_rejects_invalid_combinations():
    assert validate_market_report("us", "pre_market").id == "us"
    assert get_default_report_type("hk") == "after_close"
    assert get_default_report_type("us") == "after_hours"

    try:
        validate_market_report("us", "morning")
    except ValueError as exc:
        assert "invalid report type" in str(exc)
    else:
        raise AssertionError("expected invalid report type")

    try:
        get_market_definition("crypto")
    except ValueError as exc:
        assert "unknown market" in str(exc)
    else:
        raise AssertionError("expected unknown market")
