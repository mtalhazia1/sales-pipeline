"""All business logic. The REST API (humans) and the MCP server (agents) are thin adapters over
these functions, so both always behave identically — including the audit trail and the review
flag: anything an agent writes is marked `needs_review` until a human looks at it."""

import hashlib
import json
import math
import re
import statistics
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, get_args
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import String, and_, func, or_, select, text, type_coerce
from sqlalchemy import delete as sql_delete
from sqlalchemy import update as sql_update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import domain
from app.db import iso, utcnow
from app.models import (
    AgentRun,
    Event,
    IdemKey,
    MessageCategory,
    MessageTemplate,
    Notification,
    Opportunity,
    Reminder,
    SeenItem,
    Setting,
    StateCounter,
    StateRow,
)


class ServiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Actor:
    type: str  # human | agent
    name: str
    user_id: int | None = None

    @property
    def is_agent(self) -> bool:
        return self.type == "agent"


# ---------------------------------------------------------------- helpers

EDITABLE = {
    "kind", "company", "title", "application_url", "company_url", "channel", "network", "stage",
    "inbound", "waiting_on", "lost_reason", "contact_name", "contact_email", "contact_url",
    "budget", "value", "fit", "description", "notes",
    "resume_url", "resume_version", "cover_letter_url", "template_id",
}
ENUMS = {
    "kind": domain.KINDS, "channel": domain.CHANNELS, "network": domain.NETWORKS,
    "stage": domain.STAGES, "lost_reason": domain.LOST_REASONS,
    "waiting_on": [("me", ""), ("client", "")],
}
# Only names that are never a posting's identity — `source`/`src`/`origin` are ids on some job boards.
TRACKING_PARAMS = re.compile(r"^(utm_.*|trk.*|ref|refid|referrer|fbclid|gclid|tracking.*|lipi|mcid)$", re.I)


def get_timezone(s: Session) -> ZoneInfo:
    row = s.get(Setting, "timezone")
    try:
        return ZoneInfo(row.value if row else "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def url_key(url: str | None) -> str | None:
    """Canonical identity of a posting so the same job can't be added twice
    (agents re-find the same posts constantly). None = not a posting URL, so no dedup:
    merging two different deals silently is worse than a visible duplicate."""
    if not url or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower().removeprefix("www.")
        has_userinfo = parts.username is not None
    except ValueError:
        return None
    # "N/A", an email address, "acme" — not a web address.
    if parts.scheme not in ("http", "https") or "." not in host or has_userinfo or " " in raw:
        return None
    path = parts.path.rstrip("/")
    query = dict(parse_qsl(parts.query))
    if host.endswith("upwork.com"):
        m = re.search(r"~0[0-9a-z]+", path, re.I)
        return f"upwork:{m.group(0).lower()}" if m else None
    if host.endswith("linkedin.com"):
        if m := re.search(r"/jobs/view/(?:[^/]*-)?(\d+)", path):
            return f"linkedin-job:{m.group(1)}"
        if query.get("currentJobId", "").isdigit():
            return f"linkedin-job:{query['currentJobId']}"
        return None  # a profile, feed or search page is not a posting
    kept = sorted((k, v) for k, v in query.items() if not TRACKING_PARAMS.match(k))
    # Single-page career sites route by fragment (#/job/123); a plain #section anchor is not identity.
    route = f"#{parts.fragment}" if parts.fragment.startswith(("/", "!/")) else ""
    if not path and not kept and not route:
        return None  # a bare homepage is shared by every deal at that company
    return f"{host}{path}" + (f"?{urlencode(kept)}" if kept else "") + route


def channel_for_url(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    return next((ch for h, ch in domain.CHANNEL_BY_HOST.items() if host == h or host.endswith("." + h)), None)


def parse_when(value: str | datetime | None, tz: ZoneInfo, default_hour: int = 9) -> datetime | None:
    """'2026-10-05' → 09:00 that day in the workspace timezone; a datetime with an offset is
    taken as-is; a naive datetime is read in the workspace timezone. Returns naive UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = value.strip().replace("Z", "+00:00")
        try:
            if re.fullmatch(r"\d{4}-?\d{2}-?\d{2}", text):
                dt = datetime.combine(date.fromisoformat(text), time(default_hour))
            else:
                dt = datetime.fromisoformat(text)
        except ValueError as e:
            raise ServiceError(f"Couldn't read the date {value!r} — use YYYY-MM-DD or an ISO datetime "
                               f"(today is {datetime.now(tz).date().isoformat()} in {tz}).") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    try:
        return dt.astimezone(UTC).replace(tzinfo=None)
    except OverflowError as e:  # e.g. 9999-12-31T23:00-05:00 is past year 9999 in UTC
        raise ServiceError(f"The date {value!r} is out of range.") from e


URL_FIELDS = ("application_url", "company_url", "contact_url", "url", "resume_url", "cover_letter_url")
# Long enough for any real job post; bounded so one bad agent call can't store megabytes.
MAX_LEN = {"description": 50_000, "notes": 20_000, "message": 10_000, "summary": 10_000, "body": 10_000, "resume_version": 120,
           "name": 120, "subject": 300, "purpose": 2000}


def _clean(field: str, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if value == "" and field not in ("company",):
            value = None
        elif len(value) > MAX_LEN.get(field, 1000):
            raise ServiceError(f"{field} is too long (max {MAX_LEN.get(field, 1000):,} characters).")
    if field in URL_FIELDS and value is not None:
        # Rendered as links in the UI: web addresses only (no javascript:, data:, app-protocol handlers).
        # "acme.com" and "localhost:8080/x" are fine (no scheme / a port), "javascript:…" is not.
        scheme = re.match(r"^([a-z][a-z0-9+.-]*):(?!\d)", value, re.I)
        if scheme and scheme.group(1).lower() not in ("http", "https"):
            raise ServiceError(f"{field} must be a web address (https://…).")
    if value is None:
        if field in ("company", "kind", "channel", "network", "stage"):
            raise ServiceError(f"{field} can't be empty.")
        return None
    if field in ENUMS and value not in {k for k, _ in ENUMS[field]}:
        allowed = ", ".join(k for k, _ in ENUMS[field])
        raise ServiceError(f"{field} must be one of: {allowed} (got {value!r}).")
    if field == "company" and not value:
        raise ServiceError("company can't be empty.")
    if field == "template_id":
        if isinstance(value, bool) or not isinstance(value, int | str) or not re.fullmatch(r"[1-9]\d{0,17}", str(value)):
            raise ServiceError("template_id is a message template id (from get_message_template).")
        value = int(value)
    if field == "fit":
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ServiceError("fit is a 1-5 score.") from None
        if not 1 <= value <= 5:
            raise ServiceError("fit is a 1-5 score.")
    if field == "value":
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ServiceError("value is a number in USD.") from None
        if not math.isfinite(value) or value < 0:
            raise ServiceError("value must be a number ≥ 0 in USD.")
    if field == "inbound":
        if isinstance(value, str):
            if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
                raise ServiceError("inbound is true or false.")
            value = value.lower() in ("true", "1", "yes")
        value = bool(value)
    return value


def _milestone_rank(stage: str) -> int:
    """How far along the milestone chain a stage is (-1 = none yet). Sending a Toptal profile to the
    matcher is that channel's application, so it counts as applied in the funnel."""
    stage = "applied" if stage == "matcher" else stage
    return domain.MILESTONE_CHAIN.index(stage) if stage in domain.MILESTONE_CHAIN else -1


def _rewind_milestones(opp: Opportunity, stage: str) -> None:
    """Moving a deal back to an earlier open stage (a misdrag, or "that wasn't really a reply")
    un-stamps the milestones past it — the stage is the truth, and Insights counts milestones."""
    for m in domain.MILESTONE_CHAIN[_milestone_rank(stage) + 1:]:
        setattr(opp, domain.MILESTONES[m], None)


def _stamp_milestones(opp: Opportunity, stage: str, when: datetime) -> None:
    if stage == "matcher" and opp.applied_at is None:
        opp.applied_at = when
    if stage in domain.MILESTONE_CHAIN:
        for m in domain.MILESTONE_CHAIN[: domain.MILESTONE_CHAIN.index(stage) + 1]:
            attr = domain.MILESTONES[m]
            if getattr(opp, attr) is None:
                setattr(opp, attr, when)
    if stage == "won":
        for m in ("applied", "replied"):
            if getattr(opp, domain.MILESTONES[m]) is None:
                setattr(opp, domain.MILESTONES[m], when)
    opp.closed_at = when if stage in domain.CLOSED_STAGES else None
    if stage in domain.CLOSED_STAGES:
        opp.waiting_on = None
    if stage != "lost":
        opp.lost_reason = None


def _event(s: Session, opp: Opportunity, actor: Actor, kind: str, body: str | None = None,
           changes: dict | None = None, occurred_at: datetime | None = None, **usage: Any) -> Event:
    ev = Event(opportunity_id=opp.id, kind=kind, body=body, changes=changes, actor_type=actor.type,
               actor_name=actor.name, occurred_at=occurred_at or utcnow(), **usage)
    s.add(ev)
    return ev


def _loggable(changes: dict, s: Session) -> dict:
    """The timeline shows which message was sent by name, not by id."""
    if "template_id" in changes:
        name = lambda tid: (t.name if (t := s.get(MessageTemplate, tid)) else f"#{tid}") if tid else None  # noqa: E731
        changes = {**changes, "first_message": [name(v) for v in changes["template_id"]]}
        del changes["template_id"]
    return changes


def _touch(opp: Opportunity, actor: Actor, activity: bool = True) -> None:
    now = utcnow()
    opp.updated_at = now
    if activity:
        opp.last_activity_at = now
    # An agent's write needs a human look; a human acting on the deal has looked at it.
    opp.needs_review = actor.is_agent


def _get(s: Session, opp_id: int) -> Opportunity:
    opp = s.get(Opportunity, opp_id)
    if not opp or opp.archived_at:
        raise ServiceError(f"Opportunity {opp_id} not found.", 404)
    return opp


# ---------------------------------------------------------------- serialization

def summary(opp: Opportunity) -> dict:
    open_rem = [r for r in opp.reminders if not r.done_at]
    nxt = min(open_rem, key=lambda r: r.due_at) if open_rem else None
    return {
        "id": opp.id,
        "deleted": opp.archived_at is not None,
        "kind": opp.kind,
        "company": opp.company,
        "title": opp.title,
        "channel": opp.channel,
        "network": opp.network,
        "stage": opp.stage,
        "inbound": opp.inbound,
        "waiting_on": opp.waiting_on,
        "lost_reason": opp.lost_reason,
        "application_url": opp.application_url,
        "value": opp.value,
        "budget": opp.budget,
        "fit": opp.fit,
        # The deal's first message (Insights credits replies to it). "Already contacted" is the stage: past lead.
        "template_id": opp.template_id,
        "resume_url": opp.resume_url,
        "cover_letter_url": opp.cover_letter_url,
        "resume_version": opp.resume_version,
        "needs_review": opp.needs_review,
        "created_by": opp.created_by,
        "created_at": iso(opp.created_at),
        "last_activity_at": iso(opp.last_activity_at),
        "next_reminder": {"id": nxt.id, "due_at": iso(nxt.due_at), "note": nxt.note} if nxt else None,
    }


def detail(s: Session, opp: Opportunity, events_limit: int = 100) -> dict:
    events = s.scalars(
        select(Event).where(Event.opportunity_id == opp.id)
        .order_by(Event.occurred_at.desc(), Event.id.desc()).limit(events_limit)
    ).all()
    return {
        **summary(opp),
        "company_url": opp.company_url,
        "contact_name": opp.contact_name,
        "contact_email": opp.contact_email,
        "contact_url": opp.contact_url,
        "description": opp.description,
        "notes": opp.notes,
        "resume_url": opp.resume_url,
        "resume_version": opp.resume_version,
        "cover_letter_url": opp.cover_letter_url,
        "template": template_ref(opp.template),
        "updated_at": iso(opp.updated_at),
        "applied_at": iso(opp.applied_at),
        "replied_at": iso(opp.replied_at),
        "call_at": iso(opp.call_at),
        "proposal_at": iso(opp.proposal_at),
        "closed_at": iso(opp.closed_at),
        "reminders": [reminder_dict(r) for r in opp.reminders],
        "events": [event_dict(e) for e in events],
    }


def reminder_dict(r: Reminder) -> dict:
    return {"id": r.id, "opportunity_id": r.opportunity_id, "due_at": iso(r.due_at), "note": r.note,
            "done_at": iso(r.done_at), "created_by": r.created_by}


def event_dict(e: Event, opp: Opportunity | None = None) -> dict:
    d = {"id": e.id, "opportunity_id": e.opportunity_id, "kind": e.kind, "body": e.body, "changes": e.changes,
         "actor_type": e.actor_type, "actor_name": e.actor_name, "occurred_at": iso(e.occurred_at),
         "channel": e.channel, "template": template_ref(e.template)}
    if opp is not None:
        d["company"], d["title"] = opp.company, opp.title
    return d


# ---------------------------------------------------------------- opportunities

def find_duplicate(s: Session, application_url: str | None) -> Opportunity | None:
    key = url_key(application_url)
    return s.scalar(select(Opportunity).where(Opportunity.url_key == key)) if key else None


def create(s: Session, actor: Actor, data: dict) -> tuple[Opportunity, bool]:
    """Returns (opportunity, created). An existing posting with the same URL is returned
    untouched with created=False — re-adding is safe and never duplicates."""
    unknown = set(data) - EDITABLE - {"reminder_at", "reminder_note"}
    if unknown:
        raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    if existing := find_duplicate(s, data.get("application_url")):
        # Includes deleted ones: a deletion sticks, so an agent re-finding the same posting can't revive it.
        return existing, False

    values = {k: _clean(k, v) for k, v in data.items() if k in EDITABLE}
    if values.get("template_id") is not None:
        _assignable_template(s, values["template_id"], None)
    values.setdefault("channel", channel_for_url(values.get("application_url")) or "other")
    values.setdefault("stage", "lead")
    if "company" not in values:
        raise ServiceError("company is required.")
    _check_stage(values["stage"], values["channel"])
    _check_lost(values["stage"], values.get("lost_reason"))
    if data.get("reminder_at") and values["stage"] == "lost":  # a won deal can have one (kickoff, invoice)
        raise ServiceError("A lost deal has no next step: leave out reminder_at.")
    now = utcnow()
    opp = Opportunity(**values, url_key=url_key(values.get("application_url")), created_by=actor.name,
                      needs_review=actor.is_agent, created_at=now, updated_at=now, last_activity_at=now)
    if opp.waiting_on is None:
        opp.waiting_on = _default_waiting(opp.stage)
    _stamp_milestones(opp, opp.stage, now)
    # pysqlite opens a transaction only at the first write, so without this the SAVEPOINT below would be the
    # outermost transaction and commit the deal on its own — a later failure (a bad reminder_at) would leave it.
    _write_lock(s)
    try:
        with s.begin_nested():  # two agents adding the same posting at once: the loser gets the winner's row
            s.add(opp)
            s.flush()
    except IntegrityError:
        if existing := find_duplicate(s, data.get("application_url")):
            return existing, False
        raise
    _event(s, opp, actor, "created", None, _loggable({k: [None, v] for k, v in values.items()
                                                      if k not in ("description", "notes")}, s))
    if data.get("reminder_at"):
        add_reminder(s, actor, opp.id, data["reminder_at"], data.get("reminder_note") or "Follow up")
    return opp, True


def _check_stage(stage: str, channel: str) -> None:
    if stage == "matcher" and channel != "toptal":
        raise ServiceError("stage 'matcher' only applies with channel 'toptal'.")


def _check_lost(stage: str, lost_reason: str | None) -> None:
    # The reason is what makes "Lost" useful in Insights — ghosted, rejected and passed mean different fixes.
    reasons = ", ".join(k for k, _ in domain.LOST_REASONS)
    if stage == "lost" and not lost_reason:
        raise ServiceError(f"Pass lost_reason with stage 'lost': {reasons}.")
    if stage != "lost" and lost_reason:
        raise ServiceError("lost_reason only applies together with stage 'lost'.")


def _default_waiting(stage: str) -> str | None:
    """Whose move a stage implies when nobody said: you've sent something → theirs; they replied → yours."""
    return {"matcher": "client", "applied": "client", "proposal": "client", "replied": "me"}.get(stage)


def update(s: Session, actor: Actor, opp_id: int, data: dict) -> Opportunity:
    opp = _get(s, opp_id)
    unknown = set(data) - EDITABLE
    if unknown:
        raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    derived = ("waiting_on", "lost_reason")
    before = {k: getattr(opp, k) for k in derived}
    changes: dict[str, list] = {}
    for field, raw in data.items():
        new = _clean(field, raw)
        if field == "template_id" and new is not None:
            _assignable_template(s, new, opp.template_id)
        old = getattr(opp, field)
        if new != old:
            changes[field] = [old, new]
            setattr(opp, field, new)
    if not changes:
        if not actor.is_agent and opp.needs_review:
            mark_reviewed(s, actor, opp.id)
        return opp
    _check_stage(opp.stage, opp.channel)
    if "stage" in changes and opp.stage != "lost" and "lost_reason" not in data:
        opp.lost_reason = None  # reopening a lost deal drops its reason
    if "stage" in changes or "lost_reason" in changes:  # older rows lost without a reason stay editable
        _check_lost(opp.stage, opp.lost_reason)
    if "application_url" in changes:
        key = url_key(opp.application_url)
        dup = s.scalar(select(Opportunity).where(Opportunity.url_key == key, Opportunity.id != opp.id)) if key else None
        if dup:
            raise ServiceError(f"That URL is already opportunity #{dup.id} ({dup.company}).", 409)
        opp.url_key = key
    closed_reminders = 0
    if "stage" in changes:
        now = utcnow()
        if opp.stage in domain.OPEN_STAGES:
            _rewind_milestones(opp, opp.stage)
        _stamp_milestones(opp, opp.stage, now)
        if "waiting_on" not in changes and (wo := _default_waiting(opp.stage)):
            opp.waiting_on = wo
        if opp.stage == "lost":
            # A dead deal's follow-ups would keep surfacing on Today; a won deal keeps its (kickoff, invoice…) reminders.
            for r in opp.reminders:
                if not r.done_at:
                    r.done_at, closed_reminders = now, closed_reminders + 1
    # Field edits are bookkeeping; only a stage move counts as deal activity.
    _touch(opp, actor, activity="stage" in changes)
    # Long text fields are logged as "edited" rather than copied into the audit trail.
    logged = {k: ([None, "edited"] if k in ("description", "notes") else v) for k, v in changes.items()}
    logged |= {k: [before[k], getattr(opp, k)] for k in derived if k not in logged and getattr(opp, k) != before[k]}
    if closed_reminders:
        logged["reminders_closed"] = [None, closed_reminders]
    _event(s, opp, actor, "updated", None, _loggable(logged, s))
    return opp


def archive(s: Session, actor: Actor, opp_id: int) -> None:
    opp = _get(s, opp_id)
    opp.archived_at = utcnow()
    _event(s, opp, actor, "updated", "Deleted")


def log_activity(s: Session, actor: Actor, opp_id: int, kind: str, body: str | None,
                 occurred_at: str | datetime | None = None, template_id: int | None = None,
                 channel: str | None = None) -> Opportunity:
    """Record something that happened and move the deal along the obvious way:
    a client message → stage Replied (if earlier) and it's your move; your message → their move;
    a call → stage Call booked (if earlier). A my_message records the platform it went out on
    (`channel`, default the deal's) and, with `template_id`, which template it was based on — that is
    the usage count. The first template sent before the client ever replied is the deal's first
    message, which Insights compares by reply rate."""
    if kind not in {k for k, _ in domain.ACTIVITY_KINDS}:
        raise ServiceError(f"kind must be one of: {', '.join(k for k, _ in domain.ACTIVITY_KINDS)}.")
    if (template_id is not None or channel) and kind != "my_message":
        raise ServiceError("template_id and channel only go with kind='my_message' (a message you sent).")
    opp = _get(s, opp_id)
    if template_id is not None:
        template_id = _clean("template_id", template_id)
        _assignable_template(s, template_id, opp.template_id)
    channel = _clean("channel", channel) if channel else None
    body = _clean("summary", body)  # the MCP parameter name, so a too-long error makes sense to the agent
    when = parse_when(occurred_at, get_timezone(s)) or utcnow()
    if when > utcnow() + timedelta(minutes=10):
        raise ServiceError("occurred_at is in the future — log things when they happen. For a call that's booked "
                           "for later, log kind='call' now and set_reminder for the call time.")
    order = domain.STAGE_ORDER
    before = {"stage": opp.stage, "waiting_on": opp.waiting_on, "inbound": opp.inbound, "lost_reason": opp.lost_reason,
              "template_id": opp.template_id}
    # Later templates (a follow-up, a rate card) are counted as uses but never re-credit the deal's reply.
    if template_id is not None and opp.template_id is None and (opp.replied_at is None or when < opp.replied_at):
        opp.template_id = template_id
    if kind == "client_message":
        if opp.stage == "lead":
            opp.inbound = opp.inbound or opp.applied_at is None
        # A client writing back revives a deal that went silent — not one they rejected or you passed on
        # ("thanks, we went with someone else" must not reopen it).
        revive = opp.stage == "lost" and opp.lost_reason == "no_response"
        if revive or (opp.stage in domain.OPEN_STAGES and order[opp.stage] < order["replied"]):
            opp.stage = "replied"
        if opp.stage in domain.OPEN_STAGES:
            opp.waiting_on = "me"
    elif kind == "my_message":
        if opp.stage == "lead":
            opp.stage = "applied"
        if opp.stage in domain.OPEN_STAGES:
            opp.waiting_on = "client"
    elif kind == "call":
        if opp.stage in domain.OPEN_STAGES and order[opp.stage] < order["call"]:
            opp.stage = "call"
    if opp.stage != before["stage"]:
        _stamp_milestones(opp, opp.stage, when)
    # Back-filled history: an earlier piece of evidence moves its milestone earlier.
    milestone = {"my_message": "applied_at", "client_message": "replied_at", "call": "call_at"}.get(kind)
    if milestone and (stamped := getattr(opp, milestone)) and when < stamped:
        setattr(opp, milestone, when)
    changes = {k: [v, getattr(opp, k)] for k, v in before.items() if getattr(opp, k) != v}
    _touch(opp, actor, activity=False)
    if kind != "note":  # a note is bookkeeping, not contact with the client
        opp.last_activity_at = max(opp.last_activity_at, when)
    usage = {"channel": channel or opp.channel, "template_id": template_id} if kind == "my_message" else {}
    _event(s, opp, actor, kind, body, _loggable(changes, s) or None, occurred_at=when, **usage)
    return opp


def mark_reviewed(s: Session, actor: Actor, opp_id: int | None = None, ids: list[int] | None = None) -> int:
    q = select(Opportunity).where(Opportunity.needs_review.is_(True), Opportunity.archived_at.is_(None))
    if opp_id is not None:
        q = q.where(Opportunity.id == opp_id)
    if ids is not None:  # only what the reviewer actually saw — not whatever an agent added since
        q = q.where(Opportunity.id.in_(ids))
    opps = s.scalars(q).all()
    for opp in opps:
        opp.needs_review = False
        _event(s, opp, actor, "reviewed")
    return len(opps)


def search(s: Session, *, q: str | None = None, stage: list[str] | None = None, channel: str | None = None,
           network: str | None = None, kind: str | None = None, waiting_on: str | None = None,
           needs_review: bool | None = None, include_closed: bool = True, limit: int = 500) -> list[Opportunity]:
    stmt = select(Opportunity).where(Opportunity.archived_at.is_(None))
    if q and q.strip():
        like = f"%{q.strip()}%"
        matches = [Opportunity.company.ilike(like), Opportunity.title.ilike(like),
                   Opportunity.contact_name.ilike(like), Opportunity.notes.ilike(like),
                   Opportunity.description.ilike(like), Opportunity.application_url.ilike(like),
                   Opportunity.contact_email.ilike(like)]
        if "/" in q and (key := url_key(q)):  # any form of a posting's URL finds it
            matches.append(Opportunity.url_key == key)
        stmt = stmt.where(or_(*matches))
    if stage:
        stmt = stmt.where(Opportunity.stage.in_(stage))
    elif not include_closed:
        stmt = stmt.where(Opportunity.stage.in_(domain.OPEN_STAGES))
    for col, val in ((Opportunity.channel, channel), (Opportunity.network, network),
                     (Opportunity.kind, kind), (Opportunity.waiting_on, waiting_on)):
        if val:
            stmt = stmt.where(col == val)
    if needs_review is not None:
        stmt = stmt.where(Opportunity.needs_review.is_(needs_review))
    stmt = stmt.order_by(Opportunity.last_activity_at.desc()).limit(min(limit, 1000))
    return list(s.scalars(stmt).unique().all())


# ---------------------------------------------------------------- reminders

def add_reminder(s: Session, actor: Actor, opp_id: int, due: str | datetime, note: str = "") -> Reminder:
    opp = _get(s, opp_id)
    due_at = parse_when(due, get_timezone(s))
    if due_at is None:
        raise ServiceError("A reminder needs a date.")
    r = Reminder(opportunity=opp, due_at=due_at, note=(note or "").strip()[:500], created_by=actor.name)
    s.add(r)
    s.flush()
    _touch(opp, actor, activity=False)
    _event(s, opp, actor, "reminder", r.note or None, {"due_at": [None, iso(due_at)]})
    return r


def update_reminder(s: Session, actor: Actor, reminder_id: int, *, done: bool | None = None,
                    due: str | None = None, note: str | None = None) -> Reminder:
    r = s.get(Reminder, reminder_id)
    if not r or r.opportunity.archived_at:
        raise ServiceError(f"Reminder {reminder_id} not found.", 404)
    changes: dict[str, list] = {}
    if done is not None and bool(r.done_at) != done:  # repeating "done" is a no-op, not a second event
        r.done_at = utcnow() if done else None
        changes["done_at"] = [None, iso(r.done_at)] if done else ["done", None]
    if due and (new_due := parse_when(due, get_timezone(s))) != r.due_at:
        changes["due_at"] = [iso(r.due_at), iso(new_due)]
        r.due_at = new_due
    if note is not None and note.strip()[:500] != r.note:
        changes["note"] = [r.note or None, note.strip()[:500] or None]
        r.note = note.strip()[:500]
    if changes:
        _touch(r.opportunity, actor, activity=False)
        _event(s, r.opportunity, actor, "reminder", r.note or None, changes)
    return r


def delete_reminder(s: Session, actor: Actor, reminder_id: int) -> None:
    r = s.get(Reminder, reminder_id)
    if not r or r.opportunity.archived_at:
        raise ServiceError(f"Reminder {reminder_id} not found.", 404)
    _touch(r.opportunity, actor, activity=False)
    _event(s, r.opportunity, actor, "reminder", r.note or None, {"deleted": [iso(r.due_at), None]})
    s.delete(r)


# ---------------------------------------------------------------- message templates (recommended examples, by category)

def template_ref(t: MessageTemplate | None) -> dict | None:
    return {"id": t.id, "category": t.category, "name": t.name} if t else None


def placeholders(t: MessageTemplate) -> list[str]:
    """The {names} the agent must fill, in order of first use."""
    return list(dict.fromkeys(re.findall(r"\{(\w+)\}", f"{t.subject or ''}\n{t.body}")))


def category_dict(c: MessageCategory) -> dict:
    return {"key": c.key, "name": c.name, "purpose": c.purpose, "has_subject": c.has_subject,
            "needs_review": c.needs_review, "updated_by": c.updated_by, "archived": c.archived_at is not None,
            "created_at": iso(c.created_at), "updated_at": _version(c)}


def template_dict(t: MessageTemplate, usage: dict | None = None) -> dict:
    return {"id": t.id, "category": t.category, "name": t.name, "subject": t.subject, "body": t.body,
            "placeholders": placeholders(t),
            "is_current": t.is_current, "archived": t.archived_at is not None,
            "needs_review": t.needs_review, "updated_by": t.updated_by,
            "created_at": iso(t.created_at), "updated_at": _version(t),
            **({"usage": usage} if usage is not None else {})}


def _reviewed_by(obj: MessageCategory | MessageTemplate, actor: Actor) -> None:
    """Agents write templates on the owner's behalf: flag it until a person has looked (same rule as deals)."""
    obj.needs_review = actor.is_agent
    obj.updated_by = actor.name
    obj.updated_at = utcnow()


def _version(obj: MessageCategory | MessageTemplate) -> str:
    """`updated_at` to the microsecond: the web UI sends it back as the version it showed."""
    return obj.updated_at.isoformat(timespec="microseconds") + "Z"


def _seen_version(obj: MessageCategory | MessageTemplate, data: dict) -> dict:
    """The web UI sends back the `updated_at` it showed, so a save or "looks good" never lands on a newer
    version an agent wrote since. Returns the remaining fields."""
    data = dict(data)
    seen = data.pop("updated_at", None)
    if seen is not None and seen != _version(obj):
        raise ServiceError(f"{obj.name!r} changed since you opened it (by {obj.updated_by}). Reload and look again.", 409)
    return data


def _check_types(data: dict, allowed: set[str], text: tuple[str, ...], flags: tuple[str, ...]) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    for k in text:
        if k in data and not isinstance(data[k], str | None):
            raise ServiceError(f"{k} must be text.")
    for k in flags:
        if k in data and not isinstance(data[k], bool):
            raise ServiceError(f"{k} is true or false.")


def _live_keys(s: Session) -> list[str]:
    return list(s.scalars(select(MessageCategory.key).where(MessageCategory.archived_at.is_(None)).order_by(MessageCategory.id)))


def _category(s: Session, key: Any) -> MessageCategory:
    c = s.scalar(select(MessageCategory).where(MessageCategory.key == key)) if isinstance(key, str) else None
    if not c or c.archived_at:
        raise ServiceError(f"No message category {key!r}. Categories: {', '.join(_live_keys(s)) or 'none yet'}.", 404)
    return c


def _category_fields(s: Session, data: dict, current: MessageCategory | None) -> dict:
    _check_types(data, {"name", "purpose", "has_subject"}, ("name", "purpose"), ("has_subject",))
    out = {k: _clean(k, data[k]) for k in ("name", "purpose") if k in data}
    if "name" in out:
        if not out["name"]:
            raise ServiceError("name can't be empty.")
        clash = s.scalar(select(MessageCategory).where(func.casefold(MessageCategory.name) == out["name"].casefold(),
                                                       MessageCategory.archived_at.is_(None)))
        if clash and clash is not current:
            raise ServiceError(f"There is already a category named {clash.name!r} (key {clash.key!r}).")
    if "has_subject" in data:
        out["has_subject"] = data["has_subject"]
        if current and out["has_subject"] != current.has_subject and s.scalar(
                select(MessageTemplate.id).where(MessageTemplate.category == current.key, MessageTemplate.archived_at.is_(None))):
            raise ServiceError("Whether messages have a subject line can only change while the category has no messages.")
    return out


def categories(s: Session, *, include_archived: bool = False) -> list[MessageCategory]:
    stmt = select(MessageCategory).order_by(MessageCategory.id)
    if not include_archived:
        stmt = stmt.where(MessageCategory.archived_at.is_(None))
    return list(s.scalars(stmt))


def create_category(s: Session, actor: Actor, data: dict) -> MessageCategory:
    _write_lock(s)  # two agents creating the same name: the second sees the first and is refused
    fields = _category_fields(s, data, None)
    if not fields.get("name"):
        raise ServiceError("A category needs a name.")
    # The key is what agents pass around, so it is derived once and never changes (renaming keeps it).
    ascii_name = unicodedata.normalize("NFKD", fields["name"]).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_name).strip("_")[:36].strip("_") or "category"
    taken = set(s.scalars(select(MessageCategory.key).where(MessageCategory.key.like(f"{base}%"))))
    key = next(k for n in range(1, 1000) if (k := base if n == 1 else f"{base}_{n}") not in taken)
    now = utcnow()
    c = MessageCategory(key=key, created_at=now, **{"has_subject": False, **fields})
    _reviewed_by(c, actor)
    s.add(c)
    s.flush()
    return c


def update_category(s: Session, actor: Actor, key: str, data: dict) -> MessageCategory:
    _write_lock(s)
    c = _category(s, key)
    data = _seen_version(c, data)
    fields = {k: v for k, v in _category_fields(s, data, c).items() if getattr(c, k) != v}
    for k, v in fields.items():
        setattr(c, k, v)
    if fields:
        _reviewed_by(c, actor)
    elif not actor.is_agent:  # a person saving it unchanged ("looks good") has reviewed it
        c.needs_review = False
    return c


def delete_category(s: Session, key: str) -> None:
    """Only an empty category can go. One whose (deleted) messages have history is archived so Insights can
    still name them."""
    c = _category(s, key)
    rows = s.scalars(select(MessageTemplate).where(MessageTemplate.category == c.key)).all()
    if any(not t.archived_at for t in rows):
        raise ServiceError("Delete the messages in this category first.")
    if rows:
        c.archived_at, c.needs_review = utcnow(), False
    else:
        s.delete(c)


def _template(s: Session, template_id: int) -> MessageTemplate:
    t = s.get(MessageTemplate, template_id)
    if not t:
        raise ServiceError(f"Message template {template_id} not found.", 404)
    return t


def _assignable_template(s: Session, template_id: int, current_id: int | None) -> MessageTemplate:
    """A deal may point at a live variant, or keep the (possibly since-deleted) one it already has."""
    t = s.get(MessageTemplate, template_id)
    if not t or (t.archived_at and t.id != current_id):
        raise ServiceError(f"Message template {template_id} doesn't exist or was deleted by the owner. If you sent it, "
                           "log the message without template_id; call get_message_template before the next one.", 404)
    return t


def _template_fields(data: dict, category: MessageCategory) -> dict:
    _check_types(data, {"name", "subject", "body", "is_current", "category"}, ("name", "subject", "body"), ("is_current",))
    out = {k: _clean(k, data[k]) for k in ("name", "subject", "body") if k in data}
    for k in ("name", "body"):
        if k in out and not out[k]:
            raise ServiceError(f"{k} can't be empty.")
    if category.has_subject:
        if "subject" in out and not out["subject"]:
            raise ServiceError(f"A {category.name} needs a subject line.")
    else:
        out.pop("subject", None)  # e.g. LinkedIn messages have no subject line
    if "is_current" in data:
        out["is_current"] = data["is_current"]
    return out


def _make_current(s: Session, t: MessageTemplate) -> None:
    # One UPDATE (it takes the write lock), so two "use this" clicks can't leave two current variants.
    s.execute(sql_update(MessageTemplate).where(MessageTemplate.category == t.category, MessageTemplate.id != t.id)
              .values(is_current=False).execution_options(synchronize_session="fetch"))
    t.is_current = True


def _uses(s: Session, since: datetime | None = None) -> list[tuple[int, str | None, datetime]]:
    """(template_id, channel, when) for every logged message that used a template, on live deals."""
    stmt = (select(Event.template_id, Event.channel, Event.occurred_at)
            .join(Opportunity, Event.opportunity_id == Opportunity.id)
            .where(Event.template_id.is_not(None), Opportunity.archived_at.is_(None)))
    if since:
        stmt = stmt.where(Event.occurred_at >= since)
    return [tuple(r) for r in s.execute(stmt)]


def templates(s: Session, *, include_archived: bool = False, category: str | None = None) -> list[dict]:
    """Every variant with its usage (all time): how often it was sent and on which platform, and — as a
    deal's first message — how those deals did (outbound deals that were sent)."""
    stmt = select(MessageTemplate).order_by(MessageTemplate.category, MessageTemplate.id)
    if not include_archived:
        stmt = stmt.where(MessageTemplate.archived_at.is_(None))
    if category is not None:
        stmt = stmt.where(MessageTemplate.category == _category(s, category).key)
    first = s.scalars(select(Opportunity).where(Opportunity.template_id.is_not(None),
                                                Opportunity.archived_at.is_(None))).unique().all()
    uses = _uses(s)
    out = []
    for t in s.scalars(stmt):
        mine = [o for o in first if o.template_id == t.id and not o.inbound and o.applied_at]
        replied = sum(1 for o in mine if o.replied_at)
        used = [(ch, when) for tid, ch, when in uses if tid == t.id]
        by_channel: dict[str, int] = {}
        for ch, _ in used:
            by_channel[ch or "other"] = by_channel.get(ch or "other", 0) + 1
        out.append(template_dict(t, {
            "uses": len(used), "by_channel": by_channel, "last_used_at": iso(max((w for _, w in used), default=None)),
            "sent": len(mine), "replied": replied, "calls": sum(1 for o in mine if o.call_at),
            "won": sum(1 for o in mine if o.stage == "won"), "reply_rate": round(replied / len(mine), 3) if mine else None}))
    return out


def library(s: Session, category: str | None = None) -> list[dict]:
    """Categories (with their purpose) and their live messages — what an agent reads before sending or editing."""
    rows = [_category(s, category)] if category is not None else categories(s)
    msgs = templates(s, category=category)
    return [{**category_dict(c), "messages": [m for m in msgs if m["category"] == c.key]} for c in rows]


def current_template(s: Session, category: str) -> MessageTemplate:
    c = _category(s, category)
    t = s.scalar(select(MessageTemplate).where(MessageTemplate.category == c.key, MessageTemplate.is_current,
                                               MessageTemplate.archived_at.is_(None)))
    if not t:
        why = "none is picked as current" if _has_messages(s, c.key) else "it has no messages yet"
        raise ServiceError(f"There is no current {c.name} ({why}). Don't write one yourself; tell the owner with "
                           "notify_owner.", 404)
    return t


def current_message(s: Session, category: str) -> dict:
    """What an agent sends from: the current message plus its category's purpose (when to use it)."""
    t = current_template(s, category)
    c = _category(s, category)
    return {**template_dict(t), "category_name": c.name, "purpose": c.purpose}


def _has_messages(s: Session, key: str) -> bool:
    return s.scalar(select(MessageTemplate.id).where(MessageTemplate.category == key,
                                                     MessageTemplate.archived_at.is_(None)).limit(1)) is not None


def create_template(s: Session, actor: Actor, data: dict) -> MessageTemplate:
    if data.get("category") is None:
        raise ServiceError("Pass the category the message belongs to (a key from list_message_templates).")
    c = _category(s, data.get("category"))
    fields = _template_fields(data, c)
    if not fields.get("name") or not fields.get("body"):
        raise ServiceError("A message needs a name and a body.")
    if c.has_subject and not fields.get("subject"):
        raise ServiceError(f"A {c.name} needs a subject line.")
    # An agent's message only goes live by itself as a category's first one: a category the owner left
    # without a current message stays that way until someone picks one.
    first = not _has_messages(s, c.key)
    now = utcnow()
    t = MessageTemplate(category=c.key, created_at=now, **{**fields, "is_current": False})
    _reviewed_by(t, actor)
    s.add(t)
    s.flush()
    has_current = s.scalar(select(MessageTemplate.id).where(MessageTemplate.category == c.key, MessageTemplate.is_current,
                                                            MessageTemplate.archived_at.is_(None)))
    if fields.get("is_current") or (not has_current and (first or not actor.is_agent)):
        _make_current(s, t)
    return t


def update_template(s: Session, actor: Actor, template_id: int, data: dict) -> MessageTemplate:
    t = _template(s, template_id)
    if t.archived_at:
        raise ServiceError("That message is deleted; create a new one instead.")
    if "category" in data and data["category"] != t.category:
        raise ServiceError("A message's category can't change; create a new one in the other category.")
    fields = _template_fields(_seen_version(t, data), _category(s, t.category))
    current = fields.pop("is_current", None)
    if current is False and t.is_current and actor.is_agent:
        raise ServiceError("Only the owner can leave a category with no current message; make another one current instead.")
    changed = {k: v for k, v in fields.items() if getattr(t, k) != v}
    for k, v in changed.items():
        setattr(t, k, v)
    if current and not t.is_current:
        _make_current(s, t)
        changed["is_current"] = True
    elif current is False and t.is_current:
        t.is_current = False
        changed["is_current"] = False
    if changed:
        _reviewed_by(t, actor)
    elif not actor.is_agent:  # a person saving it unchanged ("looks good") has reviewed it
        t.needs_review = False
    return t


def delete_template(s: Session, template_id: int) -> None:
    """A variant nothing live used is removed; one that was sent is archived, so its stats survive."""
    t = _template(s, template_id)
    live = Opportunity.archived_at.is_(None)
    if (s.scalar(select(func.count()).where(Opportunity.template_id == t.id, live))
            or s.scalar(select(func.count()).select_from(Event).join(Opportunity, Event.opportunity_id == Opportunity.id)
                        .where(Event.template_id == t.id, live))):
        t.archived_at, t.is_current, t.needs_review = utcnow(), False, False
    else:
        s.delete(t)


# ---------------------------------------------------------------- notifications

def notify(s: Session, actor: Actor, title: str, message: str | None = None, opportunity_id: int | None = None,
           url: str | None = None) -> tuple[Notification, bool]:
    """An alert for the owner's Alerts inbox. It is its own record (sender + time), not a deal event, and
    doesn't flag the deal for review. Sending the same unread alert again (same title and deal) returns
    the existing one with created=False, so an agent on a schedule doesn't pile up copies."""
    title = (title or "").strip()
    if not title:
        raise ServiceError("title can't be empty.")
    if len(title) > 200:
        raise ServiceError("title is too long (max 200 characters) — put the details in message.")
    message, url = _clean("message", message), _clean("url", url)
    opp = _get(s, opportunity_id) if opportunity_id is not None else None
    existing = s.scalar(select(Notification).where(
        Notification.read_at.is_(None), Notification.title == title,
        Notification.opportunity_id.is_(None) if opp is None else Notification.opportunity_id == opp.id))
    if existing:
        return existing, False
    n = Notification(title=title, body=message, url=url, opportunity=opp, created_by=actor.name, created_at=utcnow())
    s.add(n)
    s.flush()
    return n, True


def notification_dict(n: Notification) -> dict:
    opp = n.opportunity if n.opportunity and not n.opportunity.archived_at else None
    return {"id": n.id, "title": n.title, "message": n.body, "url": n.url,
            "opportunity": {"id": opp.id, "company": opp.company, "title": opp.title} if opp else None,
            "created_by": n.created_by, "created_at": iso(n.created_at), "read_at": iso(n.read_at)}


def notifications(s: Session, *, unread_only: bool = False, limit: int = 200) -> list[Notification]:
    """Unread first, then newest first."""
    stmt = (select(Notification).order_by(Notification.read_at.is_not(None), Notification.id.desc())
            .limit(max(1, min(limit, 500))))
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(s.scalars(stmt).unique().all())


def mark_notifications_read(s: Session, ids: list[int], read: bool = True) -> int:
    rows = s.scalars(select(Notification).where(Notification.id.in_(ids))).unique().all()
    for n in rows:
        if read and not n.read_at:
            n.read_at = utcnow()
        elif not read:
            n.read_at = None
    return len(rows)


# ---------------------------------------------------------------- agent state (durable memory for scheduled agents)
# Rows (ns → section → key), windowed counters, a seen-set and a run log with a lease. Not deal records:
# no Event and no review flag, or 700 runs a day would bury the Review queue. The owner watches the
# State page instead; what needs them still goes through notify_owner.

STATE_CAPS = {k: cap for k, _, cap in domain.STATE_SECTIONS}
STATE_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,59}")
MAX_SEEN_IDS = 500
STATE_PAGE_LIMIT = 2000  # rows on the State page
EXPIRED_LEASE = "Ended without run_end (lease ran out)"
IDEM_TTL = timedelta(hours=24)  # how long a count idem key replays its first reply
MAX_VALUE_DEPTH = 32  # nesting of a JSON value; deeper ones can't be serialized back to readers
SEEN_DAYS = 90  # default ttl_days of a seen id
# Nightly purge (app.backup): idle counter windows after 90 days, runs after 60.
COUNTER_DAYS, RUN_DAYS = 90, 60


def _shown(value: Any) -> str:
    """An input echoed back in an error, cut short so a huge bad value doesn't fill the reply."""
    r = repr(value)
    return r if len(r) <= 60 else r[:57] + "..."


def _name(field: str, value: Any) -> str:
    """Namespaces, workers, sections, sources and counter keys are short lowercase names, so
    "LinkedIn" and "linkedin" can't become two namespaces."""
    v = value.strip().lower() if isinstance(value, str) else None
    if not v or not STATE_NAME.fullmatch(v):
        raise ServiceError(f"{field} must be a short name like 'upwork' or 'linkedin-jobs' "
                           f"(letters, digits, - _ . up to 60; got {_shown(value)}).")
    return v


def _names(field: str, value: Any, limit: int = 20) -> list[str]:
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else None
    if items is None or len(items) > limit:
        raise ServiceError(f"{field} is a name or a list of up to {limit} names.")
    return list(dict.fromkeys(_name(field, v) for v in items))


def _int(field: str, value: Any, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ServiceError(f"{field} must be a whole number from {lo:,} to {hi:,} (got {_shown(value)}).")
    return value


def _moment(s: Session, field: str, value: Any, past: bool = False) -> datetime | None:
    """An ISO time, YYYY-MM-DD, "now", or a duration from now (30m, 12h, 7d; back from now when `past`)."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().lower() == "now":
        return utcnow()
    if isinstance(value, str) and (m := re.fullmatch(r"(\d{1,5})([mhd])", value.strip().lower())):
        delta = timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[m.group(2)]: int(m.group(1))})
        return utcnow() - delta if past else utcnow() + delta
    error = ServiceError(f"{field}: use an ISO time or YYYY-MM-DD (years 1-9999), now, or a duration like 30m, 12h, 7d "
                         f"(got {_shown(value)}).")
    if not isinstance(value, str):
        raise error
    try:
        return parse_when(value, get_timezone(s))
    except ServiceError:
        raise error from None


def _write_lock(s: Session) -> None:
    """Take SQLite's write lock now (a no-op UPDATE). MCP tools run in threads, so a read-then-write
    (a counter, a `max` cursor, a lease) must hold the lock before it reads: then no other request can
    commit in between, and the reads that follow see the latest data."""
    s.execute(text("UPDATE agent_runs SET id = id WHERE 0"))


def _live_rows(now: datetime):
    return or_(StateRow.expires_at.is_(None), StateRow.expires_at > now)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _value_size(value: Any) -> int:
    """Characters of a value (JSON text for non-strings), refusing what readers couldn't get back:
    NaN / Infinity aren't JSON, and very deep nesting can't be serialized."""
    if isinstance(value, str):
        return len(value)
    stack = [(value, 1)]
    while stack:  # iterative: a recursive walk would itself hit Python's recursion limit
        v, depth = stack.pop()
        if isinstance(v, dict | list):
            if depth > MAX_VALUE_DEPTH:
                raise ServiceError(f"value is nested too deeply (max {MAX_VALUE_DEPTH} levels).")
            stack.extend((c, depth + 1) for c in (v.values() if isinstance(v, dict) else v))
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    except ValueError:
        raise ServiceError("value can't contain NaN or Infinity.") from None


def _iso_time(value: str) -> datetime | None:
    if not re.match(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _larger(old: Any, new: Any) -> Any:
    """`max`: numbers compare as numbers, ISO times as times (offsets included), other text as text.
    Mixed kinds are refused: as text "9" > "10", which would move a cursor backwards."""
    num = lambda v: isinstance(v, int | float) and not isinstance(v, bool)  # noqa: E731
    if num(old) and num(new):
        return new if new > old else old
    if isinstance(old, str) and isinstance(new, str):
        a, b = _iso_time(old), _iso_time(new)
        if a and b:
            return new if b > a else old
        return new if new > old else old
    kind = "a number" if num(old) else "text" if isinstance(old, str) else "neither a number nor text"
    raise ServiceError(f"max needs the same kind of value as stored ({kind}): numbers, or text such as ISO times.")


def state_row_dict(r: StateRow, *, full: bool = True) -> dict:
    d = {"value": r.value, "by": r.by, "updated_at": iso(r.updated_at)}
    if r.locked:
        d["locked"] = True
    if r.due_at:
        d["due_at"] = iso(r.due_at)
    if r.expires_at:
        d["expires_at"] = iso(r.expires_at)
    return {"ns": r.ns, "section": r.section, "key": r.key, **d} if full else d


def _apply_change(s: Session, actor: Actor, default_ns: str, ch: Any, now: datetime) -> dict:
    if not isinstance(ch, dict):
        raise ServiceError("Each change is an object {section, key, value, op, due, expires, ns}.")
    unknown = set(ch) - {"ns", "section", "key", "value", "op", "due", "expires", "locked"}
    if unknown:
        raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
    ns = _name("ns", ch["ns"]) if ch.get("ns") is not None else default_ns
    section = _name("section", ch.get("section"))
    fixed = section in STATE_CAPS
    key = ch.get("key").strip() if isinstance(ch.get("key"), str) else ""
    if not key or len(key) > 200:
        raise ServiceError("key is text of 1-200 characters.")
    op = ch.get("op") or "set"
    if op not in get_args(domain.StateOp):
        raise ServiceError(f"op must be one of: {', '.join(get_args(domain.StateOp))} (got {op!r}).")
    has_value = "value" in ch  # omitted on an existing row = keep it (change only due / expires / locked)
    value = ch.get("value")
    if "locked" in ch and (actor.is_agent or not isinstance(ch["locked"], bool)):
        raise ServiceError("Only the owner can lock a row." if actor.is_agent else "locked is true or false.")
    # due / expires: omitted = unchanged, null = cleared.
    when = {f: _moment(s, f, ch[f]) for f in ("due", "expires") if f in ch}
    ref = {"section": section, "key": key, **({"ns": ns} if ns != default_ns else {})}

    row = s.scalar(select(StateRow).where(StateRow.ns == ns, StateRow.section == section, StateRow.key == key))
    live = row if row and (row.expires_at is None or row.expires_at > now) else None  # an expired row counts as gone
    if op != "delete" and not has_value and not live:
        raise ServiceError("value is required for a new row (null deletes a row).")
    deleting = op == "delete" or (has_value and value is None)
    if live and live.locked and actor.is_agent:
        drops = op == "merge" and isinstance(value, dict) and any(v is None for v in value.values())
        if fixed or (op != "merge" and has_value) or deleting or "expires" in when or drops:
            raise ServiceError("owner_row: the owner set this row; " + (
                "agents can only read it." if fixed else "agents may only merge new or updated fields into it, or change its due."))
    if deleting:
        if row:
            s.delete(row)
        return ref
    if not has_value:
        value = live.value
    elif op == "merge":
        if live and live.locked and actor.is_agent and not isinstance(live.value, dict):
            raise ServiceError("owner_row: its value isn't a JSON object, so nothing can be merged into it; change "
                               "only its due, and record the outcome in a row of your own.")
        if not isinstance(value, dict) or (live and not isinstance(live.value, dict)):
            raise ServiceError("merge needs a JSON object, and the stored value must be one; use op=set.")
        value = {k: v for k, v in {**(live.value if live else {}), **value}.items() if v is not None}  # null drops a field
    elif op == "max" and live:
        value = _larger(live.value, value)
    limit = domain.FIXED_VALUE_MAX if fixed else domain.LIST_VALUE_MAX
    if (size := _value_size(value)) > limit:
        raise ServiceError(f"value is too long ({size:,} characters; max {limit:,} in {'fixed section' if fixed else 'a list'} "
                           f"{section!r}). Store less{'' if fixed else ' or split it over keys'}.")
    if not live:
        cap = STATE_CAPS.get(section, domain.LIST_CAP)
        used = s.scalar(select(func.count()).where(StateRow.ns == ns, StateRow.section == section, _live_rows(now)))
        if used >= cap:
            raise ServiceError(f"Section {section!r} is full ({cap} rows in {ns!r}); delete one first.")
    keep = lambda f, col: when[f] if f in when else getattr(live, col) if live else None  # noqa: E731
    fields = {"value": value, "due_at": keep("due", "due_at"), "expires_at": keep("expires", "expires_at"),
              "locked": ch["locked"] if "locked" in ch else bool(live.locked) if live else not actor.is_agent,
              # An agent merging into an owner row leaves it the owner's.
              "by": live.by if live and live.locked and actor.is_agent else _agent_name(actor) if actor.is_agent else "owner",
              "updated_at": now}
    if row:
        for k, v in fields.items():
            setattr(row, k, v)
    else:
        s.add(StateRow(ns=ns, section=section, key=key, **fields))
    s.flush()  # the next change's cap count sees this row
    return {**ref, "value": value} if op == "max" and has_value and value != ch.get("value") else ref


def _agent_name(actor: Actor) -> str:
    """`by: owner` means the owner wrote it, so an agent (token) named "owner" can't pass as them."""
    return f"{actor.name} (agent)" if actor.name.strip().lower() == "owner" else actor.name


def state_set(s: Session, actor: Actor, ns: str, changes: Any) -> dict:
    """Applies each valid change and rejects the rest one by one, with the reason. ops: set replaces;
    merge shallow-merges into a JSON object (null drops a field); max keeps the larger value, so cursor
    writes never go backwards; delete (or value null) removes. All under the write lock, so concurrent
    workers never lose a merge or a cursor advance. Owner (locked) rows: see _apply_change."""
    ns = _name("ns", ns)
    if not isinstance(changes, list) or not 1 <= len(changes) <= 100:
        raise ServiceError("changes is a list of 1-100 {section, key, value, op, due, expires, ns}.")
    _write_lock(s)
    now = utcnow()
    applied, rejected = [], []
    for i, ch in enumerate(changes):
        try:
            applied.append(_apply_change(s, actor, ns, ch, now))
        except ServiceError as e:
            where = {k: ch[k] for k in ("ns", "section", "key") if isinstance(ch, dict) and isinstance(ch.get(k), str)}
            rejected.append({"index": i, **where, "reason": e.message})  # index: its place in `changes`
    return {k: v for k, v in {"applied": applied, "rejected": rejected}.items() if v}


def state_rows(s: Session, ns: list[str] | None = None, sections: list[str] | None = None, keys: list[str] | None = None,
               q: str | None = None, due_before: datetime | None = None, limit: int = STATE_PAGE_LIMIT) -> list[StateRow]:
    """Live rows, ordered ns → section → due_at (earliest first, undated last) → key. A filter list of None
    means any, an empty list means none. `q` matches a case-insensitive substring of the key or value;
    `due_before` keeps rows due at or before it."""
    stmt = select(StateRow).where(_live_rows(utcnow()))
    if ns is not None:
        stmt = stmt.where(StateRow.ns.in_(ns))
    if sections is not None:
        stmt = stmt.where(StateRow.section.in_(sections))
    if keys is not None:
        stmt = stmt.where(StateRow.key.in_(keys))
    if due_before:
        stmt = stmt.where(StateRow.due_at <= due_before)
    if q and q.strip():
        # casefold() is registered on every connection (app.db); values are stored as JSON text, so the
        # needle is JSON-escaped too, which finds text with quotes or newlines in it.
        needle = q.strip().casefold()
        escaped = json.dumps(needle, ensure_ascii=False)[1:-1]
        stmt = stmt.where(or_(func.instr(func.casefold(StateRow.key), needle) > 0,
                              func.instr(func.casefold(type_coerce(StateRow.value, String)), escaped) > 0))
    order = (StateRow.ns, StateRow.section, StateRow.due_at.asc().nulls_last(), StateRow.key)
    return list(s.scalars(stmt.order_by(*order).limit(limit)))


def _bucket(period: str, now: datetime) -> str:
    """The current window of a counter, in UTC. Weeks are ISO weeks."""
    if period == "day":
        return now.date().isoformat()
    if period == "week":
        y, w, _ = now.isocalendar()
        return f"{y}-W{w:02d}"
    return now.strftime("%Y-%m") if period == "month" else "all"


def _current_counters(s: Session, ns: list[str], now: datetime) -> dict:
    """{ns: {key: {period: value}}} for the windows in force now."""
    windows = [and_(StateCounter.period == p, StateCounter.bucket == _bucket(p, now)) for p in get_args(domain.CounterPeriod)]
    out: dict[str, dict] = {}
    for c in s.scalars(select(StateCounter).where(StateCounter.ns.in_(ns), or_(*windows)).order_by(StateCounter.key)):
        out.setdefault(c.ns, {}).setdefault(c.key, {})[c.period] = c.value
    return out


def count(s: Session, items: Any, idem: Any = None) -> dict:
    """Spend (by > 0), read (by 0) or give back (by < 0, never below 0) counters, all or nothing: if any
    spend would pass its limit, or the call spends while any of its ns has a `stop` row, nothing changes. Limits come from
    the caller; the server stores no policy. With `idem`, a repeat within 24 hours replays the first
    successful reply instead of spending again (a refusal spent nothing, so it is never replayed)."""
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ServiceError("items is a list of 1-20 {ns, key, period, by, limit}.")
    if idem is not None and (not isinstance(idem, str) or not 0 < len(idem.strip()) <= 200):
        raise ServiceError("idem is a unique text key per action, up to 200 characters.")
    periods = get_args(domain.CounterPeriod)
    parsed = []
    for it in items:
        if not isinstance(it, dict) or set(it) - {"ns", "key", "period", "by", "limit"}:
            raise ServiceError("Each item is {ns, key, period, by, limit}.")
        period = it.get("period") or "day"
        if period not in periods:
            raise ServiceError(f"period must be one of: {', '.join(periods)} (got {period!r}).")
        limit = it.get("limit")
        parsed.append((_name("ns", it.get("ns")), _name("key", it.get("key")), period,
                       _int("by", it.get("by", 1), -100_000, 100_000),
                       None if limit is None else _int("limit", limit, 0, 10_000_000)))
    _write_lock(s)
    now = utcnow()
    idents = {(ns, key, period, _bucket(period, now)) for ns, key, period, _, _ in parsed}
    rows = {(c.ns, c.key, c.period, c.bucket): c for c in s.scalars(select(StateCounter).where(
        or_(*(and_(StateCounter.ns == i[0], StateCounter.key == i[1], StateCounter.period == i[2], StateCounter.bucket == i[3])
              for i in idents))))}
    values = {i: rows[i].value if i in rows else 0 for i in idents}
    start = dict(values)
    reply = lambda ok_each, extra: {  # noqa: E731
        "ok": not extra, **extra, "counters": [
            {"ns": ns, "key": key, "period": period, "value": values[(ns, key, period, _bucket(period, now))], "allowed": ok}
            for (ns, key, period, _, _), ok in zip(parsed, ok_each, strict=True)]}

    # A halt beats everything, even a replay: a call that spends is refused while any of its namespaces has
    # a stop. Reads and give-backs still pass (an agent can check its budget or return what it didn't use);
    # their reply names the stop, and a read shows no room.
    stops = s.scalars(select(StateRow).where(StateRow.ns.in_({p[0] for p in parsed}), StateRow.section == "stop",
                                             _live_rows(now)).order_by(StateRow.ns, StateRow.key)).all()
    stopped = "; ".join(f"{r.ns} {r.key}: {_text(r.value)}" for r in stops)
    if stopped and any(p[3] > 0 for p in parsed):
        return reply([False] * len(parsed), {"stopped": stopped})
    # Scoped to this exact call: the same idem with other items (another agent, another cap) is a new call.
    # A pure read changes nothing, so it is never replayed (that would show a stale value).
    changes_something = any(p[3] != 0 for p in parsed)
    key = hashlib.sha256(json.dumps([idem.strip(), parsed]).encode()).hexdigest() if idem and changes_something else None
    if key and (prev := s.get(IdemKey, key)) and prev.created_at > now - IDEM_TTL:
        return prev.response

    allowed, refused = [], []
    for ns, k, period, by, limit in parsed:
        ident = (ns, k, period, _bucket(period, now))
        before = values[ident]
        ok = limit is None or by < 0 or before + max(by, 1) <= limit  # a read (by 0): is there room for one more?
        ok = ok and not (stopped and by == 0)  # not while spending is stopped
        allowed.append(ok)
        if by > 0 and not ok:
            refused.append(f"{ns} {k} ({period}) is at {before} of {limit}")
        values[ident] = max(0, before + by)
    if refused:
        values = start
        return reply(allowed, {"refused": "Nothing counted: " + "; ".join(refused) + "."})
    for ident, v in values.items():
        if v == start[ident]:
            continue
        if ident in rows:
            rows[ident].value, rows[ident].updated_at = v, now
        else:
            s.add(StateCounter(ns=ident[0], key=ident[1], period=ident[2], bucket=ident[3], value=v, updated_at=now))
    out = {**reply(allowed, {}), **({"stopped": stopped} if stopped else {})}
    if key:
        s.merge(IdemKey(key=key, response=out, created_at=now))
    return out


def seen(s: Session, ns: str, source: str, ids: Any, mark: bool = True, ttl_days: int = SEEN_DAYS) -> dict:
    """Which of these item ids weren't seen in ns+source (or their ttl ran out); marks them seen for
    `ttl_days` unless mark=False."""
    ns, source = _name("ns", ns), _name("source", source)
    ttl_days = _int("ttl_days", ttl_days, 1, 3650)
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_SEEN_IDS:
        raise ServiceError(f"ids is a list of 1-{MAX_SEEN_IDS} item ids.")
    if any(isinstance(i, bool) or not isinstance(i, str | int) or not str(i).strip() or len(str(i).strip()) > 300 for i in ids):
        raise ServiceError("Each id is text or a number, up to 300 characters.")
    given: dict[str, Any] = {}  # repeats in one call count once; ids come back as the caller sent them
    for i in ids:
        given.setdefault(str(i).strip(), i if isinstance(i, int) else str(i).strip())
    uniq = list(given)
    now = utcnow()
    if mark:
        # One statement: a never-seen id is inserted, an expired one renewed, a live one left alone — and
        # RETURNING lists exactly the first two, even with a concurrent call.
        expires = now + timedelta(days=ttl_days)
        stmt = sqlite_insert(SeenItem).values([{"ns": ns, "source": source, "item_id": i, "expires_at": expires} for i in uniq])
        new = set(s.scalars(stmt.on_conflict_do_update(
            index_elements=["ns", "source", "item_id"], set_={"expires_at": expires},
            where=SeenItem.expires_at <= now).returning(SeenItem.item_id)))
    else:
        new = set(uniq) - set(s.scalars(select(SeenItem.item_id).where(
            SeenItem.ns == ns, SeenItem.source == source, SeenItem.item_id.in_(uniq), SeenItem.expires_at > now)))
    return {"new": [given[i] for i in uniq if i in new]}


def _close_expired_runs(s: Session, now: datetime, ns: str | None = None, worker: str | None = None) -> None:
    """A run that never called run_end ends (as an error) when its lease runs out."""
    stmt = sql_update(AgentRun).where(AgentRun.ended_at.is_(None), AgentRun.lease_until <= now)
    if ns is not None:
        stmt = stmt.where(AgentRun.ns == ns, AgentRun.worker == worker)
    s.execute(stmt.values(ended_at=AgentRun.lease_until, status="error", summary=EXPIRED_LEASE)
              .execution_options(synchronize_session=False))


def run_dict(r: AgentRun, now: datetime | None = None) -> dict:
    now = now or utcnow()
    expired = r.ended_at is None and r.lease_until <= now  # not closed yet: shown as it will be
    ended = r.lease_until if expired else r.ended_at
    return {"id": r.id, "ns": r.ns, "worker": r.worker, "started_at": iso(r.started_at), "ended_at": iso(ended),
            "lease_until": iso(r.lease_until),
            "status": "error" if expired else r.status or "running",
            "summary": EXPIRED_LEASE if expired else r.summary, "counts": r.counts or {}}


def run_start(s: Session, ns: str, worker: str = "main", also: Any = None, include: Any = None, lease_min: int = 50) -> dict:
    """Start a run: takes the ns+worker lease (busy=true if a live run holds it) and returns the brief —
    this ns's fixed sections, list names with row counts, stops from the `also` namespaces, which of those
    rows are the owner's, current counters of ns and also, this worker's last run, and for each `include`
    list its rows due now (earliest first, up to 50)."""
    ns, worker = _name("ns", ns), _name("worker", worker or "main")
    also = [a for a in _names("also", also or [], limit=10) if a != ns]
    include = _names("include", include or [], limit=10)
    if fixed := [x for x in include if x in STATE_CAPS]:
        raise ServiceError(f"include takes list sections; {', '.join(fixed)} already come in the brief.")
    lease_min = _int("lease_min", lease_min, 1, 24 * 60)
    _write_lock(s)  # two run_starts at once: the second waits, then sees the first one's run
    now = utcnow()
    _close_expired_runs(s, now, ns, worker)
    where = (AgentRun.ns == ns, AgentRun.worker == worker)
    if live := s.scalar(select(AgentRun).where(*where, AgentRun.ended_at.is_(None))):
        return {"busy": True, "now": iso(now), "started_at": iso(live.started_at), "lease_until": iso(live.lease_until)}
    last = s.scalar(select(AgentRun).where(*where, AgentRun.ended_at.is_not(None)).order_by(AgentRun.started_at.desc()).limit(1))
    run = AgentRun(ns=ns, worker=worker, started_at=now, lease_until=now + timedelta(minutes=lease_min))
    s.add(run)
    s.flush()

    state: dict[str, dict] = {}
    stops: dict[str, dict] = {}
    owner: dict[str, dict] = {}  # ns → section → keys of owner rows in this brief
    for r in [*state_rows(s, [ns], list(STATE_CAPS)), *state_rows(s, also, ["stop"])]:
        (state.setdefault(r.section, {}) if r.ns == ns else stops.setdefault(r.ns, {}))[r.key] = r.value
        if r.locked:
            owner.setdefault(r.ns, {}).setdefault(r.section, []).append(r.key)
    lists = dict(s.execute(select(StateRow.section, func.count()).where(
        StateRow.ns == ns, StateRow.section.not_in(list(STATE_CAPS)), _live_rows(now)).group_by(StateRow.section)).all())
    due = {x: [{"key": r.key, **state_row_dict(r, full=False)} for r in state_rows(s, [ns], [x], due_before=now, limit=50)]
           for x in include}
    brief = {"run_id": run.id, "now": iso(now), "state": state, "owner": owner, "lists": lists, "also": stops,
             "counters": _current_counters(s, [ns, *also], now),
             "last": {k: v for k, v in {"status": last.status, "summary": last.summary, "ended_at": iso(last.ended_at)}.items()
                      if v is not None} if last else None,
             "include": {x: rows for x, rows in due.items() if rows}}
    return {k: v for k, v in brief.items() if v}


def _summary_line(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ServiceError("summary is one line of text.")
    line = " ".join(value.split())  # one line
    if len(line) > 500:
        raise ServiceError("summary is too long (max 500 characters) — one line saying what happened.")
    return line or None


def _counts(value: Any) -> dict | None:
    if value is None:
        return None
    ok = isinstance(value, dict) and len(value) <= 30 and all(
        isinstance(k, str) and 0 < len(k) <= 40 and isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)
        for k, v in value.items())
    if not ok:
        raise ServiceError('counts is an object of up to 30 numbers, e.g. {"applied": 3, "skipped": 12}.')
    return value or None


def run_end(s: Session, actor: Actor, run_id: Any, status: str, summary: Any = None, counts: Any = None,
            changes: Any = None) -> dict:
    """End a run: record how it went, apply its state changes (as state_set on the run's ns) and free the
    lease. Idempotent per run: a repeat call (a retry after a timeout) returns the first reply and applies
    nothing. A run closed because its lease ran out can still be ended once with its real outcome."""
    missing = ServiceError(f"Run {_shown(run_id)} not found — pass the run_id run_start returned.", 404)
    if isinstance(run_id, bool) or not isinstance(run_id, int) or not 0 < run_id < 2**63:
        raise missing
    if status not in {k for k, _ in domain.RUN_STATUSES}:
        raise ServiceError(f"status must be one of: {', '.join(k for k, _ in domain.RUN_STATUSES)} (got {status!r}).")
    summary, counts = _summary_line(summary), _counts(counts)
    _write_lock(s)  # read the run under the lock: a concurrent repeat may have just ended it
    if not (run := s.get(AgentRun, run_id)):
        raise missing
    if run.result is not None:
        return run.result
    result = {"run_id": run.id, "ended": True, **(state_set(s, actor, run.ns, changes) if changes else {})}
    run.ended_at, run.status, run.summary, run.counts, run.result = utcnow(), status, summary, counts, result
    return result


def runs(s: Session, *, ns: str | None = None, statuses: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Newest first, for the Runs list. `statuses` may include "running"."""
    now = utcnow()
    stmt = select(AgentRun).order_by(AgentRun.id.desc()).limit(max(1, min(limit, 500)))
    if ns:
        stmt = stmt.where(AgentRun.ns == ns.strip().lower())
    if statuses:
        live, lapsed = and_(AgentRun.ended_at.is_(None), AgentRun.lease_until > now), and_(AgentRun.ended_at.is_(None), AgentRun.lease_until <= now)
        match = [AgentRun.status.in_(statuses)]
        if "running" in statuses:
            match.append(live)
        if "error" in statuses:  # a run whose lease ran out shows as an error before anyone closes it
            match.append(lapsed)
        stmt = stmt.where(or_(*match))
    return [run_dict(r, now) for r in s.scalars(stmt)]


def run_digest(s: Session, since: datetime, ns: list[str] | None = None) -> dict:
    """Per ns → worker: how many runs, how many per status, summed counts, and the latest 20 summaries
    of runs that weren't quiet (never the raw run list)."""
    stmt = select(AgentRun).where(AgentRun.started_at >= since).order_by(AgentRun.started_at)
    if ns:
        stmt = stmt.where(AgentRun.ns.in_(ns))
    now = utcnow()
    out: dict[str, dict] = {}
    for r in s.scalars(stmt):
        d = run_dict(r, now)
        g = out.setdefault(r.ns, {}).setdefault(r.worker, {"runs": 0, "status": {}, "counts": {}, "notes": []})
        g["runs"] += 1
        g["status"][d["status"]] = g["status"].get(d["status"], 0) + 1
        for k, v in d["counts"].items():
            g["counts"][k] = g["counts"].get(k, 0) + v
        if d["status"] != "quiet" and d["summary"]:
            g["notes"].append({"at": d["started_at"], "status": d["status"], "summary": d["summary"]})
    for workers in out.values():
        for g in workers.values():
            g["notes"] = g["notes"][-20:]
            for k in ("counts", "notes"):
                if not g[k]:
                    del g[k]
    return out


def state_get(s: Session, ns: Any, sections: Any = None, keys: Any = None, q: str | None = None,
              due_before: Any = None, limit: Any = 100, runs_since: Any = None) -> dict:
    """Rows grouped ns → section → key (ns may be a name, a list, or "*" for all), each section's rows
    earliest due first. With runs_since, a run digest too; then rows come back only if sections, keys, q
    or due_before were also given."""
    nss = None if ns == "*" else _names("ns", ns)
    sections = _names("sections", sections, limit=50) if sections is not None else None
    if keys is not None and (not isinstance(keys, list) or len(keys) > 500 or not all(isinstance(k, str) for k in keys)):
        raise ServiceError("keys is a list of up to 500 keys.")
    keys = [k.strip() for k in keys] if keys is not None else None  # stored keys are stripped
    if q is not None and not isinstance(q, str):
        raise ServiceError("q is text.")
    limit = _int("limit", limit, 1, 500)
    due = _moment(s, "due_before", due_before)
    since = _moment(s, "runs_since", runs_since, past=True)
    out: dict[str, Any] = {}
    if since is None or sections is not None or keys is not None or due or (q and q.strip()):
        rows = state_rows(s, nss, sections, keys, q, due, limit=limit + 1)
        grouped: dict[str, dict] = {}
        for r in rows[:limit]:
            grouped.setdefault(r.ns, {}).setdefault(r.section, {})[r.key] = state_row_dict(r, full=False)
        out["state"] = grouped
        if len(rows) > limit:
            out["more"] = True  # raise limit (max 500) or narrow with sections, keys, q or due_before
    if since is not None:
        out["runs"] = run_digest(s, since, nss)
    return out


def state_page(s: Session, ns: str | None = None, section: str | None = None, q: str | None = None,
               limit: int = STATE_PAGE_LIMIT) -> dict:
    """The State page: rows (flat, ns → section order), `more` when cut at `limit`, plus the overview."""
    limit = _int("limit", limit, 0, STATE_PAGE_LIMIT)
    rows = state_rows(s, [_name("ns", ns)] if ns else None, [_name("section", section)] if section else None,
                      q=q, limit=limit + 1) if limit else []
    return {"rows": [state_row_dict(r) for r in rows[:limit]], "more": len(rows) > limit, **state_overview(s)}


def state_overview(s: Session) -> dict:
    """For the State page's filters: every namespace with rows or runs, the sections in use, and the
    current counters."""
    now = utcnow()
    namespaces = sorted(set(s.scalars(select(StateRow.ns).where(_live_rows(now)).distinct()))
                        | set(s.scalars(select(AgentRun.ns).distinct()))
                        | set(s.scalars(select(StateCounter.ns).distinct())))
    used = set(s.scalars(select(StateRow.section).where(_live_rows(now)).distinct()))
    return {"namespaces": namespaces, "sections": [*STATE_CAPS, *sorted(used - set(STATE_CAPS))],
            "counters": _current_counters(s, namespaces, now)}


def forget_namespace(s: Session, ns: str) -> int:
    """The owner retires an agent: its rows, counters, seen ids and runs all go. Returns rows deleted."""
    ns = _name("ns", ns)
    return sum(s.execute(sql_delete(m).where(m.ns == ns)).rowcount for m in (StateRow, StateCounter, SeenItem, AgentRun))


def purge_state(s: Session) -> None:
    """Nightly: drop expired rows, seen ids and idem keys, idle counter windows and old runs; close crashed runs."""
    now = utcnow()
    _close_expired_runs(s, now)
    s.execute(sql_delete(StateRow).where(StateRow.expires_at <= now))
    s.execute(sql_delete(SeenItem).where(SeenItem.expires_at <= now))
    s.execute(sql_delete(IdemKey).where(IdemKey.created_at <= now - IDEM_TTL))
    s.execute(sql_delete(StateCounter).where(StateCounter.period != "total",
                                             StateCounter.updated_at < now - timedelta(days=COUNTER_DAYS)))
    s.execute(sql_delete(AgentRun).where(AgentRun.ended_at.is_not(None), AgentRun.started_at < now - timedelta(days=RUN_DAYS)))


# ---------------------------------------------------------------- agenda / insights

def agenda(s: Session) -> dict:
    """What to do today, in priority order. Shared by the Today screen and the agents."""
    tz = get_timezone(s)
    now = utcnow()
    local_today = datetime.now(tz).date()
    end_of_today = datetime.combine(local_today + timedelta(days=1), time()).replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
    week_end = end_of_today + timedelta(days=7)
    active = Opportunity.archived_at.is_(None)

    due = s.execute(
        select(Reminder, Opportunity).join(Opportunity)
        .where(Reminder.done_at.is_(None), Reminder.due_at < end_of_today, active)
        .order_by(Reminder.due_at)
    ).all()
    upcoming = s.execute(
        select(Reminder, Opportunity).join(Opportunity)
        .where(Reminder.done_at.is_(None), Reminder.due_at >= end_of_today, Reminder.due_at < week_end, active)
        .order_by(Reminder.due_at)
    ).all()
    open_opps = s.scalars(select(Opportunity).where(active, Opportunity.stage.in_(domain.OPEN_STAGES))).unique().all()

    your_move = sorted((o for o in open_opps if o.waiting_on == "me"), key=lambda o: o.last_activity_at)
    quiet = []
    for o in open_opps:
        if o.stage == "lead" or o.waiting_on == "me" or any(not r.done_at for r in o.reminders):
            continue
        idle = (now - o.last_activity_at).days
        if idle >= domain.QUIET_AFTER_DAYS[o.stage]:
            quiet.append({**summary(o), "idle_days": idle})
    quiet.sort(key=lambda d: -d["idle_days"])
    leads = sorted((o for o in open_opps if o.stage == "lead"),
                   key=lambda o: (-(o.fit or 0), -o.id))

    def rem(r: Reminder, o: Opportunity) -> dict:
        return {**reminder_dict(r), "overdue": r.due_at < now, "opportunity": summary(o)}

    return {
        "today": local_today.isoformat(),
        "timezone": str(tz),
        "due_reminders": [rem(r, o) for r, o in due],
        "your_move": [summary(o) for o in your_move],
        "gone_quiet": quiet,
        "new_leads": [summary(o) for o in leads[:30]],
        "new_leads_total": len(leads),
        "upcoming": [rem(r, o) for r, o in upcoming],
        "needs_review": s.scalar(select(func.count()).where(Opportunity.needs_review.is_(True), active)) or 0,
        "unread_notifications": s.scalar(select(func.count()).where(Notification.read_at.is_(None))) or 0,
        "messages_need_review": sum(s.scalar(select(func.count()).where(m.needs_review.is_(True), m.archived_at.is_(None))) or 0
                                    for m in (MessageCategory, MessageTemplate)),
    }


def stats(s: Session, days: int | None = 90) -> dict:
    """Funnel per channel/network for outbound work applied to in the window, plus the open
    pipeline and a 12-week activity series."""
    now = utcnow()
    since = now - timedelta(days=days) if days else datetime.min
    all_opps = s.scalars(select(Opportunity).where(Opportunity.archived_at.is_(None))).unique().all()
    cohort = [o for o in all_opps if o.applied_at and o.applied_at >= since]

    def funnel(rows: list[Opportunity]) -> dict:
        out = [o for o in rows if not o.inbound]
        n = len(out)
        replied = sum(1 for o in out if o.replied_at)
        won = [o for o in rows if o.stage == "won"]
        reply_days = sorted((o.replied_at - o.applied_at).total_seconds() / 86400 for o in out
                            if o.replied_at and o.applied_at and o.replied_at >= o.applied_at)
        return {
            "applied": n,
            "replied": replied,
            "calls": sum(1 for o in out if o.call_at),
            "proposals": sum(1 for o in out if o.proposal_at),
            "won": len(won),
            "won_value": sum(o.value or 0 for o in won),
            "reply_rate": round(replied / n, 3) if n else None,
            "win_rate": round(sum(1 for o in out if o.stage == "won") / n, 3) if n else None,
            "median_days_to_reply": round(statistics.median(reply_days), 1) if reply_days else None,
            "inbound": sum(1 for o in rows if o.inbound),
        }

    def grouped(attr: str, options: list[tuple[str, str]]) -> list[dict]:
        rows = []
        for key, lbl in options:
            group = [o for o in cohort if getattr(o, attr) == key]
            if group:
                rows.append({"key": key, "label": lbl, **funnel(group)})
        return rows

    tz = get_timezone(s)
    this_monday = datetime.now(tz).date() - timedelta(days=datetime.now(tz).weekday())
    weeks = []
    for i in range(11, -1, -1):
        start_local = this_monday - timedelta(weeks=i)
        start = datetime.combine(start_local, time()).replace(tzinfo=tz).astimezone(UTC).replace(tzinfo=None)
        end = start + timedelta(weeks=1)
        within = lambda d, start=start, end=end: d is not None and start <= d < end  # noqa: E731
        weeks.append({
            "week": start_local.isoformat(),
            "applied": sum(1 for o in all_opps if within(o.applied_at) and not o.inbound),
            "replies": sum(1 for o in all_opps if within(o.replied_at)),
            "won": sum(1 for o in all_opps if o.stage == "won" and within(o.closed_at)),
        })

    def by_value(key_fn, label_fn) -> list[dict]:
        keys = sorted({k for o in cohort if (k := key_fn(o)) is not None}, key=str)
        rows = [{"key": str(k), "label": label_fn(k), **funnel([o for o in cohort if key_fn(o) == k])} for k in keys]
        return sorted(rows, key=lambda r: -r["applied"])

    variants = {t.id: t for t in s.scalars(select(MessageTemplate))}
    category_names = {c.key: c.name for c in s.scalars(select(MessageCategory))}

    def variant_label(tid: int) -> str:
        t = variants.get(tid)
        if not t:
            return f"#{tid}"
        return f"{category_names.get(t.category, t.category)} · {t.name}" + (" (deleted)" if t.archived_at else "")

    # How often each template was used in the window, per platform it went out on.
    usage: dict[int, dict[str, int]] = {}
    for tid, ch, _ in _uses(s, since if days else None):
        usage.setdefault(tid, {})
        usage[tid][ch or "other"] = usage[tid].get(ch or "other", 0) + 1

    open_opps = [o for o in all_opps if o.stage in domain.OPEN_STAGES]
    return {
        "days": days,
        "overall": funnel(cohort),
        "by_channel": grouped("channel", domain.CHANNELS),
        "by_network": grouped("network", domain.NETWORKS),
        "by_kind": grouped("kind", domain.KINDS),
        "by_template": by_value(lambda o: o.template_id, variant_label),
        "by_resume_version": by_value(lambda o: o.resume_version, str),
        "template_usage": sorted(
            ({"key": str(tid), "label": variant_label(tid), "category": variants[tid].category if tid in variants else None,
              "uses": sum(chs.values()),
              "by_channel": [{"key": k, "label": lbl, "count": chs[k]} for k, lbl in domain.CHANNELS if chs.get(k)]}
             for tid, chs in usage.items()),
            key=lambda r: -r["uses"]),
        # Every deal that died in the window, including leads you passed on — not just the applied cohort.
        "lost_reasons": [{"key": k, "label": lbl, "count": n} for k, lbl in domain.LOST_REASONS
                         if (n := sum(1 for o in all_opps if o.stage == "lost" and o.lost_reason == k
                                      and o.closed_at and o.closed_at >= since))],
        "open_by_stage": [{"stage": k, "label": lbl, "count": sum(1 for o in open_opps if o.stage == k),
                           "value": sum(o.value or 0 for o in open_opps if o.stage == k)}
                          for k, lbl in domain.STAGES if k in domain.OPEN_STAGES],
        "weekly": weeks,
    }


def activity_feed(s: Session, *, limit: int = 100, actor_type: str | None = None, before_id: int | None = None) -> list[dict]:
    stmt = (select(Event, Opportunity).join(Opportunity, Event.opportunity_id == Opportunity.id)
            .where(Opportunity.archived_at.is_(None))
            .order_by(Event.id.desc()).limit(max(1, min(limit, 300))))
    if actor_type:
        stmt = stmt.where(Event.actor_type == actor_type)
    if before_id:
        stmt = stmt.where(Event.id < before_id)
    return [event_dict(e, o) for e, o in s.execute(stmt).all()]
