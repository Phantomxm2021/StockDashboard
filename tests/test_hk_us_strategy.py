import pandas as pd
import run_job
from datetime import datetime
from zoneinfo import ZoneInfo

from stock_dashboard.market_strategies import (
    build_hk_candidates_from_quotes,
    build_us_candidates_from_quotes,
    run_hk_report,
    run_us_report,
)
from stock_dashboard.reports import ReportQuery, build_report_payload


def test_hk_strategy_filters_low_liquidity_and_scores_candidates():
    quotes = pd.DataFrame(
        [
            {"code": "00700", "名称": "腾讯控股", "最新价": 380, "涨跌幅": 3.2, "成交额": 9_000_000_000},
            {"code": "09999", "名称": "薄弱股份", "最新价": 8.0, "涨跌幅": 9.0, "成交额": 1_000_000},
        ]
    )

    candidates = build_hk_candidates_from_quotes(quotes, report_type="after_close")

    assert list(candidates["代码"]) == ["00700"]
    assert candidates.iloc[0]["买入观察等级"].startswith("A_")
    assert candidates.iloc[0]["市场"] == "港股"


def test_us_strategy_filters_low_price_and_scores_candidates():
    quotes = pd.DataFrame(
        [
            {"code": "NVDA", "名称": "NVIDIA", "最新价": 150, "涨跌幅": 4.5, "成交额": 25_000_000_000},
            {"code": "PENNY", "名称": "Penny Corp", "最新价": 1.2, "涨跌幅": 20.0, "成交额": 500_000_000},
        ]
    )

    candidates = build_us_candidates_from_quotes(quotes, report_type="after_hours")

    assert list(candidates["代码"]) == ["NVDA"]
    assert candidates.iloc[0]["买入观察等级"].startswith("A_")
    assert candidates.iloc[0]["市场"] == "美股"


def test_hk_runner_falls_back_when_primary_akshare_source_fails(tmp_path):
    class FakeAk:
        def stock_hk_spot_em(self):
            raise RuntimeError("primary failed")

        def stock_hk_spot(self):
            return pd.DataFrame(
                [{"symbol": "00700", "name": "腾讯控股", "price": 380, "change_pct": 3.2, "amount": 9_000_000_000}]
            )

    csv_path, html_path = run_hk_report(
        "after_close",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 16, 20, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    assert csv_path.exists()
    assert html_path.exists()
    assert pd.read_csv(csv_path, dtype={"代码": str})["代码"].tolist() == ["00700"]


def test_us_runner_falls_back_when_primary_akshare_source_fails(tmp_path):
    class FakeAk:
        def stock_us_spot_em(self):
            raise RuntimeError("primary failed")

        def stock_us_spot(self):
            return pd.DataFrame(
                [{"symbol": "NVDA", "name": "NVIDIA", "price": 150, "change_pct": 4.5, "amount": 25_000_000_000}]
            )

    csv_path, html_path = run_us_report(
        "after_hours",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 4, 17, 15, tzinfo=ZoneInfo("America/New_York")),
    )

    assert csv_path.exists()
    assert html_path.exists()
    assert pd.read_csv(csv_path)["代码"].tolist() == ["NVDA"]


def test_pre_market_output_populates_core_pool(tmp_path):
    output_dir = tmp_path / "output"
    report_dir = tmp_path / "reports"

    class FakeAk:
        def stock_us_spot_em(self):
            return pd.DataFrame(
                [{"symbol": "NVDA", "name": "NVIDIA", "price": 150, "change_pct": 4.5, "amount": 25_000_000_000}]
            )

    csv_path, _ = run_us_report(
        "pre_market",
        output_dir,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    us_dir = report_dir / "us"
    us_dir.mkdir(parents=True)
    csv_path.replace(us_dir / "latest_pre_market.csv")

    payload = build_report_payload(
        report_dir,
        ReportQuery(market="us", report_type="pre_market", pool="core", page=1, page_size=50),
    )

    assert payload["pagination"]["total"] == 1
    assert payload["rows"][0]["早盘买入等级"] == "早盘重点确认"


def test_us_extended_report_uses_akshare_only(tmp_path):
    class FakeAk:
        def stock_us_spot_em(self):
            return pd.DataFrame(
                [
                    {"symbol": "NVDA", "name": "NVIDIA", "price": 151.0, "change_pct": 4.14, "amount": 30_200_000_000},
                    {"symbol": "MSFT", "name": "Microsoft", "price": 421.0, "change_pct": -2.09, "amount": 11_000_000_000},
                    {"symbol": "PENNY", "name": "Penny Corp", "price": 1.2, "change_pct": 20.0, "amount": 500_000_000},
                ]
            )

    csv_path, _ = run_us_report(
        "pre_market",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    rows = pd.read_csv(csv_path)
    assert rows["代码"].tolist() == ["NVDA"]
    assert rows.iloc[0]["涨跌幅"] == 4.14
    assert rows.iloc[0]["成交额亿"] == 302.0


def test_hk_fallback_maps_chinese_name_column(tmp_path):
    class FakeAk:
        def stock_hk_spot_em(self):
            raise RuntimeError("primary failed")

        def stock_hk_spot(self):
            return pd.DataFrame(
                [{"symbol": "00700", "中文名称": "腾讯控股", "price": 380, "change_pct": 3.2, "amount": 9_000_000_000}]
            )

    csv_path, _ = run_hk_report(
        "after_close",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 16, 20, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    assert pd.read_csv(csv_path, dtype={"代码": str})["名称"].tolist() == ["腾讯控股"]


def test_hk_pre_market_runner_allows_opening_auction_window(tmp_path):
    class FakeAk:
        def stock_hk_spot_em(self):
            return pd.DataFrame(
                [{"symbol": "00700", "name": "腾讯控股", "price": 380, "change_pct": 3.2, "amount": 9_000_000_000}]
            )

    csv_path, html_path = run_hk_report(
        "pre_market",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 9, 22, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    assert csv_path.exists()
    assert html_path.exists()
    rows = pd.read_csv(csv_path, dtype={"代码": str})
    assert rows["代码"].tolist() == ["00700"]
    assert "早盘买入等级" in rows.columns


def test_cn_run_report_uses_market_scoped_report_directory(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr(run_job, "REPORT_DIR", tmp_path / "reports")

    def fake_after_close(force=False, report_dir=run_job.REPORT_DIR):
        calls.append((force, report_dir))

    monkeypatch.setattr(run_job, "run_after_close", fake_after_close)

    run_job.run_report("cn", "after_close", force=True)

    assert calls == [(True, tmp_path / "reports" / "cn")]


def test_cn_morning_auto_bootstraps_after_close_when_candidates_missing(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports" / "cn"
    output_dir = tmp_path / "output"
    script_path = tmp_path / "a_stock_shortlist_akshare_html.py"
    script_path.write_text("# test script", encoding="utf-8")
    calls = []

    monkeypatch.setattr(run_job, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(run_job, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run_job, "SCRIPT_PATH", script_path)

    def fake_after_close(force=False, report_dir=run_job.REPORT_DIR):
        calls.append(("after_close", force, report_dir))
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "latest_candidates.csv").write_text("code,名称\n000001,测试\n", encoding="utf-8")

    def fake_run_subprocess(args):
        calls.append(("morning", args))
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "morning_confirm_20260506_094000.html").write_text("<html>ok</html>", encoding="utf-8")
        (output_dir / "morning_confirm_20260506_094000.csv").write_text(
            "code,代码,名称,早盘买入等级\n000001,000001,测试,A_早盘重点确认\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(run_job, "run_after_close", fake_after_close)
    monkeypatch.setattr(run_job, "run_subprocess", fake_run_subprocess)

    run_job.run_morning(force=True, report_dir=report_dir)

    assert calls[0] == ("after_close", True, report_dir)
    assert calls[1][0] == "morning"
    assert report_dir.joinpath("latest_morning.html").exists()
    assert report_dir.joinpath("latest_morning.csv").exists()


def test_us_manual_runner_allows_outside_extended_session(tmp_path):
    class FakeAk:
        def stock_us_spot_em(self):
            return pd.DataFrame(
                [{"symbol": "NVDA", "name": "NVIDIA", "price": 150, "change_pct": 4.5, "amount": 25_000_000_000}]
            )

    csv_path, _ = run_us_report(
        "pre_market",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 4, 17, 15, tzinfo=ZoneInfo("America/New_York")),
    )

    assert pd.read_csv(csv_path)["代码"].tolist() == ["NVDA"]


def test_hk_manual_runner_allows_outside_scheduled_window(tmp_path):
    class FakeAk:
        def stock_hk_spot_em(self):
            return pd.DataFrame(
                [{"symbol": "00700", "name": "腾讯控股", "price": 380, "change_pct": 3.2, "amount": 9_000_000_000}]
            )

    csv_path, _ = run_hk_report(
        "after_close",
        tmp_path,
        ak_module=FakeAk(),
        now=datetime(2026, 5, 5, 21, 30, tzinfo=ZoneInfo("Asia/Hong_Kong")),
    )

    assert pd.read_csv(csv_path, dtype={"代码": str})["代码"].tolist() == ["00700"]
