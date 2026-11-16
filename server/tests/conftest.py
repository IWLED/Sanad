"""إعدادات وتجهيز بيئة الاختبار لقاعدة البيانات وpytest."""

from collections.abc import AsyncGenerator

import pytest

from app.db.base import Base, engine


@pytest.fixture(autouse=True, scope="session")
async def setup_test_db() -> AsyncGenerator[None, None]:
    """التأكد من إنشاء كافة جداول قاعدة البيانات قبل بدء تشغيل الاختبارات."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
