"""OAuth 2.1 authorization server for MCP clients (Claude apps and other remote MCP clients).
The SDK serves the protocol endpoints (/authorize, /token, /register, /revoke, metadata); this
provider only stores clients, codes and tokens. The "log in and approve" step is the web UI's
/oauth/consent page, which calls `approve()` below."""

import secrets
import time
from datetime import UTC, timedelta
from urllib.parse import urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select, update

from app import config
from app.auth import new_token, sha256, token_row
from app.db import session_scope, utcnow
from app.models import AgentToken, OAuthClient, OAuthCode, User
from app.service import ServiceError

SCOPE = "sales"
# Pending consent requests live in memory for 10 minutes (single process; a restart just means
# the person clicks "connect" again). Bounded by evicting the oldest — never by refusing, which would let
# anyone lock the owner out of connecting by filling the slots.
_pending: dict[str, tuple[float, str, AuthorizationParams]] = {}
MAX_PENDING = 1000
# Registration is open and anonymous (that's how MCP clients connect), so each stored row is small (only
# the fields we use, short); nginx rate-limits the endpoint and the daily job purges clients that never
# connected. No hard count cap for the same lock-out reason.
_KEEP_CLIENT_FIELDS = {"client_id", "client_secret", "client_id_issued_at", "client_secret_expires_at", "redirect_uris",
                       "token_endpoint_auth_method", "grant_types", "response_types", "client_name", "client_uri", "scope"}


_BLOCKED_SCHEMES = {"javascript", "data", "vbscript", "blob", "file", "about"}


def _safe_redirect(uri: str) -> bool:
    """https anywhere; http only to loopback (native clients like Claude Code); custom app schemes
    (cursor://…) allowed; script-capable schemes never — the consent page navigates to this URI."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    if scheme == "https":
        return bool(parts.hostname)
    if scheme == "http":
        return parts.hostname in ("localhost", "127.0.0.1", "::1")
    return bool(scheme) and scheme not in _BLOCKED_SCHEMES


def _client_name(info: OAuthClientInformationFull) -> str:
    return (info.client_name or "MCP client").strip()[:80]


class Provider:
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with session_scope() as s:
            row = s.get(OAuthClient, client_id)
            return OAuthClientInformationFull.model_validate(row.info) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = client_info.redirect_uris or []
        if len(uris) > 10 or any(len(str(u)) > 500 for u in uris):
            raise RegistrationError("invalid_redirect_uri", "At most 10 redirect URIs of up to 500 characters.")
        for uri in uris:
            if not _safe_redirect(str(uri)):
                raise RegistrationError("invalid_redirect_uri", f"Redirect URI not allowed: {uri}")
        info = {k: v for k, v in client_info.model_dump(mode="json").items() if k in _KEEP_CLIENT_FIELDS}
        info["client_name"] = _client_name(client_info)
        if info.get("client_uri") and len(info["client_uri"]) > 300:
            info["client_uri"] = None
        if info.get("scope") and len(info["scope"]) > 100:
            raise RegistrationError("invalid_client_metadata", "Scope too long.")
        with session_scope() as s:
            s.merge(OAuthClient(client_id=client_info.client_id, info=info))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if len(params.state or "") > 500 or len(params.code_challenge) > 128 or len(params.resource or "") > 500:
            raise AuthorizeError("invalid_request", "state, code_challenge or resource is too long.")
        now = time.time()
        for key in [k for k, (ts, _, _) in _pending.items() if ts < now - 600]:
            _pending.pop(key, None)
        while len(_pending) >= MAX_PENDING:
            _pending.pop(next(iter(_pending)))  # oldest first (dicts keep insertion order)
        request_id = secrets.token_urlsafe(24)
        _pending[request_id] = (now, client.client_id, params)
        return f"{config.BASE_URL}/oauth/consent?request={request_id}"

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str):
        with session_scope() as s:
            row = s.get(OAuthCode, sha256(authorization_code))
            if not row or row.client_id != client.client_id or row.expires_at < utcnow():
                return None
            return AuthorizationCode.model_validate({**row.data, "code": authorization_code})

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        with session_scope() as s:
            row = s.get(OAuthCode, sha256(authorization_code.code))
            if not row:  # single use
                raise TokenError("invalid_grant", "Authorization code already used.")
            user_id = row.user_id
            s.delete(row)
            return _issue(s, client, user_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str):
        with session_scope() as s:
            row = token_row(s, refresh_token, kinds=("refresh",))
            if not row or row.client_id != client.client_id:
                return None
            return RefreshToken(token=refresh_token, client_id=row.client_id, scopes=row.scopes,
                                resource=row.resource, subject=str(row.user_id))

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with session_scope() as s:
            row = token_row(s, refresh_token.token, kinds=("refresh",))
            if not row:
                raise TokenError("invalid_grant", "Refresh token is no longer valid.")
            row.revoked_at = utcnow()  # rotation: every refresh token works once
            return _issue(s, client, row.user_id, scopes or row.scopes, row.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with session_scope() as s:
            row = token_row(s, token)
            if not row:
                return None
            return AccessToken(
                token=token, client_id=row.client_id or f"api-key-{row.id}", scopes=row.scopes or [SCOPE],
                expires_at=int(row.expires_at.replace(tzinfo=UTC).timestamp()) if row.expires_at else None,
                resource=row.resource, subject=str(row.user_id),
                claims={"actor_name": row.name},
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with session_scope() as s:
            row = s.scalar(select(AgentToken).where(AgentToken.token_hash == sha256(token.token)))
            if row and row.client_id:
                # Revoking either half of a grant ends the whole connection for that client.
                s.execute(update(AgentToken).where(AgentToken.client_id == row.client_id,
                                                   AgentToken.user_id == row.user_id,
                                                   AgentToken.revoked_at.is_(None)).values(revoked_at=utcnow()))


def _issue(s, client: OAuthClientInformationFull, user_id: int, scopes: list[str], resource: str | None) -> OAuthToken:
    now = utcnow()
    access, refresh = new_token("spa"), new_token("spr")
    common = dict(name=_client_name(client), user_id=user_id, client_id=client.client_id,
                  scopes=scopes or [SCOPE], resource=resource)
    s.add(AgentToken(token_hash=sha256(access), kind="access", prefix=access[:10],
                     expires_at=now + timedelta(seconds=config.ACCESS_TOKEN_TTL), **common))
    s.add(AgentToken(token_hash=sha256(refresh), kind="refresh", prefix=refresh[:10],
                     expires_at=now + timedelta(seconds=config.REFRESH_TOKEN_TTL), **common))
    return OAuthToken(access_token=access, expires_in=config.ACCESS_TOKEN_TTL,
                      scope=" ".join(scopes or [SCOPE]), refresh_token=refresh)


# ---------------------------------------------------------------- consent (called by the web UI)

def pending_request(s, request_id: str) -> dict:
    entry = _pending.get(request_id)
    if not entry or entry[0] < time.time() - 600:
        raise ServiceError("This connection request expired — start it again from your app.", 404)
    _, client_id, params = entry
    client = s.get(OAuthClient, client_id)
    info = OAuthClientInformationFull.model_validate(client.info)
    return {"client_name": _client_name(info), "redirect_host": params.redirect_uri.host,
            "client_uri": str(info.client_uri) if info.client_uri else None}


def approve(s, user: User, request_id: str, allow: bool) -> str:
    """Returns the URL to send the browser back to (the MCP client's redirect_uri)."""
    entry = _pending.pop(request_id, None)
    if not entry or entry[0] < time.time() - 600:
        raise ServiceError("This connection request expired — start it again from your app.", 404)
    _, client_id, params = entry
    if not _safe_redirect(str(params.redirect_uri)):
        raise ServiceError("This app's redirect address isn't allowed.", 400)
    if not allow:
        return construct_redirect_uri(str(params.redirect_uri), error="access_denied", state=params.state)
    code = secrets.token_urlsafe(32)
    data = AuthorizationCode(
        code="-", scopes=params.scopes or [SCOPE], expires_at=time.time() + 300, client_id=client_id,
        code_challenge=params.code_challenge, redirect_uri=params.redirect_uri,
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource, subject=str(user.id),
    ).model_dump(mode="json", exclude={"code"})
    s.add(OAuthCode(code_hash=sha256(code), client_id=client_id, user_id=user.id, data=data,
                    expires_at=utcnow() + timedelta(minutes=5)))
    return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)
