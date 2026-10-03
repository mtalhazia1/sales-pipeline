"""MCP server — the agent interface. Every tool is a thin call into app.service, so agents and the
web UI share one set of rules. Agents are identified by their token's name in the audit trail and
everything they write lands in the human Review queue."""

from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from app import config, service
from app.db import session_scope
from app.domain import ActivityKind, Channel, Kind, LostReason, Network, Stage, WaitingOn
from app.oauth import SCOPE, Provider
from app.service import Actor, ServiceError

INSTRUCTIONS = """\
Sales pipeline for a one-person B2B software / AI services business. Each record is an
*opportunity*: a job or project at a client company, found on a channel (LinkedIn, Email, Upwork,
Toptal, Direct/Website, Referral), optionally reached through a network (LinkedIn, FirstGlance,
Referral).

Stages, in order: lead (found, not applied yet) → matcher (Toptal only: sent to a matcher) →
applied → replied (client responded) → call (call booked) → proposal (proposal sent) →
won (contract done) | lost (with lost_reason).

How to work:
- Before adding, call find_opportunities — or just call add_opportunity with the application_url:
  the same posting is never stored twice (it returns the existing one with created=false).
- Record conversation with log_activity, not by editing the stage: a client_message moves the
  deal to "replied" and marks it "your move"; a my_message marks it "their move"; a call moves
  it to "call". Use update_opportunity for facts (stage jumps like proposal/won/lost, budget,
  value, contact) and set_reminder for every next step — an open deal should always have one.
- Only mark won/lost with clear evidence (a signed contract, an explicit rejection).
- Put the job post text in `description`, your reasoning in `notes`; set `fit` 1-5 when you
  judge how well a lead matches (5 = perfect fit for an AI / full-stack software shop).
- Dates: YYYY-MM-DD (means 09:00 in the owner's timezone) or ISO-8601 datetime.
- Everything you write is shown to the owner for review; be factual and concise.
"""

mcp = MCPServer(
    name="sales-pipeline",
    title="Sales Pipeline",
    instructions=INSTRUCTIONS,
    version="1.0.0",
    auth_server_provider=Provider(),
    auth=AuthSettings(
        issuer_url=config.BASE_URL,
        resource_server_url=f"{config.BASE_URL}/mcp",
        validate_token_resource=False,  # API keys carry no resource; tokens are only ever ours
        client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
    ),
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
IDEMPOTENT_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


def _actor() -> Actor:
    token = get_access_token()
    name = ((token.claims or {}).get("actor_name") if token else None) or "Agent"
    return Actor("agent", name, int(token.subject) if token and token.subject else None)


def _run(fn, *args, **kwargs) -> Any:
    try:
        with session_scope() as s:
            return fn(s, *args, **kwargs)
    except ServiceError as e:
        raise ToolError(e.message) from e  # surfaces to the agent as a tool error it can act on


Str = Annotated[str | None, Field(default=None)]


@mcp.tool(annotations=READ)
def find_opportunities(
    query: Annotated[str | None, Field(description="Text to match in company, title, contact, notes or URL")] = None,
    stage: Annotated[list[Stage] | None, Field(description="Only these stages")] = None,
    channel: Channel | None = None,
    network: Network | None = None,
    kind: Kind | None = None,
    waiting_on: Annotated[WaitingOn | None, Field(description="'me' = the owner owes a reply")] = None,
    include_closed: Annotated[bool, Field(description="Include won/lost deals")] = True,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> dict:
    """Search the pipeline. Returns compact summaries, most recently active first."""
    def go(s):
        rows = service.search(s, q=query, stage=stage, channel=channel, network=network, kind=kind,
                              waiting_on=waiting_on, include_closed=include_closed, limit=limit)
        return {"count": len(rows), "opportunities": [service.summary(o) for o in rows]}
    return _run(go)


@mcp.tool(annotations=READ)
def get_opportunity(opportunity_id: int) -> dict:
    """Full record: every field, reminders and the timeline of messages, calls, notes and changes."""
    return _run(lambda s: service.detail(s, service._get(s, opportunity_id)))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def add_opportunity(
    company: Annotated[str, Field(description="Client or company name")],
    kind: Kind = "job",
    title: Annotated[str | None, Field(description="Job / project title")] = None,
    application_url: Annotated[str | None, Field(description="The posting or application link — used to prevent duplicates")] = None,
    company_url: str | None = None,
    channel: Annotated[Channel | None, Field(description="Where it was found; inferred from the URL when omitted")] = None,
    network: Network = "none",
    stage: Stage = "lead",
    inbound: Annotated[bool, Field(description="True when the client reached out first")] = False,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_url: Annotated[str | None, Field(description="Contact's LinkedIn or profile URL")] = None,
    budget: Annotated[str | None, Field(description="Budget as posted, e.g. '$50-70/hr' or '$8k fixed'")] = None,
    value: Annotated[float | None, Field(description="Expected contract value in USD")] = None,
    fit: Annotated[int | None, Field(ge=1, le=5, description="How good a match, 1-5")] = None,
    description: Annotated[str | None, Field(description="The job post / project brief")] = None,
    notes: str | None = None,
    reminder_at: Annotated[str | None, Field(description="Optional first follow-up date")] = None,
    reminder_note: str | None = None,
) -> dict:
    """Add a job or project. Safe to call for something that may already exist: if the
    application_url matches an existing record, nothing changes and that record is returned
    with created=false (use update_opportunity / log_activity to change it). deleted=true means the
    owner deleted it on purpose — leave it alone."""
    data = {k: v for k, v in locals().items() if v is not None}

    def go(s):
        opp, created = service.create(s, _actor(), data)
        return {"created": created, "opportunity": service.summary(opp)}
    return _run(go)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def update_opportunity(
    opportunity_id: int,
    stage: Stage | None = None,
    lost_reason: Annotated[LostReason | None, Field(description="Set with stage='lost'")] = None,
    waiting_on: WaitingOn | None = None,
    company: str | None = None,
    title: str | None = None,
    kind: Kind | None = None,
    application_url: str | None = None,
    company_url: str | None = None,
    channel: Channel | None = None,
    network: Network | None = None,
    inbound: bool | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_url: str | None = None,
    budget: str | None = None,
    value: float | None = None,
    fit: Annotated[int | None, Field(ge=1, le=5)] = None,
    description: str | None = None,
    notes: Annotated[str | None, Field(description="Replaces the notes; read them first to append")] = None,
) -> dict:
    """Change fields of an opportunity. Only the fields you pass are changed."""
    fields = {k: v for k, v in locals().items() if v is not None and k != "opportunity_id"}
    if not fields:
        raise ToolError("Pass at least one field to change.")
    return _run(lambda s: service.summary(service.update(s, _actor(), opportunity_id, fields)))


@mcp.tool(annotations=WRITE)
def log_activity(
    opportunity_id: int,
    kind: Annotated[ActivityKind, Field(description="client_message | my_message | call | note")],
    summary: Annotated[str, Field(description="What was said or happened, in a sentence or two")],
    occurred_at: Annotated[str | None, Field(description="When it happened (default now)")] = None,
) -> dict:
    """Record a message, call or note on the timeline. Moves the stage forward and sets whose move
    it is (see server instructions)."""
    return _run(lambda s: service.summary(service.log_activity(s, _actor(), opportunity_id, kind, summary, occurred_at)))


@mcp.tool(annotations=WRITE)
def set_reminder(
    opportunity_id: int,
    due: Annotated[str, Field(description="YYYY-MM-DD or ISO datetime")],
    note: Annotated[str, Field(description="The next step, e.g. 'Follow up if no reply'")] = "",
) -> dict:
    """Schedule the next step for an opportunity. It shows up on the owner's Today list when due."""
    return _run(lambda s: service.reminder_dict(service.add_reminder(s, _actor(), opportunity_id, due, note)))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def complete_reminder(reminder_id: int) -> dict:
    """Mark a reminder done."""
    return _run(lambda s: service.reminder_dict(service.update_reminder(s, _actor(), reminder_id, done=True)))


@mcp.tool(annotations=READ)
def get_agenda() -> dict:
    """Today's priorities: due/overdue reminders, deals where the owner owes a reply, open deals that
    went quiet without a next step, best new leads, and the coming week's reminders."""
    return _run(service.agenda)


@mcp.tool(annotations=READ)
def pipeline_stats(days: Annotated[int | None, Field(ge=1, description="Look-back window; omit for all time")] = 90) -> dict:
    """Funnel and conversion rates (reply, win) by channel, network and kind; open pipeline by stage;
    12 weeks of activity."""
    return _run(service.stats, days)
