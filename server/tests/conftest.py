"""إعدادات وتجهيز بيئة الاختبار لقاعدة البيانات وpytest."""

import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from sqlalchemy import text

from app.config import settings
from app.db.base import Base, engine

# ضمان وجود مجلد تصدير قابل للكتابة أثناء بيئة الاختبار والـ CI
test_exports_dir = Path(tempfile.gettempdir()) / "sanad_test_exports"
test_exports_dir.mkdir(parents=True, exist_ok=True)
settings.exports_dir = test_exports_dir

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
