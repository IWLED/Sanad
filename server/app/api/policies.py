"""إدارة سياسات التطبيقات المراقبة والسماح بالرد (Section 8.2 & Section 9.2)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.db.base import get_db_session
from app.db.models import AppPolicy

router = APIRouter(prefix="/v1/policies", tags=["policies"])


class AppPolicyItem(BaseModel):
    """إعدادات وسياسة تطبيق محدد."""

    package: str = Field(..., description="اسم حزمة التطبيق (e.g. com.whatsapp)")
    label: str | None = Field(default=None, description="الاسم المعروض للتطبيق")
    monitor: bool = Field(default=True, description="هل التطبيق مراقب في صندوق الوارد")
    allow_reply: bool = Field(default=True, description="هل يُسمح باقتراح ردود له")
    default_priority: str = Field(default="normal", description="الأولوية الافتراضية")
    sensitivity_floor: str = Field(default="normal", description="الحد الأدنى للحساسية")


@router.get(
    "/apps",
    response_model=list[AppPolicyItem],
    status_code=status.HTTP_200_OK,
    summary="استرجاع قائمة سياسات التطبيقات المراقبة",
)
async def get_app_policies(
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[AppPolicyItem]:
    """استرجاع كافة سياسات التطبيقات المحددة مسبقاً."""
    stmt = select(AppPolicy).order_by(AppPolicy.package.asc())
    res = await session.execute(stmt)
    policies = res.scalars().all()

    return [
        AppPolicyItem(
            package=p.package,
            label=p.label,
            monitor=bool(p.monitor),
            allow_reply=bool(p.allow_reply),
            default_priority=p.default_priority,
            sensitivity_floor=p.sensitivity_floor,
        )
        for p in policies
    ]


@router.put(
    "/apps",
    response_model=AppPolicyItem,
    status_code=status.HTTP_200_OK,
    summary="تحديث أو إضافة سياسة لتطبيق محدد",
)
async def update_app_policy(
    policy_item: AppPolicyItem,
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> AppPolicyItem:
    """تحديث إعدادات المراقبة والسماح بالرد لتطبيق معين."""
    now_iso = datetime.now(UTC).isoformat()
    stmt = select(AppPolicy).where(AppPolicy.package == policy_item.package)
    res = await session.execute(stmt)
    policy = res.scalar_one_or_none()

    if policy:
        policy.label = policy_item.label
        policy.monitor = 1 if policy_item.monitor else 0
        policy.allow_reply = 1 if policy_item.allow_reply else 0
        policy.default_priority = policy_item.default_priority
        policy.sensitivity_floor = policy_item.sensitivity_floor
        policy.updated_at = now_iso
    else:
        new_policy = AppPolicy(
            package=policy_item.package,
            label=policy_item.label,
            monitor=1 if policy_item.monitor else 0,
            allow_reply=1 if policy_item.allow_reply else 0,
            default_priority=policy_item.default_priority,
            sensitivity_floor=policy_item.sensitivity_floor,
            updated_at=now_iso,
        )
        session.add(new_policy)

    await session.commit()
    return policy_item
