from pathlib import Path

from stock_dashboard.bootstrap import bootstrap_reports


def test_bootstrap_reports_is_noop(monkeypatch, tmp_path: Path):
    bootstrap_reports(tmp_path)

    assert not (tmp_path / "reports").exists()
