from __future__ import annotations

import logging
from pathlib import Path


LOGGER = logging.getLogger(__name__)


def bootstrap_reports(base_dir: Path) -> None:
    LOGGER.info("Startup report bootstrap removed; skipping automatic data fetch.")
