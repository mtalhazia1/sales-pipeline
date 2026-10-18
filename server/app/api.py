"""REST API for the web UI. Humans authenticate with the session cookie; scripts can also send an
API key as a bearer token (they are then recorded as that agent, like MCP calls)."""

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, config, domain, oauth, service
from app.db import SessionLocal, iso, utcnow
from app.models import AgentToken, Setting, User
from app.service import Actor, ServiceError

router = APIRouter(prefix="/api")


def db():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# scope="function": commit when the endpoint returns, BEFORE the response goes out. With FastAPI's default
# ("request") the commit ran after sending it, so a client could act on a reply whose write wasn't saved yet
# (or never was, if the commit failed). Use DB for every session parameter so they share one session.
DB = Depends(db, scope="function")


class Ctx:
    def __init__(self, actor: Actor, user: User | None):
        self.actor, self.user = actor, user


def ctx(request: Request, s: Session = DB) -> Ctx:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        row = auth.token_row(s, header[7:].strip())
        if not row:
            raise HTTPException(401, "Invalid or expired token.")
        return Ctx(auth.agent_actor(row), None)
    user = auth.user_for_session(s, request.cookies.get(auth.SESSION_COOKIE))
    if not user:
        raise HTTPException(401, "Not logged in.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # CSRF: the cookie is SameSite=Lax, and browsers send Origin on every mutation, so a present
        # Origin must be exactly ours. (No Origin = not a browser page, e.g. scripts/smoke.py.)
        origin = request.headers.get("origin")
        if origin and not _own_origin(origin):
            raise HTTPException(403, "Cross-origin request refused.")
    return Ctx(auth.human_actor(user), user)


def _own_origin(origin: str) -> bool:
    if origin.rstrip("/") == config.BASE_URL:
        return True
    # Local development only: the Vite dev server (another port) proxies to a loopback BASE_URL.
    try:
        host, base_host = urlsplit(origin).hostname, urlsplit(config.BASE_URL).hostname
    except ValueError:
        return False
    return base_host in ("localhost", "127.0.0.1", "::1") and host in ("localhost", "127.0.0.1", "::1")


def human(c: Ctx = Depends(ctx)) -> Ctx:
    if not c.user:
        raise HTTPException(403, "Only people can do this.")
    return c


def register_errors(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def _service_error(_req: Request, e: ServiceError):
        return JSONResponse({"detail": e.message}, status_code=e.status)


# ---------------------------------------------------------------- auth

class LoginIn(BaseModel):
    email: str
    password: str


def _user_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, s: Session = DB):
    user, token = auth.login(s, body.email, body.password, request.client.host if request.client else "?")
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=config.SECURE_COOKIES, samesite="lax", path="/")
    return _user_dict(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, s: Session = DB):
    auth.logout(s, request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
def me(c: Ctx = Depends(human)):
    return _user_dict(c.user)


class PasswordIn(BaseModel):
    current: str
    new: str


@router.post("/auth/password")
def change_password(body: PasswordIn, request: Request, c: Ctx = Depends(human), s: Session = DB):
    user = s.get(User, c.user.id)
    if not auth.verify_password(user, body.current):
        raise ServiceError("Current password is wrong.")
    user.password_hash = auth.hash_password(body.new)
    auth.end_other_sessions(s, user, request.cookies.get(auth.SESSION_COOKIE))
    return {"ok": True}


# ---------------------------------------------------------------- meta & settings

@router.get("/meta")
def meta(c: Ctx = Depends(ctx), s: Session = DB):
    return {**domain.meta(), "timezone": str(service.get_timezone(s)), "base_url": config.BASE_URL,
            # False until someone picks one — only then may the UI adopt the browser's zone.
            "timezone_set": s.get(Setting, "timezone") is not None}


class SettingsIn(BaseModel):
    timezone: str | None = None


@router.patch("/settings")
def update_settings(body: SettingsIn, c: Ctx = Depends(human), s: Session = DB):
    if body.timezone:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ServiceError("Unknown timezone.") from e
        s.merge(Setting(key="timezone", value=body.timezone))
    return {"timezone": body.timezone}


# ---------------------------------------------------------------- opportunities

@router.get("/opportunities")
def list_opportunities(q: str | None = None, stage: str | None = None, channel: str | None = None,
                       network: str | None = None, kind: str | None = None, waiting_on: str | None = None,
                       needs_review: bool | None = None, include_closed: bool = True,
                       c: Ctx = Depends(ctx), s: Session = DB):
    rows = service.search(s, q=q, stage=stage.split(",") if stage else None, channel=channel, network=network,
                          kind=kind, waiting_on=waiting_on, needs_review=needs_review, include_closed=include_closed)
    return [service.summary(o) for o in rows]


@router.post("/opportunities")
def create_opportunity(body: dict[str, Any], c: Ctx = Depends(ctx), s: Session = DB):
    opp, created = service.create(s, c.actor, body)
    return {"created": created, "opportunity": service.summary(opp)}


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int, c: Ctx = Depends(ctx), s: Session = DB):
    return service.detail(s, service._get(s, opp_id))


@router.patch("/opportunities/{opp_id}")
def update_opportunity(opp_id: int, body: dict[str, Any], c: Ctx = Depends(ctx), s: Session = DB):
    opp = service.update(s, c.actor, opp_id, body)
    s.flush()
    return service.detail(s, opp)


@router.delete("/opportunities/{opp_id}")
def delete_opportunity(opp_id: int, c: Ctx = Depends(human), s: Session = DB):
    service.archive(s, c.actor, opp_id)
    return {"ok": True}


class ActivityIn(BaseModel):
    kind: str
    body: str | None = None
    occurred_at: str | None = None
    template_id: int | None = None
    channel: str | None = None


@router.post("/opportunities/{opp_id}/activities")
def log_activity(opp_id: int, body: ActivityIn, c: Ctx = Depends(ctx), s: Session = DB):
    opp = service.log_activity(s, c.actor, opp_id, body.kind, body.body, body.occurred_at, body.template_id, body.channel)
    s.flush()
    return service.detail(s, opp)


class ReminderIn(BaseModel):
    due_at: str
    note: str = ""


@router.post("/opportunities/{opp_id}/reminders")
def add_reminder(opp_id: int, body: ReminderIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.reminder_dict(service.add_reminder(s, c.actor, opp_id, body.due_at, body.note))


class ReminderPatch(BaseModel):
    done: bool | None = None
    due_at: str | None = None
    note: str | None = None


@router.patch("/reminders/{reminder_id}")
def update_reminder(reminder_id: int, body: ReminderPatch, c: Ctx = Depends(ctx), s: Session = DB):
    return service.reminder_dict(service.update_reminder(s, c.actor, reminder_id, done=body.done,
                                                         due=body.due_at, note=body.note))


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, c: Ctx = Depends(ctx), s: Session = DB):
    service.delete_reminder(s, c.actor, reminder_id)
    return {"ok": True}


@router.post("/opportunities/{opp_id}/review")
def review_one(opp_id: int, c: Ctx = Depends(human), s: Session = DB):
    return {"reviewed": service.mark_reviewed(s, c.actor, opp_id)}


class ApproveIn(BaseModel):
    ids: list[int] | None = None


@router.post("/review/approve-all")
def review_all(body: ApproveIn, c: Ctx = Depends(human), s: Session = DB):
    return {"reviewed": service.mark_reviewed(s, c.actor, ids=body.ids)}


# ---------------------------------------------------------------- notifications (agents send them via MCP)

@router.get("/notifications")
def list_notifications(unread: bool = False, c: Ctx = Depends(ctx), s: Session = DB):
    return [service.notification_dict(n) for n in service.notifications(s, unread_only=unread)]


class ReadIn(BaseModel):
    ids: list[int]
    read: bool = True


@router.post("/notifications/read")
def mark_read(body: ReadIn, c: Ctx = Depends(human), s: Session = DB):
    return {"updated": service.mark_notifications_read(s, body.ids, body.read)}


# ---------------------------------------------------------------- message templates and their categories

@router.get("/template-categories")
def list_categories(include_archived: bool = False, c: Ctx = Depends(ctx), s: Session = DB):
    return [service.category_dict(x) for x in service.categories(s, include_archived=include_archived)]


@router.post("/template-categories")
def create_category(body: dict[str, Any], c: Ctx = Depends(human), s: Session = DB):
    return service.category_dict(service.create_category(s, c.actor, body))


@router.patch("/template-categories/{key}")
def update_category(key: str, body: dict[str, Any], c: Ctx = Depends(human), s: Session = DB):
    return service.category_dict(service.update_category(s, c.actor, key, body))


@router.delete("/template-categories/{key}")
def delete_category(key: str, c: Ctx = Depends(human), s: Session = DB):
    service.delete_category(s, key)
    return {"ok": True}


@router.get("/templates")
def list_templates(include_archived: bool = False, c: Ctx = Depends(ctx), s: Session = DB):
    return service.templates(s, include_archived=include_archived)


@router.post("/templates")
def create_template(body: dict[str, Any], c: Ctx = Depends(human), s: Session = DB):
    return service.template_dict(service.create_template(s, c.actor, body))


@router.patch("/templates/{template_id}")
def update_template(template_id: int, body: dict[str, Any], c: Ctx = Depends(human), s: Session = DB):
    return service.template_dict(service.update_template(s, c.actor, template_id, body))


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, c: Ctx = Depends(human), s: Session = DB):
    service.delete_template(s, template_id)
    return {"ok": True}


# ---------------------------------------------------------------- agent state (agents use the MCP tools of the same names)

@router.get("/state")
def get_state(ns: str | None = None, section: str | None = None, q: str | None = None, limit: int = service.STATE_PAGE_LIMIT,
              c: Ctx = Depends(ctx), s: Session = DB):
    """The State page: rows (flat), plus every namespace, the sections in use and the current counters."""
    return service.state_page(s, ns, section, q, limit)


class StateSetIn(BaseModel):
    ns: str
    changes: list[Any]


@router.post("/state")
def set_state(body: StateSetIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.state_set(s, c.actor, body.ns, body.changes)


@router.delete("/state/namespaces/{ns}")
def forget_namespace(ns: str, c: Ctx = Depends(human), s: Session = DB):
    return {"deleted": service.forget_namespace(s, ns)}


class StateGetIn(BaseModel):
    ns: Any
    sections: list[str] | None = None
    keys: list[str] | None = None
    q: str | None = None
    due_before: str | None = None
    limit: int = 100
    runs_since: str | None = None


@router.post("/state/get")
def query_state(body: StateGetIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.state_get(s, body.ns, body.sections, body.keys, body.q, body.due_before, body.limit, body.runs_since)


class CountIn(BaseModel):
    items: list[Any]
    idem: str | None = None


@router.post("/state/count")
def count(body: CountIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.count(s, body.items, body.idem)


class SeenIn(BaseModel):
    ns: str
    source: str
    ids: list[Any]
    mark: bool = True
    ttl_days: int = service.SEEN_DAYS


@router.post("/state/seen")
def seen(body: SeenIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.seen(s, body.ns, body.source, body.ids, body.mark, body.ttl_days)


@router.get("/state/runs")
def list_runs(ns: str | None = None, status: str | None = None, limit: int = 100,
              c: Ctx = Depends(ctx), s: Session = DB):
    return service.runs(s, ns=ns, statuses=status.split(",") if status else None, limit=limit)


class RunStartIn(BaseModel):
    ns: str
    worker: str = "main"
    also: list[str] | None = None
    include: list[str] | None = None
    lease_min: int = 50


@router.post("/state/runs")
def run_start(body: RunStartIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.run_start(s, body.ns, body.worker, body.also, body.include, body.lease_min)


class RunEndIn(BaseModel):
    status: str
    summary: str | None = None
    counts: dict[str, Any] | None = None
    changes: list[Any] | None = None


@router.post("/state/runs/{run_id}/end")
def run_end(run_id: int, body: RunEndIn, c: Ctx = Depends(ctx), s: Session = DB):
    return service.run_end(s, c.actor, run_id, body.status, body.summary, body.counts, body.changes)


# ---------------------------------------------------------------- dashboards

@router.get("/agenda")
def agenda(c: Ctx = Depends(ctx), s: Session = DB):
    return service.agenda(s)


@router.get("/stats")
def stats(days: int | None = 90, c: Ctx = Depends(ctx), s: Session = DB):
    return service.stats(s, days if days and days > 0 else None)


@router.get("/activity")
def activity(limit: int = 100, actor_type: str | None = None, before_id: int | None = None,
             c: Ctx = Depends(ctx), s: Session = DB):
    return service.activity_feed(s, limit=limit, actor_type=actor_type, before_id=before_id)


# ---------------------------------------------------------------- agent access (humans only)

@router.get("/agents")
def list_agents(c: Ctx = Depends(human), s: Session = DB):
    """API keys plus OAuth-connected apps (one row per client, newest token's info)."""
    now = utcnow()
    keys = s.scalars(select(AgentToken).where(AgentToken.kind == "api_key", AgentToken.revoked_at.is_(None))
                     .order_by(AgentToken.created_at.desc())).all()
    tokens = s.scalars(select(AgentToken).where(AgentToken.kind == "refresh", AgentToken.revoked_at.is_(None),
                                                AgentToken.expires_at > now)).all()
    apps: dict[str, dict] = {}
    for t in tokens:
        a = apps.setdefault(t.client_id, {"client_id": t.client_id, "name": t.name, "connected_at": iso(t.created_at),
                                          "last_used_at": None})
        a["connected_at"] = min(a["connected_at"], iso(t.created_at))
    for t in s.scalars(select(AgentToken).where(AgentToken.client_id.in_(apps), AgentToken.last_used_at.is_not(None))):
        a = apps[t.client_id]
        a["last_used_at"] = max(a["last_used_at"] or "", iso(t.last_used_at))
    return {
        "mcp_url": f"{config.BASE_URL}/mcp",
        "api_keys": [{"id": k.id, "name": k.name, "prefix": k.prefix, "created_at": iso(k.created_at),
                      "last_used_at": iso(k.last_used_at)} for k in keys],
        "apps": sorted(apps.values(), key=lambda a: a["connected_at"], reverse=True),
    }


class KeyIn(BaseModel):
    name: str


@router.post("/agents/keys")
def create_key(body: KeyIn, c: Ctx = Depends(human), s: Session = DB):
    row, token = auth.create_api_key(s, c.user, body.name)
    return {"id": row.id, "name": row.name, "token": token}


@router.delete("/agents/keys/{key_id}")
def revoke_key(key_id: int, c: Ctx = Depends(human), s: Session = DB):
    row = s.get(AgentToken, key_id)
    if not row or row.kind != "api_key":
        raise ServiceError("Key not found.", 404)
    row.revoked_at = utcnow()
    return {"ok": True}


@router.delete("/agents/apps/{client_id}")
def disconnect_app(client_id: str, c: Ctx = Depends(human), s: Session = DB):
    for t in s.scalars(select(AgentToken).where(AgentToken.client_id == client_id, AgentToken.revoked_at.is_(None))):
        t.revoked_at = utcnow()
    return {"ok": True}


# ---------------------------------------------------------------- OAuth consent (MCP clients)

@router.get("/oauth/requests/{request_id}")
def oauth_request(request_id: str, c: Ctx = Depends(human), s: Session = DB):
    return oauth.pending_request(s, request_id)


class ConsentIn(BaseModel):
    allow: bool


@router.post("/oauth/requests/{request_id}")
def oauth_consent(request_id: str, body: ConsentIn, c: Ctx = Depends(human), s: Session = DB):
    return {"redirect_to": oauth.approve(s, c.user, request_id, body.allow)}

