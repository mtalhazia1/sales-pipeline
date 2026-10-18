# Run state for scheduled agents (Sales Pipeline MCP)

Paste this into a scheduled agent's instructions. When you connect, the server's own instructions cover deals,
messages and the owner; this guide covers remembering things between runs.

## Why this exists
You run on a schedule and start each run with no memory of the last one. The pipeline remembers for you:
what you've already looked at, where you left off, what you learned, what you're waiting for, and how much of
each daily budget is spent. Keep all of that here, never in local files or your own memory. That way any run
(or another agent, or the owner on the State page) can pick up where the last one stopped.

Use your judgment about what is worth remembering. A good test: would the next run behave worse without it?
Keep rows short and specific, and drop them when they stop being true.

## A run
1. **`run_start` first.** It returns your brief: where you left off, any stops, today's counters, your last
   run's summary and the list rows due now. Read it before deciding what to do.
   If it says `busy`, another run of this worker is still going, so end quietly.
2. **Work.** Before evaluating a batch of items, pass their ids to `seen` and only look at the new ones.
   Before each action with a budget (a connection request, an application, an email), call `count`. If it
   says no, don't act. It's either the budget or a stop, and both are deliberate.
3. **`run_end` last**, with an honest status and a one-line summary, plus the changes you want remembered.
   Retrying it is safe. If you crash, the lease frees itself after `lease_min`, and the run is logged as an error.

## What to keep where
Your namespace (`ns`) is your agent name (e.g. `upwork`). Shared namespaces (e.g. `linkedin`) hold budgets,
stops and lists that several agents respect; name the ones you follow in `also`.

Fixed sections come back in every brief, so keep them small:

| Section | For | Rows |
|---|---|---|
| `next` | where you left off: cursors, last-checked times, what to pick up next | 30 |
| `stop` | brakes on an activity (an account warning, "pause outreach"). Obey them | 5 |
| `blocker` | you're stuck and need the owner: say exactly what they must do | 20 |
| `waiting` | waiting on the owner or someone else | 20 |
| `lesson` | something you learned that should change how you work next time | 15 |
| `platform` | how a site behaves: limits, quirks, what breaks | 10 |
| `proposal` | a change you suggest to the owner (to your rules, budgets, targets) | 10 |

Any other section name is a **list** you define yourself (`targets`, `contacts`, `drafts`, …), with one row
per key. Read lists with `state_get`. Give a list row a `due` time to be handed it in `run_start` when it's due.

**Owner rows** (`by: owner`) are instructions from the owner: follow them. In fixed sections you can't change
them. In lists you can add or update fields, but not remove them or replace the row. If one looks wrong or out
of date, say so with `notify_owner` or a `proposal` row instead of working around it.

A `blocker` or `waiting` row is your own record of the problem. When the owner actually needs to act, also
call `notify_owner`: that's what reaches them.

## Reference
Times you send: ISO-8601, `YYYY-MM-DD` (09:00 in the owner's timezone), `now`, or a duration from now
(`30m`, `12h`, `7d`). Times you get back are UTC (`…Z`). Namespaces, sections, workers and sources are case-insensitive; row keys are exact.
Errors are one line saying what to fix.

**`run_start(ns, worker="main", also=[], include=[], lease_min=50)`**
→ `run_id`, `now`, `state` (your fixed sections), `owner` (which rows are the owner's), `lists` (row counts),
`also` (stops in those namespaces), `counters`, `last` (this worker's last run), `include` (for each listed list,
rows due now, earliest first, up to 50). Or `busy: true` when this worker is already running. `worker` separates
jobs in one ns (e.g. `finder`, `sender`); different workers never block each other.

**`run_end(run_id, status, summary, counts, changes)`**
`status`: `quiet` (nothing happened), `routine`, `attention` (the owner should look) or `error`. `summary`: one line.
`counts`: numbers, e.g. `{"applied": 3, "skipped": 12}`. `changes`: as in `state_set`.
→ the applied and rejected changes. A repeat returns the first reply and applies nothing.

**`state_set(ns, changes)`**, with up to 100 changes. Each change is
`{section, key, value, op, due, expires, ns}`:
- `value`: text, number or JSON. Up to 500 characters in fixed sections, 16,000 in lists; longer values are
  rejected, never trimmed. `null` deletes the row. Leave it out to change only `due` or `expires`.
- `op`: `set` (default; replace), `merge` (update fields of a JSON object; a `null` field drops it), `max` (keep the
  larger, for cursors: numbers, or ISO times, but always the same kind as what's stored), or `delete`.
- `due` (list rows) and `expires`: a time; `null` clears it; leaving it out keeps it. Expired rows disappear.
- `ns`: write to another namespace, e.g. a shared list.
→ applied and rejected changes. Each change is checked on its own: a bad one is rejected with its reason and the
rest still apply.

**`state_get(ns, sections, keys, q, due_before, limit=100, runs_since)`**
`ns`: a name, a list of names, or `"*"`. `q`: text to find in keys and values (any case). `due_before`: e.g. `now`.
→ rows grouped ns → section → key, earliest due first (with `value`, `by`, `updated_at`, and `due_at`, `expires_at`, `locked` when set);
`more: true` when `limit` (max 500) cut it short. `runs_since` (e.g. `24h`) adds a digest per ns and worker: run
count, statuses, summed counts, and the summaries of runs that weren't quiet.

**`count(items, idem)`**, with up to 20 items, each `{ns, key, period, by, limit}`:
- `period`: `day`, `week` (ISO), `month` or `total`; windows are UTC and a new one starts at 0.
- `by`: units to spend (default 1); `0` just reads; negative gives back (never below 0).
- `limit`: refuse if this spend would pass it. You bring the limit; use one item per cap, e.g. the shared
  daily budget and your own share.
- `idem`: a key unique to this action (e.g. the job id). Retrying the same call within 24h replays the first
  success instead of spending twice; the same key with different items is a new spend.
→ `ok` and each counter's value. All or nothing: when `ok` is false nothing was counted. `refused` names the cap,
or `stopped` quotes a stop row in one of the namespaces (a stop can appear mid-run).

**`seen(ns, source, ids, mark=true, ttl_days=90)`**, with up to 500 ids. `source` says what the ids are
(e.g. `upwork-jobs`).
→ `new`: the ids not seen before in this ns and source (or whose `ttl_days` ran out), as you sent them; they're
now marked. `mark=false` only checks; mark them later, once you've actually evaluated them.
