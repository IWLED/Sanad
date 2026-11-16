"""اختبارات الوحدة لاستيعاب الأحداث وأدوات صندوق الوارد ومزامنة جهات الاتصال (Phase 2)."""

import secrets
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contacts import router as contacts_router
from app.api.ingest import router as ingest_router
from app.api.policies import router as policies_router
from app.core.crypto import mint_jwt_access_token
from app.db.base import async_session_factory
from app.db.models import AppPolicy, Contact, ContactIdentifier, Device, Event
from app.tools.inbox import (
    GetEventArgs,
    GetEventTool,
    GetThreadArgs,
    GetThreadTool,
    SearchInboxArgs,
    SearchInboxTool,
)


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(ingest_router)
    app.include_router(contacts_router)
    app.include_router(policies_router)
    return app


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as sess:
        yield sess


@pytest.mark.asyncio
async def test_ingest_and_inbox_tools_flow(test_app: FastAPI, db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(8)}"
    device = Device(
        id=device_id,
        name="Test Phone",
        pubkey_pem="fake-pem",
        created_at="2026-11-16T12:00:00Z",
    )
    session.add(device)

    # سياسة تطبيق محظور
    blocked_app = AppPolicy(
        package=f"com.blocked.app_{secrets.token_hex(4)}",
        label="Blocked App",
        monitor=0,
        allow_reply=0,
        default_priority="low",
        sensitivity_floor="normal",
        updated_at="2026-11-16T12:00:00Z",
    )
    # سياسة تطبيق مسموح
    allowed_app = AppPolicy(
        package=f"com.whatsapp_{secrets.token_hex(4)}",
        label="WhatsApp",
        monitor=1,
        allow_reply=1,
        default_priority="normal",
        sensitivity_floor="normal",
        updated_at="2026-11-16T12:00:00Z",
    )
    session.add_all([blocked_app, allowed_app])
    await session.commit()

    token, _ = mint_jwt_access_token(device_id)
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(test_app)

    # 1. إرسال دفعة أحداث إلى /v1/ingest/events
    ext_id_1 = f"msg_{secrets.token_hex(6)}"
    ext_id_otp = f"msg_{secrets.token_hex(6)}"
    ext_id_blocked = f"msg_{secrets.token_hex(6)}"
    unique_keyword = f"كلمةفريدة{secrets.token_hex(3)}"
    sender_name_1 = f"سعد_{secrets.token_hex(4)}"

    events_payload: list[dict[str, Any]] = [
        {
            "source": "notification",
            "external_id": ext_id_1,
            "thread_key": f"chat_{secrets.token_hex(4)}",
            "app_package": allowed_app.package,
            "sender_name": sender_name_1,
            "content": f"السلام عليكم، هل موعد {unique_keyword} غداً بعد صلاة العصر؟",
            "reply_capable": True,
            "occurred_at": "2026-11-16T10:00:00Z",
        },
        {
            "source": "sms",
            "external_id": ext_id_otp,
            "thread_key": f"sms_{secrets.token_hex(4)}",
            "app_package": "com.android.mms",
            "sender_name": "AlRajhiBank",
            "content": "رمز التحقق OTP الخاص بك هو: 849201 لعملية الدخول.",
            "reply_capable": False,
            "occurred_at": "2026-11-16T10:05:00Z",
        },
        {
            "source": "notification",
            "external_id": ext_id_blocked,
            "thread_key": f"blocked_{secrets.token_hex(4)}",
            "app_package": blocked_app.package,
            "sender_name": "مجهول",
            "content": "إشعار من تطبيق محظور",
            "occurred_at": "2026-11-16T10:06:00Z",
        },
    ]

    resp = client.post("/v1/ingest/events", json=events_payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["created_count"] == 2  # WhatsApp + SMS
    assert data["duplicate_count"] == 0

    results = {r["external_id"]: r for r in data["results"]}
    assert results[ext_id_1]["status"] == "created"
    assert results[ext_id_otp]["status"] == "created"
    assert results[ext_id_blocked]["status"] == "rejected"
    assert results[ext_id_blocked]["reason"] == "app_package_blocked_by_policy"

    # التحقق من R-09: الـ OTP لم يتم تخزين محتواه في قاعدة البيانات
    otp_event_id = results[ext_id_otp]["event_id"]
    otp_db = (await session.execute(select(Event).where(Event.id == otp_event_id))).scalar_one()
    assert otp_db.content is None
    assert otp_db.sensitivity == "secret"

    # 2. اختبار كشف التكرار (Idempotency)
    resp_dup = client.post("/v1/ingest/events", json=events_payload, headers=headers)
    assert resp_dup.status_code == 200
    dup_data = resp_dup.json()
    assert dup_data["created_count"] == 0
    assert dup_data["duplicate_count"] == 2

    # 3. اختبار أداة البحث في الوارد search_inbox (بكلمة مع تطبيع عربي)
    search_tool = SearchInboxTool()
    search_res = await search_tool.run(SearchInboxArgs(query=unique_keyword), {})
    assert search_res["count"] >= 1
    found_item = search_res["results"][0]
    assert "<untrusted" in found_item["content"]
    assert sender_name_1 in found_item["sender"]

    # 4. اختبار أداة استرجاع سياق المحادثة get_thread
    thread_tool = GetThreadTool()
    th_key = str(events_payload[0]["thread_key"])
    thread_res = await thread_tool.run(GetThreadArgs(thread_key=th_key), {})
    assert thread_res["count"] == 1
    assert "السلام عليكم" in thread_res["messages"][0]["content"]

    # 5. اختبار أداة استرجاع تفاصيل حدث get_event
    event_tool = GetEventTool()
    event_res = await event_tool.run(GetEventArgs(event_id=results[ext_id_1]["event_id"]), {})
    assert event_res["found"] is True
    assert event_res["app"] == allowed_app.package
    assert event_res["reply_capable"] is True


@pytest.mark.asyncio
async def test_contacts_sync_and_policies_api(test_app: FastAPI, db_session: AsyncSession) -> None:
    session = db_session
    device_id = f"dev_{secrets.token_hex(8)}"
    device = Device(
        id=device_id,
        name="Test Phone 2",
        pubkey_pem="fake-pem",
        created_at="2026-11-16T12:00:00Z",
    )
    session.add(device)
    await session.commit()

    token, _ = mint_jwt_access_token(device_id)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(test_app)

    unique_name_1 = f"سعد_{secrets.token_hex(4)}"
    unique_name_2 = f"خالد_{secrets.token_hex(4)}"
    unique_phone_1 = f"050{secrets.randbelow(8999999) + 1000000}"
    unique_phone_2 = f"055{secrets.randbelow(8999999) + 1000000}"

    # 1. مزامنة جهات الاتصال POST /v1/contacts/sync
    contacts_payload = [
        {
            "raw_name": unique_name_1,
            "phones": [unique_phone_1],
            "aliases": ["أبو فهد"],
            "is_vip": True,
            "starred": False,
        },
        {
            "raw_name": unique_name_2,
            "phones": [unique_phone_2],
            "aliases": ["المدير"],
            "is_vip": False,
            "starred": True,
        },
    ]

    resp_contacts = client.post("/v1/contacts/sync", json=contacts_payload, headers=headers)
    assert resp_contacts.status_code == 200
    sync_data = resp_contacts.json()
    assert sync_data["synced_count"] == 2

    # التحقق من قاعدة البيانات
    stmt_c = select(Contact).where(Contact.display_name == unique_name_1)
    c1 = (await session.execute(stmt_c)).scalar_one()
    assert c1.priority == "high"

    # التحقق من المعرفات وتطبيع الهاتف إلى E.164
    stmt_i = select(ContactIdentifier).where(ContactIdentifier.contact_id == c1.id)
    idents = (await session.execute(stmt_i)).scalars().all()
    kinds = {i.kind: i.value_norm for i in idents}
    assert "phone" in kinds
    assert kinds["phone"].startswith("+96650")
    assert "alias" in kinds

    # 2. فحص وتحديث سياسات التطبيقات PUT/GET /v1/policies/apps
    policy_payload = {
        "package": f"com.telegram.messenger_{secrets.token_hex(4)}",
        "label": "Telegram",
        "monitor": True,
        "allow_reply": True,
        "default_priority": "normal",
        "sensitivity_floor": "normal",
    }
    put_resp = client.put("/v1/policies/apps", json=policy_payload, headers=headers)
    assert put_resp.status_code == 200

    get_resp = client.get("/v1/policies/apps", headers=headers)
    assert get_resp.status_code == 200
    apps = get_resp.json()
    tg_app = next((a for a in apps if a["package"] == policy_payload["package"]), None)
    assert tg_app is not None
    assert tg_app["monitor"] is True
