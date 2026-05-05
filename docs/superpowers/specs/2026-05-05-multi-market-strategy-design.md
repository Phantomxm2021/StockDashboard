# Multi-Market Strategy Design

## Goal

Extend the stock dashboard from a single A-share workflow into a three-market workflow for A-shares, Hong Kong stocks, and US stocks. Users can choose the active market from a sidebar dropdown. The left navigation, reports, job actions, and strategy execution scope change with that market.

The dashboard must not show strategy explanations in the normal UI. It should present results, status, and operations only.

## Markets And Navigation

The sidebar keeps one global market selector:

- A股市场 (`cn`)
- 港股市场 (`hk`)
- 美股市场 (`us`)

Menu items are market-specific:

- A股：收盘观察、早盘确认、市场状态、任务中心、用户管理
- 港股：收盘观察、盘前观察、市场状态、任务中心、用户管理
- 美股：盘后观察、盘前观察、市场状态、任务中心、用户管理

Only root users can see and use 市场状态、任务中心、用户管理. Normal users can only view observation reports for the selected market.

## API Shape

The backend should treat market and report type as first-class parameters.

New or revised endpoints:

- `GET /api/markets`
- `GET /api/reports/{market}/{report_type}`
- `GET /api/status/{market}`
- `POST /api/jobs/run` with `{ "market": "...", "report_type": "..." }`
- `GET /api/jobs/{job_id}`

The legacy A-share endpoints may remain temporarily for compatibility, but the React app should use the new market-aware endpoints.

## Report Types

Each market owns its valid report types:

- `cn.after_close`：A股收盘观察
- `cn.morning`：A股早盘确认
- `hk.after_close`：港股收盘观察
- `hk.pre_market`：港股盘前观察
- `us.after_hours`：美股盘后观察
- `us.pre_market`：美股盘前观察

The app should reject invalid combinations, such as `us.morning`.

## Report Storage

Reports should be isolated by market:

- `reports/cn/latest_after_close.csv`
- `reports/cn/latest_morning.csv`
- `reports/hk/latest_after_close.csv`
- `reports/hk/latest_pre_market.csv`
- `reports/us/latest_after_hours.csv`
- `reports/us/latest_pre_market.csv`

Status files should also be market scoped:

- `reports/cn/status.json`
- `reports/hk/status.json`
- `reports/us/status.json`

This prevents one market run from overwriting another market's latest report.

## Strategy Architecture

Add a market strategy layer instead of expanding the current A-share script into a large branching script.

Core units:

- `MarketDefinition`: market id, display name, valid report types, default report type.
- `ReportTypeDefinition`: report type id, display name, output file prefix, pool definitions.
- `StrategyRunner`: interface for running one `market + report_type` job and writing report artifacts.
- `ReportRepository`: reads market-scoped CSV/status files and builds API payloads.
- `JobManager`: starts background jobs with market and report type.

The A-share implementation should keep the current mainline model behavior. Hong Kong and US implementations should be separate runners that normalize AKShare data into the same report shape.

## Strategy Direction

The UI should not explain these rules, but the backend should implement market-appropriate scoring.

A-shares keep the current 主线强势模型:

- 成交额
- 涨幅
- 板块强度
- 资金流向
- 位置风险
- 新闻催化
- 市场放量/缩量环境

Hong Kong stocks should emphasize:

- 成交额 and liquidity
- 涨幅
- 南向资金 or available fund-flow proxy
- 行业/板块强弱
- AH/中概联动 when data is available
- 位置风险
- Filter low-liquidity names and penny-stock style candidates

US stocks should emphasize:

- Dollar volume or turnover proxy
- Price change and relative volume
- Sector/industry strength where available
- Pre-market or after-hours move for the relevant report type
- News catalyst or hot-rank proxy where available
- Position risk
- Filter low-price and low-liquidity names

If a specific AKShare enrichment source is unavailable at runtime, the runner should continue with neutral scores for that dimension and log the fallback in job output.

## Frontend Behavior

The sidebar market dropdown controls all market-aware views.

When the user changes market:

- Reset to that market's default observation view.
- Rebuild the left menu from `/api/markets`.
- Fetch reports using `market + report_type`.
- Keep admin-only controls hidden for non-root users.

The topbar should show only the selected market and current view title. It should not show strategy descriptions.

Tables keep the current professional dark style, skeleton loading, pool tabs, pagination, and high-z-index action tooltip behavior.

## Scheduler

The scheduler should support market-scoped automatic jobs.

Initial schedules:

- A股收盘观察：北京时间交易日 `15:05`
- A股早盘确认：北京时间交易日 `09:40`
- 港股收盘观察：香港交易日收盘后，默认北京时间 `16:15`
- 港股盘前观察：香港交易日前，默认北京时间 `09:15`
- 美股盘后观察：美股交易日收盘后，默认北京时间 `05:15`
- 美股盘前观察：美股交易日前，默认北京时间 `21:00`

Holiday handling should use the best available AKShare calendar per market. If calendar data fails, the scheduler should skip weekends and log that it used a fallback calendar.

## Compatibility And Migration

Existing A-share reports should remain readable during migration. If old files exist at the root of `reports/`, the repository may fall back to them for A-share until a new market-scoped run writes `reports/cn/...`.

The root account, SQLite user database, and root-only permissions remain unchanged.

## Error Handling

- Invalid market or report type returns `400`.
- Missing report returns an empty payload with a clear message rather than a frontend crash.
- AKShare data-source failures are logged and converted to neutral scoring where practical.
- A full runner failure marks the job as failed and keeps prior reports intact.

## Testing

Add focused tests before implementation:

- Market definitions expose the expected menus and report types.
- Report repository reads market-scoped files and keeps A-share fallback behavior.
- API rejects invalid market/report type combinations.
- Job manager starts jobs with `market + report_type` and rejects invalid combinations.
- Frontend build validates TypeScript changes.

Existing A-share strategy tests should continue to pass.
