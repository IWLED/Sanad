"""اختبار أمني إلزامي للقاعدة R-01:

حظر أي أثر خارجي دون اعتماد بشري مسبق صريح.
الأدوات ذات الخطورة Tier >= 2 يجب ألا تُنفَّذ مباشرة إطلاقاً.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.hitl.engine import hitl_engine
from app.db.base import Base
from app.db.models import Action
from app.tools.registry import tool_registry


@pytest.fixture
async def memory_db_session() -> AsyncGenerator[AsyncSession, None]:
    """قاعدة بيانات SQLite في الذاكرة معزولة للاختبار."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_R01_no_external_effect_without_approval(
    memory_db_session: AsyncSession,
) -> None:
    """التحقق من إنشاء إجراء PENDING_APPROVAL وعدم التنفيذ المباشر لأدوات Tier 2 و Tier 3."""
    session = memory_db_session
    device_id = "dev_test_r01"

    # 1. فحص أداة Tier 2 (إرسال رسالة)
    tool_t2 = tool_registry.get("mock_t2")
    assert tool_t2 is not None
    assert tool_t2.risk_tier == 2

    args = {"recipient": "+966500000000", "message": "السلام عليكم ورحمة الله"}

    action_t2 = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool_t2,
        args_dict=args,
        session_tainted=False,
    )

    # التحقق من أن حالة الإجراء معلّقة بانتظار الاعتماد فقط
    assert action_t2.status == "PENDING_APPROVAL"
    assert action_t2.executed_at is None
    assert action_t2.risk_tier == 2

    # 2. فحص أداة Tier 3 (حذف حساب أو تحويل)
    tool_t3 = tool_registry.get("mock_t3")
    assert tool_t3 is not None
    assert tool_t3.risk_tier == 3

    args_t3 = {"action_detail": "حذف النسخة الاحتياطية", "confirm": True}
    action_t3 = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool_t3,
        args_dict=args_t3,
        session_tainted=True,
    )

    assert action_t3.status == "PENDING_APPROVAL"
    assert action_t3.executed_at is None
    assert action_t3.risk_tier == 3

    # التحقق في قاعدة البيانات أن الإجراءات لم تُنفذ
    actions = (await session.execute(Action.__table__.select())).fetchall()
    assert len(actions) == 2
    for act in actions:
        assert act.status == "PENDING_APPROVAL"
        assert act.executed_at is None
