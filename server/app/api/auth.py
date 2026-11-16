"""إدارة الجلسات وتجديد الرموز مع كشف إعادة الاستخدام وتدوير المفاتيح (R-12, Section 8.1)."""

import base64
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import append_audit_log
from app.core.crypto import (
    generate_secure_token,
    hash_with_pepper,
    mint_jwt_access_token,
    verify_device_signature,
)
from app.db.base import get_db_session
from app.db.models import Device, RefreshToken

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RefreshRequest(BaseModel):
    """بيانات طلب تجديد الجلسة وإثبات الحيازة."""

    device_id: str = Field(..., description="معرف الجهاز")
    refresh_token: str = Field(..., description="رمز التحديث الحالي")
    ts: str = Field(..., description="الختم الزمني للطلب ISO-8601")
    nonce: str = Field(..., min_length=8, description="قيمة عشوائية لمنع هجمات إعادة الإرسال")
    signature: str = Field(..., description="توقيع Keystore (Base64 أو Hex) على device_id|ts|nonce")


class RefreshResponse(BaseModel):
    """رموز الجلسة المجددة."""

    access_token: str
    refresh_token: str
    expires_in: int


def decode_signature(sig_str: str) -> bytes:
    """فك ترميز التوقيع سواء كان Base64 أو Hex."""
    try:
        return base64.b64decode(sig_str)
    except Exception:
        try:
            return bytes.fromhex(sig_str)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature encoding (expected Base64 or Hex)",
            ) from e


@router.post("/refresh", response_model=RefreshResponse, status_code=status.HTTP_200_OK)
async def refresh_tokens(
    req: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RefreshResponse:
    """تدوير رمز التحديث وإصدار JWT جديد مع التحقق من إثبات الحيازة وكشف إعادة الاستخدام (R-12)."""
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    # 1. التحقق من انحراف الوقت (Clock drift <= 300 ثانية)
    try:
        req_time = datetime.fromisoformat(req.ts)
        if abs((now - req_time).total_seconds()) > 300:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp expired or clock skew too large",
            )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid timestamp format",
        ) from e

    # 2. جلب الجهاز والتحقق من حالته
    stmt = select(Device).where(Device.id == req.device_id)
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found",
        )

    if device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device access has been revoked",
        )

    # 3. التحقق من توقيع المفتاح الخاص للجهاز (إثبات الحيازة Proof-of-Possession)
    expected_message = f"{req.device_id}|{req.ts}|{req.nonce}".encode()
    sig_bytes = decode_signature(req.signature)

    if not verify_device_signature(device.pubkey_pem, expected_message, sig_bytes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device signature",
        )

    # 4. فحص رمز التحديث
    token_hash = hash_with_pepper(req.refresh_token)
    stmt_rt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    res_rt = await session.execute(stmt_rt)
    token_entry = res_rt.scalar_one_or_none()

    if not token_entry:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # 5. كشف إعادة الاستخدام (Token Reuse Attack - R-12)
    if token_entry.used_at is not None:
        # هجوم محتمل: الرمز تم استخدامه سابقاً! نقوم بإلغاء الجهاز فوراً
        device.revoked_at = now_iso
        await append_audit_log(
            session=session,
            actor=f"device:{device.id}",
            event="security_alert_token_reuse_detected",
            ref_id=device.id,
            details={"attempted_token_id": token_entry.id},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Security violation: Refresh token reuse detected. Device revoked.",
        )

    if token_entry.expires_at < now_iso:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )

    # 6. تدوير الرمز (Rotation)
    new_token_id = f"rt_{uuid.uuid4().hex[:16]}"
    token_entry.used_at = now_iso
    token_entry.replaced_by = new_token_id

    new_refresh_raw = generate_secure_token(32)
    new_refresh_hash = hash_with_pepper(new_refresh_raw)
    new_expires_iso = datetime.fromtimestamp(now.timestamp() + 30 * 86400, tz=UTC).isoformat()

    new_token_entry = RefreshToken(
        id=new_token_id,
        device_id=device.id,
        token_hash=new_refresh_hash,
        issued_at=now_iso,
        expires_at=new_expires_iso,
    )
    session.add(new_token_entry)

    # 7. إصدار JWT Access Token جديد
    access_token, expires_in = mint_jwt_access_token(device_id=device.id)
    device.last_seen_at = now_iso

    await append_audit_log(
        session=session,
        actor=f"device:{device.id}",
        event="token_refreshed",
        ref_id=device.id,
        details={"new_token_id": new_token_id},
    )

    await session.commit()

    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_refresh_raw,
        expires_in=expires_in,
    )
