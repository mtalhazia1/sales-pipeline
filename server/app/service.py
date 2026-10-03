"""All business logic. The REST API (humans) and the MCP server (agents) are thin adapters over
these functions, so both always behave identically — including the audit trail and the review
flag: anything an agent writes is marked `needs_review` until a human looks at it."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import domain
from app.db import iso, utcnow
from app.models import Event, Opportunity, Reminder, Setting


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
TRACKING_PARAMS = re.compile(r"^(utm_.*|trk.*|ref|refid|referrer|source|src|fbclid|gclid|tracking.*|origin|lipi|mcid)$", re.I)


def get_timezone(s: Session) -> ZoneInfo:
    row = s.get(Setting, "timezone")
    try:
        return ZoneInfo(row.value if row else "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def url_key(url: str | None) -> str | None:
    """Canonical identity of a posting so the same job can't be added twice
    (agents re-find the same posts constantly)."""
    if not url or not url.strip():
        return None
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    query = dict(parse_qsl(parts.query))
    if host.endswith("upwork.com") and (m := re.search(r"~0[0-9a-z]+", path, re.I)):
        return f"upwork:{m.group(0).lower()}"
    if host.endswith("linkedin.com"):
        if m := re.search(r"/jobs/view/(?:[^/]*-)?(\d+)", path):
            return f"linkedin-job:{m.group(1)}"
        if query.get("currentJobId", "").isdigit():
            return f"linkedin-job:{query['currentJobId']}"
    kept = sorted((k, v) for k, v in query.items() if not TRACKING_PARAMS.match(k))
    return f"{host}{path}" + (f"?{urlencode(kept)}" if kept else "")


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
            if len(text) == 10:
                dt = datetime.combine(date.fromisoformat(text), time(default_hour))
            else:
                dt = datetime.fromisoformat(text)
        except ValueError as e:
            raise ServiceError(f"Couldn't read the date {value!r} — use YYYY-MM-DD or an ISO datetime.") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(UTC).replace(tzinfo=None)


def _clean(field: str, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if value == "" and field not in ("company",):
            value = None
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
        value = int(value)
        if not 1 <= value <= 5:
            raise ServiceError("fit is a 1-5 score.")
    if field == "value":
        value = float(value)
        if value < 0:
            raise ServiceError("value can't be negative.")
    if field == "inbound":
        value = bool(value)
    return value


def _stamp_milestones(opp: Opportunity, stage: str, when: datetime) -> None:
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
        if existing.archived_at:  # re-adding something deleted brings it back
            existing.archived_at = None
            _event(s, existing, actor, "updated", "Restored (added again)")
        return existing, False

    values = {k: _clean(k, v) for k, v in data.items() if k in EDITABLE}
    values.setdefault("channel", channel_for_url(values.get("application_url")) or "other")
    values.setdefault("stage", "lead")
    if "company" not in values:
        raise ServiceError("company is required.")
    _check_stage(values["stage"], values["channel"])
    now = utcnow()
    opp = Opportunity(**values, url_key=url_key(values.get("application_url")), created_by=actor.name,
                      needs_review=actor.is_agent, created_at=now, updated_at=now, last_activity_at=now)
    if opp.waiting_on is None and opp.stage in ("matcher", "applied", "proposal"):
        opp.waiting_on = "client"
    _stamp_milestones(opp, opp.stage, now)
    s.add(opp)
    s.flush()
    _event(s, opp, actor, "created", None, {k: [None, v] for k, v in values.items()
                                            if k not in ("description", "notes")})
    if data.get("reminder_at"):
        add_reminder(s, actor, opp.id, data["reminder_at"], data.get("reminder_note") or "Follow up")
    return opp, True


def _check_stage(stage: str, channel: str) -> None:
    if stage == "matcher" and channel != "toptal":
        raise ServiceError("'Sent to matcher' only applies to Toptal opportunities.")


def update(s: Session, actor: Actor, opp_id: int, data: dict) -> Opportunity:
    opp = _get(s, opp_id)
    unknown = set(data) - EDITABLE
    if unknown:
        raise ServiceError(f"Unknown field(s): {', '.join(sorted(unknown))}.")
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
    if "application_url" in changes:
        key = url_key(opp.application_url)
        dup = s.scalar(select(Opportunity).where(Opportunity.url_key == key, Opportunity.id != opp.id)) if key else None
        if dup:
            raise ServiceError(f"That URL is already opportunity #{dup.id} ({dup.company}).", 409)
        opp.url_key = key
    if "stage" in changes:
        _stamp_milestones(opp, opp.stage, utcnow())
        if opp.stage in ("applied", "matcher", "proposal") and "waiting_on" not in changes:
            opp.waiting_on = "client"
        if opp.stage == "lost" and not opp.lost_reason:
            opp.lost_reason = "rejected"
    if opp.stage != "lost":
        opp.lost_reason = None
    # Field edits are bookkeeping; only a stage move counts as deal activity.
    _touch(opp, actor, activity="stage" in changes)
    # Long text fields are logged as "edited" rather than copied into the audit trail.
    logged = {k: ([None, "edited"] if k in ("description", "notes") else v) for k, v in changes.items()}
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
    order = domain.STAGE_ORDER
    before = {"stage": opp.stage, "waiting_on": opp.waiting_on}
    if kind == "client_message":
        if opp.stage == "lead":
            opp.inbound = opp.inbound or opp.applied_at is None
        if opp.stage == "lost" or order[opp.stage] < order["replied"]:
            opp.stage = "replied"
        if opp.stage != "won":
            opp.waiting_on = "me"
    elif kind == "my_message":
        if opp.stage == "lead":
            opp.stage = "applied"
        if opp.stage not in domain.CLOSED_STAGES:
            opp.waiting_on = "client"
    elif kind == "call":
        if opp.stage in domain.OPEN_STAGES and order[opp.stage] < order["call"]:
            opp.stage = "call"
    if opp.stage != before["stage"]:
        _stamp_milestones(opp, opp.stage, when)
    changes = {k: [v, getattr(opp, k)] for k, v in before.items() if getattr(opp, k) != v}
    _touch(opp, actor, activity=False)
    if kind != "note":  # a note is bookkeeping, not contact with the client
        opp.last_activity_at = max(opp.last_activity_at, when)
    _event(s, opp, actor, kind, (body or "").strip() or None, changes or None, occurred_at=when)
    return opp


def mark_reviewed(s: Session, actor: Actor, opp_id: int | None = None) -> int:
    q = select(Opportunity).where(Opportunity.needs_review.is_(True), Opportunity.archived_at.is_(None))
    if opp_id is not None:
        q = q.where(Opportunity.id == opp_id)
    opps = s.scalars(q).all()
    for opp in opps:
        opp.needs_review = False
        _event(s, opp, actor, "reviewed")
    return len(opps)


def search(s: Session, *, q: str | None = None, stage: list[str] | None = None, channel: str | None = None,
           network: str | None = None, kind: str | None = None, waiting_on: str | None = None,
           needs_review: bool | None = None, include_closed: bool = True, limit: int = 500) -> list[Opportunity]:
    stmt = select(Opportunity).where(Opportunity.archived_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Opportunity.company.ilike(like), Opportunity.title.ilike(like),
                              Opportunity.contact_name.ilike(like), Opportunity.notes.ilike(like),
                              Opportunity.application_url.ilike(like), Opportunity.contact_email.ilike(like)))
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
    if not r:
        raise ServiceError(f"Reminder {reminder_id} not found.", 404)
    if done is not None:
        r.done_at = utcnow() if done else None
        if done:
            _event(s, r.opportunity, actor, "reminder", r.note or None, {"done_at": [None, iso(r.done_at)]})
    if due:
        r.due_at = parse_when(due, get_timezone(s))
    if note is not None:
        r.note = note.strip()[:500]
    _touch(r.opportunity, actor, activity=False)
    return r


def delete_reminder(s: Session, actor: Actor, reminder_id: int) -> None:
    r = s.get(Reminder, reminder_id)
    if not r:
        raise ServiceError(f"Reminder {reminder_id} not found.", 404)
    s.delete(r)


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
            "median_days_to_reply": round(reply_days[len(reply_days) // 2], 1) if reply_days else None,
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
        "lost_reasons": [{"key": k, "label": lbl, "count": n} for k, lbl in domain.LOST_REASONS
                         if (n := sum(1 for o in cohort if o.stage == "lost" and o.lost_reason == k))],
        "open_by_stage": [{"stage": k, "label": lbl, "count": sum(1 for o in open_opps if o.stage == k),
                           "value": sum(o.value or 0 for o in open_opps if o.stage == k)}
                          for k, lbl in domain.STAGES if k in domain.OPEN_STAGES],
        "weekly": weeks,
    }


def activity_feed(s: Session, *, limit: int = 100, actor_type: str | None = None, before_id: int | None = None) -> list[dict]:
    stmt = (select(Event, Opportunity).join(Opportunity, Event.opportunity_id == Opportunity.id)
            .order_by(Event.id.desc()).limit(min(limit, 300)))
    if actor_type:
        stmt = stmt.where(Event.actor_type == actor_type)
    if before_id:
        stmt = stmt.where(Event.id < before_id)
    return [event_dict(e, o) for e, o in s.execute(stmt).all()]
