"""اختبارات الوحدة لـ Phase 4 و Phase 5: الصوت (STT)، مولد Office، التذكيرات، والتقويم والبريد."""

import io
import os
import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audio import router as audio_router
from app.api.files import router as files_router
from app.core.crypto import mint_jwt_access_token
from app.db.base import async_session_factory
from app.db.models import Action, Device, Event, File, Job
from app.tools.calendar import (
    CalendarCreateArgs,
    CalendarCreateTool,
    CalendarListArgs,
    CalendarListTool,
)
from app.tools.email import (
    GmailCreateDraftArgs,
    GmailCreateDraftTool,
    GmailSendArgs,
    GmailSendTool,
)
from app.tools.office.generator import sanitize_excel_cell
from app.tools.office.specs import DocSection, DocSpec, SheetSpec, WorkbookSpec
from app.tools.office.tool import GenerateDocumentArgs, GenerateDocumentTool
from app.tools.reminders import (
    ScheduleMessageArgs,
    ScheduleMessageTool,
    ScheduleReminderArgs,
    ScheduleReminderTool,
)
from app.workers.jobs_dispatcher import process_due_jobs


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(audio_router)
    app.include_router(files_router)
    return app


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as sess:
        yield sess


@pytest.mark.asyncio
async def test_audio_transcribe_endpoint(test_app: FastAPI, db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Audio Test Device",
        pubkey_pem="fake-pem",
        created_at=datetime.now(UTC).isoformat(),
    )
    session.add(device)
    await session.commit()

    token, _ = mint_jwt_access_token(device_id)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(test_app)

    # محاكاة مزود STT لتجنب الاتصال الخارجي في الاختبار
    fake_audio_bytes = b"RIFF....WAVEfmt ...."
    with patch(
        "app.core.audio.stt.stt_provider.transcribe",
        new_callable=AsyncMock,
    ) as mock_stt:
        mock_stt.return_value = {
            "text": "السلام عليكم، هل يمكنك تلخيص جدول اليوم؟",
            "duration": 4.5,
            "language": "ar",
        }

        # رفع ملف صوتي سليم
        files = {"file": ("audio_note.m4a", io.BytesIO(fake_audio_bytes), "audio/m4a")}
        resp = client.post(
            "/v1/audio/transcribe", data={"lang": "ar"}, files=files, headers=headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "السلام عليكم" in data["text"]
        assert data["language"] == "ar"
        assert data["duration"] == 4.5

        mock_stt.assert_awaited_once()

    # فحص رفض الملف الفارغ
    empty_files = {"file": ("empty.m4a", io.BytesIO(b""), "audio/m4a")}
    resp_empty = client.post("/v1/audio/transcribe", files=empty_files, headers=headers)
    assert resp_empty.status_code == 400


@pytest.mark.asyncio
async def test_office_document_generation_and_formula_defense(
    test_app: FastAPI, db_session: AsyncSession
) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Office Test Device",
        pubkey_pem="fake-pem",
        created_at=datetime.now(UTC).isoformat(),
    )
    session.add(device)
    await session.commit()

    # 1. اختبار تطهير حقن صيغ Excel (Formula Injection Sanitization - Section 11.8)
    assert sanitize_excel_cell("نص عادي") == "نص عادي"
    assert sanitize_excel_cell("=1+1") == "'=1+1"
    assert sanitize_excel_cell("+SUM(A1:A5)") == "'+SUM(A1:A5)"
    assert sanitize_excel_cell("-100") == "'-100"
    assert (
        sanitize_excel_cell("@HYPERLINK('http://malicious.com')")
        == "'@HYPERLINK('http://malicious.com')"
    )

    # 2. توليد مستند Word (.docx)
    tool = GenerateDocumentTool()
    ctx = {"session": session}

    doc_spec = DocSpec(
        title="تقرير الأداء الأسبوعي",
        sections=[
            DocSection(
                heading="الملخص التنفيذي",
                paragraphs=["تم إنجاز كافة المهام وفق الخطة الزمنية."],
                bullets=["المهمة الأولى: مكتملة", "المهمة الثانية: قيد المراجعة"],
                table=[["البند", "الحالة"], ["الخادم", "يعمل 100%"]],
            )
        ],
    )
    res_docx = await tool.run(
        GenerateDocumentArgs(kind="docx", spec=doc_spec.model_dump()),
        ctx,
    )
    assert res_docx["status"] == "ready"
    assert res_docx["filename"].endswith(".docx")
    assert res_docx["size_bytes"] > 0

    # 3. توليد جدول Excel (.xlsx)
    sheet_spec = WorkbookSpec(
        title="الميزانية",
        sheets=[
            SheetSpec(
                name="يناير",
                columns=["البند", "المبلغ"],
                rows=[["الاشتراكات", 1500], ["الخوادم", 800]],
                formulas=[{"cell": "B4", "formula": "=SUM(B2:B3)"}],
            )
        ],
    )
    res_xlsx = await tool.run(
        GenerateDocumentArgs(kind="xlsx", spec=sheet_spec.model_dump()),
        ctx,
    )
    assert res_xlsx["status"] == "ready"
    assert res_xlsx["filename"].endswith(".xlsx")
    await session.commit()

    # 4. التحقق من تنزيل الملف عبر نقطة النهاية GET /v1/files/{file_id}/download
    token, _ = mint_jwt_access_token(device_id)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(test_app)

    file_id = res_docx["file_id"]
    resp_dl = client.get(f"/v1/files/{file_id}/download", headers=headers)
    assert resp_dl.status_code == 200
    assert len(resp_dl.content) == res_docx["size_bytes"]

    # تنظيف الملفات المنشأة أثناء الاختبار
    for res_f in [res_docx, res_xlsx]:
        file_rec = (
            await session.execute(select(File).where(File.id == res_f["file_id"]))
        ).scalar_one()
        if os.path.exists(file_rec.path):
            os.remove(file_rec.path)


@pytest.mark.asyncio
async def test_reminders_and_scheduled_messages(db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Reminder Test Device",
        pubkey_pem="fake-pem",
        created_at=datetime.now(UTC).isoformat(),
    )
    session.add(device)

    # 1. اختبار جدولة تذكير داخلي
    rem_tool = ScheduleReminderTool()
    ctx = {"device_id": device_id, "session": session}
    now_past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

    rem_res = await rem_tool.run(
        ScheduleReminderArgs(
            title="شراء المستلزمات اليومية",
            remind_at=now_past,
            notes="حليب وخبز وعصير",
        ),
        ctx,
    )
    assert rem_res["status"] == "scheduled"
    job_id = rem_res["job_id"]

    # 2. اختبار جدولة رسالة رد مؤجلة مرتبطة بحدث
    event_id = f"evt_{secrets.token_hex(6)}"
    test_event = Event(
        id=event_id,
        device_id=device_id,
        source="notification",
        app_package="com.whatsapp",
        external_id=f"ext_{secrets.token_hex(6)}",
        thread_key="chat_123",
        sender_name="سعد",
        content="متى نلتقي؟",
        reply_capable=1,
        occurred_at=datetime.now(UTC).isoformat(),
        received_at=datetime.now(UTC).isoformat(),
    )
    session.add(test_event)
    await session.commit()

    msg_tool = ScheduleMessageTool()
    msg_res = await msg_tool.run(
        ScheduleMessageArgs(
            event_id=event_id,
            draft_text="نلتقي غداً في المساء إن شاء الله",
            run_at=now_past,
        ),
        ctx,
    )
    assert msg_res["status"] == "PENDING_APPROVAL"
    assert "action_id" in msg_res
    action_id = msg_res["action_id"]

    # محاكاة موافقة المستخدم على بطاقة الاعتماد
    action = (await session.execute(select(Action).where(Action.id == action_id))).scalar_one()
    action.status = "APPROVED"
    job_msg = (await session.execute(select(Job).where(Job.action_id == action_id))).scalar_one()
    job_msg.status = "approved"
    await session.commit()

    # 3. تشغيل معالج المهام المستحقة process_due_jobs
    processed = await process_due_jobs()
    assert processed >= 2

    # تحديث حالة كائنات الجلسة بعد تعديلها في قاعدة البيانات
    session.expire_all()

    # التحقق من إكمال التذكير
    updated_rem = (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()
    assert updated_rem.status == "completed"

    # التحقق من انتقال الإجراء المجدول لحالة EXECUTING
    updated_act = (await session.execute(select(Action).where(Action.id == action_id))).scalar_one()
    assert updated_act.status == "EXECUTING"


@pytest.mark.asyncio
async def test_calendar_and_email_tools(db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(6)}"
    device = Device(
        id=device_id,
        name="Integ Test Device",
        pubkey_pem="fake-pem",
        created_at=datetime.now(UTC).isoformat(),
    )
    session.add(device)
    await session.commit()

    ctx = {"device_id": device_id, "session": session}

    # 1. اختبار CalendarCreateTool (بلا مدعوين -> Tier 1 مباشر)
    now = datetime.now(UTC)
    cal_tool = CalendarCreateTool()
    res_cal_direct = await cal_tool.run(
        CalendarCreateArgs(
            title="اجتماع فريق التطوير",
            start_time=(now + timedelta(hours=2)).isoformat(),
            end_time=(now + timedelta(hours=3)).isoformat(),
        ),
        ctx,
    )
    assert res_cal_direct["status"] == "created"

    # 2. اختبار CalendarCreateTool (بمدعوين -> Tier 3 يتطلب اعتماداً بالبصمة)
    res_cal_hitl = await cal_tool.run(
        CalendarCreateArgs(
            title="مقابلة توظيف خارجية",
            start_time=(now + timedelta(days=1)).isoformat(),
            end_time=(now + timedelta(days=1, hours=1)).isoformat(),
            attendees=["candidate@example.com"],
        ),
        ctx,
    )
    assert res_cal_hitl["status"] == "PENDING_APPROVAL"
    assert res_cal_hitl["requires_biometric"] is True

    # 3. اختبار CalendarListTool (استرجاع المواعيد)
    list_tool = CalendarListTool()
    res_list = await list_tool.run(CalendarListArgs(days_ahead=3), ctx)
    assert res_list["count"] >= 1
    assert "<untrusted" in res_list["events"][0]["title"]

    # 4. اختبار GmailCreateDraftTool
    draft_tool = GmailCreateDraftTool()
    res_draft = await draft_tool.run(
        GmailCreateDraftArgs(
            recipient="manager@company.sa",
            subject="تقرير المبيعات",
            body="مرفق لكم تقرير المبيعات لهذا الشهر.",
        ),
        ctx,
    )
    assert res_draft["status"] == "draft_created"
    assert "draft_id" in res_draft

    # 5. اختبار GmailSendTool (يتطلب اعتماداً بشرياً + تحذير للمستلم غير المسجل)
    send_tool = GmailSendTool()
    res_send = await send_tool.run(
        GmailSendArgs(
            recipient="stranger@external.com",
            subject="استفسار تجاري",
            body="السلام عليكم، نود الاستفسار عن خدماتكم.",
        ),
        ctx,
    )
    assert res_send["status"] == "PENDING_APPROVAL"
    assert "action_id" in res_send

    # التحقق من وجود التحذير في بطاقة الاعتماد R-03-ج
    act = (
        await session.execute(select(Action).where(Action.id == res_send["action_id"]))
    ).scalar_one()
    assert act.status == "PENDING_APPROVAL"
    assert "stranger@external.com" in act.preview_json
