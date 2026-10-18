from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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


class MessageCategory(Base):
    """A kind of recurring message (LinkedIn first contact, cold email, ...). `purpose` tells
    agents when to send it. Created by the owner or, on their behalf, by an agent. A category whose
    messages have history is archived, not deleted, so Insights can still name them."""

    __tablename__ = "message_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)  # what agents pass; never changes
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(Text)
    has_subject: Mapped[bool] = mapped_column(Boolean, default=False)  # emails
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)


class MessageTemplate(Base):
    """The owner's recommended example of a message in a category. One per category is current — that is
    the one agents adapt and send. A variant that was used is archived, not deleted, so its usage history survives."""

    __tablename__ = "message_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40), index=True)  # MessageCategory.key
    name: Mapped[str] = mapped_column(String(120))
    subject: Mapped[str | None] = mapped_column(String(300))  # emails only
    body: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Agents keep template ids; AUTOINCREMENT stops SQLite handing a removed message's id to a new one.
    __table_args__ = {"sqlite_autoincrement": True}


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    # The agent whose own follow-up this is (null = the owner's step). It counts as the deal's next step
    # but reaches the owner's Today only once it's missed.
    agent: Mapped[str | None] = mapped_column(String(120))
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
    # my_message only: the platform it went out on, and the template it was based on (usage telemetry).
    channel: Mapped[str | None] = mapped_column(String(20))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("message_templates.id", ondelete="SET NULL"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    template: Mapped["MessageTemplate | None"] = relationship(lazy="joined")


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


# ---------------------------------------------------------------- agent state
# Durable memory for scheduled agents, so they keep nothing in local files between runs. `ns` (namespace)
# is an agent's name ("upwork") or one several agents share ("linkedin"). Not deal records: no Event and
# no review flag — the owner watches it on the State page.


class StateRow(Base):
    """One remembered value. `section` is a fixed brief section (domain.STATE_SECTIONS) or a list name.
    `locked` = an owner row: agents can't change it (in a list they may only merge fields into it)."""

    __tablename__ = "agent_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    ns: Mapped[str] = mapped_column(String(60))
    section: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[Any] = mapped_column(JSON)  # any JSON: text, number, object, list
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    by: Mapped[str] = mapped_column(String(120))  # agent name, or "owner"
    due_at: Mapped[datetime | None] = mapped_column(DateTime)  # list rows worked on a schedule
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("ns", "section", "key"), Index("ix_agent_state_due", "ns", "section", "due_at"))


class StateCounter(Base):
    """A usage count in one time window (bucket): day 2026-10-18, week 2026-W42, month 2026-10, total all.
    A new window is a new row starting at zero, so nobody ever resets a counter."""

    __tablename__ = "agent_counters"
    id: Mapped[int] = mapped_column(primary_key=True)
    ns: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(60))
    period: Mapped[str] = mapped_column(String(10))
    bucket: Mapped[str] = mapped_column(String(10))
    value: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (UniqueConstraint("ns", "key", "period", "bucket"),)


class SeenItem(Base):
    """An item an agent already evaluated (a job id, a comment id, a URL), so later runs skip it until
    `expires_at` (the caller's ttl_days); after that it counts as new again."""

    __tablename__ = "agent_seen"
    ns: Mapped[str] = mapped_column(String(60), primary_key=True)
    source: Mapped[str] = mapped_column(String(60), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(300), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class AgentRun(Base):
    """One scheduled run of a worker in a namespace. While `ended_at` is empty and `lease_until` is in the
    future the run holds its ns+worker, so runs never overlap; a crashed run frees it at `lease_until`."""

    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ns: Mapped[str] = mapped_column(String(60))
    worker: Mapped[str] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_until: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str | None] = mapped_column(String(10))  # domain.RUN_STATUSES; empty while running
    summary: Mapped[str | None] = mapped_column(String(500))
    counts: Mapped[dict | None] = mapped_column(JSON)  # {"applied": 3, "skipped": 12}
    result: Mapped[dict | None] = mapped_column(JSON)  # run_end's first reply; a repeat call returns it

    __table_args__ = (Index("ix_agent_runs_ns_worker", "ns", "worker", "started_at"),)


class IdemKey(Base):
    """A `count` call's idempotency key and its reply, so a retry after a timeout doesn't spend twice.
    Honoured for 24 hours, then purged nightly."""

    __tablename__ = "agent_idem"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(500))
