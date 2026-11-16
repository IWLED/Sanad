"""نقطة الدخول الرئيسية لتطبيق FastAPI وتكوين المسارات ومراقبة الجاهزية."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.pairing import router as pairing_router
from app.api.ws import router as ws_router
from app.config import settings
from app.core.safety.logging_filter import configure_logging, logger
from app.core.ws.dispatcher import dispatcher


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """تهيئة موارد الخادم عند البدء والتنظيف عند الإغلاق."""
    configure_logging(settings.log_level)
    logger.info("sanad_server_startup", env=settings.app_env, tz=settings.timezone)
    dispatcher.start()
    yield
    dispatcher.stop()
    logger.info("sanad_server_shutdown")


def create_app() -> FastAPI:
    """مصنع تطبيق FastAPI الأساسي."""
    app = FastAPI(
        title="Sanad AI Secretary API",
        version="0.1.0",
        description="الواجهة البرمجية الموحدة للسكرتير الشخصي الذكي (سند)",
        lifespan=lifespan,
    )

    # تسجيل مسارات الفحص والاقتران والمصادقة والـ WebSocket
    app.include_router(health_router)
    app.include_router(pairing_router)
    app.include_router(auth_router)
    app.include_router(ws_router)

    return app


app = create_app()
