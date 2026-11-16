"""اختبار أمني إلزامي للقاعدة R-12:

مفتاح الجهاز في Android Keystore؛ Refresh يدور مع كشف إعادة الاستخدام (يلغي الجهاز فوراً).
"""

import base64
import secrets
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.crypto import hash_with_pepper
from app.db.base import async_session_factory
from app.db.models import Device, PairingCode
from app.main import app


def generate_test_device_keypair() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """توليد مفتاح تجريبي يحاكي Android Keystore (EC P-256)."""
    priv_key = ec.generate_private_key(ec.SECP256R1())
    pub_pem = (
        priv_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return priv_key, pub_pem


def sign_refresh_payload(
    priv_key: ec.EllipticCurvePrivateKey, device_id: str, ts: str, nonce: str
) -> str:
    """توقيع device_id|ts|nonce بالمفتاح الخاص."""
    msg = f"{device_id}|{ts}|{nonce}".encode()
    sig = priv_key.sign(msg, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode("utf-8")


@pytest.mark.asyncio
async def test_R12_refresh_token_rotation_and_reuse_revocation() -> None:
    """التحقق من تدوير الرمز بنجاح، وإلغاء الجهاز بالكامل عند محاولة إعادة استخدام رمز قديم."""
    # 1. إنشاء رمز اقتران صالح في قاعدة البيانات
    test_code = f"PAIR_{secrets.token_hex(8).upper()}"
    code_hash = hash_with_pepper(test_code)
    now_iso = datetime.now(UTC).isoformat()
    expires_iso = datetime.fromtimestamp(datetime.now(UTC).timestamp() + 600, tz=UTC).isoformat()

    async with async_session_factory() as session:
        session.add(
            PairingCode(
                code_hash=code_hash,
                created_at=now_iso,
                expires_at=expires_iso,
            )
        )
        await session.commit()

    priv_key, pub_pem = generate_test_device_keypair()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 2. إتمام الاقتران الأولي
        pair_res = await client.post(
            "/v1/pair",
            json={
                "code": test_code,
                "device_name": "Pixel 9 Pro (Test)",
                "pubkey_pem": pub_pem,
                "android_sdk": 36,
                "app_version": "1.0.0",
            },
        )
        assert pair_res.status_code == 200
        pair_data = pair_res.json()
        device_id = pair_data["device_id"]
        old_refresh_token = pair_data["refresh_token"]

        # 3. التجديد الشرعي الأول (Rotation)
        ts1 = datetime.now(UTC).isoformat()
        nonce1 = secrets.token_hex(8)
        sig1 = sign_refresh_payload(priv_key, device_id, ts1, nonce1)

        ref_res1 = await client.post(
            "/v1/auth/refresh",
            json={
                "device_id": device_id,
                "refresh_token": old_refresh_token,
                "ts": ts1,
                "nonce": nonce1,
                "signature": sig1,
            },
        )
        assert ref_res1.status_code == 200
        ref_data1 = ref_res1.json()
        new_refresh_token = ref_data1["refresh_token"]
        assert new_refresh_token != old_refresh_token

        # 4. محاولة هجوم: إعادة استخدام old_refresh_token الذي تم استخدامه وتدويره سابقاً!
        ts2 = datetime.now(UTC).isoformat()
        nonce2 = secrets.token_hex(8)
        sig2 = sign_refresh_payload(priv_key, device_id, ts2, nonce2)

        reuse_res = await client.post(
            "/v1/auth/refresh",
            json={
                "device_id": device_id,
                "refresh_token": old_refresh_token,  # رمز معاد استخدامه
                "ts": ts2,
                "nonce": nonce2,
                "signature": sig2,
            },
        )
        # يجب رفض الطلب وإلغاء الجهاز
        assert reuse_res.status_code == 401
        assert "reuse detected" in reuse_res.json()["detail"].lower()

        # 5. التحقق في قاعدة البيانات أن الجهاز تم إلغاؤه (revoked_at IS NOT NULL)
        async with async_session_factory() as session:
            stmt = select(Device).where(Device.id == device_id)
            res = await session.execute(stmt)
            dev = res.scalar_one()
            assert dev.revoked_at is not None

        # 6. التأكد أن الجهاز الملغى لا يستطيع التجديد حتى بالرمز الأحدث!
        ts3 = datetime.now(UTC).isoformat()
        nonce3 = secrets.token_hex(8)
        sig3 = sign_refresh_payload(priv_key, device_id, ts3, nonce3)

        after_revocation_res = await client.post(
            "/v1/auth/refresh",
            json={
                "device_id": device_id,
                "refresh_token": new_refresh_token,
                "ts": ts3,
                "nonce": nonce3,
                "signature": sig3,
            },
        )
        assert after_revocation_res.status_code == 401
        assert "revoked" in after_revocation_res.json()["detail"].lower()
