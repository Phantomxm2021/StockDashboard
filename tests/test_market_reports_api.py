from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from dashboard_server import create_app

from stock_dashboard.reports import ReportQuery, build_report_payload, read_status


def _login(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_market_scoped_report_payload_reads_hk_report(tmp_path: Path):
    report_dir = tmp_path / "reports"
    hk_dir = report_dir / "hk"
    hk_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "code": "00700",
                "代码": "00700",
                "名称": "腾讯控股",
                "买入观察等级": "A_核心关注",
                "主线强势分": 72,
                "次日动作建议": "观察承接",
            },
            {
                "code": "00941",
                "代码": "00941",
                "名称": "中国移动",
                "买入观察等级": "B_继续观察",
                "主线强势分": 61,
                "次日动作建议": "等待确认",
            },
        ]
    ).to_csv(hk_dir / "latest_after_close.csv", index=False)

    payload = build_report_payload(
        report_dir,
        ReportQuery(market="hk", report_type="after_close", pool="core", page=1, page_size=50),
    )

    assert payload["market"] == "hk"
    assert payload["report_type"] == "after_close"
    assert payload["pools"][0]["title"] == "核心关注"
    assert payload["pagination"]["total"] == 1
    assert payload["rows"][0]["买入观察等级"] == "核心关注"


def test_cn_report_falls_back_to_legacy_root_file(tmp_path: Path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    pd.DataFrame(
        [{"code": "600000", "代码": "600000", "名称": "浦发银行", "买入观察等级": "A_核心关注"}]
    ).to_csv(report_dir / "latest_candidates.csv", index=False)

    payload = build_report_payload(
        report_dir,
        ReportQuery(market="cn", report_type="after_close", pool="core", page=1, page_size=50),
    )

    assert payload["pagination"]["total"] == 1
    assert payload["rows"][0]["名称"] == "浦发银行"


def test_market_status_is_scoped(tmp_path: Path):
    status_dir = tmp_path / "reports" / "us"
    status_dir.mkdir(parents=True)
    (status_dir / "status.json").write_text('{"status":"ok","market":"us"}', encoding="utf-8")

    assert read_status(tmp_path / "reports", "us")["market"] == "us"


def test_empty_filtered_pool_still_hides_internal_columns(tmp_path: Path):
    report_dir = tmp_path / "reports"
    hk_dir = report_dir / "hk"
    hk_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "code": "00941",
                "代码": "00941",
                "名称": "中国移动",
                "买入观察等级": "B_继续观察",
                "换手率": 1.2,
                "数据源": "akshare",
            },
        ]
    ).to_csv(hk_dir / "latest_after_close.csv", index=False)

    payload = build_report_payload(
        report_dir,
        ReportQuery(market="hk", report_type="after_close", pool="core", page=1, page_size=50),
    )

    assert payload["pagination"]["total"] == 0
    assert "code" not in payload["columns"]
    assert "换手率" not in payload["columns"]
    assert "数据源" not in payload["columns"]


def test_markets_api_returns_market_menu(tmp_path: Path):
    app = create_app(
        report_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        frontend_dist_dir=tmp_path / "dist",
    )
    client = TestClient(app)
    token = _login(client)

    response = client.get("/api/markets", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[1]["id"] == "hk"
    assert response.json()[2]["reports"][0]["title"] == "盘后观察"


def test_market_report_api_rejects_invalid_combination(tmp_path: Path):
    app = create_app(
        report_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        frontend_dist_dir=tmp_path / "dist",
    )
    client = TestClient(app)
    token = _login(client)

    response = client.get("/api/reports/us/morning", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400
    assert "invalid report type" in response.json()["detail"]


def test_unknown_api_path_returns_json_404(tmp_path: Path):
    app = create_app(
        report_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        frontend_dist_dir=tmp_path / "dist",
    )
    client = TestClient(app)

    response = client.get("/api/not-a-real-route")

    assert response.status_code == 404
    assert response.json()["detail"] == "API route not found"


def test_market_report_api_accepts_hyphenated_report_type(tmp_path: Path):
    report_dir = tmp_path / "reports"
    hk_dir = report_dir / "hk"
    hk_dir.mkdir(parents=True)
    pd.DataFrame(
        [{"code": "00700", "代码": "00700", "名称": "腾讯控股", "买入观察等级": "A_核心关注"}]
    ).to_csv(hk_dir / "latest_after_close.csv", index=False)
    app = create_app(
        report_dir=report_dir,
        data_dir=tmp_path / "data",
        output_dir=tmp_path / "output",
        frontend_dist_dir=tmp_path / "dist",
    )
    client = TestClient(app)
    token = _login(client)

    response = client.get("/api/reports/hk/after-close", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["report_type"] == "after_close"
