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
            ReportTypeDefinition(
                id="after_close",
                title="收盘观察",
                latest_csv="latest_after_close.csv",
                latest_html="latest_after_close.html",
                output_prefix="candidates",
            ),
            ReportTypeDefinition(
                id="morning",
                title="早盘确认",
                latest_csv="latest_morning.csv",
                latest_html="latest_morning.html",
                output_prefix="morning_confirm",
            ),
        ),
    ),
    MarketDefinition(
        id="hk",
        name="港股市场",
        short_name="港股",
        default_report_type="after_close",
        reports=(
            ReportTypeDefinition(
                id="after_close",
                title="收盘观察",
                latest_csv="latest_after_close.csv",
                latest_html="latest_after_close.html",
                output_prefix="hk_after_close",
            ),
            ReportTypeDefinition(
                id="pre_market",
                title="盘前观察",
                latest_csv="latest_pre_market.csv",
                latest_html="latest_pre_market.html",
                output_prefix="hk_pre_market",
            ),
        ),
    ),
    MarketDefinition(
        id="us",
        name="美股市场",
        short_name="美股",
        default_report_type="after_hours",
        reports=(
            ReportTypeDefinition(
                id="after_hours",
                title="盘后观察",
                latest_csv="latest_after_hours.csv",
                latest_html="latest_after_hours.html",
                output_prefix="us_after_hours",
            ),
            ReportTypeDefinition(
                id="pre_market",
                title="盘前观察",
                latest_csv="latest_pre_market.csv",
                latest_html="latest_pre_market.html",
                output_prefix="us_pre_market",
            ),
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
    if any(report.id == report_type for report in market.reports):
        return market
    raise ValueError(f"invalid report type for market {market_id}: {report_type}")


def get_default_report_type(market_id: str) -> str:
    return get_market_definition(market_id).default_report_type
