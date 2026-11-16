"""اختبارات الوحدة لـ Phase 3: محرك الذاكرة FTS5، مجمّع السياق، الإيجاز الذكي، واقتراح الردود."""

import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.briefings import router as briefings_router
from app.api.ingest import router as ingest_router
from app.core.agent.autonomous_trigger import evaluate_and_trigger_reply_suggestion
from app.core.agent.context import assemble_agent_context
from app.core.agent.memory import forget_memory, get_memories_by_category, remember, search_memories
from app.core.briefing.engine import generate_briefing
from app.core.crypto import mint_jwt_access_token
from app.db.base import async_session_factory
from app.db.models import Action, Contact, Device, Event
from app.tools.reply import ProposeReplyArgs, ProposeReplyTool


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(briefings_router)
    app.include_router(ingest_router)
    return app


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as sess:
        yield sess


@pytest.mark.asyncio
async def test_memory_crud_and_fts5_search(db_session: AsyncSession) -> None:
    session = db_session
    unique_keyword = f"كلمةذاكرة_{secrets.token_hex(4)}"

    # 1. حفظ تفضيل في الذاكرة
    mem = await remember(
        category="preference",
        content=f"المستخدم يفضل عقد الاجتماعات دائماً في {unique_keyword}",
        source="user",
        session=session,
    )
    assert mem.id.startswith("mem_")

    # 2. البحث في الذاكرة عبر FTS5 مع التطبيع العربي
    search_results = await search_memories(unique_keyword, limit=5, session=session)
    assert len(search_results) >= 1
    found = search_results[0]
    assert found["id"] == mem.id
    assert unique_keyword in found["content"]

    # 3. استرجاع حسب الفئة
    prefs = await get_memories_by_category("preference", limit=10, session=session)
    assert any(p.id == mem.id for p in prefs)

    # 4. حذف الذاكرة وحق النسيان R-21
    forgotten = await forget_memory(mem.id, session=session)
    assert forgotten is True

    # التأكد من زوالها من البحث النصي FTS5
    search_after = await search_memories(unique_keyword, limit=5, session=session)
    assert len(search_after) == 0


@pytest.mark.asyncio
async def test_context_assembler(db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"

    # إضافة أسلوب رد مميز
    style_keyword = f"أسلوب_{secrets.token_hex(4)}"
    await remember(
        category="style",
        content=f"ردودي يجب أن تكون دائماً بصيغة {style_keyword}",
        source="user",
        session=session,
    )

    messages = await assemble_agent_context(
        user_query=f"هل لدي أي مواعيد مرتبطة بـ {style_keyword}؟",
        device_id=device_id,
        session=session,
    )

    assert len(messages) >= 2
    system_msg = messages[0]["content"]
    assert "أنت «سكرتير» شخصي ذكي" in system_msg
    assert style_keyword in system_msg


@pytest.mark.asyncio
async def test_briefing_engine_and_rest_api(test_app: FastAPI, db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Briefing Test Device",
        pubkey_pem="fake-pubkey",
        created_at="2026-11-16T12:00:00Z",
    )
    session.add(device)

    # 1. إنشاء جهة اتصال عائلية ذات أولوية عالية
    contact_id = f"cnt_{secrets.token_hex(6)}"
    family_contact = Contact(
        id=contact_id,
        display_name=f"الوالدة_{secrets.token_hex(4)}",
        relation="family",
        priority="high",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    session.add(family_contact)

    # 2. إنشاء أحداث حديثة لاختبار تصنيف الدرجات
    now_iso = datetime.now(UTC).isoformat()
    evt_family = Event(
        id=f"evt_{secrets.token_hex(6)}",
        source="notification",
        external_id=f"ext_{secrets.token_hex(6)}",
        thread_key=f"family_thread_{secrets.token_hex(4)}",
        sender_contact_id=contact_id,
        sender_name=family_contact.display_name,
        content="لا تنسَ المرور علينا اليوم",
        reply_capable=1,
        occurred_at=now_iso,
        received_at=now_iso,
    )

    evt_missed_call = Event(
        id=f"evt_{secrets.token_hex(6)}",
        source="missed_call",
        external_id=f"ext_{secrets.token_hex(6)}",
        thread_key=f"call_{secrets.token_hex(4)}",
        sender_name=f"د. أحمد_{secrets.token_hex(4)}",
        content="مكالمة فائتة",
        reply_capable=0,
        occurred_at=now_iso,
        received_at=now_iso,
    )

    session.add_all([evt_family, evt_missed_call])
    await session.commit()

    # 3. تشغيل محرك الإيجاز
    briefing = await generate_briefing(kind="morning", hours_lookback=24, session=session)
    assert briefing.id.startswith("brf_")
    assert "الإيجاز الصباحي" in briefing.rendered_text
    assert family_contact.display_name in briefing.rendered_text
    assert "عاجل والعائلة" in briefing.rendered_text

    # 4. اختبار نقاط REST API لـ briefings
    token, _ = mint_jwt_access_token(device_id)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(test_app)

    # GET /v1/briefings/latest
    resp_latest = client.get("/v1/briefings/latest", headers=headers)
    assert resp_latest.status_code == 200
    data_latest = resp_latest.json()
    assert data_latest["id"] == briefing.id
    assert data_latest["kind"] == "morning"

    # POST /v1/briefings/{id}/ack
    resp_ack = client.post(f"/v1/briefings/{briefing.id}/ack", headers=headers)
    assert resp_ack.status_code == 200
    assert resp_ack.json()["status"] == "acknowledged"


@pytest.mark.asyncio
async def test_propose_reply_tool_and_autonomous_trigger(db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Reply Test Phone",
        pubkey_pem="fake-pem",
        created_at="2026-11-16T12:00:00Z",
    )
    session.add(device)

    # إنشاء حدث وارد قابل للرد
    event_id = f"evt_{secrets.token_hex(6)}"
    thread_key = f"com.whatsapp:chat_{secrets.token_hex(4)}"
    test_event = Event(
        id=event_id,
        device_id=device_id,
        source="notification",
        app_package="com.whatsapp",
        external_id=f"ext_{secrets.token_hex(6)}",
        thread_key=thread_key,
        sender_name="خالد التميمي",
        content="السلام عليكم، هل موعدنا قائم الليلة بعد العشاء؟",
        reply_capable=1,
        occurred_at=datetime.now(UTC).isoformat(),
        received_at=datetime.now(UTC).isoformat(),
    )
    session.add(test_event)
    await session.commit()

    # 1. اختبار أداة propose_reply المباشرة
    tool = ProposeReplyTool()
    ctx = {"device_id": device_id}
    res = await tool.run(
        ProposeReplyArgs(
            event_id=event_id, draft_text="وعليكم السلام، نعم بإذن الله نلتقي بعد العشاء."
        ),
        ctx,
    )
    assert res["status"] == "PENDING_APPROVAL"
    assert "action_id" in res

    # التحقق من تسجيل الإجراء في قاعدة البيانات بحالة DRAFTED / PENDING_APPROVAL
    action = (
        await session.execute(select(Action).where(Action.id == res["action_id"]))
    ).scalar_one()
    assert action.kind in ["propose_reply", "send_notification_reply"]
    assert action.executor == "device"
    assert action.args_hash != ""

    # 2. اختبار تقييم محرك الاقتراح الذاتي (Autonomous Trigger)
    with patch(
        "app.core.agent.autonomous_trigger.AgentRunner.run", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = None
        triggered = await evaluate_and_trigger_reply_suggestion(
            event_id=event_id,
            device_id=device_id,
            session=session,
        )
        assert triggered is True
        mock_run.assert_awaited_once()
