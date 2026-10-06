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


class Ctx:
    def __init__(self, actor: Actor, user: User | None):
        self.actor, self.user = actor, user


def ctx(request: Request, s: Session = Depends(db)) -> Ctx:
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
def login(body: LoginIn, request: Request, response: Response, s: Session = Depends(db)):
    user, token = auth.login(s, body.email, body.password, request.client.host if request.client else "?")
    response.set_cookie(auth.SESSION_COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        secure=config.SECURE_COOKIES, samesite="lax", path="/")
    return _user_dict(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, s: Session = Depends(db)):
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
def change_password(body: PasswordIn, request: Request, c: Ctx = Depends(human), s: Session = Depends(db)):
    user = s.get(User, c.user.id)
    if not auth.verify_password(user, body.current):
        raise ServiceError("Current password is wrong.")
    user.password_hash = auth.hash_password(body.new)
    auth.end_other_sessions(s, user, request.cookies.get(auth.SESSION_COOKIE))
    return {"ok": True}


# ---------------------------------------------------------------- meta & settings

@router.get("/meta")
def meta(c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return {**domain.meta(), "timezone": str(service.get_timezone(s)), "base_url": config.BASE_URL,
            # False until someone picks one — only then may the UI adopt the browser's zone.
            "timezone_set": s.get(Setting, "timezone") is not None}


class SettingsIn(BaseModel):
    timezone: str | None = None


@router.patch("/settings")
def update_settings(body: SettingsIn, c: Ctx = Depends(human), s: Session = Depends(db)):
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
                       c: Ctx = Depends(ctx), s: Session = Depends(db)):
    rows = service.search(s, q=q, stage=stage.split(",") if stage else None, channel=channel, network=network,
                          kind=kind, waiting_on=waiting_on, needs_review=needs_review, include_closed=include_closed)
    return [service.summary(o) for o in rows]


@router.post("/opportunities")
def create_opportunity(body: dict[str, Any], c: Ctx = Depends(ctx), s: Session = Depends(db)):
    opp, created = service.create(s, c.actor, body)
    return {"created": created, "opportunity": service.summary(opp)}


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.detail(s, service._get(s, opp_id))


@router.patch("/opportunities/{opp_id}")
def update_opportunity(opp_id: int, body: dict[str, Any], c: Ctx = Depends(ctx), s: Session = Depends(db)):
    opp = service.update(s, c.actor, opp_id, body)
    s.flush()
    return service.detail(s, opp)


@router.delete("/opportunities/{opp_id}")
def delete_opportunity(opp_id: int, c: Ctx = Depends(human), s: Session = Depends(db)):
    service.archive(s, c.actor, opp_id)
    return {"ok": True}


class ActivityIn(BaseModel):
    kind: str
    body: str | None = None
    occurred_at: str | None = None


@router.post("/opportunities/{opp_id}/activities")
def log_activity(opp_id: int, body: ActivityIn, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    opp = service.log_activity(s, c.actor, opp_id, body.kind, body.body, body.occurred_at)
    s.flush()
    return service.detail(s, opp)


class ReminderIn(BaseModel):
    due_at: str
    note: str = ""


@router.post("/opportunities/{opp_id}/reminders")
def add_reminder(opp_id: int, body: ReminderIn, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.reminder_dict(service.add_reminder(s, c.actor, opp_id, body.due_at, body.note))


class ReminderPatch(BaseModel):
    done: bool | None = None
    due_at: str | None = None
    note: str | None = None


@router.patch("/reminders/{reminder_id}")
def update_reminder(reminder_id: int, body: ReminderPatch, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.reminder_dict(service.update_reminder(s, c.actor, reminder_id, done=body.done,
                                                         due=body.due_at, note=body.note))


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    service.delete_reminder(s, c.actor, reminder_id)
    return {"ok": True}


@router.post("/opportunities/{opp_id}/review")
def review_one(opp_id: int, c: Ctx = Depends(human), s: Session = Depends(db)):
    return {"reviewed": service.mark_reviewed(s, c.actor, opp_id)}


class ApproveIn(BaseModel):
    ids: list[int] | None = None


@router.post("/review/approve-all")
def review_all(body: ApproveIn, c: Ctx = Depends(human), s: Session = Depends(db)):
    return {"reviewed": service.mark_reviewed(s, c.actor, ids=body.ids)}


# ---------------------------------------------------------------- dashboards

@router.get("/agenda")
def agenda(c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.agenda(s)


@router.get("/stats")
def stats(days: int | None = 90, c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.stats(s, days if days and days > 0 else None)


@router.get("/activity")
def activity(limit: int = 100, actor_type: str | None = None, before_id: int | None = None,
             c: Ctx = Depends(ctx), s: Session = Depends(db)):
    return service.activity_feed(s, limit=limit, actor_type=actor_type, before_id=before_id)


# ---------------------------------------------------------------- agent access (humans only)

@router.get("/agents")
def list_agents(c: Ctx = Depends(human), s: Session = Depends(db)):
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
def create_key(body: KeyIn, c: Ctx = Depends(human), s: Session = Depends(db)):
    row, token = auth.create_api_key(s, c.user, body.name)
    return {"id": row.id, "name": row.name, "token": token}


@router.delete("/agents/keys/{key_id}")
def revoke_key(key_id: int, c: Ctx = Depends(human), s: Session = Depends(db)):
    row = s.get(AgentToken, key_id)
    if not row or row.kind != "api_key":
        raise ServiceError("Key not found.", 404)
    row.revoked_at = utcnow()
    return {"ok": True}


@router.delete("/agents/apps/{client_id}")
def disconnect_app(client_id: str, c: Ctx = Depends(human), s: Session = Depends(db)):
    for t in s.scalars(select(AgentToken).where(AgentToken.client_id == client_id, AgentToken.revoked_at.is_(None))):
        t.revoked_at = utcnow()
    return {"ok": True}


# ---------------------------------------------------------------- OAuth consent (MCP clients)

@router.get("/oauth/requests/{request_id}")
def oauth_request(request_id: str, c: Ctx = Depends(human), s: Session = Depends(db)):
    return oauth.pending_request(s, request_id)


class ConsentIn(BaseModel):
    allow: bool


@router.post("/oauth/requests/{request_id}")
def oauth_consent(request_id: str, body: ConsentIn, c: Ctx = Depends(human), s: Session = Depends(db)):
    return {"redirect_to": oauth.approve(s, c.user, request_id, body.allow)}

