"""All business logic. The REST API (humans) and the MCP server (agents) are thin adapters over
these functions, so both always behave identically — including the audit trail and the review
flag: anything an agent writes is marked `needs_review` until a human looks at it."""

import math
import re
import statistics
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import domain
from app.db import iso, utcnow
from app.models import Event, Notification, Opportunity, Reminder, Setting


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
    return dt.astimezone(UTC).replace(tzinfo=None)


URL_FIELDS = ("application_url", "company_url", "contact_url", "url")
# Long enough for any real job post; bounded so one bad agent call can't store megabytes.
MAX_LEN = {"description": 50_000, "notes": 20_000, "message": 10_000}


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
            raise ServiceError("value must be a positive number in USD.")
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
           changes: dict | None = None, occurred_at: datetime | None = None) -> Event:
    ev = Event(opportunity_id=opp.id, kind=kind, body=body, changes=changes, actor_type=actor.type,
               actor_name=actor.name, occurred_at=occurred_at or utcnow())
    s.add(ev)
    return ev


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
         "actor_type": e.actor_type, "actor_name": e.actor_name, "occurred_at": iso(e.occurred_at)}
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
    values.setdefault("channel", channel_for_url(values.get("application_url")) or "other")
    values.setdefault("stage", "lead")
    if "company" not in values:
        raise ServiceError("company is required.")
    _check_stage(values["stage"], values["channel"])
    _check_lost(values["stage"], values.get("lost_reason"))
    now = utcnow()
    opp = Opportunity(**values, url_key=url_key(values.get("application_url")), created_by=actor.name,
                      needs_review=actor.is_agent, created_at=now, updated_at=now, last_activity_at=now)
    if opp.waiting_on is None:
        opp.waiting_on = _default_waiting(opp.stage)
    _stamp_milestones(opp, opp.stage, now)
    try:
        with s.begin_nested():  # two agents adding the same posting at once: the loser gets the winner's row
            s.add(opp)
            s.flush()
    except IntegrityError:
        if existing := find_duplicate(s, data.get("application_url")):
            return existing, False
        raise
    _event(s, opp, actor, "created", None, {k: [None, v] for k, v in values.items()
                                            if k not in ("description", "notes")})
    if data.get("reminder_at"):
        add_reminder(s, actor, opp.id, data["reminder_at"], data.get("reminder_note") or "Follow up")
    return opp, True


def _check_stage(stage: str, channel: str) -> None:
    if stage == "matcher" and channel != "toptal":
        raise ServiceError("'Sent to matcher' only applies to Toptal opportunities.")


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
    _event(s, opp, actor, "updated", None, logged)
    return opp


def archive(s: Session, actor: Actor, opp_id: int) -> None:
    opp = _get(s, opp_id)
    opp.archived_at = utcnow()
    _event(s, opp, actor, "updated", "Deleted")


def log_activity(s: Session, actor: Actor, opp_id: int, kind: str, body: str | None,
                 occurred_at: str | datetime | None = None) -> Opportunity:
    """Record something that happened and move the deal along the obvious way:
    a client message → stage Replied (if earlier) and it's your move; your message → their move;
    a call → stage Call booked (if earlier)."""
    if kind not in {k for k, _ in domain.ACTIVITY_KINDS}:
        raise ServiceError(f"kind must be one of: {', '.join(k for k, _ in domain.ACTIVITY_KINDS)}.")
    opp = _get(s, opp_id)
    when = parse_when(occurred_at, get_timezone(s)) or utcnow()
    if when > utcnow() + timedelta(minutes=10):
        raise ServiceError("occurred_at is in the future — log things when they happen. For a call that's booked "
                           "for later, log kind='call' now and set_reminder for the call time.")
    order = domain.STAGE_ORDER
    before = {"stage": opp.stage, "waiting_on": opp.waiting_on, "inbound": opp.inbound, "lost_reason": opp.lost_reason}
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
    _event(s, opp, actor, kind, (body or "").strip() or None, changes or None, occurred_at=when)
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

    open_opps = [o for o in all_opps if o.stage in domain.OPEN_STAGES]
    return {
        "days": days,
        "overall": funnel(cohort),
        "by_channel": grouped("channel", domain.CHANNELS),
        "by_network": grouped("network", domain.NETWORKS),
        "by_kind": grouped("kind", domain.KINDS),
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
