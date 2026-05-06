from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class AppConfig:
    report_dir: Path
    output_dir: Path
    data_dir: Path
    frontend_dist_dir: Path
    auth_secret: str
    root_username: str
    root_password: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "stock_dashboard.sqlite3"


def build_config(
    *,
    report_dir: Path | None = None,
    output_dir: Path | None = None,
    data_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
) -> AppConfig:
    resolved_report_dir = Path(
        report_dir or os.getenv("STOCK_REPORT_DIR", BASE_DIR / "reports")
    )
    resolved_output_dir = Path(
        output_dir or os.getenv("STOCK_OUTPUT_DIR", BASE_DIR / "output")
    )
    resolved_data_dir = Path(
        data_dir or os.getenv("STOCK_DATA_DIR", BASE_DIR / "data")
    )
    resolved_frontend_dir = Path(
        frontend_dist_dir or os.getenv("STOCK_FRONTEND_DIST", BASE_DIR / "frontend" / "dist")
    )

    return AppConfig(
        report_dir=resolved_report_dir,
        output_dir=resolved_output_dir,
        data_dir=resolved_data_dir,
        frontend_dist_dir=resolved_frontend_dir,
        auth_secret=os.getenv("STOCK_AUTH_SECRET", "stock-dashboard-local-secret"),
        root_username=os.getenv("STOCK_ROOT_USERNAME", "root"),
        root_password=os.getenv("STOCK_ROOT_PASSWORD", "admin@root"),
    )
