# Run state for scheduled agents (Sales Pipeline MCP)

Give this to each scheduled agent. The server's own instructions cover deals, messages and the owner; this
guide covers remembering between runs.

## Why
Each run starts with no memory of the last. Keep here what the next run needs (where you left off, what you
looked at, what you learned, what you wait for, how much of each budget is spent), never in local files or your
own memory, so any run, another agent or the owner (State page) can pick up. Keep what the next run would do
worse without; keep rows short and drop them once untrue.

## Names
Your instructions name your namespace (`ns`, usually your agent name) and the shared ones you obey (`also`, e.g.
a LinkedIn budget several agents spend); `state_get` with `ns: "*"` lists all. Give each agent its own API key: its
name is how the owner sees who wrote what. `run_start` brings only the stops and counters of `also` namespaces;
read their other rows with `state_get` when needed.

## A run
1. **`run_start` first**, and read the brief (where you left off, stops, counters, your last summary, due rows
   of the lists in `include`) before deciding. `busy`: this worker is already running; stop, with no `run_end`.
2. **Work.** `seen(mark=false)` on each batch, evaluate only the `new` ids, then mark the ones you evaluated, so
   a run cut short skips nothing. `count` before each budgeted action (a request, an application, an email),
   with any shared budget in the same call so a stop raised mid-run reaches you; a refusal (budget or stop) is
   deliberate: don't act.
3. **`run_end` last**: an honest status, a one-line summary, the changes to keep. Safe to retry. Set `lease_min`
   above your longest run: a crashed run frees itself then and is logged as an error; after that another run may
   start, and a late `run_end` still applies.

## What goes where
Fixed sections return in every brief, so keep them small:

| Section | For | Rows |
|---|---|---|
| `next` | Where you left off: cursors, last-checked times, what to pick up next | 30 |
| `stop` | A brake: `count` refuses any spending in its namespace while it stands. Obey it | 5 |
| `blocker` | You are stuck: exactly what the owner must do | 20 |
| `waiting` | Waiting on the owner or someone else | 20 |
| `lesson` | What should change how you work next time | 15 |
| `platform` | How a site behaves: limits, quirks, what breaks | 10 |
| `proposal` | A change you suggest to the owner (rules, budgets, targets) | 10 |

A stop halts its whole namespace, so a narrow brake ("no invites, messages fine") gets a namespace only that
activity counts against.

Any other section is a **list** you define (`targets`, `contacts`, `drafts`), one row per key, read with
`state_get`. A row's `due` schedules it: `run_start` returns due rows of the lists in `include`. Your own to-dos go
here; deal reminders (`set_reminder`) are the owner's Today list.

**Owner rows** (`locked: true`; the brief lists fixed ones under `owner`) are instructions. Fixed ones are
read-only. In lists you may add or update fields and change `due`, never remove fields or the row: when done,
clear `due` and merge the outcome (`{"done": true, "result": "…"}`); a non-object value takes no merge, so record
the outcome in your own row. The owner removes it. One that looks wrong: say so with `notify_owner` or a
`proposal`, never work around it.

**The owner answers** by editing your row (it then shows `by: owner` but stays yours: act, then update or delete
it), deleting it (handled), adding a lesson, stop or locked row, or changing the deal. What needs the owner also
needs `notify_owner`, which is what reaches them; record it in `blocker` or `waiting` too, and read those and your
`proposal` rows every run.

## Reference
**Times you send:** ISO-8601 with an offset or `Z` (none: the owner's timezone), `YYYY-MM-DD` (09:00 the owner's
time), `now`, or `30m` / `12h` / `7d` (from now; back from now for `runs_since`). Times returned are UTC.
**Names** (ns, worker, section, counter key, seen source): lowercase letters, digits, `_ . -`, up to 60
characters, any case. Row keys: exact text, up to 200. Empty keys are left out of replies; errors say what to fix.

**`run_start(ns, worker="main", also=[], include=[], lease_min=50)`** → `run_id`, `now`, `state` (fixed
sections), `owner`, `lists` (row counts), `also` (their stops), `counters`, `last` (this worker's last run),
`include` (per list, rows due now, earliest first, up to 50); or `busy: true`. Workers in one ns (`finder`,
`sender`) never block each other. `also` and `include` take up to 10 names each.

**`run_end(run_id, status, summary, counts, changes)`**: `status` `quiet` (nothing happened), `routine`,
`attention` (the owner should look) or `error`; `summary` one line; `counts` up to 30 numbers; `changes` as in
`state_set`. → applied and rejected changes; a repeat returns the first reply and applies nothing.

**`state_set(ns, changes)`**, up to 100, each `{section, key, value, op, due, expires, ns}`:
- `value`: text, number or JSON; up to 500 characters in fixed sections, 16,000 in lists, longer rejected, never
  trimmed. `null` deletes the row; omit it to change only `due` or `expires`.
- `op`: `set` (default), `merge` (fields of a JSON object; a `null` field drops it), `max` (keep the larger, for
  cursors: numbers only as JSON numbers, since `"10"` against `"9"` compares as text; ISO times compare as times;
  a number against text is refused), `delete`.
- `due`, `expires`: a time; `null` clears, omitted keeps. Expired rows disappear.
- `ns`: another namespace, e.g. a shared list.
→ applied and rejected changes; each is checked alone, a bad one rejected with its `index` and reason.

**`state_get(ns, sections, keys, q, due_before, limit=100, runs_since)`**: `ns` a name, a list or `"*"`; `q` text in
keys and values, any case; `due_before` e.g. `now`. → rows by ns → section → key, earliest due first (`value`,
`by`, `updated_at`, plus `due_at`, `expires_at`, `locked` when set); `more: true` when `limit` (max 500) cut it.
`runs_since` (e.g. `24h`) adds per ns and worker: run count, statuses, summed counts, the latest 20 non-quiet
summaries; rows then come only with `sections`, `keys`, `q` or `due_before`.

**`count(items, idem)`**, up to 20 items `{ns, key, period, by, limit}`, one per cap (e.g. the shared daily budget
and your share):
- `period`: `day`, `week` (ISO), `month`, `total`; UTC windows (a day starts 00:00 UTC), each new one at 0.
- `by`: units to spend (default 1); `0` reads; negative gives back, never below 0. `limit`: yours to bring;
  refuse if this spend would pass it.
- `idem`: unique to you and the action (`upwork-finder:job-42`). A retry within 24h replays the first success
  instead of spending twice; different items or a changed `limit` make a new spend; a read is never replayed.
- A stop beats a replay: keep a refused action and its idem in a list row with `due`, and retry the same call
  once the stop clears (within 24h the replay confirms one spend; later it spends again). Give back (`by: -1`)
  only when dropping the action for good, after seeing its spend succeed (no reply seen: retry once the stop
  clears, then give back), and within the same window, since a unit from an earlier window is gone and returning
  it would let today's budget be passed. The give-back takes its own idem (`…:back`); never retry the spend's
  idem after it, or its stored success replays and you act without spending.
→ `ok` and `counters` (each `value`, `allowed`); all or nothing: `ok: false` counts nothing, with `refused` (the cap)
or `stopped` (the stop rows: a spending call is refused while any of its namespaces has one). Reads and
give-backs still work during a stop and carry `stopped`; a read's `allowed` is then false, otherwise it says
whether one more fits.

**`seen(ns, source, ids, mark=true, ttl_days=90)`**, up to 500 ids; `source` says what they are (`upwork-jobs`).
→ `new`: ids not seen in this ns and source (or past `ttl_days`), as sent, marked when `mark=true`;
`mark=false` only checks.
