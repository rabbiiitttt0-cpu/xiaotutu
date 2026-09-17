"""看图兔 - 图纸识别助手（统一 FastAPI 后端）"""
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from config import OUTPUT_DIR, DATA_DIR, WEB_ROOT, BUNDLE_DIR


def _setup_logging():
    """系统错误日志：滚动文件 data/logs/app.log（仅管理员可查）"""
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return handler


_setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时初始化数据库 + 创建默认管理员"""
    from db.database import init_db
    init_db()

    from db.database import SessionLocal
    from auth.models import User
    from auth.service import hash_password
    db = SessionLocal()
    try:
        if not db.query(User).first():
            admin = User(
                username="admin",
                hashed_password=hash_password("admin123"),
                display_name="管理员",
                is_super_admin=True,
                is_active=True,
            )
            db.add(admin)
            db.commit()
            print("[auth] 已创建默认管理员账户: admin / admin123")
    finally:
        db.close()
    yield


app = FastAPI(
    title="看图兔 - 图纸识别助手",
    description="独立的工程图纸识别助手",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局未处理异常 → 记入错误日志文件，返回统一 500 JSON"""
    logging.getLogger("app").exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


# ===== 路由注册 =====
from auth import auth_router
from auth.deps import get_current_user, require_super_admin
from api.drawing import router as drawing_router
from api.audit_logs import router as audit_router
from api.system_status import router as status_router

app.include_router(auth_router)  # /api/auth/*
app.include_router(drawing_router, prefix="/api/drawing", tags=["看图助手"],
                   dependencies=[Depends(get_current_user)])
app.include_router(audit_router, prefix="/api/audit", tags=["日志查询"],
                   dependencies=[Depends(require_super_admin)])
app.include_router(status_router, dependencies=[Depends(get_current_user)])  # /api/system/*


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "system": "看图兔 - 图纸识别助手",
        "version": "1.0.0",
        "description": "独立的工程图纸识别助手 — 看图、问答、材料提取、快速交底",
    }


# ===== 静态文件挂载 =====
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")


# ===== 前端 SPA（PC 前端 / + 移动前端 /m，双前端共存）=====
frontend_dist = BUNDLE_DIR / "frontend" / "dist"
if not frontend_dist.exists():
    frontend_dist = WEB_ROOT / "frontend-pc" / "dist"

_NO_CACHE_HEADERS = {"Cache-Control": "no-cache"}


class ImmutableStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


# PC 前端 assets
if frontend_dist.exists() and (frontend_dist / "assets").exists():
    app.mount("/assets", ImmutableStaticFiles(directory=str(frontend_dist / "assets")), name="assets")

# 移动前端 SPA（挂载 /m，须在 PC catch-all 之前注册）
mobile_dist = WEB_ROOT / "frontend-mobile" / "dist"
if mobile_dist.exists():
    m_index = mobile_dist / "index.html"
    if (mobile_dist / "assets").exists():
        app.mount("/m/assets", ImmutableStaticFiles(directory=str(mobile_dist / "assets")), name="m_assets")

    @app.get("/m", include_in_schema=False)
    async def mobile_root():
        return FileResponse(str(m_index), headers=_NO_CACHE_HEADERS)

    @app.get("/m/{full_path:path}", include_in_schema=False)
    async def mobile_spa(full_path: str):
        file_path = mobile_dist / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(m_index), headers=_NO_CACHE_HEADERS)

# PC 前端 SPA catch-all（最后注册，避免抢 /m）
if frontend_dist.exists():
    index_path = frontend_dist / "index.html"

    @app.api_route("/{full_path:path}", methods=["GET"], include_in_schema=False)
    async def spa_catch_all(full_path: str):
        file_path = frontend_dist / full_path
        if file_path.is_file():
            if file_path.suffix in (".html", ".htm"):
                return FileResponse(str(file_path), headers=_NO_CACHE_HEADERS)
            return FileResponse(str(file_path))
        return FileResponse(str(index_path), headers=_NO_CACHE_HEADERS)
