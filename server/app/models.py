from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebSession(Base):
    """Browser login. The cookie holds a random token; only its sha256 is stored."""

    __tablename__ = "web_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    user: Mapped[User] = relationship(lazy="joined")


class AgentToken(Base):
    """Every credential an agent holds: a named API key (no expiry) or an OAuth access /
    refresh token issued to an MCP client. Only the sha256 is stored. `name` is what the
    activity log shows as the actor, e.g. "Upwork scout" or "Claude"."""

    __tablename__ = "agent_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(10))  # api_key | access | refresh
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))  # shown in the UI so keys are recognisable
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[str | None] = mapped_column(String(80))  # OAuth client, null for API keys
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    resource: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class OAuthClient(Base):
    """MCP clients registered through dynamic client registration (RFC 7591)."""

    __tablename__ = "oauth_clients"
    client_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    info: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OAuthCode(Base):
    __tablename__ = "oauth_codes"
    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSON)  # the SDK's AuthorizationCode fields
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="job")
    company: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(300))
    application_url: Mapped[str | None] = mapped_column(String(1000))
    url_key: Mapped[str | None] = mapped_column(String(1000), unique=True)  # normalized, for dedup
    company_url: Mapped[str | None] = mapped_column(String(1000))
    channel: Mapped[str] = mapped_column(String(20), default="other")
    network: Mapped[str] = mapped_column(String(20), default="none")
    stage: Mapped[str] = mapped_column(String(20), default="lead")
    inbound: Mapped[bool] = mapped_column(Boolean, default=False)  # the client reached out first
    waiting_on: Mapped[str | None] = mapped_column(String(10))  # me | client
    lost_reason: Mapped[str | None] = mapped_column(String(20))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_url: Mapped[str | None] = mapped_column(String(1000))
    budget: Mapped[str | None] = mapped_column(String(120))  # as posted: "$40-60/hr", "$5k fixed"
    value: Mapped[float | None] = mapped_column(Float)  # expected / actual contract value, USD
    fit: Mapped[int | None] = mapped_column(Integer)  # 1-5, how good a match it is
    description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    # Job applications: the tailored copies the applicant agent stored (Google Drive links).
    resume_url: Mapped[str | None] = mapped_column(String(1000))
    resume_version: Mapped[str | None] = mapped_column(String(120))  # the base it was tailored from
    cover_letter_url: Mapped[str | None] = mapped_column(String(1000))
    # The first-contact message sent — Insights compares reply rates per variant.
    template_id: Mapped[int | None] = mapped_column(ForeignKey("message_templates.id", ondelete="SET NULL"), index=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime)
    call_at: Mapped[datetime | None] = mapped_column(DateTime)
    proposal_at: Mapped[datetime | None] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="Reminder.due_at"
    )
    template: Mapped["MessageTemplate | None"] = relationship()

    __table_args__ = (Index("ix_opp_stage", "stage"), Index("ix_opp_activity", "last_activity_at"))


class MessageTemplate(Base):
    """A first-contact message variant (LinkedIn, cold or warm email). One per category is current —
    that is the one agents send. A variant that deals point to is archived, not deleted, so its
    reply-rate history survives."""

    __tablename__ = "message_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str | None] = mapped_column(String(300))  # emails only
    body: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    opportunity: Mapped[Opportunity] = relationship(back_populates="reminders")


class Event(Base):
    """The timeline + audit log in one: every change and every logged activity, with who did it.
    kind: created | updated | client_message | my_message | call | note | reminder | reviewed"""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    body: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[dict | None] = mapped_column(JSON)  # {field: [old, new]}
    actor_type: Mapped[str] = mapped_column(String(10))  # human | agent
    actor_name: Mapped[str] = mapped_column(String(120))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Notification(Base):
    """An alert an agent sends the owner: something they need to act on or decide. Read in the web
    app's Alerts inbox; `read_at` is set when the owner has seen it."""

    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    opportunity: Mapped[Opportunity | None] = relationship(lazy="joined")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
