"""نقطة ربط الرسائل الواردة من WebSocket مع حلقة الوكيل ومحرك HITL."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.agent.loop import agent_runner
from app.core.audit import append_audit_log
from app.core.hitl.engine import hitl_engine
from app.core.safety.logging_filter import logger
from app.core.ws.connection_manager import connection_manager
from app.core.ws.protocol import make_envelope
from app.db.base import async_session_factory
from app.db.models import Action


async def route_incoming_ws_message(
    device_id: str,
    msg_type: str,
    payload: dict[str, Any],
) -> None:
    """توجيه الرسائل الواردة من الجهاز إلى المكون المناسب (Section 8.3 & Section 10.3)."""
    if msg_type == "user_message":
        await _handle_user_message(device_id, payload)
    elif msg_type == "action_decision":
        await _handle_action_decision(device_id, payload)
    elif msg_type == "device_exec_result":
        await _handle_device_exec_result(device_id, payload)
    elif msg_type == "cancel":
        await _handle_cancel(device_id, payload)
    else:
        logger.warning("unhandled_ws_app_message", device_id=device_id, msg_type=msg_type)


async def _handle_user_message(device_id: str, payload: dict[str, Any]) -> None:
    """معالجة رسالة المستخدم النصية وتشغيل دورة الوكيل."""
    text = payload.get("text", "").strip()
    if not text:
        await connection_manager.send_json(
            device_id,
            make_envelope("error", {"code": "EMPTY_MESSAGE", "message": "Text cannot be empty"}),
        )
        return

    async with async_session_factory() as session:
        try:
            await agent_runner.run(
                device_id=device_id,
                user_message=text,
                session=session,
            )
        except Exception as e:
            logger.error("agent_run_failed", device_id=device_id, error=str(e))
            await connection_manager.send_json(
                device_id,
                make_envelope(
                    "error",
                    {"code": "AGENT_ERROR", "message": "حدث خطأ أثناء معالجة الطلب"},
                ),
            )


async def _handle_action_decision(device_id: str, payload: dict[str, Any]) -> None:
    """معالجة قرار المستخدم حول إجراء معلّق (APPROVE أو REJECT أو EDIT)."""
    action_id = payload.get("action_id")
    version = payload.get("version", 1)
    args_hash = payload.get("args_hash", "")
    decision = payload.get("decision", "REJECT")
    edited_text = payload.get("edited_text")
    biometric_ok = payload.get("biometric_ok", False)

    if not action_id or not args_hash:
        await connection_manager.send_json(
            device_id,
            make_envelope(
                "error",
                {"code": "INVALID_DECISION_PAYLOAD", "message": "Missing action_id or args_hash"},
            ),
        )
        return

    async with async_session_factory() as session:
        try:
            target_action = await hitl_engine.process_decision(
                session=session,
                device_id=device_id,
                action_id=action_id,
                version=version,
                args_hash=args_hash,
                decision=decision,
                edited_text=edited_text,
                biometric_ok=biometric_ok,
            )

            # إشعار الجهاز بتحديث حالة الإجراء
            await connection_manager.enqueue_and_send(
                session=session,
                device_id=device_id,
                msg_type="action_update",
                payload={
                    "action_id": target_action.id,
                    "version": target_action.version,
                    "status": target_action.status,
                },
            )
        except Exception as e:
            logger.warning("decision_processing_failed", action_id=action_id, error=str(e))
            await connection_manager.send_json(
                device_id,
                make_envelope(
                    "error",
                    {"code": "DECISION_FAILED", "message": str(e), "action_id": action_id},
                ),
            )


async def _handle_device_exec_result(device_id: str, payload: dict[str, Any]) -> None:
    """معالجة نتيجة تنفيذ الإجراء على الجهاز الجوال وتحديث الحالة وسجل التدقيق."""
    action_id = payload.get("action_id")
    status = payload.get("status", "FAILED")
    detail = payload.get("detail")
    fallback_used = payload.get("fallback_used", False)

    if not action_id:
        return

    now_iso = datetime.now(UTC).isoformat()
    async with async_session_factory() as session:
        stmt = select(Action).where(Action.id == action_id)
        res = await session.execute(stmt)
        action = res.scalar_one_or_none()
        if not action:
            logger.warning("exec_result_unknown_action", action_id=action_id)
            return

        if status in ("SENT_VERIFIED", "SENT_UNVERIFIED"):
            action.status = "EXECUTED"
        else:
            action.status = "FAILED"

        action.executed_at = now_iso
        action.result_json = json.dumps(
            {"status": status, "fallback_used": fallback_used, "detail": detail},
            ensure_ascii=False,
        )

        await append_audit_log(
            session=session,
            actor=f"device:{device_id}",
            event="device_exec_result_received",
            ref_id=action.id,
            details={"status": status, "fallback_used": fallback_used},
        )

        await connection_manager.enqueue_and_send(
            session=session,
            device_id=device_id,
            msg_type="action_update",
            payload={
                "action_id": action.id,
                "version": action.version,
                "status": action.status,
                "detail": detail,
            },
        )
        await session.commit()


async def _handle_cancel(device_id: str, payload: dict[str, Any]) -> None:
    """إلغاء إجراء قيد الانتظار أو جولة وكيل جارية."""
    action_id = payload.get("action_id")
    if not action_id:
        return

    now_iso = datetime.now(UTC).isoformat()
    async with async_session_factory() as session:
        stmt = select(Action).where(Action.id == action_id)
        res = await session.execute(stmt)
        action = res.scalar_one_or_none()
        if action and action.status == "PENDING_APPROVAL":
            action.status = "CANCELLED"
            action.decided_at = now_iso
            action.decided_by_device = device_id
            await append_audit_log(
                session=session,
                actor=f"user:{device_id}",
                event="action_cancelled_by_user",
                ref_id=action.id,
            )
            await connection_manager.enqueue_and_send(
                session=session,
                device_id=device_id,
                msg_type="action_update",
                payload={"action_id": action.id, "version": action.version, "status": "CANCELLED"},
            )
            await session.commit()
