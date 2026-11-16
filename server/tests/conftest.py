"""إعدادات وتجهيز بيئة الاختبار لقاعدة البيانات وpytest."""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text

from app.db.base import Base, engine

CREATE_FTS5_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    content_norm,
    sender_norm,
    title_norm,
    content='',
    contentless_delete=1,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content_norm,
    content='',
    contentless_delete=1,
    tokenize='unicode61 remove_diacritics 2'
);
"""


@pytest.fixture(autouse=True)
async def setup_test_db() -> AsyncGenerator[None, None]:
    """التأكد من إنشاء كافة جداول قاعدة البيانات وجداول FTS5 قبل بدء تشغيل الاختبارات."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for statement in CREATE_FTS5_SQL.strip().split(";"):
            if statement.strip():
                await conn.execute(text(statement.strip()))
    yield
