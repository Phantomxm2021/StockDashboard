from __future__ import annotations

import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .markets import validate_market_report


@dataclass(frozen=True)
class JobResult:
    market: str
    report_type: str
    returncode: int
    output: str


JobStatusValue = Literal["queued", "running", "succeeded", "failed"]


@dataclass
class JobStatus:
    job_id: str
    market: str
    report_type: str
    status: JobStatusValue
    logs: str
    returncode: int | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "market": self.market,
            "report_type": self.report_type,
            "mode": f"{self.market}.{self.report_type}",
            "status": self.status,
            "logs": self.logs,
            "returncode": self.returncode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()

    def start(self, market: str, report_type: str) -> JobStatus:
        validate_market_report(market, report_type)
        now = _now()
        job = JobStatus(
            job_id=uuid.uuid4().hex,
            market=market,
            report_type=report_type,
            status="queued",
            logs="任务已排队，等待启动...\n",
            returncode=None,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.job_id] = job

        thread = threading.Thread(target=self._run_background, args=(job.job_id,), daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> JobStatus | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return JobStatus(**job.__dict__)

    def _run_background(self, job_id: str) -> None:
        self._update(job_id, status="running", logs="任务已启动...\n")
        job = self.get(job_id)
        if job is None:
            return
        try:
            result = run_job(job.market, job.report_type, self.base_dir)
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                logs=f"任务执行异常：{exc}\n",
                returncode=1,
            )
            return
        final_status: JobStatusValue = "succeeded" if result.returncode == 0 else "failed"
        self._update(
            job_id,
            status=final_status,
            logs=result.output,
            returncode=result.returncode,
        )

    def _update(
        self,
        job_id: str,
        *,
        status: JobStatusValue,
        logs: str,
        returncode: int | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            job.logs = logs
            job.returncode = returncode
            job.updated_at = _now()


def run_job(market: str, report_type: str, base_dir: Path) -> JobResult:
    validate_market_report(market, report_type)
    result = subprocess.run(
        [
            sys.executable,
            str(base_dir / "run_job.py"),
            "--market",
            market,
            "--report-type",
            report_type,
            "--force",
        ],
        cwd=str(base_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return JobResult(market=market, report_type=report_type, returncode=result.returncode, output=result.stdout)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
