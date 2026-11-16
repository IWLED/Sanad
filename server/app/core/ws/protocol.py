"""مخططات وبروتوكول رسائل WebSocket (Section 8.3, shared/protocol)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class WSEnvelope(BaseModel):
    """الغلاف الموحد لجميع رسائل WebSocket."""

    v: int = Field(default=1, description="إصدار البروتوكول")
    type: str = Field(..., description="نوع الرسالة")
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, description="معرف الرسالة الفريد")
    seq: int | None = Field(default=None, description="رقم التسلسل للرسائل الصادرة من الخادم")
    ts: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="الختم الزمني ISO-8601",
    )
    payload: dict[str, Any] = Field(default_factory=dict, description="حمولة الرسالة")


def make_envelope(
    msg_type: str,
    payload: dict[str, Any],
    seq: int | None = None,
    msg_id: str | None = None,
) -> dict[str, Any]:
    """توليد غلاف رسالة موحد ومتطابق مع المخطط."""
    env = WSEnvelope(
        type=msg_type,
        id=msg_id or uuid.uuid4().hex,
        seq=seq,
        payload=payload,
    )
    return env.model_dump()
