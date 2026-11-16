"""مزامنة واسترجاع جهات الاتصال والمطابقة (Section 8.2 & Section 7.3)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_authenticated_device_id
from app.core.contacts.matcher import format_phone_e164
from app.core.text.normalize_ar import normalize_ar
from app.db.base import get_db_session
from app.db.models import Contact, ContactIdentifier

router = APIRouter(prefix="/v1/contacts", tags=["contacts"])


class ContactSyncItem(BaseModel):
    """عنصر جهة اتصال وارد للمزامنة."""

    raw_name: str = Field(..., description="الاسم الأصلي لجهة الاتصال")
    phones: list[str] = Field(default_factory=list, description="أرقام هواتف جهة الاتصال")
    aliases: list[str] = Field(default_factory=list, description="الألقاب والأسماء المستعارة")
    is_vip: bool = Field(default=False, description="هل جهة الاتصال VIP")
    starred: bool = Field(default=False, description="مفضلة")


class ContactSyncResponse(BaseModel):
    """نتيجة مزامنة جهات الاتصال."""

    synced_count: int
    updated_count: int


@router.post(
    "/sync",
    response_model=ContactSyncResponse,
    status_code=status.HTTP_200_OK,
    summary="مزامنة مجمعة لجهات الاتصال من الجوال (Section 8.2)",
)
async def sync_contacts(
    contacts: list[ContactSyncItem],
    device_id: str = Depends(get_authenticated_device_id),
    session: AsyncSession = Depends(get_db_session),
) -> ContactSyncResponse:
    """مزامنة وتطبيع جهات الاتصال وتحديث أرقام E.164 وأسمائها المعيارية ومعرفاتها."""
    now_iso = datetime.now(UTC).isoformat()
    synced_count = 0
    updated_count = 0

    for item in contacts:
        raw_name = item.raw_name.strip()
        if not raw_name:
            continue

        norm_name = normalize_ar(raw_name)

        # تطبيع الأرقام إلى E.164
        valid_phones: list[tuple[str, str]] = []
        for p in item.phones:
            formatted = format_phone_e164(p)
            if formatted:
                valid_phones.append((p, formatted))

        # البحث عن جهة اتصال مطابقة بالهاتف أو الاسم
        existing_contact_id: str | None = None
        for _, p_e164 in valid_phones:
            stmt = select(ContactIdentifier.contact_id).where(
                ContactIdentifier.kind == "phone",
                ContactIdentifier.value_norm == p_e164,
            )
            res = await session.execute(stmt)
            found_id = res.scalar_one_or_none()
            if found_id:
                existing_contact_id = found_id
                break

        if not existing_contact_id:
            stmt = select(ContactIdentifier.contact_id).where(
                ContactIdentifier.kind == "notif_name",
                ContactIdentifier.value_norm == norm_name,
            )
            res = await session.execute(stmt)
            existing_contact_id = res.scalar_one_or_none()

        if not existing_contact_id:
            stmt = select(Contact.id).where(Contact.display_name == raw_name)
            res = await session.execute(stmt)
            existing_contact_id = res.scalar_one_or_none()

        priority = "high" if (item.is_vip or item.starred) else "normal"

        if existing_contact_id:
            stmt_c = select(Contact).where(Contact.id == existing_contact_id)
            res_c = await session.execute(stmt_c)
            contact = res_c.scalar_one_or_none()
            if contact:
                contact.display_name = raw_name
                contact.priority = priority
                contact.updated_at = now_iso
                updated_count += 1
        else:
            contact_id = f"cnt_{uuid.uuid4().hex[:16]}"
            new_contact = Contact(
                id=contact_id,
                display_name=raw_name,
                priority=priority,
                created_at=now_iso,
                updated_at=now_iso,
            )
            session.add(new_contact)
            existing_contact_id = contact_id
            synced_count += 1

        # مسح المعرفات السابقة لجهة الاتصال لتجديدها
        await session.execute(
            delete(ContactIdentifier).where(ContactIdentifier.contact_id == existing_contact_id)
        )

        # إضافة المعرفات مع تفادي أي تصادم في القيد الفريد (kind, value_norm)
        identifiers_to_add: list[ContactIdentifier] = []
        seen_kinds_norms: set[tuple[str, str]] = set()

        # 1. اسم الإشعار المعياري
        if ("notif_name", norm_name) not in seen_kinds_norms:
            seen_kinds_norms.add(("notif_name", norm_name))
            await session.execute(
                delete(ContactIdentifier).where(
                    ContactIdentifier.kind == "notif_name",
                    ContactIdentifier.value_norm == norm_name,
                )
            )
            identifiers_to_add.append(
                ContactIdentifier(
                    contact_id=existing_contact_id,
                    kind="notif_name",
                    value_raw=raw_name,
                    value_norm=norm_name,
                )
            )

        # 2. الهواتف
        for raw_p, p_e164 in valid_phones:
            if ("phone", p_e164) not in seen_kinds_norms:
                seen_kinds_norms.add(("phone", p_e164))
                await session.execute(
                    delete(ContactIdentifier).where(
                        ContactIdentifier.kind == "phone",
                        ContactIdentifier.value_norm == p_e164,
                    )
                )
                identifiers_to_add.append(
                    ContactIdentifier(
                        contact_id=existing_contact_id,
                        kind="phone",
                        value_raw=raw_p,
                        value_norm=p_e164,
                    )
                )

        # 3. الألقاب
        for alias in item.aliases:
            alias_clean = alias.strip()
            if alias_clean:
                norm_alias = normalize_ar(alias_clean)
                if ("alias", norm_alias) not in seen_kinds_norms:
                    seen_kinds_norms.add(("alias", norm_alias))
                    await session.execute(
                        delete(ContactIdentifier).where(
                            ContactIdentifier.kind == "alias",
                            ContactIdentifier.value_norm == norm_alias,
                        )
                    )
                    identifiers_to_add.append(
                        ContactIdentifier(
                            contact_id=existing_contact_id,
                            kind="alias",
                            value_raw=alias_clean,
                            value_norm=norm_alias,
                        )
                    )

        session.add_all(identifiers_to_add)

    return ContactSyncResponse(
        synced_count=synced_count,
        updated_count=updated_count,
    )
