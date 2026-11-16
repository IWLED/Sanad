"""اختبارات الوحدة للاقتران والمصادقة وحالات الخطأ."""

import secrets

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from httpx import ASGITransport, AsyncClient

from app.core.crypto import (
    hash_with_pepper,
    mint_jwt_access_token,
    verify_jwt_access_token,
)
from app.db.base import async_session_factory
from app.db.models import PairingCode
from app.main import app


def get_dummy_ec_pubkey() -> str:
    priv = ec.generate_private_key(ec.SECP256R1())
    return (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


@pytest.mark.asyncio
async def test_invalid_pairing_code() -> None:
    """التحقق من رفض رموز الاقتران غير الموجودة أو منتهية الصلاحية."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # رمز غير موجود
        res = await client.post(
            "/v1/pair",
            json={
                "code": "NON_EXISTENT_CODE",
                "device_name": "Test Device",
                "pubkey_pem": get_dummy_ec_pubkey(),
            },
        )
        assert res.status_code == 400
        assert "Invalid pairing code" in res.json()["detail"]


@pytest.mark.asyncio
async def test_expired_pairing_code() -> None:
    """التحقق من رفض رمز الاقتران المنتهي."""
    code = f"EXPIRED_{secrets.token_hex(8)}"
    code_hash = hash_with_pepper(code)
    past_iso = "2020-01-01T00:00:00+00:00"

    async with async_session_factory() as session:
        session.add(
            PairingCode(
                code_hash=code_hash,
                created_at=past_iso,
                expires_at=past_iso,
            )
        )
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/v1/pair",
            json={
                "code": code,
                "device_name": "Test Device",
                "pubkey_pem": get_dummy_ec_pubkey(),
            },
        )
        assert res.status_code == 400
        assert "expired" in res.json()["detail"].lower()


def test_jwt_mint_and_verify() -> None:
    """التحقق من سلامة إصدار وتفكيك وفحص صلاحية JWT."""
    token, expires_in = mint_jwt_access_token("dev_123", ttl_minutes=15)
    assert expires_in == 900
    claims = verify_jwt_access_token(token)
    assert claims["device_id"] == "dev_123"
    assert claims["sub"] == "dev_123"

    with pytest.raises(ValueError):
        verify_jwt_access_token("corrupted.token.value")
