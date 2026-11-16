"""إدارة الذاكرة طويلة الأمد وتخزين التفضيلات والبحث عبر FTS5 (Section 11.2 & R-03-د)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text.normalize_ar import normalize_ar
from app.db.base import async_session_factory
from app.db.models import Memory


async def remember(
    category: str,
    content: str,
    source: str = "user",
    session: AsyncSession | None = None,
) -> Memory:
    """حفظ حقيقة أو تفضيل في الذاكرة طويلة الأمد وفهرستها في FTS5."""
    now_iso = datetime.now(UTC).isoformat()
    norm_content = normalize_ar(content)
    mem_id = f"mem_{uuid.uuid4().hex[:16]}"

    async def _insert(s: AsyncSession) -> Memory:
        mem = Memory(
            id=mem_id,
            category=category,
            content=content,
            content_norm=norm_content,
            source=source,
            created_at=now_iso,
        )
        s.add(mem)
        await s.flush()

        res_rowid = await s.execute(
            text("SELECT rowid FROM memories WHERE id = :id"),
            {"id": mem_id},
        )
        rowid = res_rowid.scalar_one()

        await s.execute(
            text(
                """
                INSERT INTO memories_fts(rowid, content_norm)
                VALUES (:rowid, :content_norm)
                """
            ),
            {"rowid": rowid, "content_norm": norm_content},
        )
        return mem

    if session:
        return await _insert(session)

    async with async_session_factory() as sess:
        mem = await _insert(sess)
        await sess.commit()
        return mem


async def search_memories(
    query: str,
    limit: int = 5,
    session: AsyncSession | None = None,
) -> list[dict[str, str]]:
    """البحث في الذاكرة باستخدام الكلمات المفتاحية وفهرس FTS5."""
    norm_query = normalize_ar(query)
    if not norm_query:
        return []

    fts_query = " ".join([f'"{token}"*' for token in norm_query.split()])

    async def _search(s: AsyncSession) -> list[dict[str, str]]:
        sql = text(
            """
            SELECT m.id, m.category, m.content, m.created_at
            FROM memories_fts f
            JOIN memories m ON m.rowid = f.rowid
            WHERE memories_fts MATCH :q
            ORDER BY m.created_at DESC
            LIMIT :limit
            """
        )
        res = await s.execute(sql, {"q": fts_query, "limit": limit})
        rows = res.fetchall()
        return [
            {
                "id": r.id,
                "category": r.category,
                "content": r.content,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    if session:
        return await _search(session)

    async with async_session_factory() as sess:
        return await _search(sess)


async def forget_memory(
    memory_id: str,
    session: AsyncSession | None = None,
) -> bool:
    """حذف عنصر من الذاكرة وحذف فهرسته استجابة لأمر النسيان R-21."""

    async def _forget(s: AsyncSession) -> bool:
        res_rowid = await s.execute(
            text("SELECT rowid FROM memories WHERE id = :id"),
            {"id": memory_id},
        )
        rowid = res_rowid.scalar_one_or_none()
        if not rowid:
            return False

        await s.execute(
            text("DELETE FROM memories_fts WHERE rowid = :rowid"),
            {"rowid": rowid},
        )
        await s.execute(delete(Memory).where(Memory.id == memory_id))
        return True

    if session:
        return await _forget(session)

    async with async_session_factory() as sess:
        deleted = await _forget(sess)
        await sess.commit()
        return deleted


async def get_memories_by_category(
    category: str,
    limit: int = 10,
    session: AsyncSession | None = None,
) -> list[Memory]:
    """استرجاع الذكريات حسب الفئة (preference, fact, project, style, person)."""

    async def _get(s: AsyncSession) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.category == category)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        res = await s.execute(stmt)
        return list(res.scalars().all())

    if session:
        return await _get(session)

    async with async_session_factory() as sess:
        return await _get(sess)
