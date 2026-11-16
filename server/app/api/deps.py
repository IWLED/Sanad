"""تبعيات FastAPI المشتركة (المصادقة واستخراج جلسة الجهاز)."""

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import verify_jwt_access_token
from app.db.base import get_db_session
from app.db.models import Device

security_bearer = HTTPBearer(auto_error=False)


async def get_current_device(
    credentials: HTTPAuthorizationCredentials | None = Security(security_bearer),
    session: AsyncSession = Depends(get_db_session),
) -> Device:
    """استخراج والتحقق من هوية الجهاز المرتبط عبر رمز JWT غير منتهي."""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        claims = verify_jwt_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    device_id = claims.get("device_id")
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing device identity",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stmt = select(Device).where(Device.id == device_id)
    result = await session.execute(stmt)
    device = result.scalar_one_or_none()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device access has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return device


async def get_authenticated_device_id(
    device: Device = Depends(get_current_device),
) -> str:
    """استرجاع معرف الجهاز الموثوق فقط."""
    return device.id
