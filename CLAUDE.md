# CLAUDE.md — Sales Pipeline

Sales monitoring for a one-person B2B software/AI services business. Agents add most data via MCP;
humans review and monitor in the web UI. Standalone project — NOT part of FirstGlance (it only shares
the EC2 host; see `deploy/README.md` for the per-project isolation convention).

## Rules that matter
- **One source of truth per concern.** Vocabulary (stages, channels, networks, kinds, lost reasons,
  activity kinds, message template categories) lives ONLY in `server/app/domain.py`; the UI reads it from `/api/meta`, MCP tool schemas
  use its Literals. All business rules live ONLY in `server/app/service.py`; `api.py` (humans) and
  `mcp_server.py` (agents) are thin adapters — never put logic in them.
- Every write goes through `service.*` with an `Actor`, which records an `Event` (timeline + audit log) and
  sets `needs_review` (agent → true, human → false). Don't bypass it.
- Times are stored naive UTC; date-only input means 09:00 in the workspace timezone (`settings.timezone`).
  Convert a stored datetime to epoch with `.replace(tzinfo=UTC)` — a bare `.timestamp()` reads it as local time.
- MCP SDK is `mcp==2.3.0` (`MCPServer`, not FastMCP). Raise `ToolError` for messages the agent should see —
  other exceptions are hidden as "Error executing tool".
- Single uvicorn worker by design (in-memory login throttle + pending OAuth consents).
- Simplicity first: SQLite, one process, no queue, no Docker. Push back on complexity that adds little.

## Verify
- `cd web && npx tsc -b && npm run build`
- `python server/scripts/smoke.py <base_url> <email> <password>` against a running server — covers REST,
  all MCP tools on both protocol eras, and the full OAuth flow. Run it after any server change.

## Deploy
`bash deploy/deploy.sh` (see `deploy/README.md`). Judgment calls taken on the owner's behalf: `DECISIONS.md`
(append a dated section when you take a new one).
