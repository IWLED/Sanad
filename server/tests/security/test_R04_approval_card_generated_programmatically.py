"""اختبار أمني إلزامي للقاعدة R-04:

توليد بطاقة الاعتماد برمجياً وحتمياً عبر الكود (build_preview) وليس من مخرجات النموذج.
"""

import json
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.hitl.engine import hitl_engine
from app.db.base import Base
from app.tools.registry import tool_registry


@pytest.fixture
async def memory_db_session() -> AsyncGenerator[AsyncSession, None]:
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_R04_approval_card_generated_programmatically(
    memory_db_session: AsyncSession,
) -> None:
    """التحقق من أن هيكل بطاقة الاعتماد مبني بالكامل عبر الكود مع فحص DLP الآلي."""
    session = memory_db_session
    device_id = "dev_test_r04"
    tool = tool_registry.get("mock_t2")
    assert tool is not None

    # مسودة تحتوي على IBAN لاختبار فحص DLP التلقائي
    draft_with_iban = "الرجاء تحويل المبلغ إلى الحساب SA0380000000608010167519 وشكراً"
    action = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool,
        args_dict={"recipient": "+966500000000", "message": draft_with_iban},
        extra_warnings=["تحذير إضافي من السياسة الأمنية"],
    )

    preview = json.loads(action.preview_json)
    # المعاينة يجب أن تحتوي على الحقول الثابتة
    assert "title" in preview
    assert "draft_text" in preview
    assert "warnings" in preview
    assert isinstance(preview["warnings"], list)

    # يجب أن يظهر تحذير كشف الآيبان المضاف برمجياً بواسطة DLP
    warnings = preview["warnings"]
    assert any("آيبان" in w for w in warnings)
    assert any("السياسة الأمنية" in w for w in warnings)
