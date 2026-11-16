"""نقاط فحص الحياة والجاهزية للنظام (Liveness & Readiness Probes)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session

router = APIRouter(tags=["health"])


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    """فحص استجابة العملية الحية (Liveness probe) بدون تسريب أي بيانات (R-13)."""
    return {
        "status": "ok",
        "ts": datetime.now(UTC).isoformat(),
    }


@router.get("/readyz")
async def readyz(
    session: AsyncSession = Depends(get_db_session),
) -> JSONResponse:
    """فحص جاهزية الخادم وقاعدة البيانات للتشغيل (Readiness probe)."""
    try:
        # فحص اتصال SQLite والـ WAL
        result = await session.execute(text("SELECT 1;"))
        val = result.scalar()
        if val != 1:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "error": "Database returned unexpected value"},
            )

        # فحص توفر الجداول الأساسية
        check_table = await session.execute(text("SELECT COUNT(*) FROM devices;"))
        _ = check_table.scalar()

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "ready",
                "database": "connected",
                "ts": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "error": f"Database check failed: {type(exc).__name__}",
            },
        )
