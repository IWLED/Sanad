"""العمليات المشفرة: إدارة المفاتيح، توقيع والتحقق من JWT، والتجزئة بملح (Pepper)."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import settings

# إذا لم يُحدد مفتاح توقيع JWT، يتم توليد زوج مفاتيح EC P-256 محلي في الذاكرة
_LOCAL_PRIVATE_KEY: ec.EllipticCurvePrivateKey | None = None


def get_jwt_private_key() -> ec.EllipticCurvePrivateKey:
    """الحصول على المفتاح الخاص لتوقيع JWT (من الإعدادات أو مولد محلي)."""
    global _LOCAL_PRIVATE_KEY
    key_pem = settings.get_jwt_signing_key()
    if key_pem:
        loaded = serialization.load_pem_private_key(key_pem.encode("utf-8"), password=None)
        if isinstance(loaded, ec.EllipticCurvePrivateKey):
            return loaded
        raise ValueError("JWT_SIGNING_KEY must be an EC P-256 private key")

    if _LOCAL_PRIVATE_KEY is None:
        _LOCAL_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
    return _LOCAL_PRIVATE_KEY


def get_jwt_public_key() -> ec.EllipticCurvePublicKey:
    """الحصول على المفتاح العام للتحقق من توقيع JWT."""
    return get_jwt_private_key().public_key()


def generate_secure_token(nbytes: int = 32) -> str:
    """توليد رمز عشوائي مشفر وآمن (Hex string)."""
    return secrets.token_hex(nbytes)


def hash_with_pepper(token: str, pepper: str | None = None) -> str:
    """تجزئة الرمز عبر SHA-256 مع الملح السري (R-15)."""
    p = pepper if pepper is not None else settings.get_pepper()
    payload = f"{token}:{p}".encode()
    return hashlib.sha256(payload).hexdigest()


def mint_jwt_access_token(
    device_id: str,
    ttl_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, int]:
    """إصدار رمز وصول JWT مشفر بـ ES256 (مدة الصلاحية الافتراضية 15 دقيقة)."""
    ttl = ttl_minutes or settings.access_token_ttl_min
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=ttl)
    expires_in_seconds = int((exp - now).total_seconds())

    claims: dict[str, Any] = {
        "sub": device_id,
        "device_id": device_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": "sanad-server",
    }
    if extra_claims:
        claims.update(extra_claims)

    priv_key = get_jwt_private_key()
    token = jwt.encode(claims, priv_key, algorithm="ES256")
    return token, expires_in_seconds


def verify_jwt_access_token(token: str) -> dict[str, Any]:
    """التحقق من صحة وصلاحية رمز الوصول JWT."""
    pub_key = get_jwt_public_key()
    try:
        decoded = jwt.decode(
            token,
            pub_key,
            algorithms=["ES256"],
            issuer="sanad-server",
        )
        return decoded
    except jwt.PyJWTError as e:
        raise ValueError(f"Invalid JWT: {e}") from e


def verify_device_signature(pubkey_pem: str, message: bytes, signature_bytes: bytes) -> bool:
    """التحقق من توقيع جهاز الأندرويد بمفتاحه العام في Android Keystore (EC P-256)."""
    try:
        pub_key = serialization.load_pem_public_key(pubkey_pem.encode("utf-8"))
        if not isinstance(pub_key, ec.EllipticCurvePublicKey):
            return False

        pub_key.verify(signature_bytes, message, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, Exception):
        return False
