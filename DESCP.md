# Pipeline: AI-Agent-Native Sales CRM with an MCP Server

> **Read this file for the portfolio project. You do not need to open the codebase.**
> It is written for agents that apply to jobs and bid on projects on the owner's behalf. Everything below
> is verified against the source code (as of 2026-10-08). Section 12 lists what you must **not** claim.

---

## 0. Quick facts

| | |
|---|---|
| **Project** | Pipeline: sales monitoring / lightweight CRM for a B2B software & AI services business |
| **One-liner** | A production CRM that AI agents fill in through a custom **MCP server** (Model Context Protocol, with OAuth 2.1), and a human reviews in a fast React web app |
| **Built by** | Muhammad Talha Bin Zia: solo, end to end (product design, backend, AI-agent interface, frontend, security, DevOps) |
| **Status** | **Live in production** at `https://sales.muhammadtalhabinzia.com` (login-only private tool, no public demo account) |
| **Shipped** | v1 deployed 2026-10-03 · independent end-to-end re-review + security hardening shipped 2026-10-07 |
| **Agents it works with** | Claude (web, desktop, Cowork) as a custom connector · Claude Code · any MCP client · any script via API key |
| **Backend** | Python 3.12 · FastAPI · official MCP Python SDK 2.3 (latest protocol, 2026-07-28) · SQLAlchemy 2 · Alembic · SQLite (WAL) · argon2 |
| **Frontend** | React 19 · TypeScript · Vite · Tailwind CSS v4 · TanStack Query · React Router |
| **Infra** | AWS EC2 (Ubuntu 24.04) · nginx · Let's Encrypt · systemd (sandboxed) · scripted zero-drift deploys · daily backups |
| **Size** | ~2,300 lines of Python and ~3,300 lines of TypeScript/React. Small on purpose: one process, one port, one database file |
| **Interfaces** | Web UI (5 screens + login + OAuth consent) · REST API (26 endpoints) · MCP server (9 tools) · admin CLI |
| **Code** | Private repository. Walkthrough or screen-share available on request |

---

## 1. Pitches (copy, then adapt to the job)

**One line**
> I built and run a production CRM where AI agents (Claude, via a custom MCP server with OAuth 2.1) log leads,
> messages and follow-ups, and a human approves their work in a review queue.

**Two sentences**
> Pipeline is an AI-agent-native sales CRM I designed, built and deployed solo: agents find and record jobs,
> conversations and follow-ups through a secure MCP server, and every agent write lands in a human review
> queue with a full audit trail. It runs on FastAPI + React on a hardened AWS box, with OAuth 2.1 so it plugs
> straight into Claude as a connector.

**Paragraph (for proposals and cover letters)**
> One of my recent projects is Pipeline, a CRM built for the way AI agents actually work. Agents (Claude or
> any MCP client) connect over OAuth 2.1 or an API key and use nine purpose-built tools to search the
> pipeline, add opportunities, log client messages and calls, set reminders and pull a daily agenda. The
> business rules move each deal forward automatically: a client reply flips it to "Replied, your move", and
> a booked call moves it to "Call booked". Agents can't create duplicates, can't delete, and can't log events
> in the future. Everything they write is attributed by name and held for human review. The human side is a
> keyboard-driven React app with a Today agenda, a drag-and-drop kanban, a review queue and conversion
> analytics by channel. I built the whole thing myself, from the domain model to OAuth, security hardening,
> systemd sandboxing and scripted deploys, and it runs in production with an end-to-end test suite that
> covers every MCP tool and the full OAuth flow.

---

## 2. The problem it solves

A one-person B2B software/AI consultancy gets work from many places: Upwork, LinkedIn, Toptal, email,
its own website, referrals. Following up is where deals are lost: who replied, whose turn it is, which lead
went quiet, which channel converts.

The owner wanted **AI agents to do the data entry** (scouting postings, reading inboxes, logging
conversations, scheduling follow-ups) while **a human stays in control**: one screen that says what needs
attention today, and a clear record of what each agent changed.

Off-the-shelf CRMs don't fit that. They are built for human data entry, their APIs aren't designed for LLM
agents, they have no MCP support, and they have no idea that an agent's write should be reviewed.

---

## 3. Case study (STAR / Challenge → Approach → Result)

**Challenge.** Build a sales system where AI agents are first-class users and do most of the writing, without
losing data quality, trust or control. Constraints: one owner, no ops team, shared server with other
production projects, must connect to Claude's official connector flow (which requires OAuth 2.1 with dynamic
client registration and PKCE).

**Approach.**
1. **Designed the domain first.** One ordered pipeline (Lead → Sent to matcher (Toptal) → Applied → Replied →
   Call booked → Proposal sent → Won / Lost with reason) plus a separate *"whose move"* field, because "replied"
   and "client messaged" are about whose turn it is, which flips back and forth.
2. **One rule engine, two front doors.** All business logic lives in a single service layer. The REST API
   (for humans) and the MCP server (for agents) are thin adapters over it, so agents and humans always get
   identical behaviour, validation and audit logging.
3. **Agent-proofed the API.** Deterministic, forward-only automation; URL-canonical deduplication (agents
   re-find the same posting constantly); error messages written as instructions the agent can act on;
   structured JSON outputs; tool annotations (read-only / idempotent); embedded agent operating instructions.
4. **Human-in-the-loop by construction.** Every write records an event (who, human or which agent, what,
   when). Agent writes set a `needs_review` flag that only a human clears.
5. **Production-grade auth and security** from day one: OAuth 2.1 authorization server, hashed tokens,
   refresh rotation, CSRF, CSP, rate limits, OS-level sandboxing.
6. **Kept it simple.** SQLite + one process + systemd instead of Postgres/Docker/queues. Less to run, less to
   break, and enough for the workload.

**Result.**
- Shipped to production on its own subdomain with TLS; Claude connects in three clicks (add connector → paste
  URL → approve).
- Automated end-to-end smoke test (~40 checks per run) verified against production: REST, all 9 MCP tools on
  both the current and the legacy MCP protocol handshake, and the complete OAuth flow (discovery,
  registration, consent, PKCE token exchange, single-use codes, refresh rotation, revocation).
- An independent re-review four days after launch led to a second pass of correctness and security fixes
  (bounded OAuth registration, OOM-safe password hashing, timing-safe login, stricter URL validation, kernel-
  level sandboxing), all documented in a decision log.
- Runs isolated beside other production projects on the same EC2 host: no shared users, database or secrets.

**What it demonstrates:** building AI-agent tooling (MCP) that's safe to put in front of real data,
full-stack product engineering, security engineering, and pragmatic DevOps, all by one engineer.

---

## 4. Complete capability list

### 4.1 AI agent integration (MCP server)
- **Custom MCP server** on the official Python SDK (`mcp` 2.3.0), serving the **latest protocol (2026-07-28)**
  and still accepting **older-handshake clients**, over **stateless streamable HTTP** with JSON responses.
- **9 purpose-designed tools:**
  | Tool | What it does |
  |---|---|
  | `find_opportunities` | Search by text, any form of a posting URL, stage(s), channel, network, type, "whose move"; paginates with a `more` flag |
  | `get_opportunity` | Full record + reminders + timeline of messages, calls, notes and field changes |
  | `add_opportunity` | Add a job/project; channel inferred from the URL; duplicate-safe (returns the existing record with `created=false`); optional first reminder |
  | `update_opportunity` | Change only the fields passed; validated stage rules |
  | `log_activity` | Log client message / my message / call / note; **moves the deal forward automatically** |
  | `set_reminder` | Schedule the next step (shows on the owner's Today list) |
  | `update_reminder` | Complete, reopen, reschedule or reword |
  | `get_agenda` | Today's priorities: due reminders, "your move", gone-quiet deals, best new leads, the week ahead |
  | `pipeline_stats` | Funnel and conversion by channel / network / type, open pipeline, 12-week trend |
- **Structured outputs:** typed return schemas, so agents receive JSON objects (`structuredContent`), not text blobs.
- **Tool annotations** (`readOnlyHint`, `idempotentHint`, `destructiveHint=false`) so clients can auto-approve safe calls.
- **Embedded operating instructions** tell agents how to work: search before adding, log conversations instead of
  editing stages, always leave a next step, only mark won/lost with evidence, and how dates work.
- **Errors as guidance:** business-rule violations come back as tool errors written as instructions ("Pass
  lost_reason with stage 'lost': rejected, no_response, …"; "occurred_at is in the future, log the booking now
  and set_reminder for the call time").
- **Guardrails for autonomous agents:** agents cannot delete (they flag `DELETE:` for the human); can't log the
  future; can't silently merge different deals; can't revive a deal the owner deleted; text length caps;
  URL fields accept web addresses only.
- **Agent identity & attribution:** every token has a name ("Upwork scout", "Claude", "Inbox agent") that appears
  as the actor on every change.
- **Two ways to connect:** OAuth 2.1 (Claude web/desktop/Cowork custom connector, Claude Code `/mcp` sign-in)
  and **named API keys** for headless agents, cron jobs and scripts (MCP or REST).

### 4.2 OAuth 2.1 authorization server (built for MCP)
- Full authorization server: **dynamic client registration (RFC 7591)**, **PKCE (S256)**, authorization code
  flow, **protected-resource + authorization-server metadata discovery**, token endpoint, **revocation**.
- **Custom consent screen** in the web app ("Connect Claude?" → Allow/Deny) showing the client name and return host.
- Access tokens 1 h, refresh tokens 90 days with **rotation** (each refresh token works once); single-use
  authorization codes (5 min); revoking either half of a grant ends the whole connection.
- **Redirect-URI vetting:** https anywhere, http only to loopback (native apps), custom app schemes allowed,
  script-capable schemes (`javascript:`, `data:`…) refused at registration and again before redirecting.
- **Abuse-resistant open registration:** stored client fields trimmed and length-bounded, nginx rate limits,
  never-connected clients purged daily. Deliberately **no hard cap**, which would let anyone lock the owner out.
- Settings page lists **connected apps and API keys** with created / last-used times; one-click revoke/disconnect.

### 4.3 Sales workflow & business rules
- **Opportunity model:** job or project; company, title, posting URL, company URL; channel (LinkedIn, Email,
  Upwork, Toptal, Direct/Website, Referral, Other); network (LinkedIn, FirstGlance, Referral/personal: warm vs
  cold); inbound flag; contact name/email/profile; budget as posted; deal value (USD); fit score 1–5; job-post
  text; notes; any number of reminders.
- **Ordered pipeline** with Toptal-only "Sent to matcher" stage (enforced), and **Lost requires a reason**
  (rejected, no response, I passed, filled, other), so ghosting isn't counted as rejection.
- **Automatic, predictable stage movement from conversation:** client message → Replied + "your move";
  my message → Lead becomes Applied + "their move"; call → Call booked. Forward-only.
- **Smart revival:** a client message revives only a deal that was ghosted (lost · no response), never one
  where the client said no.
- **Milestone timestamps** (applied, replied, call, proposal) so analytics stay correct even after a deal is
  lost; moving a deal backwards **un-stamps** later milestones (a misdrag doesn't distort stats); back-dated
  messages move milestones earlier.
- **Reminder hygiene:** marking a deal lost auto-completes its open follow-ups; a won deal keeps them (kickoff,
  invoicing).
- **URL-canonical deduplication** of job postings: Upwork `~01…` job IDs, LinkedIn job IDs (path or
  `currentJobId`), tracking parameters stripped (utm, trk, ref, fbclid, gclid…), hash-routed career sites kept.
  Non-postings ("N/A", emails, homepages, LinkedIn profiles) are never used as identity, so different deals are
  never silently merged. Race-safe: two agents adding the same posting at once get the same row.
- **Deletions stick:** an agent re-finding a deleted posting cannot bring it back.
- **Timezone-aware scheduling:** date-only input means 09:00 in the owner's timezone; adopted from the browser
  on first login; editable.

### 4.4 Human-in-the-loop & audit
- **Event log = timeline = audit trail:** every create, field change (old → new), message, call, note,
  reminder and review is recorded with actor type (human/agent), actor name and time.
- **Review queue:** anything an agent writes is flagged until a human approves it or acts on that deal;
  shows each agent's recent changes inline; "Approve all" approves **only the deals on screen**, not ones an
  agent added since the page loaded.
- **Activity feed** filterable by everyone / agents / people.

### 4.5 Daily agenda ("Today"): shared by the UI and agents
- Prioritised: **due & overdue reminders → your move → gone quiet → new leads (by fit) → coming up (7 days)**.
- **"Gone quiet" detection:** open deals with no next step, idle past per-stage thresholds (applied 5 days,
  replied 2, call 2, proposal 3, matcher 7).
- **One-click triage with Undo:** Applied (auto-adds a 3-day follow-up), Pass, Let go (lost · no response),
  I replied, Done, +1 day snooze.
- The same agenda is an MCP tool, so an agent can write the owner a **daily briefing**.

### 4.6 Analytics ("Insights")
- KPI tiles: applied, **reply rate**, calls, wins + won value, **median days to reply**.
- **Funnel by channel, by network (warm vs cold), by job vs project**: applied → replied → calls → won, with
  inbound counted separately so it doesn't inflate outbound rates.
- **Open pipeline by stage** with value; **lost reasons** breakdown; **12-week activity chart** with hover detail.
- Windows: 30 d / 90 d / 1 y / all time. Available to agents via `pipeline_stats`.

### 4.7 Web app UX
- **Screens:** Today, Pipeline (kanban board + sortable table), Review, Insights, Settings, Login, OAuth consent.
- **Kanban with drag-and-drop** stage changes (asks for the lost reason when dropped on Lost), per-column counts
  and value; list view sortable by company, stage, channel, next step, value, last activity.
- **Deal drawer** that opens over any page and lives in the URL (`?o=12`: shareable, survives reload);
  inline editing of every field; message / call / note / reminder composers (⌘/Ctrl+Enter); timeline with
  human-readable change history.
- **Keyboard-first:** ⌘K / `/` command palette (search deals, jump anywhere), `N` new opportunity,
  `G` then `T/P/R/I/S` navigation, Esc handling layered (field → drawer).
- **Quick add:** paste a URL and the channel fills itself; optional follow-up reminder (1–14 days); detects
  "already in your pipeline" and opens it.
- **Friendly input parsing:** deal value accepts `8000`, `8k`, `1.5M`.
- **Toasts with Undo**, promise-based confirm dialogs for destructive actions, API keys shown exactly once.
- **Dark / light theme** (persisted, no flash on load), **mobile-responsive** (bottom nav, list view on
  phones, safe-area insets), accessible controls (ARIA labels, keyboard-operable rows, focus rings).
- Live data: background refresh every 30–60 s and on window focus; filters in the URL; no spinners on filter
  changes (previous results kept).

### 4.8 Security engineering
- **Passwords:** argon2; ≥10 chars; **constant-time response for unknown emails** (no user enumeration);
  hashing concurrency-limited so a login burst can't OOM the service; per-IP brute-force throttle
  (8 / 15 min) counted *before* the slow check so parallel guesses can't slip through.
- **Sessions:** random token in an HttpOnly, Secure, SameSite=Lax cookie; only the SHA-256 stored; 30-day
  sliding expiry; **password change signs out every other browser**.
- **All credentials stored hashed** (sessions, API keys, OAuth access/refresh tokens, auth codes).
- **CSRF:** exact-Origin check on every state-changing request.
- **Strict Content-Security-Policy** (no inline scripts), HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy.
- **MCP transport security:** DNS-rebinding protection with allowed hosts/origins.
- **Input hardening:** URL fields limited to http(s) (blocks `javascript:` links in the UI), length caps on
  every text field, enum validation, request-size limits in nginx.
- **Rate limiting** in nginx: general limit, plus a tight limit on login and OAuth endpoints.
- **OS-level sandbox (systemd):** dedicated no-login user, read-only OS and code, single writable private
  state dir (0700, umask 077), **no outbound network**, no devices, no new privileges, empty capability set,
  kernel tunables/modules/logs protected, namespace and SUID restrictions, 512 MB memory cap.

### 4.9 DevOps, reliability & operations
- **One-command deploy** (`deploy.sh`): builds the UI, rsyncs code, re-installs systemd units and the nginx
  site from the repo every time (**zero configuration drift**), installs dependencies, restarts, health-checks
  locally and publicly.
- **Safe changes to a shared nginx:** the new site file is staged in a root-owned location, validated with
  `nginx -t`, and **rolled back automatically** if it fails, so other projects on the box are never affected.
- **Idempotent, phased provisioning** (`provision.sh app` / `web`): system user, units, venv, then nginx +
  Let's Encrypt via webroot.
- **Database migrations** with Alembic, run automatically on every start.
- **Daily backups** via a systemd timer using SQLite's online backup API (consistent while live), 14 kept,
  carried off-box by EBS snapshots; the same job purges expired sessions/tokens/codes and abandoned OAuth clients.
- **Multi-project hosting convention** documented: per-app user, port registry, data dir, nginx file, cert,
  backups. The next project is a copy-paste.
- Admin CLI over SSH: create user, reset password, delete user.
- Health endpoint; journald logging.

### 4.10 Code quality & process
- **Single source of truth:** sales vocabulary defined once in Python; the UI loads it from `/api/meta` and
  the MCP tool schemas are generated from the same types. Add a stage once and it appears everywhere.
- **Layered architecture:** domain → service (all rules) → thin REST and MCP adapters.
- **End-to-end smoke test** (~40 checks) runnable against any environment including production, cleans up
  after itself.
- TypeScript strict build, Ruff linting, demo-data seeder for local development.
- **Decision log** (`DECISIONS.md`): every judgment call, default and deliberately-not-built feature recorded
  with reasoning so the owner can overrule any of them.

---

## 5. Architecture

```
  Claude / Claude Code / any MCP client          Browser (React SPA)            Scripts / cron agents
          │  OAuth 2.1 or API key                     │ session cookie              │ API key
          ▼                                           ▼                             ▼
  ┌────────────────────────── nginx (TLS, HSTS, CSP, rate limits) ──────────────────────────┐
  └──────────────────────────────────────────┬──────────────────────────────────────────────┘
                                             ▼  127.0.0.1 only
  ┌──────────────────── one Python process (uvicorn, sandboxed by systemd) ───────────────────┐
  │  /mcp + OAuth endpoints (MCP SDK)     /api REST (FastAPI)       static SPA                 │
  │            └───────────── thin adapters ─────────────┘                                     │
  │                               ▼                                                            │
  │          service layer: ALL business rules, validation, audit events, review flag          │
  │                               ▼                                                            │
  │          SQLAlchemy 2 → SQLite (WAL)  ·  domain vocabulary (single source of truth)        │
  └────────────────────────────────────────────────────────────────────────────────────────────┘
          daily systemd timer → consistent SQLite snapshot (14 kept) + auth-table cleanup
```

**Data model (9 tables):** users, web sessions, agent tokens (API keys + OAuth access/refresh), OAuth clients,
OAuth codes, opportunities, reminders, events (timeline + audit), settings.

**Design principles worth mentioning to technical reviewers**
- Agents and humans share one code path, so there is no "agent API" that drifts from what the UI does.
- Automation is deterministic and forward-only: predictable for both the human and the LLM.
- When in doubt, prefer a visible duplicate over silently merging two different records.
- Simplicity is a feature: SQLite + one process gives isolation and reliability with nothing extra to operate.

---

## 6. Tech stack (for keyword matching)

| Layer | Technologies |
|---|---|
| Language | Python 3.12, TypeScript |
| Backend | FastAPI, Starlette, Pydantic, Uvicorn (ASGI) |
| AI / agents | Model Context Protocol (MCP) server, MCP Python SDK 2.3, streamable HTTP transport, tool schemas/annotations, structured tool output; Claude connectors, Claude Code |
| Auth | OAuth 2.1, PKCE, Dynamic Client Registration (RFC 7591), OAuth metadata discovery, token revocation & rotation, API keys, argon2 password hashing, cookie sessions |
| Data | SQLAlchemy 2.x ORM, Alembic migrations, SQLite (WAL mode) |
| Frontend | React 19, Vite, Tailwind CSS v4, TanStack Query (React Query), React Router, lucide icons |
| Infra | AWS EC2, Ubuntu 24.04, nginx (reverse proxy, TLS, rate limiting, security headers), Let's Encrypt / certbot, systemd services & timers, Bash deploy automation, rsync, SSH |
| Quality | End-to-end smoke tests (httpx + MCP client), Ruff, TypeScript strict builds |

---

## 7. Skills demonstrated (ATS / profile keywords)

AI agent development · MCP server development · Model Context Protocol · Claude integration · LLM tool
design · agentic workflows · human-in-the-loop AI · AI automation · AI guardrails · OAuth 2.1 / OIDC-style
auth flows · API design (REST) · Python backend development · FastAPI · SQLAlchemy · database design &
migrations · React / TypeScript frontend · Tailwind CSS · SPA development · responsive & accessible UI ·
keyboard-driven UX · data visualization / dashboards · CRM development · sales automation · workflow
automation · internal tools · SaaS MVP development · application security (CSRF, CSP, rate limiting, hashing,
input validation) · Linux server administration · nginx · systemd hardening · AWS EC2 deployment · CI-style
deploy scripting · backups & disaster recovery · end-to-end testing · technical documentation · product
thinking · solo full-stack delivery.

---

## 8. Which angle to use for which job

| Job / project is about… | Lead with | Evidence to cite |
|---|---|---|
| **MCP servers, Claude/LLM tool integration, AI agents** | The MCP server + OAuth 2.1 + guardrails | 9 tools, structured outputs, tool annotations, errors-as-instructions, both protocol eras, connects to Claude in 3 clicks |
| **Agentic automation / AI workflow for a business** | Agents do data entry, humans approve | Review queue, attribution per agent, deterministic automation, daily agenda tool for briefings |
| **CRM, sales tools, pipeline/lead tracking, internal tools** | The product itself | Kanban, Today agenda, follow-up engine, dedup, conversion analytics by channel |
| **Full-stack (Python + React) / SaaS MVP** | End-to-end ownership, shipped to production | FastAPI + React 19 + TS, REST API, auth, deploy, tests, all by one engineer |
| **Backend / API / Python** | Service-layer design, data integrity | One rules engine behind REST and MCP, URL canonicalization, race-safe inserts, migrations |
| **Auth / security / OAuth** | Built an OAuth 2.1 authorization server | PKCE, DCR, rotation, redirect vetting, CSRF, CSP, timing-safe login, systemd sandbox |
| **DevOps / Linux / AWS / deployment** | Zero-drift deploys on a shared host | Scripted deploy with nginx validate-and-rollback, sandboxed units, backups, multi-project isolation convention |
| **Frontend / React / UX** | Keyboard-first, fast UI | Command palette, drag-and-drop, URL-state drawer, inline edit, undo toasts, dark mode, mobile |
| **Data / dashboards / analytics** | Insights page | Funnel by segment, reply/win rates, median time-to-reply, 12-week trend, cohort by application date |

---

## 9. Ready-to-adapt proposal snippets

**For an MCP / AI-agent integration job**
> I've built and deployed a production MCP server from scratch: an OAuth 2.1 authorization server (dynamic
> client registration, PKCE, refresh rotation) so it connects to Claude as a custom connector, plus nine tools
> with typed structured outputs, safety annotations and errors written so the agent can correct itself.
> The bigger lesson was designing tools that LLMs use reliably: deterministic side effects, duplicate-safe
> writes, no destructive actions, and a human review queue for everything an agent changes. I'd bring the
> same approach to your [system].

**For a CRM / internal-tool / workflow-automation job**
> I recently built Pipeline, a sales CRM where AI agents log leads, conversations and follow-ups, and a human
> reviews their work. It has a prioritised daily agenda, drag-and-drop kanban, automatic stage changes driven
> by logged messages, follow-up reminders with "gone quiet" detection, and conversion analytics by channel.
> It's live in production. I can build you something equally focused, without the bloat of a generic CRM.

**For a full-stack / MVP job**
> I take products from idea to production on my own. My recent project, Pipeline, is a FastAPI + React 19/TypeScript
> app with a REST API, an MCP server for AI agents, OAuth 2.1, analytics dashboards, and a hardened AWS deployment
> with one-command deploys, automated backups and an end-to-end test suite. I keep architectures simple so they're
> cheap to run and easy for your team to own.

**For a security / DevOps-flavoured job**
> On my latest production app I implemented OAuth 2.1 with PKCE and token rotation, exact-origin CSRF checks,
> a strict CSP, timing-safe and OOM-safe password login, and nginx rate limiting. It runs in a tightly
> sandboxed systemd unit (no outbound network, read-only filesystem, empty capability set). Deploys are
> scripted and drift-free, and nginx changes are validated and rolled back automatically on a host shared
> with other production apps.

---

## 10. Answers to common client questions

- **"Have you worked with MCP / Claude?"** Yes. I built a production MCP server on the official SDK, on the latest
  protocol version while staying compatible with older clients, with OAuth so it works as a Claude custom
  connector and in Claude Code.
- **"How do you stop AI agents from messing up data?"** Agents and humans go through the same validated
  business rules. Writes are deduplicated and attributed to the named agent. Agents can't delete or log the
  future. Everything an agent writes waits in a human review queue.
- **"Can it scale?"** It's deliberately sized for its workload (single process, SQLite in WAL mode), which keeps
  it reliable and nearly free to run. The layered design (all rules in one service layer, ORM, migrations)
  means moving to Postgres and multiple workers is a contained change when needed.
- **"Can I see it?"** It's a private production tool behind a login. I can give a live walkthrough or a
  screen-share of the app and the code.
- **"How long did it take?"** Don't quote a build duration (none is recorded). Say v1 went to production on
  2026-10-03 and a full re-review and hardening pass shipped four days later.

---

## 11. Engineering judgment highlights (good for senior-level roles)

- Treated "whose turn it is" as its own field, not a pipeline stage, after noticing that a conversation's turn
  flips repeatedly while the deal's stage only moves forward.
- Chose **visible duplicates over silent merges**: URL dedup only applies to real posting URLs.
- Made analytics **milestone-based** so a lost deal still counts as "replied", then made backward moves
  un-stamp milestones so a misdrag can't distort stats.
- Bounded OAuth registration **without a hard cap**, because a cap would let anyone lock the owner out of
  connecting their own agents.
- Limited argon2 concurrency after working out that a burst of logins could exceed the memory cap.
- Logged every judgment call in a decision log so the client can overrule any default.
- Said no to complexity that adds little: no Docker, no separate DB server, no queue, no multi-tenancy for a
  single-owner tool.

---

## 12. Guardrails for agents using this file (do not overstate)

**True, safe to claim:** everything in sections 0–11; live in production; built solo; MCP + OAuth 2.1;
works with Claude; security hardening listed above; end-to-end tested against production.

**Do NOT claim:**
- User counts, revenue, deals closed or ROI produced by the tool. None are recorded. Describe engineering
  outcomes, not business metrics.
- That it is multi-tenant, a commercial SaaS, or has paying customers. It is a single-owner internal tool.
- Built-in email/LinkedIn/Upwork syncing or scraping. Agents do that externally through MCP; the app has
  no outbound network access by design.
- That it uses Postgres, Docker, Kubernetes, Redis or a queue. It doesn't, on purpose.
- That the app itself calls an LLM API. It's the system agents *use*; it contains no model calls.
- A public GitHub link or a public demo login. The repo is private; offer a walkthrough instead.
- A specific number of days or hours it took to build.

---

## 13. What the owner can build for clients based on this project

- MCP servers that expose a client's own systems (CRM, ERP, database, internal APIs) to Claude and other agents,
  securely, with OAuth and audit trails.
- Human-in-the-loop AI workflows: agents draft or enter data, and people approve it in a review queue.
- Focused internal tools and CRMs: pipelines, follow-up engines, agendas, analytics dashboards.
- Full-stack MVPs (Python/FastAPI + React/TypeScript) shipped to production with auth, tests and deploys.
- Production hardening: OAuth/auth reviews, security headers, rate limiting, Linux/systemd sandboxing,
  backups, zero-drift deploy scripts.
