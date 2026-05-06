from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from dashboard_server import create_app


def make_client(tmp_path: Path) -> TestClient:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    return TestClient(
        create_app(
            report_dir=report_dir,
            output_dir=tmp_path / "output",
            data_dir=tmp_path / "data",
        )
    )


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "root", "password": "admin@root"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_after_close_report_returns_polished_pool_names_and_paginated_rows(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    rows = [
        {
            "code": "000001",
            "代码": "000001",
            "名称": "示例一",
            "换手率": 4.2,
            "有换手率数据": True,
            "龙虎榜信号": 1,
            "风险扣分": 0,
            "排除原因": "",
            "数据源": "sina",
            "买入观察等级": "A_重点盯盘",
            "涨跌幅": 3.2,
            "短线观察分": 68,
        },
        {
            "code": "000002",
            "代码": "000002",
            "名称": "示例二",
            "买入观察等级": "B_继续观察",
            "涨跌幅": 2.1,
            "短线观察分": 51,
        },
        {
            "code": "000003",
            "代码": "000003",
            "名称": "示例三",
            "买入观察等级": "C_暂不考虑",
            "涨跌幅": 8.4,
            "短线观察分": 20,
        },
    ]
    pd.DataFrame(rows).to_csv(report_dir / "latest_candidates.csv", index=False)
    client = make_client(tmp_path)

    response = client.get(
        "/api/reports/after-close?pool=core&page=1&page_size=1",
        headers=auth_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["pools"] == [
        {"key": "core", "title": "核心关注", "count": 1},
        {"key": "watch", "title": "继续观察", "count": 1},
        {"key": "defer", "title": "暂缓跟踪", "count": 1},
        {"key": "all", "title": "全部候选", "count": 3},
    ]
    assert response.json()["active_pool"] == "core"
    assert response.json()["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total": 1,
        "total_pages": 1,
    }
    assert response.json()["rows"][0]["名称"] == "示例一"
    assert response.json()["rows"][0]["买入观察等级"] == "重点盯盘"
    assert "code" not in response.json()["columns"]
    assert "换手率" not in response.json()["columns"]
    assert "有换手率数据" not in response.json()["columns"]
    assert "龙虎榜信号" not in response.json()["columns"]
    assert "风险扣分" not in response.json()["columns"]
    assert "排除原因" not in response.json()["columns"]
    assert "数据源" not in response.json()["columns"]


def test_missing_after_close_report_returns_empty_payload(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get(
        "/api/reports/after-close",
        headers=auth_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["pools"][0] == {
        "key": "core",
        "title": "核心关注",
        "count": 0,
    }
    assert response.json()["rows"] == []


def test_after_close_report_accepts_level_values_without_prefix(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    rows = [
        {"code": "000001", "代码": "000001", "名称": "示例一", "买入观察等级": "核心关注"},
        {"code": "000002", "代码": "000002", "名称": "示例二", "买入观察等级": "继续观察"},
        {"code": "000003", "代码": "000003", "名称": "示例三", "买入观察等级": "暂缓跟踪"},
    ]
    pd.DataFrame(rows).to_csv(report_dir / "latest_candidates.csv", index=False)
    client = make_client(tmp_path)

    response = client.get(
        "/api/reports/after-close?pool=core",
        headers=auth_headers(client),
    )

    assert response.status_code == 200
    assert response.json()["pools"] == [
        {"key": "core", "title": "核心关注", "count": 1},
        {"key": "watch", "title": "继续观察", "count": 1},
        {"key": "defer", "title": "暂缓跟踪", "count": 1},
        {"key": "all", "title": "全部候选", "count": 3},
    ]
    assert response.json()["rows"][0]["名称"] == "示例一"


def test_status_is_root_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/status", headers=auth_headers(client))

    assert response.status_code == 200
    assert response.json()["status"] == "empty"
