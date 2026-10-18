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

## Who you are
Your instructions from the owner name your namespace (`ns`, usually your agent name, e.g. `upwork`) and the
shared namespaces you follow (e.g. `outreach-shared` for a LinkedIn budget several agents spend). `state_get`
with `ns: "*"` shows every namespace that exists. Each agent should have its own API key: the key's name is how
the owner sees who wrote what. `run_start` brings only the stops and counters of the namespaces in `also`: read
their rules (lessons, owner rows) with `state_get` when you need them.

## A run
1. **`run_start` first.** It returns your brief: where you left off, stops (yours and the shared namespaces in
   `also`), current counters, your last run's summary, and the due rows of the lists you name in `include`. Read
   it before deciding what to do. If it says `busy`, another run of this worker is still going: stop, without
   `run_end` (there's no run to end).
2. **Work.**
   - Check each batch of items with `seen(mark=false)` and look only at the `new` ones. Mark them (`seen`
     again, default `mark=true`) once you've actually evaluated them, so a run cut short doesn't skip the rest.
   - Before each action with a budget (a connection request, an application, an email), `count` it. If it says
     no, don't act: it's either the budget or a stop, and both are deliberate. A stop in any namespace in the
     call refuses its spending, so put the shared namespace's budget in the same call: a stop raised there
     mid-run then reaches you.
3. **`run_end` last**, with an honest status and a one-line summary, plus the changes you want remembered.
   Retrying it is safe. If you crash, the lease frees itself after `lease_min`, and the run is logged as an error.
   Set `lease_min` above your longest run: once it lapses another run may start, and a late `run_end` still
   records and applies.

## What to keep where
Fixed sections come back in every brief, so keep them small:

| Section | For | Rows |
|---|---|---|
| `next` | where you left off: cursors, last-checked times, what to pick up next | 30 |
| `stop` | a brake: while one exists, `count` refuses any spending that involves its namespace. Obey it | 5 |
| `blocker` | you're stuck and need the owner: say exactly what they must do | 20 |
| `waiting` | waiting on the owner or someone else | 20 |
| `lesson` | something you learned that should change how you work next time | 15 |
| `platform` | how a site behaves: limits, quirks, what breaks | 10 |
| `proposal` | a change you suggest to the owner (to your rules, budgets, targets) | 10 |

A stop halts the whole namespace, so a narrow brake ("no connection requests, messages are fine") belongs in
a namespace that only that activity counts against.

Any other section name is a **list** you define yourself (`targets`, `contacts`, `drafts`, …), with one row
per key. Read lists with `state_get`. Give a list row a `due` time to schedule it: `run_start` hands you the due
rows of the lists you name in `include`. This is where your own to-dos go. Deal reminders (`set_reminder`) are
the owner's Today list, for steps they should see or take.

**Owner rows** are the ones the owner locked (`locked: true` on the row; in fixed sections the brief also lists
them under `owner`): instructions, follow them. In fixed sections you can't change them. In lists you can add or
update fields and change `due`, but not remove fields or delete the row: when you've done what one asks, clear its
`due` and merge the outcome into it (e.g. `{"done": true, "result": "…"}`). If its value isn't a JSON object (text,
a number, a list), nothing can be merged: record the outcome in a row of your own. The owner removes it. If one looks wrong or out of date, say so with
`notify_owner` or a `proposal` row instead of working around it.

**Hearing back from the owner.** When the owner actually needs to act, call `notify_owner`: that's what reaches
them. Record it in `blocker` or `waiting` too. The owner answers by changing your state: editing your row (it
then reads `by: owner` but stays yours: act on the answer, then delete or update the row), adding a `lesson`, a
`stop` or a locked row, or changing the deal itself. Check your `waiting`, `blocker` and `proposal` rows each run;
one the owner deleted is handled, and what they decided shows in their rows or your instructions.

## Reference
**Times you send** to these tools: ISO-8601 with an offset or `Z` (a time without one is read in the owner's
timezone), `YYYY-MM-DD` (09:00 in the owner's timezone), `now`, or a duration (`30m`, `12h`, `7d`; from now, or
back from now for `runs_since`). Times you get back are UTC (`…Z`).
**Names** (ns, worker, section, counter key, seen source): lowercase letters, digits and `_ . -`, up to 60
characters, case-insensitive. Row keys are exact text, up to 200 characters.
Keys with nothing in them are left out of replies. Errors say what to fix.

**`run_start(ns, worker="main", also=[], include=[], lease_min=50)`**
→ `run_id`, `now`, `state` (your fixed sections), `owner` (which rows are the owner's), `lists` (row counts),
`also` (stops in those namespaces), `counters`, `last` (this worker's last run), `include` (for each listed list,
rows due now, earliest first, up to 50). Or `busy: true` when this worker is already running. `worker` separates
jobs in one ns (e.g. `finder`, `sender`); different workers never block each other. `also` and `include` take up
to 10 names each.

**`run_end(run_id, status, summary, counts, changes)`**
`status`: `quiet` (nothing happened), `routine`, `attention` (the owner should look) or `error`. `summary`: one line.
`counts`: up to 30 numbers, e.g. `{"applied": 3, "skipped": 12}`. `changes`: as in `state_set`.
→ the applied and rejected changes. A repeat returns the first reply and applies nothing.

**`state_set(ns, changes)`**, with up to 100 changes. Each change is
`{section, key, value, op, due, expires, ns}`:
- `value`: text, number or JSON. Up to 500 characters in fixed sections, 16,000 in lists; longer values are
  rejected, never trimmed. `null` deletes the row. Leave it out to change only `due` or `expires`.
- `op`: `set` (default; replace), `merge` (update fields of a JSON object; a `null` field drops it), `max` (keep the
  larger, for cursors), or `delete`. For `max`, send numbers as JSON numbers: `"10"` against a stored `"9"` is
  compared as text and loses. ISO times compare as times. A number against text is refused.
- `due` (when to work a list row) and `expires`: a time; `null` clears it; leaving it out keeps it. Expired rows
  disappear.
- `ns`: write to another namespace, e.g. a shared list.
→ applied and rejected changes. Each change is checked on its own: a bad one is rejected with its `index` in
`changes` and a reason, and the rest still apply.

**`state_get(ns, sections, keys, q, due_before, limit=100, runs_since)`**
`ns`: a name, a list of names, or `"*"`. `q`: text to find in keys and values (any case). `due_before`: e.g. `now`.
→ rows grouped ns → section → key, earliest due first (with `value`, `by`, `updated_at`, and `due_at`, `expires_at`,
`locked` when set); `more: true` when `limit` (max 500) cut it short. `runs_since` (e.g. `24h`) adds a digest per
ns and worker: run count, statuses, summed counts, and the latest 20 summaries of runs that weren't quiet. With
`runs_since`, rows come back only if you also pass `sections`, `keys`, `q` or `due_before`.

**`count(items, idem)`**, with up to 20 items, each `{ns, key, period, by, limit}`:
- `period`: `day`, `week` (ISO), `month` or `total`; windows are UTC (a day starts at 00:00 UTC, not the
  owner's midnight) and a new one starts at 0.
- `by`: units to spend (default 1); `0` reads; negative gives back (never below 0).
- `limit`: refuse if this spend would pass it. You bring the limit; use one item per cap, e.g. the shared
  daily budget and your own share.
- `idem`: a key unique to you and this action (e.g. `upwork-finder:job-42`; other agents may count the same
  budget). Retrying the same call within 24h replays the first success instead of spending twice; the same key
  with different items (including a changed `limit`) is a new spend. A call that only reads is never replayed.
- A stop beats a replay. If a stop refuses your retry, keep the action (and its idem) in a list row with `due`
  and retry the same call once the stop clears: within 24h the replay confirms it counted once; after that it
  spends again. Give it back (`by: -1`) only if you're dropping the action for good, and never reuse that
  idem: the stored success would still replay and let you act without spending.
→ `ok`, and `counters` with each `value` and `allowed`. All or nothing: when `ok` is false nothing was counted;
`refused` names the cap, or `stopped` quotes the stop rows: a call that spends is refused while any of its
namespaces has a stop. A call that only reads or gives back still works then: its reply carries `stopped` too,
and a read's `allowed` is false. Otherwise a read's `allowed` says whether there's room for one more.

**`seen(ns, source, ids, mark=true, ttl_days=90)`**, with up to 500 ids. `source` says what the ids are
(e.g. `upwork-jobs`).
→ `new`: the ids not seen before in this ns and source (or whose `ttl_days` ran out), as you sent them; with
`mark=true` they're now marked. `mark=false` only checks.
