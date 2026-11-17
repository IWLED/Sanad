"""نقطة اتصال WebSocket للمحادثة والاستئناف والإشعارات الفورية (/v1/ws)."""

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select, update

from app.core.crypto import verify_jwt_access_token
from app.core.safety.logging_filter import logger
from app.core.ws.connection_manager import connection_manager
from app.core.ws.protocol import make_envelope
from app.db.base import async_session_factory
from app.db.models import Device, OutboundMessage

router = APIRouter(prefix="/v1", tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="رمز JWT الخاص بالجهاز المرتبط"),
) -> None:
    """قناة الاتصال الثنائي المستمر بين التطبيق والخادم (Section 8.3)."""
    # 1. المصادقة والتحقق من هوية الجهاز قبل قبول الاتصال
    try:
        claims = verify_jwt_access_token(token)
        device_id = claims.get("device_id")
        if not device_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing device_id")
            return
    except Exception as e:
        logger.warning("ws_auth_rejected", error=str(e))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    # 2. التحقق من أن الجهاز لم يُلغَ
    async with async_session_factory() as session:
        stmt = select(Device).where(Device.id == device_id)
        res = await session.execute(stmt)
        device = res.scalar_one_or_none()
        if not device or device.revoked_at is not None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Device revoked")
            return

    # 3. قبول الاتصال وتسجيله في مدير الاتصالات
    await connection_manager.connect(device_id, websocket)

    try:
        while True:
            raw_text = await websocket.receive_text()
            try:
                frame = json.loads(raw_text)
            except Exception:
                await connection_manager.send_json(
                    device_id,
                    make_envelope("error", {"message": "Invalid JSON frame"}),
                )
                continue

            msg_type = frame.get("type")
            payload = frame.get("payload", {})

            # معالجة رسائل التحكم
            if msg_type == "hello":
                await handle_hello(device_id, payload)
            elif msg_type == "ping":
                await connection_manager.send_json(
                    device_id,
                    make_envelope("pong", {"server_time": datetime.now(UTC).isoformat()}),
                )
            elif msg_type == "ack":
                await handle_ack(device_id, payload)
            elif msg_type in ("user_message", "action_decision", "device_exec_result", "cancel"):
                # سيتم معالجتها عبر حلقة الوكيل ومحرك HITL
                await handle_app_message(device_id, msg_type, payload)
            else:
                logger.warning("unknown_ws_message_type", msg_type=msg_type, device_id=device_id)

    except WebSocketDisconnect:
        connection_manager.disconnect(device_id, websocket)
    except Exception as e:
        logger.error("ws_loop_error", device_id=device_id, error=str(e))
        connection_manager.disconnect(device_id, websocket)


async def handle_hello(device_id: str, payload: dict[str, Any]) -> None:
    """معالجة إطار hello واستئناف الرسائل الفائتة منذ last_seq (Section 8.3)."""
    last_seq = payload.get("last_seq", 0)

    async with async_session_factory() as session:
        stmt = (
            select(OutboundMessage)
            .where(
                OutboundMessage.device_id == device_id,
                OutboundMessage.seq > last_seq,
            )
            .order_by(OutboundMessage.seq.asc())
        )
        res = await session.execute(stmt)
        missed_messages = res.scalars().all()

        # إذا كانت الفجوة ضخمة جداً (> 500) نطلب إعادة المزامنة الشاملة
        if len(missed_messages) > 500:
            await connection_manager.send_json(
                device_id,
                make_envelope("resync_required", {"since_seq": last_seq}),
            )
            return

        # إرسال إطار الترحيب
        welcome_env = make_envelope(
            "welcome",
            {
                "server_time": datetime.now(UTC).isoformat(),
                "resume": "ok",
                "missed_count": len(missed_messages),
            },
        )
        await connection_manager.send_json(device_id, welcome_env)

        # إعادة إرسال الرسائل الفائتة بالترتيب
        for msg in missed_messages:
            env = make_envelope(
                msg_type=msg.type,
                payload=json.loads(msg.payload_json),
                seq=msg.seq,
            )
            await connection_manager.send_json(device_id, env)
            msg.delivered_at = datetime.now(UTC).isoformat()

        if missed_messages:
            await session.commit()


async def handle_ack(device_id: str, payload: dict[str, Any]) -> None:
    """تأكيد تسلم الجهاز للرسائل الصادرة وتحديث acked_at."""
    acked_seq = payload.get("seq")
    if not isinstance(acked_seq, int):
        return

    now_iso = datetime.now(UTC).isoformat()
    async with async_session_factory() as session:
        stmt = (
            update(OutboundMessage)
            .where(
                OutboundMessage.device_id == device_id,
                OutboundMessage.seq <= acked_seq,
                OutboundMessage.acked_at.is_(None),
            )
            .values(acked_at=now_iso)
        )
        await session.execute(stmt)
        await session.commit()


async def handle_app_message(device_id: str, msg_type: str, payload: dict[str, Any]) -> None:
    """نقطة ربط رسائل التطبيق مع حلقة الوكيل ومحرك HITL."""
    from app.core.agent.dispatcher_hook import route_incoming_ws_message

    await route_incoming_ws_message(device_id, msg_type, payload)
