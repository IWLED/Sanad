"""نقطة اقتران وربط جهاز أندرويد لأول مرة (POST /v1/pair)."""

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
)
from app.db.base import get_db_session
from app.db.models import Device, PairingCode, RefreshToken

router = APIRouter(prefix="/v1", tags=["pairing"])


class PairRequest(BaseModel):
    """بيانات طلب ربط الجهاز لأول مرة."""

    code: str = Field(..., min_length=8, description="رمز الاقتران المؤقت الممسوح من QR")
    device_name: str = Field(..., min_length=1, max_length=100, description="اسم الجهاز")
    pubkey_pem: str = Field(..., description="المفتاح العام EC P-256 المتولد داخل Android Keystore")
    fcm_token: str | None = Field(default=None, description="رمز تسجيل FCM")
    android_sdk: int | None = Field(default=None, description="مستوى إصدار أندرويد SDK")
    app_version: str | None = Field(default=None, description="إصدار التطبيق")


class PairResponse(BaseModel):
    """رد نجاح الاقتران ومفاتيح المصادقة."""

    device_id: str
    access_token: str
    refresh_token: str
    expires_in: int


@router.post("/pair", response_model=PairResponse, status_code=status.HTTP_200_OK)
async def pair_device(
    req: PairRequest,
    session: AsyncSession = Depends(get_db_session),
) -> PairResponse:
    """التحقق من رمز الاقتران وتوثيق المفتاح العام وإصدار رموز الجلسة (Section 8.1)."""
    now_iso = datetime.now(UTC).isoformat()

    # 1. فحص رمز الاقتران بدعم المرونة في الأحرف الكبيرة/الصغيرة والمسافات والشرطات
    clean_code = req.code.strip().replace(" ", "").replace("-", "")
    code_hash = hash_with_pepper(clean_code.upper())
    stmt = select(PairingCode).where(PairingCode.code_hash == code_hash)
    result = await session.execute(stmt)
    pairing_record = result.scalar_one_or_none()

    if not pairing_record:
        for alt in [req.code.strip(), clean_code.lower()]:
            alt_hash = hash_with_pepper(alt)
            alt_stmt = select(PairingCode).where(PairingCode.code_hash == alt_hash)
            alt_res = await session.execute(alt_stmt)
            alt_record = alt_res.scalar_one_or_none()
            if alt_record:
                pairing_record = alt_record
                break

    if not pairing_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pairing code",
        )

    if pairing_record.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pairing code has already been used",
        )

    if pairing_record.expires_at < now_iso:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pairing code has expired",
        )

    # وضع علامة الاستخدام الفوري (استخدام لمرة واحدة)
    pairing_record.used_at = now_iso

    # 2. إنشاء الجهاز الجديد
    device_id = f"dev_{uuid.uuid4().hex[:16]}"
    device = Device(
        id=device_id,
        name=req.device_name,
        pubkey_pem=req.pubkey_pem.strip(),
        fcm_token=req.fcm_token,
        app_version=req.app_version,
        android_sdk=req.android_sdk,
        created_at=now_iso,
        last_seen_at=now_iso,
    )
    session.add(device)

    # 3. توليد وتخزين رمز التحديث Refresh Token (30 يوماً)
    refresh_raw = generate_secure_token(32)
    refresh_hash = hash_with_pepper(refresh_raw)
    refresh_expires_at = datetime.now(UTC)
    # 30 days
    refresh_expires_iso = (
        datetime.fromtimestamp(refresh_expires_at.timestamp() + 30 * 86400, tz=UTC)
    ).isoformat()

    refresh_entry = RefreshToken(
        id=f"rt_{uuid.uuid4().hex[:16]}",
        device_id=device_id,
        token_hash=refresh_hash,
        issued_at=now_iso,
        expires_at=refresh_expires_iso,
    )
    session.add(refresh_entry)

    # 4. إصدار JWT Access Token (15 دقيقة)
    access_token, expires_in = mint_jwt_access_token(device_id=device_id)

    # 5. تسجيل الحدث في سجل التدقيق R-16
    await append_audit_log(
        session=session,
        actor=f"device:{device_id}",
        event="device_paired",
        ref_id=device_id,
        details={
            "device_name": req.device_name,
            "android_sdk": req.android_sdk,
            "app_version": req.app_version,
        },
    )

    await session.commit()

    return PairResponse(
        device_id=device_id,
        access_token=access_token,
        refresh_token=refresh_raw,
        expires_in=expires_in,
    )
