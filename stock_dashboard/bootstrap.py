from __future__ import annotations

import logging
import os
from pathlib import Path

from .jobs import run_job
from .markets import MARKETS


LOGGER = logging.getLogger(__name__)


def bootstrap_reports(base_dir: Path) -> None:
    mode = os.getenv("STOCK_BOOTSTRAP_REPORTS", "missing").strip().lower()
    if mode in {"0", "false", "off", "no", "none", "disabled"}:
        LOGGER.info("Report bootstrap disabled")
        return

    force = mode in {"1", "true", "on", "yes", "always", "force"}
    report_dir = Path(os.getenv("STOCK_REPORT_DIR", base_dir / "reports"))
    for market in MARKETS:
        market_dir = report_dir / market.id
        for report in market.reports:
            latest_csv = market_dir / report.latest_csv
            if latest_csv.exists() and not force:
                LOGGER.info("Skipping bootstrap for %s.%s: latest report exists", market.id, report.id)
                continue
            _run_bootstrap_job(base_dir, market.id, report.id)


def _run_bootstrap_job(base_dir: Path, market: str, report_type: str) -> None:
    LOGGER.info("Bootstrapping report: %s.%s", market, report_type)
    result = run_job(market, report_type, base_dir)
    if result.returncode == 0:
        LOGGER.info("Bootstrap report finished: %s.%s", market, report_type)
        return
    LOGGER.warning(
        "Bootstrap report failed: %s.%s returncode=%s output=%s",
        market,
        report_type,
        result.returncode,
        result.output[-2000:],
    )
