"""تهيئة قاعدة البيانات وإدارة الجلسات وضبط WAL والخيارات المتقدمة."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """الفئة الأساسية لجميع نماذج قاعدة البيانات."""

    pass


def ensure_db_dir_exists(url: str) -> None:
    """التأكد من وجود مجلد قاعدة البيانات تلقائياً."""
    if "sqlite" in url:
        clean_path = url.split(":///")[-1]
        if clean_path and clean_path != ":memory:":
            db_file = Path(clean_path)
            db_file.parent.mkdir(parents=True, exist_ok=True)


def create_engine_and_session(
    database_url: str | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """إنشاء المحرك وجلسات الاتصال غير المتزامنة مع تفعيل WAL وإعدادات SQLite الصارمة."""
    url = database_url or settings.database_url
    ensure_db_dir_exists(url)

    # إعداد المحرك
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
    )

    # تفعيل خيارات SQLite الإلزامية في Section 5.1 و 7.1
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    return engine, session_factory


engine, async_session_factory = create_engine_and_session()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """مزود جلسات قاعدة البيانات للـ FastAPI Dependencies."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
