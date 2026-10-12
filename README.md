# Pipeline — sales monitoring for a one-person B2B services business

Agents find and log the work (jobs, projects, messages, follow-ups); a human reviews and steers.

- **Web UI** — Today (what needs you), Alerts (what agents flagged for you to act on), Pipeline (board + list), Review (what agents changed), Insights (funnel by channel/network), Settings (connect agents).
- **MCP server** at `/mcp` (protocol 2026-07-28, older clients still served) — 10 tools, OAuth for Claude apps, API keys for headless agents.
- **REST API** at `/api` — what the UI uses; API keys work here too.

One process (FastAPI + MCP SDK 2.3), one SQLite file, one port.

## Model

An **opportunity** = a job or project at a client company.

| Field | Values |
|---|---|
| Type | Job, Project |
| Client / company, title, application URL, company URL | text |
| Channel | LinkedIn, Email, Upwork, Toptal, Direct / Website, Referral, Other |
| Network | None (default), LinkedIn, FirstGlance, Referral / personal |
| Stage | Lead → Sent to matcher (Toptal only) → Applied → Replied → Call booked → Proposal sent → Contract done / Lost (+ reason) |
| Whose move | mine / client's — derived from the last message, editable |
| Also | inbound flag, contact (name, email, profile), budget as posted, deal value (USD), fit 1–5, notes, job post |
| Reminders | date + note, any number per opportunity |

Every change is an event (who — person or which agent — what, when): that is both the timeline and the audit log.
Anything an agent writes is flagged **needs review** until a person approves it or acts on it.

**Automation (predictable, forward-only):** logging a *client message* moves the deal to Replied and makes it your move;
logging *my message* makes it their move (and a Lead becomes Applied); logging a *call* moves it to Call booked.
The same job posted under different URL spellings (Upwork `~01…` ids, LinkedIn job ids, tracking params) is stored once.

## Develop

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r server/requirements.txt httpx2
cd server && ../.venv/bin/alembic upgrade head
../.venv/bin/python -m app.cli create-user you@example.com "Your Name"   # prints a password
../.venv/bin/uvicorn app.main:app --port 8100 --reload
cd ../web && npm install && npm run dev                                   # http://localhost:5173 (proxies /api, /mcp)
```

Checks: `cd web && npx tsc -b && npm run build` · `python server/scripts/smoke.py http://localhost:8100 EMAIL PASSWORD`
(end-to-end: REST, every MCP flow on both protocol eras, full OAuth connect/refresh/revoke; cleans up after itself).
Demo data for a local DB: `python server/scripts/seed_demo.py`.

Schema change: edit `server/app/models.py`, then `cd server && ../.venv/bin/alembic revision --autogenerate -m "…"`.

## Deploy

See [`deploy/README.md`](deploy/README.md). Day to day: `bash deploy/deploy.sh`.

## Connect an agent

- **Claude (web / desktop / Cowork):** Settings → Connectors → Add custom connector → `https://<domain>/mcp` → approve.
- **Claude Code:** `claude mcp add --transport http --scope user sales https://<domain>/mcp`, then `/mcp` to sign in
  (or create an API key in Settings and add `--header "Authorization: Bearer <key>"`).
- **Anything else:** API key from Settings as a bearer token, against `/mcp` or `/api`.
