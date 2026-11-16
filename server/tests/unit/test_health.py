"""اختبارات نقاط النهاية healthz و readyz."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_healthz_endpoint() -> None:
    """التحقق من عمل نقطة healthz بنجاح وإرجاع 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "ts" in data


@pytest.mark.asyncio
async def test_readyz_endpoint() -> None:
    """التحقق من عمل نقطة readyz والاتصال بقاعدة البيانات وإرجاع 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
