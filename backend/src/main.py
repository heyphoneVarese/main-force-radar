import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.funds import router as funds_router
from src.api.holdings import router as holdings_router
from src.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Phase 3.11 — APScheduler 实例(module-level,lifespan 启停)
_scheduler = None  # type: ignore[var-annotated]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan:启动时按 SCHEDULER_ENABLED 决定是否启动 cron。"""
    global _scheduler
    if settings.scheduler_enabled:
        from src.services.scheduler import SignalScheduler

        try:
            _scheduler = SignalScheduler()
            _scheduler.register_jobs()
            _scheduler.start()
            logger.info("✅ SignalScheduler started (4 cron jobs)")
        except Exception as e:
            logger.error("SignalScheduler 启动失败: %s: %s", type(e).__name__, e)
            _scheduler = None
    else:
        logger.info("⏸️  SCHEDULER_ENABLED=false,scheduler 未启动(开发模式)")

    yield  # FastAPI 应用运行

    if _scheduler is not None:
        try:
            _scheduler.shutdown()
        except Exception as e:
            logger.error("SignalScheduler shutdown 失败: %s", e)


app = FastAPI(
    title="主力风向标 (Main Force Radar)",
    version="0.1.0",
    lifespan=lifespan,
)

# R4 单用户、无认证,前端从任何 LAN IP 访问都允许。
# 同源走 vite proxy 时其实不需要 CORS,但加上做兜底:
# 1. 防止 iOS Safari 对同源 DELETE+Content-Type 的某些奇怪预检失败
# 2. 未来如果前端独立部署到不同 host,不用再改后端
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(funds_router)
app.include_router(holdings_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "main-force-radar",
        "scheduler_enabled": settings.scheduler_enabled,
        "scheduler_running": _scheduler is not None and _scheduler.scheduler.running,
    }
