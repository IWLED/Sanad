"""واجهة سطر الأوامر (CLI) لإدارة الخادم والربط والأمان (Section 6, 8.1)."""

import argparse
import asyncio
import json
import secrets
from datetime import UTC, datetime

from sqlalchemy import update

from app.core.audit import append_audit_log, verify_audit_chain
from app.core.crypto import hash_with_pepper
from app.db.base import async_session_factory
from app.db.models import Action, Device, PairingCode, Setting


async def cli_pair_create(ttl_minutes: int, server_url: str) -> None:
    """توليد رمز اقتران مؤقت جديد وعرضه للمسح."""
    # رمز عشوائي 128 بت = 16 بايت (32 محرف hex)
    raw_code = secrets.token_hex(16).upper()
    code_hash = hash_with_pepper(raw_code)

    now = datetime.now(UTC)
    expires = datetime.fromtimestamp(now.timestamp() + ttl_minutes * 60, tz=UTC)

    async with async_session_factory() as session:
        pairing_entry = PairingCode(
            code_hash=code_hash,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
        )
        session.add(pairing_entry)
        await session.commit()

    payload = {
        "server_url": server_url,
        "code": raw_code,
        "expires_at": expires.isoformat(),
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    print("=" * 60)
    print("🔑 رمز اقتران جديد لمشروع سند (Sanad Device Pairing)")
    print("=" * 60)
    print(f"الرمز (Code): {raw_code}")
    print(f"الصلاحية: {ttl_minutes} دقائق (حتى {expires.strftime('%H:%M:%S UTC')})")
    print(f"رابط الخادم: {server_url}")
    print("-" * 60)
    print("الحمولة لربط التطبيق (QR Payload):")
    print(payload_json)
    print("=" * 60)


async def cli_audit_verify() -> None:
    """التحقق من سلامة وتسلسل سجل التدقيق R-16."""
    async with async_session_factory() as session:
        is_valid, msg = await verify_audit_chain(session)
        if is_valid:
            print(f"✅ سلامة السجل: {msg}")
        else:
            print(f"❌ خطر أمني: {msg}")
            raise SystemExit(1)


async def cli_emergency_kill() -> None:
    """إيقاف طارئ للوكيل وإلغاء صلاحيات التشغيل والأجهزة R-17."""
    now_iso = datetime.now(UTC).isoformat()
    async with async_session_factory() as session:
        # 1. تسجيل الإيقاف الطارئ في الإعدادات
        setting = Setting(
            key="agent_emergency_killed",
            value_json=json.dumps({"killed": True, "killed_at": now_iso}),
            updated_at=now_iso,
        )
        await session.merge(setting)

        # 2. إلغاء جميع الإجراءات المعلقة
        stmt_actions = (
            update(Action)
            .where(Action.status == "PENDING_APPROVAL")
            .values(status="CANCELLED", decided_at=now_iso)
        )
        await session.execute(stmt_actions)

        # 3. إلغاء تفعيل كافة الأجهزة المتصلة
        stmt_devices = (
            update(Device)
            .where(Device.revoked_at.is_(None))
            .values(revoked_at=now_iso)
        )
        await session.execute(stmt_devices)

        # 4. توثيق الحدث في سجل التدقيق
        await append_audit_log(
            session=session,
            actor="cli:admin",
            event="emergency_kill_triggered",
            details={"killed_at": now_iso},
        )
        await session.commit()
    print("🛑 تم تفعيل الإيقاف الطارئ بنجاح. تم تعليق تنفيذ الوكيل وإبطال العمليات والأجهزة.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sanad Secretary CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # أمر pair-create
    p_pair = subparsers.add_parser("pair-create", help="إنشاء رمز اقتران مؤقت جديد")
    p_pair.add_argument("--ttl", type=int, default=10, help="مدة الصلاحية بالدقائق (افتراضياً 10)")
    p_pair.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="رابط الخادم أو النفق (server_url)",
    )

    # أمر audit-verify
    subparsers.add_parser("audit-verify", help="فحص سلامة سلسلة سجل التدقيق R-16")

    # أمر kill
    subparsers.add_parser("kill", help="إيقاف طارئ للوكيل R-17")

    # أمر forget (R-21)
    p_forget = subparsers.add_parser("forget", help="حذف شامل لجهة اتصال وكافة أحداثها (R-21)")
    p_forget.add_argument("identifier", help="معرّف جهة الاتصال أو رقم الهاتف E.164")

    args = parser.parse_args()

    if args.command == "pair-create":
        asyncio.run(cli_pair_create(ttl_minutes=args.ttl, server_url=args.url))
    elif args.command == "audit-verify":
        asyncio.run(cli_audit_verify())
    elif args.command == "kill":
        asyncio.run(cli_emergency_kill())
    elif args.command == "forget":
        from app.workers.retention import forget_contact

        ok = asyncio.run(forget_contact(args.identifier))
        if ok:
            print(f"✅ تم حذف كافة السجلات والأحداث المرتبطة بـ '{args.identifier}' بنجاح.")
        else:
            print(f"❌ لم يتم العثور على جهة اتصال تطابق '{args.identifier}'.")


if __name__ == "__main__":
    main()
