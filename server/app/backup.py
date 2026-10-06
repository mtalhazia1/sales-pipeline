"""Daily consistent snapshot of the SQLite database (safe while the app is writing — uses SQLite's
online backup API). Keeps the last 14. The EBS volume snapshots then carry these off-box.
Also clears out dead auth rows (expired sessions/tokens/codes, OAuth clients that never connected)
so anonymous registration and long use can't grow the database forever.

    python -m app.backup"""

import sqlite3
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, or_, select

from app import config
from app.db import session_scope, utcnow
from app.models import AgentToken, OAuthClient, OAuthCode, WebSession

KEEP = 14


def purge() -> None:
    now = utcnow()
    with session_scope() as s:
        s.execute(delete(WebSession).where(WebSession.expires_at < now))
        s.execute(delete(OAuthCode).where(OAuthCode.expires_at < now))
        # Spent OAuth tokens (API keys stay listed until deleted in Settings).
        s.execute(delete(AgentToken).where(AgentToken.kind != "api_key", or_(
            AgentToken.expires_at < now - timedelta(days=1), AgentToken.revoked_at < now - timedelta(days=1))))
        s.execute(delete(OAuthClient).where(
            OAuthClient.created_at < now - timedelta(days=1),
            ~exists(select(AgentToken.id).where(AgentToken.client_id == OAuthClient.client_id))))


def main() -> None:
    target_dir = config.DATA_DIR / "backups"
    target_dir.mkdir(exist_ok=True)
    target = target_dir / f"sales-{datetime.now(UTC):%Y%m%d-%H%M}.db"
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    for old in sorted(target_dir.glob("sales-*.db"))[:-KEEP]:
        old.unlink()
    print(f"backup written: {target}")
    purge()


if __name__ == "__main__":
    main()
