"""مدير اتصالات WebSocket النشطة ودعم استئناف الجلسات وإرسال الرسائل."""

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safety.logging_filter import logger
from app.core.ws.protocol import make_envelope
from app.db.models import OutboundMessage


class ConnectionManager:
    """إدارة اتصال WebSocket النشط للجهاز المفرد."""

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, device_id: str) -> asyncio.Lock:
        if device_id not in self.locks:
            self.locks[device_id] = asyncio.Lock()
        return self.locks[device_id]

    async def connect(self, device_id: str, websocket: WebSocket) -> None:
        """تسجيل اتصال جهاز جديد وإغلاق أي اتصال قديم لنفس الجهاز."""
        await websocket.accept()
        old_ws = self.active_connections.get(device_id)
        if old_ws:
            with contextlib.suppress(Exception):
                await old_ws.close(code=1000, reason="New connection opened")
        self.active_connections[device_id] = websocket
        logger.info("device_ws_connected", device_id=device_id)

    def disconnect(self, device_id: str, websocket: WebSocket) -> None:
        """إزالة الاتصال عند إغلاقه."""
        if self.active_connections.get(device_id) == websocket:
            del self.active_connections[device_id]
            logger.info("device_ws_disconnected", device_id=device_id)

    def is_connected(self, device_id: str) -> bool:
        """هل الجهاز متصل حالياً عبر WebSocket؟"""
        return device_id in self.active_connections

    async def send_json(self, device_id: str, data: dict[str, Any]) -> bool:
        """إرسال حمولة JSON للجهاز المتصل بشكل آمن ومتزامن."""
        ws = self.active_connections.get(device_id)
        if not ws:
            return False

        lock = self._get_lock(device_id)
        async with lock:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
                return True
            except Exception as e:
                logger.error("ws_send_failed", device_id=device_id, error=str(e))
                return False

    async def enqueue_and_send(
        self,
        session: AsyncSession,
        device_id: str,
        msg_type: str,
        payload: dict[str, Any],
    ) -> OutboundMessage:
        """إضافة رسالة إلى outbound_messages وإرسالها فوراً إن كان الجهاز متصلاً."""
        now_iso = datetime.now(UTC).isoformat()
        outbound = OutboundMessage(
            device_id=device_id,
            type=msg_type,
            payload_json=json.dumps(payload, ensure_ascii=False),
            created_at=now_iso,
        )
        session.add(outbound)
        await session.flush()  # للحصول على seq

        envelope = make_envelope(
            msg_type=msg_type,
            payload=payload,
            seq=outbound.seq,
        )

        sent = await self.send_json(device_id, envelope)
        if sent:
            outbound.delivered_at = datetime.now(UTC).isoformat()
            await session.commit()

        return outbound


connection_manager = ConnectionManager()
