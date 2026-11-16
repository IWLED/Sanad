"""إدارة وحساب ميزانية استهلاك التوكنات اليومية للنماذج (R-18)."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMUsage


async def get_tokens_consumed_today(session: AsyncSession) -> int:
    """حساب مجموع التوكنات المستهلكة لليوم الحالي (UTC)."""
    today_start = datetime.now(UTC).strftime("%Y-%m-%dT00:00:00")
    stmt = select(func.coalesce(func.sum(LLMUsage.tokens_in + LLMUsage.tokens_out), 0)).where(
        LLMUsage.ts >= today_start
    )

    result = await session.execute(stmt)
    total = result.scalar() or 0
    return int(total)


async def check_budget_available(session: AsyncSession, budget_limit: int) -> tuple[bool, int]:
    """فحص توفر رصيد ضمن الميزانية اليومية المحددة."""
    consumed = await get_tokens_consumed_today(session)
    remaining = budget_limit - consumed
    return (remaining > 0), max(0, remaining)
