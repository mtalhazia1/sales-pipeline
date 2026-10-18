# CLAUDE.md — Sales Pipeline

Sales monitoring for a one-person B2B software/AI services business. Agents add most data via MCP;
humans review and monitor in the web UI. Standalone project — NOT part of FirstGlance (it only shares
the EC2 host; see `deploy/README.md` for the per-project isolation convention).

## Rules that matter
- **One source of truth per concern.** Vocabulary (stages, channels, networks, kinds, lost reasons,
  activity kinds, agent-state sections / run statuses / counter periods) lives ONLY in `server/app/domain.py`; the UI reads it from `/api/meta`, MCP tool schemas
  use its Literals. Message template categories are data (`message_categories`, editable by the owner and by
  agents via MCP), not vocabulary. All business rules live ONLY in `server/app/service.py`; `api.py` (humans) and
  `mcp_server.py` (agents) are thin adapters — never put logic in them.
- Every write goes through `service.*` with an `Actor`, which records an `Event` (timeline + audit log) and
  sets `needs_review` (agent → true, human → false). Don't bypass it. Exception: agent state (`agent_*` tables,
  scheduled agents' run memory) records no Event and no review flag — ~700 runs a day would bury Review.
- Read-modify-writes that agents can race (agent state, create, update, log_activity, reminders, notify,
  category saves, template edits)
  call `_write_lock(s)` first: MCP sync tools run in threads, and SQLite only serializes them if the write lock
  is taken before the read. (pysqlite opens a transaction only at the first write, so a SAVEPOINT before any
  write would commit on its own.)
- Times are stored naive UTC; date-only input means 09:00 in the workspace timezone (`settings.timezone`).
  Convert a stored datetime to epoch with `.replace(tzinfo=UTC)` — a bare `.timestamp()` reads it as local time.
- MCP SDK is `mcp==2.3.0` (`MCPServer`, not FastMCP). Raise `ToolError` for messages the agent should see —
  other exceptions are hidden as "Error executing tool".
- Single uvicorn worker by design (in-memory login throttle + pending OAuth consents).
- Simplicity first: SQLite, one process, no queue, no Docker. Push back on complexity that adds little.
- Agent-facing text (MCP `INSTRUCTIONS`, tool and field descriptions, service error messages) is a guide, not a
  script: give the intent, the exact inputs/outputs (types, formats, limits) and the few hard rules the server
  enforces; leave the rest to the agent's judgment. Absolute wording ("never", "only", "word for word") is for
  rules the server actually enforces — agents follow text literally.
  `AGENT_GUIDE.md` is the run-state guide the owner pastes into scheduled agents: update it with the state tools.

## Verify
- `cd web && npx tsc -b && npm run build`
- `python server/scripts/smoke.py <base_url> <email> <password>` against a running server — covers REST,
  all MCP tools on both protocol eras, and the full OAuth flow. Run it after any server change.
- `python server/scripts/state_test.py` — agent-state rules (concurrent counters, `max`, lease expiry, locks, caps,
  seen) on a throwaway DB. Run it after touching the agent-state code in `service.py`.

## Deploy
`bash deploy/deploy.sh` (see `deploy/README.md`). Judgment calls taken on the owner's behalf: `DECISIONS.md`
(append a dated section when you take a new one).
