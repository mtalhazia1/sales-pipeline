import os
from pathlib import Path

# Public origin, e.g. https://sales.example.com — used for OAuth metadata and cookie security.
BASE_URL = os.environ.get("SP_BASE_URL", "http://localhost:8100").rstrip("/")
DATA_DIR = Path(os.environ.get("SP_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "sales.db"
# Built web UI (vite build output). Served by the API process — one process, one port.
WEB_DIST = Path(os.environ.get("SP_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))

SECURE_COOKIES = BASE_URL.startswith("https://")
SESSION_DAYS = 30
ACCESS_TOKEN_TTL = 60 * 60  # OAuth access tokens: 1h, refreshed by the client
REFRESH_TOKEN_TTL = 60 * 60 * 24 * 90
