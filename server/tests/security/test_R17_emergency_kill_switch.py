"""اختبار أمني إلزامي للقاعدة R-17:

زر الإيقاف الفوري (Emergency Kill Switch).
إلغاء فوري لكافة الإجراءات المعلقة وإبطال الجلسات والأجهزة وتوثيق الحدث.
"""

import secrets
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.cli import cli_emergency_kill
from app.db.base import async_session_factory
from app.db.models import Action, AuditLog, Device, Setting


@pytest.mark.asyncio
async def test_R17_emergency_kill_switch() -> None:
    """التحقق من أن زر الطوارئ يبطل الأجهزة ويلغي الإجراءات المعلقة ويسجل في سجل التدقيق."""
    now_iso = datetime.now(UTC).isoformat()
    suffix = secrets.token_hex(8)
    device_id = f"dev_kill_{suffix}"
    action_id = f"act_kill_{suffix}"

    # تجهيز جهاز وإجراء معلق
    async with async_session_factory() as session:
        dev = Device(
            id=device_id,
            name="Kill Test Device",
            pubkey_pem="fake_pem",
            created_at=now_iso,
        )
        session.add(dev)

        act = Action(
            id=action_id,
            version=1,
            kind="mock_t2",
            executor="device",
            risk_tier=2,
            args_json="{}",
            args_hash="fake_hash",
            preview_json="{}",
            origin_event_ids_json="[]",
            warnings_json="[]",
            status="PENDING_APPROVAL",
            idempotency_key=f"idem_kill_{suffix}",
            created_at=now_iso,
            expires_at=now_iso,
        )
        session.add(act)
        await session.commit()

    # تشغيل أمر الإيقاف الطارئ
    await cli_emergency_kill()

    # التحقق من الآثار الأمنية
    async with async_session_factory() as session:
        # 1. إبطال الجهاز
        res_dev = await session.execute(select(Device).where(Device.id == device_id))
        dev_after = res_dev.scalar_one()
        assert dev_after.revoked_at is not None

        # 2. إلغاء الإجراء المعلق
        res_act = await session.execute(select(Action).where(Action.id == action_id))
        act_after = res_act.scalar_one()
        assert act_after.status == "CANCELLED"

        # 3. حفظ إعداد الإيقاف
        res_set = await session.execute(
            select(Setting).where(Setting.key == "agent_emergency_killed")
        )
        set_after = res_set.scalar_one_or_none()
        assert set_after is not None

        # 4. توثيق الحدث في سجل التدقيق
        res_audit = await session.execute(
            select(AuditLog).where(AuditLog.event == "emergency_kill_triggered")
        )
        audit_entries = res_audit.scalars().all()
        assert len(audit_entries) >= 1
