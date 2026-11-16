"""محرك توليد الملخصات الذكية والإيجاز الصباحي والمسائي (Section 11.1 & ADR-001)."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.safety.logging_filter import logger
from app.core.ws.connection_manager import connection_manager
from app.db.base import async_session_factory
from app.db.models import Briefing, Contact, Event


async def generate_briefing(
    kind: str = "morning",
    hours_lookback: int = 24,
    session: AsyncSession | None = None,
) -> Briefing:
    """توليد الإيجاز المجمع للأحداث والرسائل والمكالمات وتصنيفها حتمياً بالدرجة (Score)."""
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    cutoff = (now - timedelta(hours=hours_lookback)).isoformat()

    async def _generate(s: AsyncSession) -> Briefing:
        # 1. استرجاع الأحداث الحديثة
        stmt = (
            select(Event, Contact)
            .outerjoin(Contact, Event.sender_contact_id == Contact.id)
            .where(Event.occurred_at >= cutoff)
            .order_by(Event.occurred_at.desc())
        )
        res = await s.execute(stmt)
        rows = res.all()

        threads: dict[str, list[tuple[Event, Contact | None]]] = {}
        for ev, cnt in rows:
            th_key = ev.thread_key or ev.id
            threads.setdefault(th_key, []).append((ev, cnt))

        # 2. حساب الدرجات الحتمية (Deterministic Scoring - Section 11.1)
        scored_threads: list[dict[str, Any]] = []
        for th_key, items in threads.items():
            first_ev, contact = items[0]
            score = 0

            is_high_priority = contact and contact.priority == "high"
            is_family = contact and contact.relation in [
                "family",
                "أهل",
                "والد",
                "والدة",
                "أخ",
                "أخت",
            ]

            if is_high_priority:
                score += 100
            if first_ev.source == "missed_call":
                score += 50
                if is_high_priority:
                    score += 50
            if any(ev.reply_capable == 1 for ev, _ in items):
                score += 30
            if is_family:
                score += 25

            scored_threads.append(
                {
                    "thread_key": th_key,
                    "score": score,
                    "items": items,
                    "is_family": is_family,
                    "is_high_priority": is_high_priority,
                }
            )

        # الترتيب بالدرجة التنازلية
        scored_threads.sort(key=lambda x: int(x["score"]), reverse=True)

        # 3. توزيع البنود في الأقسام المحددة (Section 11.1)
        urgent_family = []
        needs_reply = []
        missed_calls = []
        info_items = []
        all_event_ids: list[str] = []

        for th in scored_threads:
            th_items: list[tuple[Event, Contact | None]] = th["items"]
            th_first_ev, _ = th_items[0]
            all_event_ids.extend([e.id for e, _ in th_items])

            sender_label = th_first_ev.sender_name or "جهة اتصال"
            summary_item = {
                "thread_key": th["thread_key"],
                "sender": sender_label,
                "app": th_first_ev.app_package or th_first_ev.source,
                "count": len(th_items),
                "latest_text": th_first_ev.content or "",
                "time": th_first_ev.occurred_at,
                "event_ids": [e.id for e, _ in th_items],
            }

            if th["is_family"] or (th["is_high_priority"] and th["score"] >= 100):
                urgent_family.append(summary_item)
            elif th_first_ev.source == "missed_call":
                missed_calls.append(summary_item)
            elif any(e.reply_capable == 1 for e, _ in th_items):
                needs_reply.append(summary_item)
            else:
                info_items.append(summary_item)

        # 4. بناء النص المقروء (Rendered Text)
        header_title = "🌅 الإيجاز الصباحي" if kind == "morning" else "🌙 ملخص المساء والأحداث"
        lines = [f"{header_title} ({now.strftime('%Y-%m-%d %H:%M')})\n"]

        if urgent_family:
            lines.append("⚡ عاجل والعائلة:")
            for item in urgent_family:
                lines.append(f"• {item['sender']} ({item['app']}): {item['latest_text']}")
            lines.append("")

        if missed_calls:
            lines.append("📞 مكالمات فائتة:")
            for item in missed_calls:
                lines.append(f"• {item['sender']}: {item['count']} مكالمة لم يُرد عليها")
            lines.append("")

        if needs_reply:
            lines.append("💬 رسائل بانتظار الرد:")
            for item in needs_reply:
                lines.append(f"• {item['sender']} ({item['app']}): {item['latest_text']}")
            lines.append("")

        if info_items:
            lines.append("ℹ️ رسائل ومعلومات أخرى:")
            for item in info_items[:5]:  # نكتفي بأهم 5 عناصر
                lines.append(f"• {item['sender']}: {item['latest_text']}")
            lines.append("")

        if not (urgent_family or missed_calls or needs_reply or info_items):
            lines.append("لا توجد أحداث أو رسائل معلقة جديدة. يومك هادئ وموفق!")

        rendered_text = "\n".join(lines).strip()

        # 5. حفظ الإيجاز في جدول briefings
        briefing_id = f"brf_{uuid.uuid4().hex[:16]}"
        briefing = Briefing(
            id=briefing_id,
            kind=kind,
            generated_at=now_iso,
            event_ids_json=json.dumps(all_event_ids, ensure_ascii=False),
            payload_json=json.dumps(
                {
                    "urgent_family": urgent_family,
                    "missed_calls": missed_calls,
                    "needs_reply": needs_reply,
                    "info_items": info_items,
                },
                ensure_ascii=False,
            ),
            rendered_text=rendered_text,
        )
        s.add(briefing)
        await s.commit()

        # 6. البث إلى الأجهزة المتصلة عبر WebSocket
        briefing_frame = {
            "v": 1,
            "type": "assistant_message",
            "id": f"msg_briefing_{briefing_id}",
            "payload": {
                "text": rendered_text,
                "tts_ok": True,
                "is_briefing": True,
                "briefing_id": briefing_id,
            },
        }
        await connection_manager.broadcast_json(briefing_frame)
        logger.info("briefing_generated_success", briefing_id=briefing_id, kind=kind)

        return briefing

    if session:
        return await _generate(session)

    async with async_session_factory() as sess:
        b = await _generate(sess)
        await sess.commit()
        return b
