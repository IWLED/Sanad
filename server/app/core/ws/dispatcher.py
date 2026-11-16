"""مرسل الرسائل الصادرة (Dispatcher) لقراءة طابور outbound_messages ودفعها (Section 11.3)."""

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.safety.logging_filter import logger
from app.core.ws.connection_manager import connection_manager
from app.core.ws.protocol import make_envelope
from app.db.base import async_session_factory
from app.db.models import OutboundMessage


class OutboundDispatcher:
    """مهمة خلفية تدور كل 500ms لدفع الرسائل غير المؤكدة للأجهزة المتصلة."""

    def __init__(self, interval_seconds: float = 0.5) -> None:
        self.interval = interval_seconds
        self.running = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("outbound_dispatcher_started")

    def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            logger.info("outbound_dispatcher_stopped")

    async def _run_loop(self) -> None:
        while self.running:
            try:
                await self.dispatch_pending()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("dispatcher_cycle_error", error=str(e))
            await asyncio.sleep(self.interval)

    async def dispatch_pending(self) -> int:
        """جلب وإرسال الرسائل المعلقة للأجهزة المتصلة حالياً."""
        count = 0
        async with async_session_factory() as session:
            stmt = (
                select(OutboundMessage)
                .where(OutboundMessage.delivered_at.is_(None))
                .order_by(OutboundMessage.seq.asc())
                .limit(50)
            )
            result = await session.execute(stmt)
            pending_messages = result.scalars().all()

            for msg in pending_messages:
                if connection_manager.is_connected(msg.device_id):
                    payload = json.loads(msg.payload_json)
                    env = make_envelope(
                        msg_type=msg.type,
                        payload=payload,
                        seq=msg.seq,
                    )
                    sent = await connection_manager.send_json(msg.device_id, env)
                    if sent:
                        msg.delivered_at = datetime.now(UTC).isoformat()
                        count += 1

            if count > 0:
                await session.commit()

        return count


dispatcher = OutboundDispatcher()
