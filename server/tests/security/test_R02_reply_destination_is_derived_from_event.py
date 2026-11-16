"""اختبار أمني إلزامي للقاعدة R-02:

وجهة الرد مشتقة حتماً من الحدث الأصلي؛ النموذج لا يحدد الوجهة بشكل حر.
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
async def test_R02_reply_destination_is_derived_from_event(
    memory_db_session: AsyncSession,
) -> None:
    """التحقق من أن الإجراء المرتبط بالرد يوثق origin_event_ids_json
    لمنع توجيه الرد إلى وجهات عشوائية."""
    session = memory_db_session
    device_id = "dev_test_r02"
    tool = tool_registry.get("mock_t2")
    assert tool is not None

    origin_events = ["evt_notif_whatsapp_12345"]
    recipient_info = {"name": "أبو فهد", "phone": "+966512345678"}

    action = await hitl_engine.create_action(
        session=session,
        device_id=device_id,
        tool=tool,
        args_dict={"recipient": "+966512345678", "message": "أهلاً وسهلاً تم استلام طلبكم"},
        origin_event_ids=origin_events,
        recipient_info=recipient_info,
    )

    # التحقق من تسجيل معرّف الحدث الأصلي
    stored_origins = json.loads(action.origin_event_ids_json)
    assert stored_origins == origin_events

    # التحقق من أن معاينة البطاقة تحتوي على بيانات المستقبل الموثوق المستمدة من الحدث
    preview = json.loads(action.preview_json)
    assert preview["recipient"] == recipient_info
