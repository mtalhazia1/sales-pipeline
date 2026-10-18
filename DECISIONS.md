# Judgment calls

Append-only. Each section records liberties taken with the brief, defaults nobody specified, and options
deliberately not taken — so the owner can overrule any of them.

## v1 build — 2026-10-03

**Liberties with the stated spec**
- **States.** The brief listed: Sent matcher (Toptal only), sent/applied, call booked, Replied, Rejected,
  Client replied/messaged, contract done. Implemented as one ordered pipeline: Lead → Sent to matcher → Applied →
  Replied → Call booked → Proposal sent → Contract done / Lost. Read "Replied" vs "Client replied/messaged" as
  *whose turn it is* in the conversation, which flips back and forth, so it is a separate **Whose move** field
  (mine / client's) set automatically from logged messages, not two stages. "Rejected" = Lost with a reason
  (Rejected, No response, I passed, Filled, Other), so ghosting and passing are not counted as rejections.
- **Added stages:** *Lead* (found but not applied yet — what agents produce, triaged on Today) and *Proposal sent*
  (the normal services step between a call and a contract).
- **Added channels:** Referral, Other. **Added network:** Referral / personal.
- **Reminder** is a list per opportunity (date + note, done/snooze), not a single date field — one open deal can
  have a follow-up and a scheduled call.
- **Added fields:** title, inbound flag, contact (name/email/profile), budget as posted, deal value (USD), fit 1–5,
  notes, job post text.

**Added because a 1-person sales operation needs them**
- **Today** screen: due reminders → your move → gone quiet (open deal, no reminder, idle past a per-stage threshold)
  → new leads (sorted by fit) → coming up. The same agenda is an MCP tool, so an agent can write a daily brief.
- **Review queue**: everything an agent writes is flagged until a person approves it (or edits that deal); every
  event names its actor. Matches "added via agents, reviewed/monitored by humans".
- **Insights**: reply rate, calls, wins and value by channel / network (warm vs cold) / type, median days to
  reply, 12-week activity. Counted from milestone timestamps, so a deal later lost still counts as replied.
- **Dedup by posting URL** (Upwork `~01…` ids, LinkedIn job ids, tracking params stripped) — agents re-find the
  same posts constantly.
- Quick-add defaults to a 3-day follow-up reminder for applications (changeable, can be unticked).

**Unspecified defaults chosen**
- MCP: SDK `mcp` 2.3.0 = protocol 2026-07-28 (latest), still serving older handshake clients. Stateless HTTP.
- Agent auth: OAuth 2.1 (dynamic registration + PKCE + consent screen) because Claude's connectors require it,
  plus named API keys for headless agents. Access tokens 1h, refresh 90d with rotation.
- Human auth: email + password (argon2), 30-day sliding session; accounts created by CLI (no public sign-up).
- Storage: SQLite (WAL) in the app's own state dir — maximum isolation from other projects on the box, nothing to run.
- Gone-quiet thresholds (days idle): matcher 7, applied 5, replied 2, call 2, proposal 3.
- Timezone: adopted from the browser on first login; editable in Settings.
- Domain: `sales.muhammadtalhabinzia.com` (owner's call — independent of FirstGlance; apex stays the about site).

**Not built (deliberately)**
- Separate Companies/Contacts tables — company is text on the opportunity; add when one client has many deals.
- Email/LinkedIn/Upwork syncing inside the app — that's the agents' job, through MCP.
- Multi-tenant workspaces, roles, passkeys, notifications by email — not needed for one person.
- Docker / a separate Postgres — SQLite + a sandboxed systemd unit give the isolation with less to maintain.

## Hosting — 2026-10-03

- The owner moved the personal about site (`muhammadtalhabinzia.com`) to the same new server first; it now lives
  in its own repo `~/Code/personal-site` (it was in no repo before) with the same isolation pattern.
- Fresh Let's Encrypt certs on the new box instead of copying the old box's keys.
- DNS points at the new box's current public IP (<server-ip>). When FirstGlance's Elastic IP moves to this box,
  that IP is released — re-point `@`, `www`, `sales` at Namecheap to <elastic-ip> in the same step.
- The about site's contact beacon is proxied to the FirstGlance API by Elastic IP (not 127.0.0.1:5000), so it
  keeps emailing across the cutover without an edit.

## Re-review fixes — 2026-10-07

**Behaviour changes (each a judgment call — overrule freely)**
- **Lost needs a reason**, everywhere (agents, API, UI already did). The old silent default "rejected" inflated
  rejections in Insights; ghosted/passed/filled mean different fixes.
- **A client message revives only a ghosted deal** (lost · no response). On a deal lost for any other reason
  ("thanks, we went with someone else") it is logged on the timeline and the deal stays lost.
- **Marking a deal lost completes its open reminders** (logged); a **won** deal keeps them — kickoff and invoice
  reminders are real work.
- **Moving a deal back to an earlier stage un-stamps the milestones past it** (a misdrag to Won and back no longer
  counts as "replied" forever). The stage is the truth; Insights counts milestones.
- **Sent to matcher counts as the application** for Toptal (stamps applied), so Toptal shows up in the funnel.
  **Lost reasons** in Insights now cover every deal that died in the window, including leads you passed on.
- **Dedup only on real posting URLs.** "N/A", emails, bare homepages, LinkedIn profiles/feeds and Upwork pages
  without a job id no longer count as identity (two different deals were being silently merged). `source`,
  `src` and `origin` query params are kept (they are posting ids on some boards). Hash-routed career sites keep
  their `#/job/…` part.
- **Agents can't log the future.** `occurred_at` more than 10 minutes ahead is refused with guidance (log the
  booking now, put the call time in a reminder). Backdated messages move a milestone earlier.
- "Whose move" defaults to **yours** when a deal lands on Replied by any path, not only via a logged message.
- MCP: `complete_reminder` became **`update_reminder`** (done / reschedule / reword); tools now return
  structured JSON; `find_opportunities` reports `more` and accepts one stage or a list.
- Today: one-click outcomes (Pass, let go, Applied, Done) show a toast with **Undo**; **Applied adds a 3-day
  follow-up**, the same as Quick add. "Approve all" asks first and approves only the deals on screen.
- Changing your password **signs out every other browser** (agent keys and connected apps are left alone —
  revoke those in Settings).

**Security hardening**: bounded OAuth registration (stored fields trimmed, nginx rate limit, never-connected
clients purged daily — no hard count cap, which would let anyone lock the owner out) and pending authorizations
(short fields, oldest evicted past 1000); argon2 checks two at a time and attempts counted before
checking (a burst of logins could OOM the service); same response time for unknown emails; exact-Origin CSRF
check; URL fields accept web addresses only; text length caps; nginx rate limit on login and OAuth endpoints;
extra systemd sandboxing (no outbound network, no devices).

**Not done (deliberately)**: undelete (a delete is confirmed and agents can't delete); per-account login lockout
(the per-IP limit plus nginx is enough for one owner); refresh-token reuse detection (rotation is in place); a
`last_message` preview in the agenda (agents can call get_opportunity).

## Agent alerts — 2026-10-12

- New MCP tool **`notify_owner`** (title, optional message / deal / link) → the **Alerts** page (sidebar, badge,
  `G A`), plus an "unread alerts" button on Today. In-app only: no email or push, because the ask was "I check it
  when I'm available".
- An alert is **its own record** (who sent it, when, read or not). It is not a deal timeline event and doesn't flag
  the deal for review, since it says nothing new about the deal. Alerts can't be deleted; mark them read.
- **No duplicates while unread**: the same title for the same deal (or for no deal) returns the existing alert with
  `created=false`, so a scheduled agent can't flood the inbox. Once you read it, the same alert can be sent again.
- An alert about a deal that later gets deleted stays, without the deal link.

## Application documents and first-contact messages — 2026-10-14

- **Job applications** carry `resume_url`, `cover_letter_url` (the tailored Google Drive copies the applicant agent
  makes for each job) and `resume_version`, a short label for the base resume it was tailored from. Every copy has
  its own URL, so the URL can't group anything. The label is what lets Insights compare resumes ("By resume version").
  All three fields are on the deal, not on a timeline event, because there's one set per application. Shown in the
  drawer for jobs only. Upwork projects don't use them (Upwork keeps the proposal).
- **Messages** page: first-contact variants per category (LinkedIn message, cold email, warm email; emails have a
  subject). One per category is **current**; the first variant added becomes current automatically. Agents fetch
  it with MCP `get_message_template` and send it word for word, filling only `{placeholders}`. Replies are never
  templated. Only people can write templates.
- The deal remembers **which variant was sent** (`template_id`, set by `log_activity kind=my_message template_id=…`
  or from the drawer). Insights shows "By first message", and each variant card shows sent / replied / calls / won.
- **Editing** a variant changes it in place. Past deals then point at the edited text (owner's choice: minor tweaks
  are edits, a different approach is a new variant). **Deleting** a variant that a live deal used archives it
  instead, so its stats and the deals' "first message" names survive. A variant used only by deleted deals is
  removed outright.
- No current variant in a category → `get_message_template` returns an error telling the agent not to send and to
  `notify_owner`.
- Smoke test adds a non-current "Smoke Test variant" and deletes it at the end, so it never changes what real agents
  send. It becomes current only if the LinkedIn category was empty.
- Template edits are **not** timeline events. Events belong to a deal, templates are owner-only settings, and the
  `updated_at` on each variant is enough.

## Re-review fixes: templates and application docs — 2026-10-14

Judgment calls (overrule any of them):
- **One first message per deal.** `log_activity` refuses a *different* template_id once a deal has one
  ("templates are for first contact only"). Otherwise a later LinkedIn nudge silently re-credits a reply to the
  wrong variant. People can still change it in the drawer.
- **Follow-ups aren't templated either.** The agent sets a reminder instead. The ask covered first contact
  (templates) and replies (owner); follow-ups were unspecified, so they go to the safer side.
- **Warm vs cold** for agents: warm = they know the owner, or the deal's network is referral / FirstGlance. A
  LinkedIn connection alone is cold. This keeps the Insights comparison clean.
- **Unfillable placeholder → don't send, notify_owner.** `get_message_template` now returns the `placeholders` list.
- **Email variants require a subject.**
- **Deleting the current variant doesn't promote another.** The page warns in the confirm dialog and shows a
  "no current message" banner on the category until one is picked.
- A deleted (archived) variant can't be newly assigned to a deal. A deal keeps the one it already has.
- "Sent" on the Messages page counts only deals that were actually sent (applied), matching Insights.
- Search / add / update results now include `template_id` and the doc links, so an agent can see what was already sent.

## Message categories as data + template usage telemetry — 2026-10-15

Ask: agents (via MCP) and the owner (in the UI) can create categories of fixed text and messages inside them, and
record how often each message is used on each platform, with a graph.

- **Categories are data now**, not `domain.py` vocabulary: a `message_categories` table with a name, a **purpose**
  (when agents should send it; this is the rule they follow) and a "has a subject line" flag. The three old categories
  are seeded with the same keys (`linkedin`, `cold_email`, `warm_email`), so existing agent calls keep working.
  The warm/cold and first-contact rules moved out of the MCP instructions into their purposes, so you can edit them.
- A category's **key** is derived from its name once and never changes; renaming keeps it, because agents use it.
  Whether a category's messages have a subject can only change while it has no messages.
- **Agents can create and edit** categories and messages (`save_message_category`, `save_message_template`), and
  can make a message current. They can't delete. This overrules "only people can write templates". What an agent
  writes is **flagged for review**, the same rule as deals: a chip on the Messages page and a badge on the nav.
  "Looks good", or any save by you, clears it. An agent's first message in a new category goes live (becomes
  current) at once, because that's what you'd be asking for. Agents write through MCP only; REST stays human-only.
- **Usage = logged sends.** Every `my_message` now records the platform it went out on (the deal's channel, or
  `channel` when the agent sent it elsewhere) and, with `template_id`, the template it used. Counts come from
  those timeline events, with no separate counter to drift. Deleted deals don't count, as everywhere else.
  Existing history was backfilled: each deal's recorded first message is credited to its earliest sent message.
- **A deal can use several templates now.** The old "one template per deal" refusal is gone. The deal's *first
  message* (which the reply-rate comparison uses) is the first template sent before the client ever replied. Later
  ones (a rate card, a follow-up category) are counted as uses but never re-credit the reply.
- Insights: **"Message templates sent"**, stacked bars per message coloured by platform, with a table view.
  It uses the page's time window. Each message card shows "Used N× · per platform" plus its first-message results.
  `pipeline_stats` returns the same data as `template_usage`.
- An empty category can be deleted. One that has messages can't (delete them first). One whose deleted messages
  still have history is archived, not removed, so Insights can still name them.
- The smoke test now uses its own throwaway categories, so it never adds variants next to the real messages
  agents send.

## Agent State module — 2026-10-18

Ask: scheduled Claude agents (applying, LinkedIn, Upwork, forums) need memory across runs (cursors, caps, items
already seen, halts, run history) kept in the pipeline over MCP, not in local files or their own memory. Built from
the "Agent State API" spec, then its revision 2 (same day, before release: workers of one agent racing on shared
rows, halts raised mid-run, lists worked on a schedule, long drafts, agents retrying once after a timeout). It ships
as one migration (`0b8c5799a1ac_agent_state`). Judgment calls (overrule any of them):

- **Owner rows = rows with the `locked` flag**, not "anything the owner touched". Otherwise rewinding an agent's
  cursor from the State page would freeze that agent for good. Rows you add are locked by default; editing an agent's
  row keeps it writable unless you tick "Owner row". Rules for agents (rev 2): in a fixed section they can't change or
  delete an owner row; in a list they may only `merge` fields into it (and set its `due`), not set, delete or expire
  it. Rejections read `owner_row: …`. A locked row always reads `by: owner`, also after an agent merged into it.
  run_start lists the owner rows of its brief under `owner`. Agents can't lock or unlock.
- **No timeline event, no review flag** for state writes (same reasoning as alerts): they aren't deal facts, and
  ~700 runs a day would bury Review. The State page (rows + Runs list) is where you watch them; what needs you still
  comes through notify_owner.
- **Counter windows are UTC** as the spec says: "today" for a daily cap starts at 00:00 UTC, not local midnight.
- **Names are normalized to lowercase** (`LinkedIn` → `linkedin`) so one typo can't split a namespace in two.
- **Value limits** (rev 2): fixed sections 500 characters (keeps the brief small), lists 16,000 (drafts). Over → rejected
  with the limit named, never trimmed. The ~2 KB run_start brief is a design target, not enforced.
- **`due` and `expires` share one rule:** omitted = unchanged, `null` = cleared (a new row has neither). Rows are read
  earliest-due first (undated last) within each section; `state_get` returns 100 rows by default (max 500,
  `more: true` when cut). `run_start include=[lists]` returns each list's rows due now, up to 50.
- **A stop row halts counting** (rev 2): `count` refuses every item, changing nothing, while any namespace in the call
  has a live `stop` row, and quotes it (`stopped`). The stop wins even over an idem replay.
- **`count idem`** replays only a *successful* reply for 24 hours. A refusal spent nothing, so storing it would block a
  legitimate retry after the cap resets or the stop clears.
- **`run_end` is idempotent per run** (rev 2): its first reply is stored on the run itself (not in the 24-hour idem
  table, since runs live 60 days); a repeat returns it and applies nothing. A run closed because its lease ran out
  (recorded as `error` "Ended without run_end") can still be ended once with its real outcome.
- **Concurrency:** every read-modify-write (merge, max, counters, leases, run_end) takes SQLite's write lock before it
  reads (`service._write_lock`), and `seen` is a single upsert, so concurrent workers never lose a merge, an increment
  or a cursor advance. Tested with 30-60 parallel calls.
- **`seen` ids expire** after `ttl_days` (default 90); an expired id counts as new again at once, not only after the
  nightly purge.
- Small additions that save agents calls or mistakes: `seen(mark=false)` checks without marking; a change can name
  another `ns` (set a shared stop from run_end); times accept `now`, `30m / 12h / 7d` as well as ISO; `merge` with a
  null field drops it; run_start also returns list names with row counts.
- **"Forget namespace"** (State page, owner only) deletes all of an agent's rows, counters, seen ids and runs — for
  retiring an agent. The smoke test uses it to clean up after itself, so prod keeps no residue.
- REST endpoints mirror the six tools (`/api/state…`) for scripts with an API key; Claude agents use MCP.
- Nightly (the backup timer): expired rows and seen ids, idem keys older than 24 hours, counter windows idle for 90
  days and runs older than 60 days are deleted. The backup itself is a full SQLite snapshot, so the new tables are in it.

### Re-review fixes (same day, before release)

Four independent audits (concurrency, spec conformance, input edges / security, web UI); every finding re-checked
before fixing. Judgment calls in the fixes:
- **Owner list rows:** agents may add or update fields, not remove them. A merge with a null field on an owner row
  is refused; otherwise "merge but not set" could be emptied field by field.
- **`max` refuses mixed kinds** (number vs text, booleans): as text "9" > "10", which would move a cursor back. ISO
  times compare as times, offsets included.
- **`count idem` belongs to the call:** the same key with different items (another agent, another cap) is a new spend.
- **Omitting `value` on an existing row keeps it** (change only due / expires / lock). The State page uses this to send
  only what you changed, so a lock-only save can't overwrite an agent's newer write or round a big number.
- **MCP takes `changes` as plain objects**, validated one by one: a typed model made one bad change reject the whole
  call (leaving a run_end's lease held) and dropped unknown fields silently.
- **REST commits before it answers** (`api.DB`, FastAPI dependency `scope="function"`). This applies to every endpoint
  and predates the module: before, a client could be told a write succeeded whose commit hadn't run (or failed).
- Left as is: your edit of a value while an agent merges into it is last-writer-wins; an owner row you unlock reads
  `by: owner` until an agent writes it (`locked` is the protection flag); the MCP SDK pretty-prints text content
  (`structuredContent` is compact).

## Message templates are recommended examples, not fixed text — 2026-10-18

Ask: templates are a recommendation and an example for the agent, not text it sends word for word. (This reverses the
2026-10-14 answer "agent copy word for word".)

- **Agents adapt the current message**: keep its point, tone and length, change the wording to fit the person and
  the post, or send it as is when it already fits. Placeholders are filled only with facts the agent verified; one it
  can't fill is worded around, never invented. Before, an unfillable placeholder meant "don't send, notify_owner".
- **Nothing else in the 2026-10-15 categories work changes.** Categories with a purpose, agents creating and editing
  them for review, and usage per platform all hold for examples too. "Used N×" now means "messages based on it", and
  the reply-rate comparison compares approaches rather than exact wording. The agent still logs the text it
  actually sent, so you can see how far it strayed.
- **Kept: no current message means don't send.** A category without an example still blocks agents (they
  notify_owner), so nothing goes out in a category you haven't written an example for.
- Only wording changed (MCP instructions and tool descriptions, the Messages page, comments). No schema or behaviour
  change in the server.

### Re-review fixes (message categories and templates) — 2026-10-18

Independent audit of the 2026-10-15 categories work and the examples change (server, MCP contract, UI).
- **"Already contacted" is the stage, not `template_id`.** A deal's template_id is only its first message for
  reply credit; replied or hand-written deals never get one, so it can't tell an agent whether someone was
  contacted. First-contact categories now say "only while the deal is still a lead (nothing sent to them yet)",
  in the seeded purposes and the instructions. Anything sent moves a deal past lead.
- **No current message ⇒ don't write one** is now in the instructions too, not only in the error.
  get_message_template returns the category's name and purpose, so an agent that calls it directly still
  sees when the message applies.
- **An agent's new message goes live by itself only as a category's first message.** Before, it also did in a
  category you'd left with none current. A message you add still becomes current when none is. Agents
  can't un-current a message (that would stop all sending in that category); only you can.
- **Saves from the Messages page carry the version they showed.** "Looks good", "Use this" or an editor
  save on a message an agent changed since you loaded the page is refused (409, "reload and look again"),
  so you never approve or overwrite text you didn't see. Agents and older clients that don't send it are unaffected.
- **Template ids are never reused** (AUTOINCREMENT, added by the same unreleased migration's table rebuild).
  Agents keep ids; before, deleting an unused message and adding another handed the new one the old id.
- A template sent before the client's reply but logged after it now counts as the first message.
- Category names compare accent- and case-insensitively; keys drop accents ("École" → `ecole`), never end in `_`.
  Category creates take the write lock, so two agents adding one name get one category and a refusal.
- UI: Insights no longer scrolls sideways on a phone (long labels wrap and show "(deleted)"; the table
  scrolls inside its card); long links wrap in message cards; renames refresh open timelines; buttons
  name their message.
- Left as is: a first message set by hand (Drawer / update_opportunity) or by the backfill counts toward
  reply rates without a logged use; a deleted message can't be logged again except on its own deal; the
  Drawer's first-message list includes every category; MCP validation errors from the SDK are multi-line.

## Agent-facing text re-review — 2026-10-18

Two audits: every claim in the MCP instructions, tool docs and AGENT_GUIDE.md checked against the code, and a
fresh agent working only from that text on a scratch server.
- **Stops block spending, not reads or give-backs.** Revision 2 said a stop refuses every count item; an agent
  then couldn't check its budget or return a spend it didn't use. A call that spends is still refused whole.
  Stops stay per namespace (not per key): the guide says to put a narrow brake in its own namespace.
- **Owner list rows accept a due-only change** with the default op (before, only `op: merge` could reschedule).
- add_opportunity takes `lost_reason`, so a deal can be added as lost.
- MCP accepts any item in `changes`, so a non-object one is rejected alone instead of failing the whole call
  (and leaving run_end's lease held).
- Text: reminders vs agents' own to-dos (state list rows with due), how the owner's answers reach an agent, one
  API key per agent, `seen(mark=false)` then mark, times without an offset are the owner's timezone, name rules,
  `max` needs JSON numbers, `count` reads report `allowed`, lost completes reminders, and similar.
- Left as is (documented instead): reminder notes are cut at 500 characters; `max` compares non-ISO text as text;
  `due` on a fixed-section row is stored but nothing hands it to you; a duplicate notify_owner keeps the first
  message.

### Second pass — 2026-10-18
- **A call that spends is refused while any namespace in it has a stop**, even if the spend is in another
  namespace of the call. That's how an agent honours a shared namespace's stop. Reads and give-backs alone still
  pass; their reply carries `stopped`, and a read shows `allowed: false`.
- `idem` is ignored for calls that only read (replaying one showed a stale value).
- A deal added as lost refuses `reminder_at` (it would sit on Today; a won deal may keep one, e.g. kickoff); a
  rejected change carries its `index` in `changes`.
- After a stop refuses an idem retry, the agent retries the same call once the stop clears instead of giving the
  spend back (a give-back doesn't remove the stored success, so a later replay would act without spending).
- Docs: owner rows are the locked ones (an owner edit to an agent's row answers it, the row stays the agent's);
  finishing an owner list to-do = merge the outcome and clear `due`; next steps are for deals past lead;
  how to undo a wrong timeline entry; lease timing; UTC counter days; a stop beats an idem replay.
- Left as is: run_start returns only the stops (and counters) of `also` namespaces, not their other owner rows
  (the guide says to state_get them);
  `waiting_on` can be set but not cleared.

### Fourth pass — 2026-10-19
- **A refused add_opportunity no longer leaves the deal behind** (older than this work). pysqlite opens a
  transaction only at the first write, so the duplicate-check SAVEPOINT was the outermost transaction and
  committed the deal; a bad `reminder_at` then errored with the deal already saved (no "created" event; a retry
  saw a duplicate, or made a second deal without a URL). create now takes the write lock first.
- idem guidance: make keys unique per agent and action; keep a stopped action in a list row and retry the same
  call when the stop clears (after 24h it spends again); give back only when dropping the action for good.
- Merging into a locked owner row whose value isn't an object says what to do instead (change its due, record the
  outcome in your own row).
- Left as is: set_reminder works on a lost deal (a deliberate "check back in Q1"); only an add-as-lost with
  reminder_at is refused, since that one is usually a reflex.
- Also taking the write lock: log_activity, notify_owner and update_template (two agents at once could double an
  alert or log changes against a stale stage). Guide: give back only a spend you saw succeed, with its own idem.

## Agents' own follow-ups — 2026-10-19

Gap: an agent's own follow-up on a deal had no good home. As a reminder it filled the owner's Today list; kept
only in agent state, Today showed the deal as "gone quiet".
- **Reminders can be tagged `for_agent`** (set_reminder / update_reminder, REST too). One counts as the deal's
  next step, so the deal never looks quiet. It's left out of the owner's Today and upcoming lists until it's
  more than 24 hours late (`AGENT_REMINDER_MISSED_HOURS`): then it shows under Due as "<agent> missed this".
- Agents pick up their due follow-ups from get_agenda's `agent_due` and mark them done; `for_agent: false`
  hands one to the owner. Non-deal to-dos stay in state list rows with `due`.
- One migration (`5d2e8a41c9f7`) adds the column; existing reminders stay the owner's.
- Also locked: update (an agent logging on a deal while another updates it left stage and whose-move out of step)
  and update_reminder. Guide: give a spend back only in the same counter window (a give-back after UTC midnight
  lands in the new day and would let its cap be passed).
