from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from stock_dashboard.auth import create_token, parse_token
from stock_dashboard.config import BASE_DIR, AppConfig, build_config
from stock_dashboard.jobs import JobManager
from stock_dashboard.markets import get_market_definition, list_market_payloads, validate_market_report
from stock_dashboard.reports import ReportQuery, build_report_payload, read_status
from stock_dashboard.scheduler import read_scheduler_status
from stock_dashboard.users import User, UserStore


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str


class RunJobRequest(BaseModel):
    market: str = "cn"
    report_type: str | None = None
    mode: str | None = None


def create_app(
    *,
    report_dir: Path | None = None,
    output_dir: Path | None = None,
    data_dir: Path | None = None,
    frontend_dist_dir: Path | None = None,
) -> FastAPI:
    config = build_config(
        report_dir=report_dir,
        output_dir=output_dir,
        data_dir=data_dir,
        frontend_dist_dir=frontend_dist_dir,
    )
    config.report_dir.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)

    user_store = UserStore(config.database_path)
    user_store.bootstrap_root(config.root_username, config.root_password)
    job_manager = JobManager(BASE_DIR)

    app = FastAPI(title="A股短线观察池 Dashboard")
    app.state.config = config
    app.state.user_store = user_store
    app.state.job_manager = job_manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.frontend_dist_dir.exists():
        assets_dir = config.frontend_dist_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.post("/api/auth/login")
    def login(payload: LoginRequest) -> dict[str, object]:
        user = user_store.verify_credentials(payload.username, payload.password)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )
        return {
            "access_token": create_token(user.username, config.auth_secret),
            "token_type": "bearer",
            "user": user.public_dict(),
        }

    @app.get("/api/me")
    def me(current_user: CurrentUser) -> dict[str, object]:
        return current_user.public_dict()

    @app.get("/api/markets")
    def markets_api(current_user: CurrentUser) -> list[dict[str, object]]:
        return list_market_payloads()

    @app.get("/api/users")
    def list_users(current_user: RootUser) -> list[dict[str, object]]:
        return user_store.list_users()

    @app.post("/api/users", status_code=status.HTTP_201_CREATED)
    def create_user(payload: CreateUserRequest, current_user: RootUser) -> dict[str, object]:
        try:
            user = user_store.create_user(
                username=payload.username,
                password=payload.password,
                is_root=False,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return user.public_dict()

    @app.get("/api/reports/after-close")
    def after_close_report(
        current_user: CurrentUser,
        pool: str = "core",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        return build_report_payload(
            config.report_dir,
            ReportQuery(
                report_type="after-close",
                pool=pool,
                page=page,
                page_size=page_size,
            ),
        )

    @app.get("/api/reports/morning")
    def morning_report(
        current_user: CurrentUser,
        pool: str = "core",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        return build_report_payload(
            config.report_dir,
            ReportQuery(
                report_type="morning",
                pool=pool,
                page=page,
                page_size=page_size,
            ),
        )

    @app.get("/api/reports/{market}/{report_type}")
    def market_report(
        market: str,
        report_type: str,
        current_user: CurrentUser,
        pool: str = "core",
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        normalized_report_type = report_type.replace("-", "_")
        try:
            validate_market_report(market, normalized_report_type)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return build_report_payload(
            config.report_dir,
            ReportQuery(
                market=market,
                report_type=normalized_report_type,
                pool=pool,
                page=page,
                page_size=page_size,
            ),
        )

    @app.get("/api/status")
    def status_api(current_user: RootUser) -> dict[str, object]:
        return read_status(config.report_dir)

    @app.get("/api/status/{market}")
    def market_status_api(market: str, current_user: RootUser) -> dict[str, object]:
        try:
            get_market_definition(market)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return read_status(config.report_dir, market)

    @app.get("/api/scheduler/status")
    def scheduler_status_api(current_user: RootUser) -> dict[str, object]:
        return read_scheduler_status()

    @app.post("/api/jobs/run", status_code=status.HTTP_202_ACCEPTED)
    def run_job_api(payload: RunJobRequest, current_user: RootUser) -> dict[str, object]:
        market = payload.market
        report_type = payload.report_type
        if report_type is None and payload.mode is not None:
            market = "cn"
            if payload.mode == "after_close":
                report_type = "after_close"
            elif payload.mode == "morning":
                report_type = "morning"
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode must be after_close or morning")
        if report_type is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="report_type is required")
        try:
            job = job_manager.start(market, report_type)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def job_status_api(job_id: str, current_user: RootUser) -> dict[str, object]:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        return job.to_dict()

    @app.get("/after-close", response_class=HTMLResponse)
    def after_close_page() -> HTMLResponse:
        return _html_report_response(config.report_dir / "latest_after_close.html", "暂无收盘后观察池")

    @app.get("/morning", response_class=HTMLResponse)
    def morning_page() -> HTMLResponse:
        return _html_report_response(config.report_dir / "latest_morning.html", "暂无早盘确认池")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/{path:path}", response_model=None)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API route not found")
        index_path = config.frontend_dist_dir / "index.html"
        file_path = config.frontend_dist_dir / path
        if path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="zh-CN">
              <head><meta charset="utf-8"><title>Stock Dashboard</title></head>
              <body style="font-family: sans-serif; background: #0b1120; color: #e5e7eb;">
                <main style="max-width: 760px; margin: 80px auto;">
                  <h1>Stock Dashboard backend is running</h1>
                  <p>Run the React frontend build to serve the dashboard UI.</p>
                </main>
              </body>
            </html>
            """
        )

    return app


def _html_report_response(path: Path, empty_title: str) -> HTMLResponse:
    if not path.exists():
        return HTMLResponse(f"<section><h2>{empty_title}</h2><p>还没有生成数据。</p></section>")
    return HTMLResponse(path.read_text(encoding="utf-8"))


def get_current_user(request: Request) -> User:
    config: AppConfig = request.app.state.config
    user_store: UserStore = request.app.state.user_store
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    payload = parse_token(token, config.auth_secret)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")

    user = user_store.get_user(payload.username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


def require_root(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if not current_user.is_root:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_user)]
RootUser = Annotated[User, Depends(require_root)]

app = create_app()
