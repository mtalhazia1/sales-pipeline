"""Daily consistent snapshot of the SQLite database (safe while the app is writing — uses SQLite's
online backup API). Keeps the last 14. The EBS volume snapshots then carry these off-box.

    python -m app.backup"""

import sqlite3
from datetime import UTC, datetime

from app import config

KEEP = 14


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


if __name__ == "__main__":
    main()
