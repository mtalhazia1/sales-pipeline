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

**Security hardening**: bounded OAuth registration (stored fields trimmed, 50 new clients/day, unused ones purged
daily) and pending authorizations (100, short fields); argon2 checks two at a time and attempts counted before
checking (a burst of logins could OOM the service); same response time for unknown emails; exact-Origin CSRF
check; URL fields accept web addresses only; text length caps; nginx rate limit on login and OAuth endpoints;
extra systemd sandboxing (no outbound network, no devices).

**Not done (deliberately)**: undelete (a delete is confirmed and agents can't delete); per-account login lockout
(the per-IP limit plus nginx is enough for one owner); refresh-token reuse detection (rotation is in place); a
`last_message` preview in the agenda (agents can call get_opportunity).
