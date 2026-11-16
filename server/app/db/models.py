"""نماذج قاعدة البيانات المطابقة لمواصفات DDL في Section 7.1."""

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Device(Base):
    """الأجهزة الموثوقة المرتبطة بالنظام (Section 7.1)."""

    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    pubkey_pem: Mapped[str] = mapped_column(Text, nullable=False)
    fcm_token: Mapped[str | None] = mapped_column(String, nullable=True)
    app_version: Mapped[str | None] = mapped_column(String, nullable=True)
    android_sdk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    """رموز التحديث Refresh Tokens مع التدوير وكشف إعادة الاستخدام (ADR-006, R-12)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    issued_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    used_at: Mapped[str | None] = mapped_column(String, nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(String, nullable=True)

    device: Mapped["Device"] = relationship(back_populates="refresh_tokens")


class PairingCode(Base):
    """رموز الاقتران المؤقتة للربط عبر QR (Section 8.1)."""

    __tablename__ = "pairing_codes"

    code_hash: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    used_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Contact(Base):
    """جهات الاتصال المزامنة والمخصصة (Section 7.1)."""

    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    relation: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[str] = mapped_column(
        String,
        CheckConstraint("priority IN ('high','normal','low')"),
        default="normal",
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    identifiers: Mapped[list["ContactIdentifier"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan"
    )


class ContactIdentifier(Base):
    """معرفات جهة الاتصال (أرقام، ألقاب، إيميلات، أسماء إشعارات)."""

    __tablename__ = "contact_identifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[str] = mapped_column(
        String, ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(
        String,
        CheckConstraint("kind IN ('phone','email','telegram','alias','notif_name')"),
        nullable=False,
    )
    value_raw: Mapped[str] = mapped_column(String, nullable=False)
    value_norm: Mapped[str] = mapped_column(String, nullable=False)

    contact: Mapped["Contact"] = relationship(back_populates="identifiers")

    __table_args__ = (UniqueConstraint("kind", "value_norm", name="uq_contact_ident_kind_val"),)


class AppPolicy(Base):
    """سياسات التطبيقات المراقبة وقواعد الرد والحساسية (R-10)."""

    __tablename__ = "app_policies"

    package: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    monitor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    allow_reply: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    default_priority: Mapped[str] = mapped_column(String, default="normal", nullable=False)
    sensitivity_floor: Mapped[str] = mapped_column(String, default="normal", nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class Event(Base):
    """صندوق الوارد الموحد للأحداث والإشعارات والمكالمات والبريد."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    device_id: Mapped[str | None] = mapped_column(String, ForeignKey("devices.id"), nullable=True)
    source: Mapped[str] = mapped_column(
        String,
        CheckConstraint("source IN ('missed_call','call','sms','notification','email','calendar')"),
        nullable=False,
    )
    app_package: Mapped[str | None] = mapped_column(String, nullable=True)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    thread_key: Mapped[str] = mapped_column(String, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sender_contact_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("contacts.id"), nullable=True
    )
    is_group: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    context_title: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_norm: Mapped[str | None] = mapped_column(Text, nullable=True)
    sensitivity: Mapped[str] = mapped_column(
        String,
        CheckConstraint("sensitivity IN ('normal','sensitive','secret')"),
        default="normal",
        nullable=False,
    )
    media_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    reply_capable: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reply_expires_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[str] = mapped_column(String, nullable=False)
    briefed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    briefing_id: Mapped[str | None] = mapped_column(String, nullable=True)
    handled_at: Mapped[str | None] = mapped_column(String, nullable=True)
    dismissed_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_events_src_ext_id"),
        Index("idx_events_unbriefed", "briefed_at", "dismissed_at", "received_at"),
        Index("idx_events_thread", "thread_key", "occurred_at"),
    )


class Action(Base):
    """إجراءات محرك الاعتماد البشري (HITL) وقواعد الأمان R-01..R-06."""

    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    executor: Mapped[str] = mapped_column(
        String, CheckConstraint("executor IN ('device','server')"), nullable=False
    )
    risk_tier: Mapped[int] = mapped_column(
        Integer, CheckConstraint("risk_tier IN (1,2,3)"), nullable=False
    )
    args_json: Mapped[str] = mapped_column(Text, nullable=False)
    args_hash: Mapped[str] = mapped_column(String, nullable=False)
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    origin_event_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    tainted: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        CheckConstraint(
            "status IN ('DRAFTED','PENDING_APPROVAL','APPROVED','EXECUTING',"
            "'EXECUTED','FAILED','REJECTED','EXPIRED','SUPERSEDED','CANCELLED')"
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_by_device: Mapped[str | None] = mapped_column(String, nullable=True)
    executed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_actions_status", "status", "expires_at"),)


class Briefing(Base):
    """الملخصات الذكية المجمعة (Section 7.1)."""

    __tablename__ = "briefings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(
        String,
        CheckConstraint("kind IN ('wakeup','morning','on_demand')"),
        nullable=False,
    )
    generated_at: Mapped[str] = mapped_column(String, nullable=False)
    delivered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    acked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    event_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)


class ChatMessage(Base):
    """محادثات المستخدم مع السكرتير."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str] = mapped_column(
        String, CheckConstraint("role IN ('user','assistant','system')"), nullable=False
    )
    source: Mapped[str] = mapped_column(String, default="text", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class OutboundMessage(Base):
    """طابور التسليم والاستئناف للأجهزة عبر WebSocket (Section 7.1, 8.3)."""

    __tablename__ = "outbound_messages"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        String, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    delivered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    acked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    fcm_sent_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Memory(Base):
    """الذاكرة طويلة الأمد للمستخدم."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    category: Mapped[str] = mapped_column(
        String,
        CheckConstraint("category IN ('preference','fact','project','style','person')"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_norm: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Job(Base):
    """المهام المجدولة والتذكيرات والرسائل المؤجلة."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    run_at: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="scheduled", nullable=False)
    action_id: Mapped[str | None] = mapped_column(String, ForeignKey("actions.id"), nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class OAuthToken(Base):
    """رموز OAuth مشفرة بـ AES-GCM (R-15)."""

    __tablename__ = "oauth_tokens"

    provider: Mapped[str] = mapped_column(String, primary_key=True)
    account: Mapped[str] = mapped_column(String, primary_key=True)
    token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    scopes: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)


class File(Base):
    """الملفات المولدة والمصدرة."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    path: Mapped[str] = mapped_column(String, nullable=False)
    mime: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)


class AuditLog(Base):
    """سجل التدقيق متسلسل التجزئة (R-16)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event: Mapped[str] = mapped_column(String, nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False)


class LLMUsage(Base):
    """سجل استهلاك واستخدام النماذج الذكية بدون تسجيل محتوى."""

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sensitivity_max: Mapped[str] = mapped_column(String, nullable=False)
    ok: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class Setting(Base):
    """إعدادات النظام العامة بصيغة JSON."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)
