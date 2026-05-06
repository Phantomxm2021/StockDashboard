from __future__ import annotations

import logging
import os
import sys
import threading

import uvicorn

from .bootstrap import bootstrap_reports
from .config import BASE_DIR


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    thread = threading.Thread(target=bootstrap_reports, args=(BASE_DIR,), daemon=True)
    thread.start()
    port = int(os.getenv("STOCK_WEB_PORT", "8001"))
    uvicorn.run("dashboard_server:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    sys.exit(main())
