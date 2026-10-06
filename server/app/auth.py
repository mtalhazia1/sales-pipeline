"""Humans log in with email + password (cookie session). Agents use a bearer token: a named API
key made in Settings, or an OAuth token their MCP client obtained. Either way the token's name
becomes the actor shown in the activity log."""

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import utcnow
from app.models import AgentToken, User, WebSession
from app.service import Actor, ServiceError

_hasher = PasswordHasher()
SESSION_COOKIE = "sp_session"


def sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ServiceError("Use at least 10 characters.")
    return _hasher.hash(password)


# Each argon2 check takes ~64 MB for ~70 ms. Two at a time keeps a burst of logins from pushing the
# process past its memory cap (it would be OOM-killed); the rest wait their turn.
_verify_slots = threading.BoundedSemaphore(2)
# Unknown emails are checked against this, so a wrong email takes as long as a wrong password.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def verify_password(user: User | None, password: str) -> bool:
    with _verify_slots:
        try:
            return _hasher.verify(user.password_hash if user else _DUMMY_HASH, password) and user is not None
        except VerificationError:
            return False


# Brute-force brake: 8 failed logins per IP per 15 minutes. One process, so memory is enough.
_failures: dict[str, deque] = defaultdict(deque)


def check_login_allowed(ip: str) -> None:
    now = time.time()
    for key in [k for k, q in _failures.items() if not q or q[-1] < now - 900]:
        _failures.pop(key, None)  # forget IPs with nothing recent, so the table can't grow forever
    q = _failures[ip]
    while q and q[0] < now - 900:
        q.popleft()
    if len(q) >= 8:
        raise ServiceError("Too many attempts — try again in 15 minutes.", 429)


def login(s: Session, email: str, password: str, ip: str) -> tuple[User, str]:
    check_login_allowed(ip)
    # Counted before the (slow) check, so parallel guesses can't all slip in under the limit.
    attempt = time.time()
    _failures[ip].append(attempt)
    user = s.scalar(select(User).where(User.email == email.strip().lower()))
    if not verify_password(user, password):
        raise ServiceError("Wrong email or password.", 401)
    _failures[ip].remove(attempt)
    token = secrets.token_urlsafe(32)
    s.add(WebSession(token_hash=sha256(token), user_id=user.id,
                     expires_at=utcnow() + timedelta(days=config.SESSION_DAYS)))
    return user, token


def user_for_session(s: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = s.get(WebSession, sha256(token))
    if not row or row.expires_at < utcnow():
        return None
    # Sliding expiry: refresh at most once a day.
    if row.expires_at - utcnow() < timedelta(days=config.SESSION_DAYS - 1):
        row.expires_at = utcnow() + timedelta(days=config.SESSION_DAYS)
    return row.user


def logout(s: Session, token: str | None) -> None:
    if token and (row := s.get(WebSession, sha256(token))):
        s.delete(row)


def end_other_sessions(s: Session, user: User, keep_token: str | None) -> None:
    """After a password change, every other browser signed in as this user is signed out."""
    keep = sha256(keep_token) if keep_token else None
    for row in s.scalars(select(WebSession).where(WebSession.user_id == user.id)).all():
        if row.token_hash != keep:
            s.delete(row)


def create_user(s: Session, email: str, name: str, password: str) -> User:
    email = email.strip().lower()
    if s.scalar(select(User).where(User.email == email)):
        raise ServiceError("That email already has an account.")
    user = User(email=email, name=name.strip() or email.split("@")[0], password_hash=hash_password(password))
    s.add(user)
    s.flush()
    return user


# ---------------------------------------------------------------- agent tokens

def create_api_key(s: Session, user: User, name: str) -> tuple[AgentToken, str]:
    name = name.strip()
    if not name:
        raise ServiceError("Give the key a name — it's how the agent shows up in the activity log.")
    token = new_token("sp")
    row = AgentToken(token_hash=sha256(token), kind="api_key", name=name[:120], prefix=token[:10],
                     user_id=user.id, scopes=["sales"])
    s.add(row)
    s.flush()
    return row, token


def token_row(s: Session, token: str, kinds: tuple[str, ...] = ("api_key", "access")) -> AgentToken | None:
    row = s.scalar(select(AgentToken).where(AgentToken.token_hash == sha256(token)))
    if not row or row.kind not in kinds or row.revoked_at:
        return None
    if row.expires_at and row.expires_at < utcnow():
        return None
    now = utcnow()
    if not row.last_used_at or now - row.last_used_at > timedelta(minutes=5):
        row.last_used_at = now
    return row


def agent_actor(row: AgentToken) -> Actor:
    return Actor("agent", row.name, row.user_id)


def human_actor(user: User) -> Actor:
    return Actor("human", user.name, user.id)
