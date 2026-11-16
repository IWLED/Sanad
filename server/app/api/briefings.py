"""نقاط النهاية لاسترجاع وتوليد ملخصات الإيجاز اليومي (Section 8.2 & Section 11.1)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.core.briefing.engine import generate_briefing
from app.db.base import get_db_session
from app.db.models import Briefing

router = APIRouter(prefix="/v1/briefings", tags=["briefings"])


class BriefingResponse(BaseModel):
    id: str
    kind: str
    generated_at: str
    delivered_at: str | None = None
    acked_at: str | None = None
    rendered_text: str


@router.get(
    "/latest",
    response_model=BriefingResponse,
    status_code=status.HTTP_200_OK,
    summary="استرجاع أحدث إيجاز ذكي تم توليده",
)
async def get_latest_briefing(
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> BriefingResponse:
    """استرجاع آخر إيجاز محفوظ في قاعدة البيانات."""
    stmt = select(Briefing).order_by(Briefing.generated_at.desc()).limit(1)
    res = await session.execute(stmt)
    briefing = res.scalar_one_or_none()

    if not briefing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No briefings available yet",
        )

    return BriefingResponse(
        id=briefing.id,
        kind=briefing.kind,
        generated_at=briefing.generated_at,
        delivered_at=briefing.delivered_at,
        acked_at=briefing.acked_at,
        rendered_text=briefing.rendered_text,
    )


@router.post(
    "/generate",
    response_model=BriefingResponse,
    status_code=status.HTTP_200_OK,
    summary="توليد إيجاز فوري عند الطلب (On Demand)",
)
async def trigger_on_demand_briefing(
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> BriefingResponse:
    """توليد إيجاز فوري وتوزيعه على الأجهزة المتصلة."""
    briefing = await generate_briefing(kind="on_demand", session=session)
    return BriefingResponse(
        id=briefing.id,
        kind=briefing.kind,
        generated_at=briefing.generated_at,
        delivered_at=briefing.delivered_at,
        acked_at=briefing.acked_at,
        rendered_text=briefing.rendered_text,
    )


@router.post(
    "/{briefing_id}/ack",
    status_code=status.HTTP_200_OK,
    summary="تأكيد قراءة واستلام الإيجاز من الجوال",
)
async def acknowledge_briefing(
    briefing_id: str,
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """تسجيل إقرار الاستلام للإيجاز."""
    stmt = select(Briefing).where(Briefing.id == briefing_id)
    res = await session.execute(stmt)
    briefing = res.scalar_one_or_none()

    if not briefing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Briefing not found")

    briefing.acked_at = datetime.now(UTC).isoformat()
    return {"status": "acknowledged", "briefing_id": briefing_id}
