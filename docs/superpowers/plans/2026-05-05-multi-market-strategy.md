# Multi-Market Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real A-share, Hong Kong, and US market workflows with a sidebar market dropdown, market-specific menus, market-scoped reports, jobs, and strategy runners.

**Architecture:** Add market definitions as the shared contract between backend and frontend. Refactor report reading and job launching around `market + report_type`, then add isolated Hong Kong and US runners that normalize AKShare data into the existing report payload shape. Keep A-share behavior compatible while moving storage into `reports/cn`.

**Tech Stack:** FastAPI, Pydantic, pandas, AKShare, SQLite auth store, React + TypeScript + Vite, pytest.

---

## File Structure

- Create `stock_dashboard/markets.py`: market ids, report types, menu definitions, validation helpers, report filenames.
- Create `stock_dashboard/market_strategies.py`: shared scoring helpers plus HK/US runner implementations.
- Modify `stock_dashboard/reports.py`: read reports by market/report type and preserve A-share fallback.
- Modify `stock_dashboard/jobs.py`: accept market/report type and pass both to `run_job.py`.
- Modify `run_job.py`: parse `--market` and `--report-type`, route A-share to existing script and HK/US to new runners.
- Modify `dashboard_server.py`: expose `/api/markets`, market-aware reports/status, and market-aware jobs.
- Modify `stock_dashboard/scheduler.py`: schedule jobs by market/report type.
- Modify `frontend/src/api.ts`: add market types and market-aware API calls.
- Modify `frontend/src/Dashboard.tsx`: market dropdown and dynamic menu.
- Modify `frontend/src/ReportView.tsx`: fetch by market/report type.
- Modify `frontend/src/AdminViews.tsx`: run jobs with market/report type and show scoped status.
- Modify `frontend/src/styles.css`: sidebar select styling.
- Add tests in `tests/test_markets.py`, `tests/test_market_reports_api.py`, `tests/test_market_jobs.py`, and `tests/test_hk_us_strategy.py`.
- Update `README.md` with multi-market deployment and scheduling notes.

## Task 1: Market Definitions

**Files:**
- Create: `stock_dashboard/markets.py`
- Test: `tests/test_markets.py`

- [ ] **Step 1: Write the failing tests**

```python
from stock_dashboard.markets import (
    get_default_report_type,
    get_market_definition,
    list_market_payloads,
    validate_market_report,
)


def test_market_payloads_expose_dropdown_and_role_aware_menus():
    payloads = list_market_payloads()

    assert [item["id"] for item in payloads] == ["cn", "hk", "us"]
    assert payloads[0]["name"] == "A股市场"
    assert payloads[0]["default_report_type"] == "after_close"
    assert [item["title"] for item in payloads[0]["reports"]] == ["收盘观察", "早盘确认"]
    assert [item["title"] for item in payloads[1]["reports"]] == ["收盘观察", "盘前观察"]
    assert [item["title"] for item in payloads[2]["reports"]] == ["盘后观察", "盘前观察"]


def test_market_report_validation_rejects_invalid_combinations():
    assert validate_market_report("us", "pre_market").id == "us"
    assert get_default_report_type("hk") == "after_close"

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_markets.py -q
```

Expected: FAIL because `stock_dashboard.markets` does not exist.

- [ ] **Step 3: Implement market definitions**

Create `stock_dashboard/markets.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportTypeDefinition:
    id: str
    title: str
    latest_csv: str
    latest_html: str | None
    output_prefix: str

    def to_payload(self) -> dict[str, str]:
        return {"id": self.id, "title": self.title}


@dataclass(frozen=True)
class MarketDefinition:
    id: str
    name: str
    short_name: str
    default_report_type: str
    reports: tuple[ReportTypeDefinition, ...]

    def report(self, report_type: str) -> ReportTypeDefinition:
        for item in self.reports:
            if item.id == report_type:
                return item
        raise ValueError(f"invalid report type for {self.id}: {report_type}")

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "short_name": self.short_name,
            "default_report_type": self.default_report_type,
            "reports": [report.to_payload() for report in self.reports],
        }


MARKETS: tuple[MarketDefinition, ...] = (
    MarketDefinition(
        id="cn",
        name="A股市场",
        short_name="A股",
        default_report_type="after_close",
        reports=(
            ReportTypeDefinition("after_close", "收盘观察", "latest_after_close.csv", "latest_after_close.html", "candidates"),
            ReportTypeDefinition("morning", "早盘确认", "latest_morning.csv", "latest_morning.html", "morning_confirm"),
        ),
    ),
    MarketDefinition(
        id="hk",
        name="港股市场",
        short_name="港股",
        default_report_type="after_close",
        reports=(
            ReportTypeDefinition("after_close", "收盘观察", "latest_after_close.csv", "latest_after_close.html", "hk_after_close"),
            ReportTypeDefinition("pre_market", "盘前观察", "latest_pre_market.csv", "latest_pre_market.html", "hk_pre_market"),
        ),
    ),
    MarketDefinition(
        id="us",
        name="美股市场",
        short_name="美股",
        default_report_type="after_hours",
        reports=(
            ReportTypeDefinition("after_hours", "盘后观察", "latest_after_hours.csv", "latest_after_hours.html", "us_after_hours"),
            ReportTypeDefinition("pre_market", "盘前观察", "latest_pre_market.csv", "latest_pre_market.html", "us_pre_market"),
        ),
    ),
)


def list_market_payloads() -> list[dict[str, object]]:
    return [market.to_payload() for market in MARKETS]


def get_market_definition(market_id: str) -> MarketDefinition:
    for market in MARKETS:
        if market.id == market_id:
            return market
    raise ValueError(f"unknown market: {market_id}")


def validate_market_report(market_id: str, report_type: str) -> MarketDefinition:
    market = get_market_definition(market_id)
    market.report(report_type)
    return market


def get_default_report_type(market_id: str) -> str:
    return get_market_definition(market_id).default_report_type
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_markets.py -q
```

Expected: PASS.

## Task 2: Market-Scoped Report Repository

**Files:**
- Modify: `stock_dashboard/reports.py`
- Test: `tests/test_market_reports_api.py`

- [ ] **Step 1: Write failing report repository tests**

```python
from pathlib import Path

import pandas as pd

from stock_dashboard.reports import ReportQuery, build_report_payload, read_status


def test_market_scoped_report_payload_reads_hk_report(tmp_path: Path):
    report_dir = tmp_path / "reports"
    hk_dir = report_dir / "hk"
    hk_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"code": "00700", "代码": "00700", "名称": "腾讯控股", "买入观察等级": "A_核心关注", "主线强势分": 72, "次日动作建议": "观察承接"},
            {"code": "00941", "代码": "00941", "名称": "中国移动", "买入观察等级": "B_继续观察", "主线强势分": 61, "次日动作建议": "等待确认"},
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_reports_api.py -q
```

Expected: FAIL because `ReportQuery` lacks `market` and `read_status` lacks a market argument.

- [ ] **Step 3: Implement report repository changes**

Modify `stock_dashboard/reports.py`:

```python
@dataclass(frozen=True)
class ReportQuery:
    market: str = "cn"
    report_type: str = "after_close"
    pool: str = "core"
    page: int = 1
    page_size: int = 50
```

Add imports:

```python
from stock_dashboard.markets import get_market_definition
```

Replace `read_status` with:

```python
def read_status(report_dir: Path, market: str = "cn") -> dict[str, Any]:
    market_dir = report_dir / market
    path = market_dir / "status.json"
    legacy_path = report_dir / "status.json"
    if not path.exists() and market == "cn":
        path = legacy_path
    if not path.exists():
        return {"status": "empty", "market": market, "message": "还没有运行过定时任务"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("market", market)
        return data
    except Exception as exc:
        return {"status": "error", "market": market, "message": f"status.json 读取失败：{exc}"}
```

Replace report file selection in `build_report_payload` with:

```python
    market = get_market_definition(query.market)
    report_def = market.report(query.report_type)
    market_csv_path = report_dir / market.id / report_def.latest_csv
    csv_path = _legacy_cn_csv_path(report_dir, query.report_type) if market.id == "cn" and not market_csv_path.exists() else market_csv_path
    pool_defs = MORNING_POOLS if query.report_type in {"morning", "pre_market"} else AFTER_CLOSE_POOLS
```

Add payload fields:

```python
        "market": market.id,
        "market_name": market.name,
```

Add helper:

```python
def _legacy_cn_csv_path(report_dir: Path, report_type: str) -> Path:
    if report_type == "morning":
        return report_dir / "latest_morning.csv"
    return report_dir / "latest_candidates.csv"
```

- [ ] **Step 4: Update legacy call sites**

In `dashboard_server.py`, update existing `ReportQuery(...)` construction to pass `market="cn"`. In existing `read_status(config.report_dir)` calls, pass `"cn"`.

- [ ] **Step 5: Run report tests and existing tests**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_reports_api.py tests/test_reports_api.py -q
```

Expected: PASS.

## Task 3: Market-Aware API

**Files:**
- Modify: `dashboard_server.py`
- Test: `tests/test_market_reports_api.py`

- [ ] **Step 1: Add failing API tests**

Append to `tests/test_market_reports_api.py`:

```python
from fastapi.testclient import TestClient

from dashboard_server import create_app


def _login(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    assert response.status_code == 200
    return response.json()["access_token"]


def test_markets_api_returns_market_menu(tmp_path: Path):
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    token = _login(client)

    response = client.get("/api/markets", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()[1]["id"] == "hk"
    assert response.json()[2]["reports"][0]["title"] == "盘后观察"


def test_market_report_api_rejects_invalid_combination(tmp_path: Path):
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    token = _login(client)

    response = client.get("/api/reports/us/morning", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400
    assert "invalid report type" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_reports_api.py -q
```

Expected: FAIL because `/api/markets` and `/api/reports/{market}/{report_type}` do not exist.

- [ ] **Step 3: Implement endpoints**

In `dashboard_server.py`, import:

```python
from stock_dashboard.markets import list_market_payloads, validate_market_report
```

Add endpoint after `/api/me`:

```python
    @app.get("/api/markets")
    def markets_api(current_user: CurrentUser) -> list[dict[str, object]]:
        return list_market_payloads()
```

Add market-aware report endpoint:

```python
    @app.get("/api/reports/{market}/{report_type}")
    def market_report(
        market: str,
        report_type: str,
        current_user: CurrentUser,
        pool: str = "core",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        try:
            validate_market_report(market, report_type)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return build_report_payload(
            config.report_dir,
            ReportQuery(market=market, report_type=report_type, pool=pool, page=page, page_size=page_size),
        )
```

Add market status endpoint:

```python
    @app.get("/api/status/{market}")
    def market_status_api(market: str, current_user: RootUser) -> dict[str, object]:
        try:
            validate_market_report(market, get_market_definition(market).default_report_type)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return read_status(config.report_dir, market)
```

Also import `get_market_definition`.

- [ ] **Step 4: Run API tests**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_reports_api.py tests/test_auth_api.py -q
```

Expected: PASS.

## Task 4: Market-Aware Jobs

**Files:**
- Modify: `stock_dashboard/jobs.py`
- Modify: `dashboard_server.py`
- Modify: `run_job.py`
- Test: `tests/test_market_jobs.py`

- [ ] **Step 1: Write failing tests**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard_server import create_app
from stock_dashboard.jobs import JobManager


def test_job_manager_accepts_market_report_type(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run_job(market: str, report_type: str, base_dir: Path):
        calls.append((market, report_type, base_dir))
        from stock_dashboard.jobs import JobResult

        return JobResult(market=market, report_type=report_type, returncode=0, output="ok")

    monkeypatch.setattr("stock_dashboard.jobs.run_job", fake_run_job)
    manager = JobManager(tmp_path)

    job = manager.start("hk", "pre_market")
    while manager.get(job.job_id).status in {"queued", "running"}:
        pass

    final = manager.get(job.job_id)
    assert final.market == "hk"
    assert final.report_type == "pre_market"
    assert final.status == "succeeded"
    assert calls[0][:2] == ("hk", "pre_market")


def test_run_job_api_rejects_invalid_market_report(tmp_path: Path):
    app = create_app(report_dir=tmp_path / "reports", data_dir=tmp_path / "data", output_dir=tmp_path / "output", frontend_dist_dir=tmp_path / "dist")
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "root", "password": "admin@root"})
    token = login.json()["access_token"]

    response = client.post(
        "/api/jobs/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"market": "us", "report_type": "morning"},
    )

    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_jobs.py -q
```

Expected: FAIL because job API and manager still accept only `mode`.

- [ ] **Step 3: Update job data model**

In `stock_dashboard/jobs.py`, change `JobResult` and `JobStatus`:

```python
@dataclass(frozen=True)
class JobResult:
    market: str
    report_type: str
    returncode: int
    output: str
```

Add `market: str` and `report_type: str` to `JobStatus`. Keep `mode` in `to_dict()` as a compatibility string:

```python
            "market": self.market,
            "report_type": self.report_type,
            "mode": f"{self.market}.{self.report_type}",
```

Change `JobManager.start` signature:

```python
    def start(self, market: str, report_type: str) -> JobStatus:
        validate_market_report(market, report_type)
```

Change background call:

```python
        result = run_job(job.market, job.report_type, self.base_dir)
```

- [ ] **Step 4: Update subprocess runner**

In `stock_dashboard/jobs.py`, replace `run_job`:

```python
def run_job(market: str, report_type: str, base_dir: Path) -> JobResult:
    validate_market_report(market, report_type)
    result = subprocess.run(
        [sys.executable, str(base_dir / "run_job.py"), "--market", market, "--report-type", report_type, "--force"],
        cwd=str(base_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return JobResult(market=market, report_type=report_type, returncode=result.returncode, output=result.stdout)
```

- [ ] **Step 5: Update FastAPI request model and endpoint**

In `dashboard_server.py`:

```python
class RunJobRequest(BaseModel):
    market: str = "cn"
    report_type: str | None = None
    mode: str | None = None
```

In `/api/jobs/run`, derive compatibility:

```python
        report_type = payload.report_type
        market = payload.market
        if report_type is None and payload.mode is not None:
            report_type = "after_close" if payload.mode == "after_close" else "morning"
            market = "cn"
        if report_type is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="report_type is required")
        job = job_manager.start(market, report_type)
```

- [ ] **Step 6: Update run_job CLI**

In `run_job.py`, add args:

```python
    parser.add_argument("--market", choices=["cn", "hk", "us"], default="cn")
    parser.add_argument("--report-type")
```

Keep `--mode` as legacy. In `main()`:

```python
    report_type = args.report_type
    if report_type is None and args.mode is not None:
        report_type = "after_close" if args.mode == "after_close" else "morning"
    if report_type is None:
        parser.error("--report-type is required unless --mode is used")
    run_report(args.market, report_type, force=args.force)
```

Add `run_report(market, report_type, force)` that calls old `run_after_close` / `run_morning` for `cn`, and placeholder HK/US runner calls from Task 5 after those exist.

- [ ] **Step 7: Run job tests**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_market_jobs.py tests/test_auth_api.py -q
```

Expected: PASS.

## Task 5: Hong Kong And US Strategy Runners

**Files:**
- Create: `stock_dashboard/market_strategies.py`
- Modify: `run_job.py`
- Test: `tests/test_hk_us_strategy.py`

- [ ] **Step 1: Write failing pure-strategy tests**

```python
import pandas as pd

from stock_dashboard.market_strategies import (
    build_hk_candidates_from_quotes,
    build_us_candidates_from_quotes,
)


def test_hk_strategy_filters_low_liquidity_and_scores_candidates():
    quotes = pd.DataFrame(
        [
            {"code": "00700", "名称": "腾讯控股", "最新价": 380, "涨跌幅": 3.2, "成交额": 9_000_000_000},
            {"code": "09999", "名称": "薄弱股份", "最新价": 0.08, "涨跌幅": 9.0, "成交额": 1_000_000},
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
            {"code": "PENNY", "名称": "Penny Corp", "最新价": 1.2, "涨跌幅": 20.0, "成交额": 10_000_000},
        ]
    )

    candidates = build_us_candidates_from_quotes(quotes, report_type="after_hours")

    assert list(candidates["代码"]) == ["NVDA"]
    assert candidates.iloc[0]["买入观察等级"].startswith("A_")
    assert candidates.iloc[0]["市场"] == "美股"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_hk_us_strategy.py -q
```

Expected: FAIL because `stock_dashboard.market_strategies` does not exist.

- [ ] **Step 3: Implement pure scoring helpers**

Create `stock_dashboard/market_strategies.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd


def build_hk_candidates_from_quotes(quotes: pd.DataFrame, report_type: str) -> pd.DataFrame:
    df = _normalize_quote_frame(quotes, market_label="港股")
    if df.empty:
        return df
    df = df[(df["最新价"] >= 0.5) & (df["成交额"] >= 50_000_000) & (df["涨跌幅"] >= 1.0)].copy()
    return _score_candidates(df, market_label="港股", report_type=report_type, amount_divisor=2_000_000_000)


def build_us_candidates_from_quotes(quotes: pd.DataFrame, report_type: str) -> pd.DataFrame:
    df = _normalize_quote_frame(quotes, market_label="美股")
    if df.empty:
        return df
    df = df[(df["最新价"] >= 5) & (df["成交额"] >= 100_000_000) & (df["涨跌幅"] >= 1.0)].copy()
    return _score_candidates(df, market_label="美股", report_type=report_type, amount_divisor=5_000_000_000)


def _normalize_quote_frame(quotes: pd.DataFrame, market_label: str) -> pd.DataFrame:
    if quotes.empty:
        return pd.DataFrame()
    df = quotes.copy()
    rename_map = {
        "symbol": "code",
        "代码": "code",
        "名称": "名称",
        "name": "名称",
        "最新价": "最新价",
        "price": "最新价",
        "涨跌幅": "涨跌幅",
        "change_pct": "涨跌幅",
        "成交额": "成交额",
        "amount": "成交额",
    }
    df = df.rename(columns={key: value for key, value in rename_map.items() if key in df.columns})
    for column in ["code", "名称", "最新价", "涨跌幅", "成交额"]:
        if column not in df.columns:
            df[column] = "" if column in {"code", "名称"} else 0
    df["code"] = df["code"].astype(str)
    df["代码"] = df["code"]
    df["名称"] = df["名称"].astype(str)
    df["最新价"] = pd.to_numeric(df["最新价"], errors="coerce").fillna(0)
    df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce").fillna(0)
    df["成交额"] = pd.to_numeric(df["成交额"], errors="coerce").fillna(0)
    df["成交额亿"] = (df["成交额"] / 100_000_000).round(2)
    df["市场"] = market_label
    return df


def _score_candidates(df: pd.DataFrame, market_label: str, report_type: str, amount_divisor: float) -> pd.DataFrame:
    if df.empty:
        return df
    scored = df.copy()
    scored["个股强度分"] = (scored["涨跌幅"].clip(upper=8) * 2.5 + (scored["成交额"] / amount_divisor).clip(upper=1) * 15).round(2)
    scored["板块强度分"] = 0.0
    scored["资金流向分"] = 0.0
    scored["位置风险分"] = scored["涨跌幅"].map(lambda value: 8 if value >= 12 else 16 if value >= 8 else 20)
    scored["新闻催化分"] = 0.0
    scored["主线强势分"] = (
        scored["个股强度分"] + scored["板块强度分"] + scored["资金流向分"] + scored["位置风险分"] + scored["新闻催化分"]
    ).round(2)
    scored["买入观察等级"] = scored["主线强势分"].map(lambda score: "A_核心关注" if score >= 38 else "B_继续观察" if score >= 28 else "C_暂缓跟踪")
    scored["次日动作建议"] = scored.apply(lambda row: f"{market_label}{_report_label(report_type)}：观察量能延续、价格承接和风险回落。", axis=1)
    keep = ["code", "代码", "名称", "最新价", "涨跌幅", "成交额亿", "市场", "个股强度分", "板块强度分", "资金流向分", "位置风险分", "新闻催化分", "主线强势分", "买入观察等级", "次日动作建议"]
    return scored[keep].sort_values(["买入观察等级", "主线强势分"], ascending=[True, False]).reset_index(drop=True)


def _report_label(report_type: str) -> str:
    return {
        "after_close": "收盘观察",
        "pre_market": "盘前观察",
        "after_hours": "盘后观察",
    }.get(report_type, "观察")
```

- [ ] **Step 4: Add AKShare runner functions**

Append to `market_strategies.py`:

```python
def run_hk_report(report_type: str, output_dir: Path, ak_module=None) -> tuple[Path, Path]:
    ak = _load_akshare(ak_module)
    quotes = _fetch_hk_quotes(ak)
    candidates = build_hk_candidates_from_quotes(quotes, report_type)
    return _write_market_outputs(candidates, output_dir, f"hk_{report_type}")


def run_us_report(report_type: str, output_dir: Path, ak_module=None) -> tuple[Path, Path]:
    ak = _load_akshare(ak_module)
    quotes = _fetch_us_quotes(ak)
    candidates = build_us_candidates_from_quotes(quotes, report_type)
    return _write_market_outputs(candidates, output_dir, f"us_{report_type}")


def _load_akshare(ak_module):
    if ak_module is not None:
        return ak_module
    import akshare as ak

    return ak


def _fetch_hk_quotes(ak) -> pd.DataFrame:
    if hasattr(ak, "stock_hk_spot_em"):
        return ak.stock_hk_spot_em()
    if hasattr(ak, "stock_hk_spot"):
        return ak.stock_hk_spot()
    raise RuntimeError("AKShare 缺少港股实时行情接口")


def _fetch_us_quotes(ak) -> pd.DataFrame:
    if hasattr(ak, "stock_us_spot_em"):
        return ak.stock_us_spot_em()
    if hasattr(ak, "stock_us_spot"):
        return ak.stock_us_spot()
    raise RuntimeError("AKShare 缺少美股实时行情接口")


def _write_market_outputs(candidates: pd.DataFrame, output_dir: Path, prefix: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"{prefix}_{stamp}.csv"
    html_path = output_dir / f"{prefix}_{stamp}.html"
    candidates.to_csv(csv_path, index=False)
    candidates.to_html(html_path, index=False)
    return csv_path, html_path
```

- [ ] **Step 5: Wire HK/US into `run_job.py`**

In `run_job.py`, import:

```python
from stock_dashboard.market_strategies import run_hk_report, run_us_report
from stock_dashboard.markets import get_market_definition
```

Add:

```python
def run_report(market: str, report_type: str, force: bool = False) -> None:
    ensure_dirs()
    market_def = get_market_definition(market)
    report_def = market_def.report(report_type)
    market_report_dir = REPORT_DIR / market
    market_report_dir.mkdir(parents=True, exist_ok=True)

    if market == "cn" and report_type == "after_close":
        run_after_close(force=force, report_dir=market_report_dir)
        return
    if market == "cn" and report_type == "morning":
        run_morning(force=force, report_dir=market_report_dir)
        return
    if is_weekend() and not force:
        update_status({"status": "skipped_weekend", "market": market, "report_type": report_type}, report_dir=market_report_dir)
        return
    csv_path, html_path = run_hk_report(report_type, OUTPUT_DIR) if market == "hk" else run_us_report(report_type, OUTPUT_DIR)
    copy_file(csv_path, market_report_dir / report_def.latest_csv)
    if report_def.latest_html:
        copy_file(html_path, market_report_dir / report_def.latest_html)
    update_status({"status": "ok", "market": market, "report_type": report_type, "latest_csv": str(market_report_dir / report_def.latest_csv)}, report_dir=market_report_dir)
```

Also change `update_status` signature to accept `report_dir: Path = REPORT_DIR`, and update A-share functions to accept `report_dir: Path = REPORT_DIR`.

- [ ] **Step 6: Run strategy tests**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_hk_us_strategy.py tests/test_market_jobs.py -q
```

Expected: PASS.

## Task 6: Scheduler Update

**Files:**
- Modify: `stock_dashboard/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Add failing scheduler test**

Add:

```python
def test_scheduler_jobs_include_all_markets():
    from stock_dashboard.scheduler import scheduled_jobs

    jobs = scheduled_jobs()
    assert ("cn", "after_close", "15:05") in jobs
    assert ("cn", "morning", "09:40") in jobs
    assert ("hk", "after_close", "16:15") in jobs
    assert ("hk", "pre_market", "09:15") in jobs
    assert ("us", "after_hours", "05:15") in jobs
    assert ("us", "pre_market", "21:00") in jobs
```

- [ ] **Step 2: Run scheduler tests to verify failure**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_scheduler.py -q
```

Expected: FAIL because `scheduled_jobs()` does not exist.

- [ ] **Step 3: Implement scheduled job table**

In `stock_dashboard/scheduler.py`, add:

```python
def scheduled_jobs() -> list[tuple[str, str, str]]:
    return [
        ("cn", "after_close", "15:05"),
        ("cn", "morning", "09:40"),
        ("hk", "after_close", "16:15"),
        ("hk", "pre_market", "09:15"),
        ("us", "after_hours", "05:15"),
        ("us", "pre_market", "21:00"),
    ]
```

Update the scheduler loop to compare the current `%H:%M` against this table and invoke:

```python
[sys.executable, "run_job.py", "--market", market, "--report-type", report_type]
```

- [ ] **Step 4: Run scheduler tests**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest tests/test_scheduler.py -q
```

Expected: PASS.

## Task 7: Frontend Market Dropdown

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/Dashboard.tsx`
- Modify: `frontend/src/ReportView.tsx`
- Modify: `frontend/src/AdminViews.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Update API types**

In `frontend/src/api.ts`, add:

```typescript
export type ReportDefinition = {
  id: string;
  title: string;
};

export type MarketDefinition = {
  id: "cn" | "hk" | "us";
  name: string;
  short_name: string;
  default_report_type: string;
  reports: ReportDefinition[];
};
```

Add:

```typescript
export async function fetchMarkets(token: string): Promise<MarketDefinition[]> {
  const response = await authFetch("/api/markets", token);
  return (await readJson(response)) as MarketDefinition[];
}
```

Change `fetchReport` signature to:

```typescript
export async function fetchReport(
  token: string,
  market: string,
  reportType: string,
  pool: string,
  page: number,
  pageSize: number
): Promise<ReportPayload> {
  const params = new URLSearchParams({ pool, page: String(page), page_size: String(pageSize) });
  const response = await authFetch(`/api/reports/${market}/${reportType}?${params.toString()}`, token);
  return (await readJson(response)) as ReportPayload;
}
```

Add market-aware status and jobs:

```typescript
export async function fetchStatus(token: string, market: string): Promise<StatusPayload> {
  const response = await authFetch(`/api/status/${market}`, token);
  return (await readJson(response)) as StatusPayload;
}

export async function runJob(token: string, market: string, reportType: string): Promise<JobPayload> {
  const response = await authFetch("/api/jobs/run", token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ market, report_type: reportType })
  });
  return (await readJson(response)) as JobPayload;
}
```

- [ ] **Step 2: Update Dashboard state**

In `Dashboard.tsx`, fetch markets on mount, keep `activeMarketId`, and render a `select` in the sidebar:

```tsx
<label className="sidebar-label" htmlFor="market-select">市场</label>
<select
  id="market-select"
  className="market-select"
  value={activeMarketId}
  onChange={(event) => {
    const next = markets.find((item) => item.id === event.target.value);
    if (next) {
      setActiveMarketId(next.id);
      setView(next.default_report_type);
    }
  }}
>
  {markets.map((market) => (
    <option key={market.id} value={market.id}>{market.name}</option>
  ))}
</select>
```

Render observation buttons from `activeMarket.reports`, then root-only admin buttons.

- [ ] **Step 3: Update ReportView props**

Change props:

```typescript
type ReportViewProps = {
  token: string;
  market: string;
  reportType: string;
  title: string;
};
```

Call `fetchReport(token, market, reportType, activePool, page, pageSize)`.

- [ ] **Step 4: Update AdminViews props**

Change props:

```typescript
type AdminViewsProps = {
  token: string;
  market: string;
  reports: ReportDefinition[];
  view: "status" | "jobs" | "users";
};
```

Use `fetchStatus(token, market)`. For job buttons, render each market report as a trigger:

```tsx
{reports.map((report) => (
  <button key={report.id} onClick={() => startJob(report.id)}>
    运行{report.title}
  </button>
))}
```

Call `runJob(token, market, reportType)`.

- [ ] **Step 5: Add select styling**

In `frontend/src/styles.css`:

```css
.sidebar-label {
  color: var(--muted);
  display: block;
  font-size: 12px;
  margin: 18px 0 6px;
}

.market-select {
  background: #0f172a;
  border: 1px solid #334155;
  border-radius: 8px;
  color: var(--text);
  font: inherit;
  margin-bottom: 16px;
  padding: 10px 12px;
  width: 100%;
}
```

- [ ] **Step 6: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: PASS.

## Task 8: Documentation And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Add a section:

```markdown
## 多市场支持

系统支持三个市场：

- A股市场：收盘观察、早盘确认
- 港股市场：收盘观察、盘前观察
- 美股市场：盘后观察、盘前观察

页面通过左侧市场下拉框切换市场。策略说明不显示在看板页面中，任务结果按市场独立保存到 `reports/<market>/`。
```

Update manual job examples:

```bash
python run_job.py --market cn --report-type after_close --force
python run_job.py --market hk --report-type pre_market --force
python run_job.py --market us --report-type after_hours --force
```

- [ ] **Step 2: Run full Python test suite**

Run:

```bash
source /Users/nswell/Documents/Env/Miniconda3/etc/profile.d/conda.sh && conda activate base && PYTHONPATH=. python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd frontend && npm run build
```

Expected: build succeeds.

- [ ] **Step 4: Check git diff**

Run:

```bash
git diff --stat
```

Expected: changes are limited to market strategy, API, scheduler, frontend, tests, and README.
