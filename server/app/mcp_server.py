"""MCP server — the agent interface. Every tool is a thin call into app.service, so agents and the
web UI share one set of rules. Agents are identified by their token's name in the audit trail and
everything they write about deals and templates lands in the human Review queue (agent state doesn't)."""

from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from app import config, service
from app.db import session_scope
from app.domain import ActivityKind, Channel, CounterPeriod, Kind, LostReason, Network, RunStatus, Stage, WaitingOn
from app.oauth import SCOPE, Provider
from app.service import Actor, ServiceError

INSTRUCTIONS = """\
Sales pipeline for a one-person B2B software / AI services business. The owner uses it to see every
opportunity they're pursuing and decide where to spend their time, so what you record should match
what really happened. Each record is an *opportunity*: a job or project at a client company, found on
a channel (LinkedIn, Email, Upwork, Toptal, Direct/Website, Referral), optionally reached through a
network: how the owner knows them (a LinkedIn connection, FirstGlance, a referral or personal contact).

Stages, in order: lead (found, nothing sent yet) → matcher (Toptal only: sent to a matcher) →
applied → replied (client responded) → call (call booked) → proposal (proposal sent) →
won (contract done) | lost (with lost_reason).

This is guidance, not a script. The owner wants work that fits, a professional reputation and no
wasted time. When a situation isn't covered here or a guideline doesn't fit it, do what a careful
assistant to the owner would do, note your reasoning, and ask with notify_owner when the decision is
really theirs. Where the instructions you were given differ from this guidance, follow yours. The
server enforces the few hard rules; when it refuses a call, its message says why and what to do instead.

Deals:
- Search before adding (find_opportunities matches any form of a posting URL). Giving add_opportunity
  the posting's own URL also prevents duplicates; without one, nothing does.
- Record what happens with log_activity and let it move the stage, so the deal follows the
  conversation. Use update_opportunity for facts and for moves no message implies (proposal sent, won,
  lost). Mark won or lost on clear evidence, such as a signed contract or an explicit no.
- Keep one next step on every deal in progress (past lead); a deal without one gets forgotten.
  set_reminder adds one, update_reminder moves or rewords it (its id is next_reminder.id in the deal's
  summary). Reminders are the owner's Today list: steps they take, following up with the client
  included (e.g. 'Follow up if no reply'). A scheduled agent's own to-dos belong in a state list row
  with `due`.
- The job post goes in `description`, your assessment in `notes`, running commentary in a note
  activity. `fit` 1-5 is your judgment of the match (5 = ideal for an AI / full-stack software shop).
- Job applications: the tailored resume and cover letter live in the owner's Google Drive; store their
  links and the base resume you started from (resume_version, same label each time) so Insights can
  compare versions.

Messages:
- Message templates are the owner's examples of messages that recur: how they like to open a LinkedIn
  conversation, a cold or a warm email. Each category's `purpose` says when it applies; judge whether
  this situation fits. Use the current message as a model, not a script: say what it says, in the
  owner's voice and at about its length, written for this person and this post (as is, if it already
  fits). Fill {placeholders} with facts you checked; if you can't, write around it rather than guess.
- First-contact categories are for deals still at lead. A category with no current message means the
  owner hasn't decided what to send: ask them rather than write your own.
- What is unique to a deal (proposals, cover letters) is written fresh. Replies and follow-ups are the
  owner's unless a category's purpose says otherwise.
- After sending, log_activity kind=my_message with the template_id it was based on and what you
  actually sent, so the owner sees it and Insights counts it per platform.
- Create or edit categories and messages when the owner asks; they review what you write.

The owner:
- notify_owner when something needs them to act or decide (a question only they can answer, an offer,
  a call time, a close deadline), not for routine progress: the activity log already shows that.
- Everything you write about deals and templates goes to their review, so keep it factual and short.
- You can't delete deals, timeline entries, messages or categories. A deal added by mistake: log a
  note starting "DELETE:". A wrong timeline entry: log a note correcting it, put back what you can
  with update_opportunity (stage, inbound, waiting_on) and tell the owner what's left. A wrong template or category:
  notify_owner.
- Dates: YYYY-MM-DD (09:00 in the owner's timezone) or an ISO-8601 time with an offset or Z (one
  without is read in the owner's timezone). Times come back in UTC; get_agenda gives today and the
  timezone. Pass "" to clear a text field.

Scheduled agents:
- Keep run state here, never in local files or your own memory: run_start first (cursors, stops,
  counters, due rows, your last summary), seen to skip items you already evaluated, count before each
  capped action, run_end last with your changes. state_get / state_set share lists between agents
  (e.g. contacts already emailed). A stop row is a brake set by the owner or another agent: obey it
  (count refuses any spending in a call that involves its namespace).
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


# A typed (not bare `dict`) return is what makes the SDK publish an output schema and send
# structuredContent — agents then get JSON objects instead of a text blob.
Result = dict[str, Any]


@mcp.tool(annotations=READ)
def find_opportunities(
    query: Annotated[str | None, Field(description="Text to match in company, title, contact, notes, job post, or any form of the posting URL")] = None,
    stage: Annotated[Stage | list[Stage] | None, Field(description="Only this stage / these stages")] = None,
    channel: Channel | None = None,
    network: Network | None = None,
    kind: Kind | None = None,
    waiting_on: Annotated[WaitingOn | None, Field(description="'me' = the owner owes a reply")] = None,
    include_closed: Annotated[bool, Field(description="Include won/lost deals")] = True,
    limit: Annotated[int, Field(ge=1, le=200)] = 50,
) -> Result:
    """Search the pipeline. Returns compact summaries (id, company, title, stage, whose move, next
    reminder, template_id, ...), most recently active first; more=true means further matches beyond
    `limit`. A deal still at stage lead has had nothing sent yet."""
    stages = [stage] if isinstance(stage, str) else stage

    def go(s):
        rows = service.search(s, q=query, stage=stages, channel=channel, network=network, kind=kind,
                              waiting_on=waiting_on, include_closed=include_closed, limit=limit + 1)
        return {"count": min(len(rows), limit), "more": len(rows) > limit,
                "opportunities": [service.summary(o) for o in rows[:limit]]}
    return _run(go)


@mcp.tool(annotations=READ)
def get_opportunity(opportunity_id: int) -> Result:
    """Full record: every field, reminders, and the latest 100 timeline events (messages, calls, notes,
    changes)."""
    return _run(lambda s: service.detail(s, service._get(s, opportunity_id)))


@mcp.tool(annotations=WRITE)
def add_opportunity(
    company: Annotated[str, Field(description="Client or company name")],
    kind: Kind = "job",
    title: Annotated[str | None, Field(description="Job / project title")] = None,
    application_url: Annotated[str | None, Field(description="The posting or application link — used to prevent duplicates")] = None,
    company_url: str | None = None,
    channel: Annotated[Channel | None, Field(description="Where it was found; when omitted, upwork / toptal / linkedin from the URL, else other")] = None,
    network: Annotated[Network, Field(description="How the owner knows them")] = "none",
    stage: Annotated[Stage, Field(description="Starting stage. Something you applied to and lost: add it at applied, then mark it lost, so Insights counts the application")] = "lead",
    lost_reason: Annotated[LostReason | None, Field(description="Required with stage='lost'")] = None,
    inbound: Annotated[bool, Field(description="True when the client reached out first")] = False,
    contact_name: str | None = None,
    contact_email: str | None = None,
    contact_url: Annotated[str | None, Field(description="Contact's LinkedIn or profile URL")] = None,
    budget: Annotated[str | None, Field(description="Budget as posted, e.g. '$50-70/hr' or '$8k fixed'")] = None,
    value: Annotated[float | None, Field(description="Expected contract value in USD")] = None,
    fit: Annotated[int | None, Field(ge=1, le=5, description="How good a match, 1-5")] = None,
    description: Annotated[str | None, Field(description="The job post / project brief")] = None,
    notes: Annotated[str | None, Field(description="Your assessment: why it fits or doesn't, risks, what to mention")] = None,
    resume_url: Annotated[str | None, Field(description="Job applications: Google Drive link to the tailored resume sent")] = None,
    resume_version: Annotated[str | None, Field(description="Which base resume it was tailored from, e.g. 'AI engineer v2' — groups results in Insights")] = None,
    cover_letter_url: Annotated[str | None, Field(description="Job applications: Google Drive link to the cover letter sent")] = None,
    reminder_at: Annotated[str | None, Field(description="First next step (not on a lost deal): YYYY-MM-DD or ISO datetime")] = None,
    reminder_note: Annotated[str | None, Field(description="What that next step is")] = None,
) -> Result:
    """Add a job or project; returns created and the deal's summary. If application_url is a posting
    already tracked, nothing changes and that deal comes back with created=false (then use
    update_opportunity). Roles sharing one URL (a careers page) count as one posting:
    pass each role's own link, or none. deleted=true means the owner deleted it on purpose: leave it alone."""
    data = {k: v for k, v in locals().items() if v is not None}

    def go(s):
        opp, created = service.create(s, _actor(), data)
        return {"created": created, "opportunity": service.summary(opp)}
    return _run(go)


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def update_opportunity(
    opportunity_id: int,
    stage: Annotated[Stage | None, Field(description="For moves no message implies (proposal, won, lost) or to correct one; log_activity moves the rest. lost also completes the deal's open reminders")] = None,
    lost_reason: Annotated[LostReason | None, Field(description="Required with stage='lost'. no_response = they went silent: a later client_message reopens only that kind")] = None,
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
    value: Annotated[float | None, Field(description="Expected contract value in USD")] = None,
    fit: Annotated[int | None, Field(ge=1, le=5, description="How good a match, 1-5")] = None,
    description: Annotated[str | None, Field(description="The job post / project brief")] = None,
    notes: Annotated[str | None, Field(description="Replaces the notes; read them first to append")] = None,
    resume_url: Annotated[str | None, Field(description="Job applications: Google Drive link to the tailored resume sent")] = None,
    resume_version: Annotated[str | None, Field(description="Which base resume it was tailored from, e.g. 'AI engineer v2' — groups results in Insights")] = None,
    cover_letter_url: Annotated[str | None, Field(description="Job applications: Google Drive link to the cover letter sent")] = None,
    template_id: Annotated[int | None, Field(ge=1, description="Only to correct the deal's first message template; log_activity sets it")] = None,
) -> Result:
    """Change facts about a deal; only the fields you pass change. Returns the deal's summary."""
    fields = {k: v for k, v in locals().items() if v is not None and k != "opportunity_id"}
    if not fields:
        raise ToolError("Pass at least one field to change.")
    return _run(lambda s: service.summary(service.update(s, _actor(), opportunity_id, fields)))


@mcp.tool(annotations=WRITE)
def log_activity(
    opportunity_id: int,
    kind: Annotated[ActivityKind, Field(description="client_message = the client wrote; my_message = you or the owner sent something; call = booked or held; note = commentary")],
    summary: Annotated[str, Field(description="What was said or happened, briefly; for a message you sent from a template, the text you actually sent")],
    occurred_at: Annotated[str | None, Field(description="When it happened, if not now: ISO time or YYYY-MM-DD (09:00 owner's time); refused if over 10 min ahead")] = None,
    template_id: Annotated[int | None, Field(ge=1, description="kind=my_message only: id of the template your message was based on")] = None,
    channel: Annotated[Channel | None, Field(description="kind=my_message only: where you sent it, if not the deal's channel (e.g. emailed a LinkedIn lead)")] = None,
) -> Result:
    """Record a message, call or note on the timeline; it moves the deal along by itself:
    client_message → stage replied (if earlier) and it's the owner's move; my_message → a lead becomes
    applied and it's the client's move; call → stage call if earlier (put the call time in set_reminder).
    note changes nothing. Returns the deal's summary."""
    return _run(lambda s: service.summary(service.log_activity(s, _actor(), opportunity_id, kind, summary, occurred_at,
                                                               template_id, channel)))


@mcp.tool(annotations=READ)
def list_message_templates(
    category: Annotated[str | None, Field(description="Only this category key; default all")] = None,
) -> Result:
    """The owner's message examples: every category (key, name, purpose = when it applies, has_subject)
    with its messages (id, name, subject, body, placeholders, is_current, usage per platform and as a
    first message). Read it to see which category fits, or before editing them for the owner."""
    return _run(lambda s: {"categories": service.library(s, category)})


@mcp.tool(annotations=READ)
def get_message_template(
    category: Annotated[str, Field(description="Category key from list_message_templates, e.g. linkedin, cold_email, warm_email")],
) -> Result:
    """The current message in a category: id, name, subject (if it has one), body, placeholders, and the
    category's name and purpose (when it applies). A model, not a script: say what it says in the
    owner's voice, written for this person; fill placeholders with facts you checked or write around
    them. Then log_activity kind=my_message with template_id=id and what you sent."""
    return _run(service.current_message, category)


@mcp.tool(annotations=WRITE)
def save_message_category(
    name: Annotated[str | None, Field(description="Shown to the owner, e.g. 'Rate card'; required when creating")] = None,
    purpose: Annotated[str | None, Field(description="When and to whom it applies; agents read it to decide whether to use the category")] = None,
    has_subject: Annotated[bool | None, Field(description="Its messages have a subject line (emails). Only changeable while it has no messages")] = None,
    key: Annotated[str | None, Field(description="An existing category's key to change it; omit to create a new one")] = None,
) -> Result:
    """Create a message category (omit key) or change one (pass key; only the fields you pass change),
    when the owner asks. The key is derived from the name and never changes; returns the category."""
    fields = {k: v for k, v in {"name": name, "purpose": purpose, "has_subject": has_subject}.items() if v is not None}
    if key is None:
        return _run(lambda s: {"created": True, "category": service.category_dict(service.create_category(s, _actor(), fields))})
    if not fields:
        raise ToolError("Pass name, purpose or has_subject to change.")
    return _run(lambda s: {"created": False, "category": service.category_dict(service.update_category(s, _actor(), key, fields))})


@mcp.tool(annotations=WRITE)
def save_message_template(
    category: Annotated[str | None, Field(description="Category key; required when creating")] = None,
    name: Annotated[str | None, Field(description="Short label, e.g. 'Short intro v2'; required when creating")] = None,
    body: Annotated[str | None, Field(description="The example message; {placeholders} like {first_name} mark what changes per person. Required when creating")] = None,
    subject: Annotated[str | None, Field(description="Subject line: required in categories with has_subject, ignored in others")] = None,
    make_current: Annotated[bool | None, Field(description="true = this becomes the one agents work from in its category (a category's first message is current anyway; only the owner can unset it)")] = None,
    template_id: Annotated[int | None, Field(ge=1, description="An existing message's id to change it; omit to create a new one")] = None,
) -> Result:
    """Create a message in a category (omit template_id) or edit one (pass it; only the fields you pass
    change), when the owner asks. A new category's first message becomes current by itself. A different
    approach is a new message, so Insights can compare them; a small fix is an edit."""
    fields = {k: v for k, v in {"name": name, "body": body, "subject": subject, "is_current": make_current}.items()
              if v is not None}
    if template_id is None:
        return _run(lambda s: {"created": True, "message": service.template_dict(
            service.create_template(s, _actor(), {"category": category, **fields}))})
    if category is not None:
        fields["category"] = category  # the service refuses a move to another category
    if not fields:
        raise ToolError("Pass name, body, subject or make_current to change.")
    return _run(lambda s: {"created": False, "message": service.template_dict(service.update_template(s, _actor(), template_id, fields))})


@mcp.tool(annotations=WRITE)
def set_reminder(
    opportunity_id: int,
    due: Annotated[str, Field(description="YYYY-MM-DD (09:00 owner's time) or ISO datetime")],
    note: Annotated[str, Field(description="The next step, e.g. 'Follow up if no reply' (max 500 characters)")] = "",
) -> Result:
    """Add a next step to an opportunity; returns the reminder (with its id). It shows up on the owner's
    Today list when due. Each call adds one: to move or reword the existing next step, use update_reminder."""
    return _run(lambda s: service.reminder_dict(service.add_reminder(s, _actor(), opportunity_id, due, note)))


@mcp.tool(annotations=IDEMPOTENT_WRITE)
def update_reminder(
    reminder_id: int,
    done: Annotated[bool | None, Field(description="true = done; false = reopen")] = None,
    due: Annotated[str | None, Field(description="Reschedule: YYYY-MM-DD or ISO datetime")] = None,
    note: Annotated[str | None, Field(description="New wording (max 500 characters)")] = None,
) -> Result:
    """Complete, reschedule or reword a reminder; returns it. Ids are in get_opportunity, get_agenda and
    each deal summary's next_reminder."""
    if done is None and due is None and note is None:
        raise ToolError("Pass done, due or note.")
    return _run(lambda s: service.reminder_dict(service.update_reminder(s, _actor(), reminder_id, done=done, due=due, note=note)))


@mcp.tool(annotations=WRITE)
def notify_owner(
    title: Annotated[str, Field(description="One line, max 200 chars: what needs the owner, e.g. 'Acme wants a call Thursday — confirm a time'")],
    message: Annotated[str | None, Field(description="Details and the action you suggest")] = None,
    opportunity_id: Annotated[int | None, Field(description="The deal this is about, if any")] = None,
    url: Annotated[str | None, Field(description="A link the owner should open (email thread, job post, ...)")] = None,
) -> Result:
    """Alert the owner about something they need to act on or decide; it lands in their Alerts inbox.
    The same unread alert (same title and deal) is never stored twice: created=false returns the
    existing one."""
    def go(s):
        n, created = service.notify(s, _actor(), title, message, opportunity_id, url)
        return {"created": created, "notification": service.notification_dict(n)}
    return _run(go)


@mcp.tool(annotations=READ)
def get_agenda() -> Result:
    """Today's priorities: due/overdue reminders, deals where the owner owes a reply, open deals that
    went quiet without a next step, best new leads, the coming week's reminders, how many alerts (from
    any agent) the owner hasn't read, and today's date and the timezone."""
    return _run(service.agenda)


@mcp.tool(annotations=READ)
def pipeline_stats(days: Annotated[int | None, Field(ge=1, description="Look-back window in days (default 90); null = all time")] = 90) -> Result:
    """Funnel and conversion rates (reply, win) by channel, network and kind, and by first message
    (by_template) and base resume (by_resume_version); how often each message template was sent in
    the window, per platform (template_usage); open pipeline by stage; 12 weeks of activity."""
    return _run(service.stats, days)


# ---------------------------------------------------------------- agent state (durable run state)

# A change is a plain object, checked one by one in the service: a typed model would make pydantic reject the
# whole call (and leave a run_end's lease held) over one bad change, and drop unknown fields silently.
CHANGES_DOC = ("Objects {section, key, value, op, due, expires, ns}. value: text, number or JSON; null deletes; omit "
               "to change only due/expires. op: set (default) | merge (JSON fields; null drops one) | max (larger "
               "number or ISO time) | delete. due, expires: ISO, now or 30m/12h/7d; null clears. ns: another "
               "namespace.")
Changes = list[Any]


class CountItem(BaseModel):
    ns: str
    key: str
    period: CounterPeriod = "day"
    by: Annotated[int, Field(description="Units to spend; 0 reads (allowed = room for one more, false during a stop); negative gives back")] = 1
    limit: Annotated[int | None, Field(ge=0, description="Refuse if this would pass it")] = None


@mcp.tool(annotations=WRITE)
def run_start(
    ns: Annotated[str, Field(description="Your namespace: your agent name, e.g. 'upwork'")],
    worker: Annotated[str, Field(description="Which job in the ns, e.g. finder, sender")] = "main",
    also: Annotated[list[str] | None, Field(description="Shared namespaces you obey, e.g. ['outreach-shared']")] = None,
    include: Annotated[list[str] | None, Field(description="List sections whose due rows you want, e.g. ['targets']")] = None,
    lease_min: Annotated[int, Field(ge=1, le=1440, description="Minutes before a crashed run frees the lease")] = 50,
) -> Result:
    """Call first in every scheduled run. Returns run_id, now, your fixed sections (`owner` names the owner's
    locked ones), list sizes, stops from `also`, counters, this worker's last run, and per `include` list its rows
    due now (earliest first, max 50); empty keys left out. busy=true: this worker is already running;
    stop (no run_end). A stop: spend nothing in its namespace."""
    return _run(service.run_start, ns, worker, also, include, lease_min)


@mcp.tool(annotations=WRITE)
def run_end(
    run_id: int,
    status: Annotated[RunStatus, Field(description="quiet = nothing happened; routine; attention = the owner should look; error")],
    summary: Annotated[str | None, Field(description="One line: what happened")] = None,
    counts: Annotated[dict[str, int | float] | None, Field(description='e.g. {"applied": 3, "skipped": 12}')] = None,
    changes: Annotated[Changes | None, Field(description=CHANGES_DOC, max_length=100)] = None,
) -> Result:
    """Call last in every run: records status, summary and counts, applies your changes (as state_set) and
    frees the lease. Returns applied and rejected changes. Safe to retry: a repeat returns the first reply
    and applies nothing."""
    return _run(lambda s: service.run_end(s, _actor(), run_id, status, summary, counts, changes))


@mcp.tool(annotations=READ)
def state_get(
    ns: Annotated[str | list[str], Field(description="A namespace, a list, or '*' for all")],
    sections: Annotated[list[str] | None, Field(description="Only these sections")] = None,
    keys: Annotated[list[str] | None, Field(description="Only these keys")] = None,
    q: Annotated[str | None, Field(description="Case-insensitive text to find in keys and values")] = None,
    due_before: Annotated[str | None, Field(description="Only rows due by then: ISO time, 'now' or e.g. 2h")] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 100,
    runs_since: Annotated[str | None, Field(description="e.g. 24h or an ISO time: adds a run digest per ns and worker")] = None,
) -> Result:
    """Read rows grouped ns → section → key (value, by, updated_at, due_at, expires_at; locked = an owner
    row), earliest due first; more=true if limit cut it. runs_since adds per worker: run count, count by
    status, summed counts, the latest 20 non-quiet summaries; then rows come only with sections, keys, q or
    due_before."""
    return _run(service.state_get, ns, sections, keys, q, due_before, limit, runs_since)


@mcp.tool(annotations=WRITE)
def state_set(
    ns: str,
    changes: Annotated[Changes, Field(min_length=1, max_length=100, description=CHANGES_DOC)],
) -> Result:
    """Write rows; each invalid change is rejected with its index and reason. Fixed sections (in run_start;
    values ≤ 500 characters): next 30, stop 5, blocker 20, waiting 20, lesson 15, platform 10, proposal 10.
    Other sections are lists: 500 rows, values ≤ 16,000, schedulable with due. Owner rows: fixed are
    read-only; in lists merge fields or change due."""
    return _run(lambda s: service.state_set(s, _actor(), ns, changes))


@mcp.tool(annotations=WRITE)
def count(
    items: Annotated[list[CountItem], Field(min_length=1, max_length=20)],
    idem: Annotated[str | None, Field(description="Unique key per action; retrying the same call within 24h replays its first success (not for read-only calls; a stop beats a replay)")] = None,
) -> Result:
    """Check and spend caps before an action, all or nothing. ok=false: nothing counted, don't act —
    `refused` names the cap, or `stopped` quotes the stop: a call that spends is refused while any of its
    namespaces has one (reads and give-backs still work, naming it). Windows (UTC): day, week (ISO), month,
    total. One item per cap."""
    return _run(service.count, [i.model_dump(exclude_none=True) for i in items], idem)


@mcp.tool(annotations=WRITE)
def seen(
    ns: str,
    source: Annotated[str, Field(description="What the ids are, e.g. upwork-jobs, forum-comments")],
    ids: Annotated[list[str | int], Field(min_length=1, max_length=500)],
    mark: Annotated[bool, Field(description="false = only check, mark later")] = True,
    ttl_days: Annotated[int, Field(ge=1, le=3650, description="How long they stay seen")] = service.SEEN_DAYS,
) -> Result:
    """Skip what you already evaluated: returns `new`, the ids not seen in this ns+source (or whose ttl ran
    out), as you sent them, and marks them seen for ttl_days. With mark=false, mark them once you've
    actually evaluated them, so a run cut short doesn't skip the rest."""
    return _run(service.seen, ns, source, ids, mark, ttl_days)
