"""محرك الاعتماد البشري (HITL Engine) وفرض القواعد الأمنية R-01..R-06 (Section 10.5)."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit_log
from app.core.hitl.preview import build_preview
from app.core.safety.dlp import dlp_scan
from app.core.ws.connection_manager import connection_manager
from app.db.models import Action
from app.tools.base import BaseTool


def canonical_json(data: Any) -> str:
    """تحويل البيانات إلى JSON معياري وثابت لحساب التجزئة (R-05)."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_args_hash(data: Any) -> str:
    """حساب تجزئة وسائط الأداة SHA-256 لربط الموافقة بها بدقة."""
    c_json = canonical_json(data)
    return hashlib.sha256(c_json.encode("utf-8")).hexdigest()


class HITLEngine:
    """المحرك المركزي لإدارة دورة حياة الإجراءات والموافقات البشرية."""

    @staticmethod
    async def create_action(
        session: AsyncSession,
        device_id: str,
        tool: BaseTool,
        args_dict: dict[str, Any],
        origin_event_ids: list[str] | None = None,
        session_tainted: bool = True,
        extra_warnings: list[str] | None = None,
        recipient_info: dict[str, Any] | None = None,
        thread_context: list[dict[str, Any]] | None = None,
    ) -> Action:
        """إنشاء إجراء جديد في حالة PENDING_APPROVAL وبناء المعاينة وإرسال البطاقة للجوال."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        # 1. حساب التجزئة الصارمة للوسائط R-05
        args_hash = compute_args_hash(args_dict)

        # 2. فحص تسريب البيانات DLP على النصوص
        raw_text = (
            args_dict.get("message")
            or args_dict.get("text")
            or args_dict.get("action_detail")
            or ""
        )
        _, clean_text, dlp_warnings = dlp_scan(raw_text)

        all_warnings = (extra_warnings or []) + dlp_warnings

        # 3. بناء المعاينة البرمجية R-04
        preview_data = build_preview(
            title=f"طلب موافقة: {tool.description[:40]}",
            draft_text=clean_text or raw_text,
            recipient=recipient_info,
            thread_context=thread_context,
            warnings=all_warnings,
        )

        # 4. تحديد الصلاحية (30 دقيقة للردود، 4 ساعات لغيرها)
        ttl_minutes = 30 if tool.executor == "device" else 240
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()

        action_id = f"act_{uuid.uuid4().hex[:16]}"
        idempotency_key = f"idem_{uuid.uuid4().hex[:16]}"

        action = Action(
            id=action_id,
            version=1,
            kind=tool.name,
            executor=tool.executor,
            risk_tier=tool.risk_tier,
            args_json=canonical_json(args_dict),
            args_hash=args_hash,
            preview_json=json.dumps(preview_data, ensure_ascii=False),
            origin_event_ids_json=json.dumps(origin_event_ids or []),
            tainted=1 if session_tainted else 0,
            warnings_json=json.dumps(all_warnings, ensure_ascii=False),
            status="PENDING_APPROVAL",
            idempotency_key=idempotency_key,
            created_at=now_iso,
            expires_at=expires_at,
        )
        session.add(action)
        await session.flush()

        # 5. تسجيل الحدث في سجل التدقيق R-16
        await append_audit_log(
            session=session,
            actor="agent",
            event="action_drafted_pending_approval",
            ref_id=action.id,
            details={"kind": action.kind, "risk_tier": action.risk_tier, "args_hash": args_hash},
        )

        # 6. دفع بطاقة action_request للجوال عبر WebSocket
        request_payload = {
            "action_id": action.id,
            "version": action.version,
            "kind": action.kind,
            "executor": action.executor,
            "risk_tier": action.risk_tier,
            "args_hash": action.args_hash,
            "expires_at": action.expires_at,
            "requires_biometric": (action.risk_tier == 3),
            "preview": preview_data,
        }
        await connection_manager.enqueue_and_send(
            session=session,
            device_id=device_id,
            msg_type="action_request",
            payload=request_payload,
        )

        await session.commit()
        return action

    @staticmethod
    async def process_decision(
        session: AsyncSession,
        device_id: str,
        action_id: str,
        version: int,
        args_hash: str,
        decision: str,  # APPROVE | REJECT
        edited_text: str | None = None,
        biometric_ok: bool = False,
    ) -> Action:
        """معالجة قرار المستخدم والتحقق الذري من الشروط وتنفيذ الإجراء (R-01..R-06)."""
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        # قفل واسترجاع الإجراء بشكل ذري
        stmt = select(Action).where(Action.id == action_id).with_for_update()
        result = await session.execute(stmt)
        action = result.scalar_one_or_none()

        if not action:
            raise ValueError(f"Action '{action_id}' not found")

        if action.status != "PENDING_APPROVAL":
            raise ValueError(f"Action is not pending approval (current status: {action.status})")

        if action.expires_at < now_iso:
            action.status = "EXPIRED"
            await session.commit()
            raise ValueError("Action approval expired (R-05)")

        if action.version != version:
            raise ValueError(f"Version mismatch: expected {action.version}, got {version} (R-05)")

        if action.args_hash != args_hash:
            raise ValueError(
                "Arguments hash mismatch: action content was modified without review (R-05)"
            )

        # شرط البصمة لأفعال المستوى الثالث T3 (R-12, D-8)
        if action.risk_tier == 3 and not biometric_ok:
            raise ValueError("Tier-3 actions strictly require biometric confirmation")

        # حالة الرفض الصريح
        if decision.upper() == "REJECT":
            action.status = "REJECTED"
            action.decided_at = now_iso
            action.decided_by_device = device_id
            await append_audit_log(
                session=session,
                actor=f"user:{device_id}",
                event="action_rejected",
                ref_id=action.id,
            )
            await session.commit()
            return action

        # حالة التعديل النصي: إلغاء القديم وإنشاء نسخة جديدة version+1 (R-05)
        if edited_text is not None and edited_text.strip() != "":
            action.status = "SUPERSEDED"
            old_args = json.loads(action.args_json)
            # تحديث حقل النص بالقيمة المعدلة
            if "message" in old_args:
                old_args["message"] = edited_text
            elif "text" in old_args:
                old_args["text"] = edited_text

            new_args_hash = compute_args_hash(old_args)
            new_id = f"act_{uuid.uuid4().hex[:16]}"
            new_idempotency = f"idem_{uuid.uuid4().hex[:16]}"

            new_action = Action(
                id=new_id,
                version=action.version + 1,
                supersedes_id=action.id,
                kind=action.kind,
                executor=action.executor,
                risk_tier=action.risk_tier,
                args_json=canonical_json(old_args),
                args_hash=new_args_hash,
                preview_json=action.preview_json,
                origin_event_ids_json=action.origin_event_ids_json,
                tainted=action.tainted,
                warnings_json=action.warnings_json,
                status="APPROVED",  # تعديل المستخدم يعد موافقة صريحة
                idempotency_key=new_idempotency,
                created_at=now_iso,
                expires_at=action.expires_at,
                decided_at=now_iso,
                decided_by_device=device_id,
            )
            session.add(new_action)
            await session.flush()
            target_action = new_action
        else:
            action.status = "APPROVED"
            action.decided_at = now_iso
            action.decided_by_device = device_id
            target_action = action

        # التنفيذ (Executor Dispatch) - القاعدة R-01: التنفيذ فقط بعد APPROVED
        await HITLEngine._dispatch_execution(session, device_id, target_action)
        await session.commit()
        return target_action

    @staticmethod
    async def _dispatch_execution(session: AsyncSession, device_id: str, action: Action) -> None:
        """إرسال أمر التنفيذ للجهاز أو تنفيذه محلياً على الخادم."""
        now_iso = datetime.now(UTC).isoformat()
        action.status = "EXECUTING"

        if action.executor == "device":
            # إرسال exec_command للجهاز
            exec_payload = {
                "action_id": action.id,
                "version": action.version,
                "kind": action.kind,
                "args": json.loads(action.args_json),
            }
            await connection_manager.enqueue_and_send(
                session=session,
                device_id=device_id,
                msg_type="exec_command",
                payload=exec_payload,
            )
            await append_audit_log(
                session=session,
                actor="server",
                event="exec_command_dispatched_to_device",
                ref_id=action.id,
            )
        else:
            # المنفذ على الخادم (للمرحلة 1: تجربة وهمية ناجحة)
            action.status = "EXECUTED"
            action.executed_at = now_iso
            action.result_json = json.dumps(
                {"ok": True, "detail": "Mock server execution succeeded"}
            )
            await append_audit_log(
                session=session,
                actor="server",
                event="server_action_executed",
                ref_id=action.id,
            )


hitl_engine = HITLEngine()
