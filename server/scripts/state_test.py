"""Rules of the agent State module, on a throwaway database (no server needed):

    python scripts/state_test.py

Covers what smoke.py can't reach end to end: counters, merges and cursors under concurrent calls, stops,
idempotent retries, due rows, lease expiry, owner rows, caps and size limits, expiry, seen with repeats and ttl."""

import os
import sys
import tempfile
import threading
from datetime import timedelta
from pathlib import Path

os.environ["SP_DATA_DIR"] = tempfile.mkdtemp(prefix="sp-state-test-")
SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

command.upgrade(Config(str(SERVER / "alembic.ini")), "head")

from sqlalchemy import update  # noqa: E402

from app import service  # noqa: E402
from app.db import session_scope, utcnow  # noqa: E402
from app.models import AgentRun, IdemKey, SeenItem, StateRow  # noqa: E402
from app.service import Actor  # noqa: E402

AGENT, OWNER = Actor("agent", "Test agent"), Actor("human", "Owner", 1)
ok = lambda cond, msg: print(("  ✓ " if cond else "  ✗ FAIL ") + msg) or (cond or sys.exit(1))  # noqa: E731


def call(fn, *args, **kwargs):
    with session_scope() as s:
        return fn(s, *args, **kwargs)


def raises(fn) -> str:
    try:
        fn()
    except service.ServiceError as e:
        return e.message
    return ""


def parallel(n: int, fn) -> list:
    out, lock = [], threading.Lock()

    def worker():
        r = fn()
        with lock:
            out.append(r)
    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


print("count")
spend = [{"ns": "linkedin", "key": "actions", "period": "day", "limit": 40}]
results = parallel(60, lambda: call(service.count, spend))
ok(len(results) == 60 and sum(r["ok"] for r in results) == 40, "60 concurrent spends against a limit of 40: exactly 40 pass")
ok(call(service.count, [{**spend[0], "by": 0}])["counters"][0] == {"ns": "linkedin", "key": "actions", "period": "day",
                                                                    "value": 40, "allowed": False}, "by 0 reads: 40, no room")
r = call(service.count, [{"ns": "a", "key": "k", "period": "week", "limit": 5}, {"ns": "linkedin", "key": "actions", "limit": 40}])
ok(not r["ok"] and "linkedin actions (day) is at 40 of 40" in r["refused"]
   and call(service.count, [{"ns": "a", "key": "k", "period": "week", "by": 0}])["counters"][0]["value"] == 0,
   "all or nothing: one item over → the other isn't counted either")
r = call(service.count, [{"ns": "a", "key": "k", "period": "month", "by": 3}, {"ns": "a", "key": "k", "period": "month", "by": -10}])
ok(r["ok"] and r["counters"][1]["value"] == 0, "giving back never goes below 0")
bad = [{"ns": "a", "key": "k", "period": "hour"}, {"ns": "a", "key": "k", "by": True}, {"ns": "A B", "key": "k"}]
ok(all(raises(lambda b=b: call(service.count, [b])) for b in bad), "bad period / by / name refused with a message")

once = [{"ns": "mail", "key": "sent", "limit": 10}]
first = call(service.count, once, "mail:jane@example.com")
again = parallel(5, lambda: call(service.count, once, "mail:jane@example.com"))
ok(first["ok"] and all(a == first for a in again) and call(service.count, [{**once[0], "by": 0}])["counters"][0]["value"] == 1,
   "count replay with the same idem (5 concurrent retries) returns the first reply and spends once")
with session_scope() as s:
    s.execute(update(IdemKey).values(created_at=utcnow() - timedelta(hours=25)))
ok(call(service.count, once, "mail:jane@example.com")["counters"][0]["value"] == 2, "an idem key older than 24h spends again")
full = [{"ns": "mail", "key": "tiny", "limit": 0}]
ok(not call(service.count, full, "k-full")["ok"] and not call(lambda s: s.get(IdemKey, "k-full")),
   "a refusal isn't stored, so a retry is judged afresh")
look = [{"ns": "mail", "key": "peek", "by": 0}]
before_read = call(service.count, look, "k-read")["counters"][0]["value"]
call(service.count, [{"ns": "mail", "key": "peek"}])
ok(call(service.count, look, "k-read")["counters"][0]["value"] == before_read + 1, "a read with idem is never replayed (no stale value)")

call(service.state_set, OWNER, "linkedin-shared", [{"section": "stop", "key": "account_warning", "value": "Paused by owner"}])
r = call(service.count, [{"ns": "mail", "key": "sent", "limit": 10}, {"ns": "linkedin-shared", "key": "actions", "by": 0}], "k-stop")
ok(not r["ok"] and r["stopped"] == "linkedin-shared account_warning: Paused by owner" and not any(c["allowed"] for c in r["counters"])
   and r["counters"][0]["value"] == 2, "count refused (nothing changed, every item) by a stop row in any listed ns")
ok(call(service.count, [{"ns": "linkedin-shared", "key": "actions", "by": 0}])["ok"]
   and call(service.count, [{"ns": "linkedin-shared", "key": "actions", "by": -1}])["ok"], "a stop blocks spending, not reads or give-backs")
r = call(service.count, [{"ns": "linkedin-shared", "key": "actions", "by": 0, "limit": 5}])
ok(r["ok"] and r["stopped"].startswith("linkedin-shared account_warning") and not r["counters"][0]["allowed"],
   "a read during a stop names the stop and shows no room")
call(service.state_set, OWNER, "linkedin-shared", [{"section": "stop", "key": "account_warning", "op": "delete"}])
ok(call(service.count, [{"ns": "linkedin-shared", "key": "actions"}])["ok"], "clearing the stop lets counting resume")

print("state_set")
cur = lambda: call(service.state_get, "upwork", ["next"])["state"]["upwork"]["next"]  # noqa: E731
call(service.state_set, AGENT, "upwork", [{"section": "next", "key": "epoch", "value": 1760000000},
                                          {"section": "next", "key": "since", "value": "2026-10-18T08:00:00Z"}])
values = list(range(1760000001, 1760000041))
parallel(40, lambda: call(service.state_set, AGENT, "upwork", [{"section": "next", "key": "epoch", "op": "max", "value": values.pop()}]))
ok(cur()["epoch"]["value"] == 1760000040, "max on epochs under 40 concurrent writes ends at the largest")
r = call(service.state_set, AGENT, "upwork", [{"section": "next", "key": "epoch", "op": "max", "value": 5}])
ok(r["applied"][0]["value"] == 1760000040, "max never goes backwards and reports the kept value")
call(service.state_set, AGENT, "upwork", [{"section": "next", "key": "since", "op": "max", "value": "2026-10-17T23:00:00Z"},
                                          {"section": "next", "key": "since2", "op": "max", "value": "2026-10-19T01:00:00Z"}])
ok(cur()["since"]["value"] == "2026-10-18T08:00:00Z", "max on ISO times compares them as times")
call(service.state_set, AGENT, "upwork", [{"section": "warm", "key": "acme", "value": {"stage": "new", "note": "x"}}])
call(service.state_set, AGENT, "upwork", [{"section": "warm", "key": "acme", "op": "merge", "value": {"stage": "sent", "note": None}}])
ok(call(service.state_get, "upwork", ["warm"])["state"]["upwork"]["warm"]["acme"]["value"] == {"stage": "sent"},
   "merge changes one field and null drops one")
r = call(service.state_set, AGENT, "upwork", [{"section": "warm", "key": "acme", "op": "merge", "value": "text"},
                                              {"section": "warm", "key": "nothing"}])
ok(not r.get("applied") and "merge" in r["rejected"][0]["reason"] and "value is required" in r["rejected"][1]["reason"],
   "bad merge and missing value each rejected with a reason")
r = call(service.state_set, AGENT, "sizes", [{"section": "next", "key": "ok", "value": "x" * 500},
                                             {"section": "next", "key": "big", "value": "x" * 501},
                                             {"section": "drafts", "key": "ok", "value": "x" * 16_000},
                                             {"section": "drafts", "key": "big", "value": {"body": "x" * 16_000}}])
ok([a["key"] for a in r["applied"]] == ["ok", "ok"] and "max 500" in r["rejected"][0]["reason"]
   and "max 16,000" in r["rejected"][1]["reason"], "500 characters in fixed sections, 16,000 in lists; over is rejected, not trimmed")

results = parallel(30, lambda i=iter(range(30)): call(service.state_set, AGENT, "upwork", [
    {"section": "warm", "key": "shared", "op": "merge", "value": {f"w{next(i)}": True}}]))
merged = call(service.state_get, "upwork", ["warm"], ["shared"])["state"]["upwork"]["warm"]["shared"]["value"]
ok(len(merged) == 30, f"30 concurrent merges into one row from different workers: none lost ({len(merged)} fields)")

r = call(service.state_set, AGENT, "linkedin", [{"section": "stop", "key": f"s{i}", "value": "halt"} for i in range(6)])
ok(len(r["applied"]) == 5 and "full (5 rows" in r["rejected"][0]["reason"], "stop is capped at 5; the 6th is rejected")
ok(r["rejected"][0]["index"] == 5, "a rejected change carries its index in changes")
r = call(service.state_set, AGENT, "linkedin", [{"section": "stop", "key": "s0", "value": "still"}])
ok(r["applied"] and not r.get("rejected"), "changing a row in a full section is fine")

call(service.state_set, OWNER, "linkedin", [{"section": "lesson", "key": "tone", "value": "No emojis"}])
r = call(service.state_set, AGENT, "linkedin", [{"section": "lesson", "key": "tone", "value": "Emojis ok"},
                                                {"section": "lesson", "key": "tone", "op": "delete"},
                                                {"section": "lesson", "key": "x", "value": 1, "locked": False}])
ok(len(r["rejected"]) == 3 and r["rejected"][0]["reason"].startswith("owner_row") and "owner" in r["rejected"][2]["reason"],
   "fixed-section owner row: agents can't change, delete or unlock it")
row = call(service.state_get, "linkedin", ["lesson"])["state"]["linkedin"]["lesson"]["tone"]
ok(row["value"] == "No emojis" and row["locked"] and row["by"] == "owner", "the owner's row is intact")
call(service.state_set, OWNER, "linkedin", [{"section": "lesson", "key": "tone", "value": "No emojis", "locked": False}])
ok(call(service.state_set, AGENT, "linkedin", [{"section": "lesson", "key": "tone", "value": "Short"}]).get("applied"),
   "the owner can unlock a row for agents")

call(service.state_set, OWNER, "linkedin", [{"section": "contacts", "key": "jane", "value": {"company": "Acme"}, "due": "2030-01-01"}])
r = call(service.state_set, AGENT, "linkedin", [{"section": "contacts", "key": "jane", "op": "merge", "value": {"emailed": True}, "due": "2030-02-01"},
                                                {"section": "contacts", "key": "jane", "value": {"x": 1}},
                                                {"section": "contacts", "key": "jane", "op": "delete"},
                                                {"section": "contacts", "key": "jane", "op": "merge", "value": {"y": 1}, "expires": "1d"}])
jane = call(service.state_get, "linkedin", ["contacts"])["state"]["linkedin"]["contacts"]["jane"]
ok(len(r["applied"]) == 1 and len(r["rejected"]) == 3 and all(x["reason"].startswith("owner_row") for x in r["rejected"])
   and jane["value"] == {"company": "Acme", "emailed": True} and jane["by"] == "owner" and jane["locked"]
   and jane["due_at"].startswith("2030-02-01"), "list owner row: agents may merge (and reschedule), not set, delete or expire it")
r = call(service.state_set, AGENT, "linkedin", [{"section": "contacts", "key": "jane", "due": "2030-03-01"}])
jane = call(service.state_get, "linkedin", ["contacts"])["state"]["linkedin"]["contacts"]["jane"]
ok(r.get("applied") and jane["due_at"].startswith("2030-03-01") and jane["value"] == {"company": "Acme", "emailed": True},
   "list owner row: a due-only change (no value, default op) is allowed")

call(service.state_set, AGENT, "upwork", [{"section": "draft", "key": "d1", "value": "x", "expires": "1d"}])
with session_scope() as s:
    s.execute(update(StateRow).where(StateRow.key == "d1").values(expires_at=utcnow() - timedelta(seconds=1)))
ok("draft" not in call(service.state_get, "upwork")["state"]["upwork"], "expired rows are hidden")
call(service.state_set, AGENT, "upwork", [{"section": "draft", "key": "d1", "op": "merge", "value": {"a": 1}}])
ok(call(service.state_get, "upwork", ["draft"])["state"]["upwork"]["draft"]["d1"]["value"] == {"a": 1},
   "writing an expired row starts it fresh")
ok(call(service.state_get, "*", q="STAGE")["state"] == {"upwork": {"warm": {"acme": call(
   service.state_get, "upwork", ["warm"])["state"]["upwork"]["warm"]["acme"]}}}, "q matches values, case-insensitively, across ns='*'")

print("seen")
r = call(service.seen, "upwork", "jobs", ["a", "b", "a", 7, " b "])
ok(r["new"] == ["a", "b", 7], "repeats in one call count once; ids come back as sent")
ok(call(service.seen, "upwork", "jobs", ["a", "c"], False)["new"] == ["c"] and call(service.seen, "upwork", "jobs", ["c"])["new"] == ["c"],
   "mark=false only checks")
call(service.seen, "upwork", "posts", ["p1"], ttl_days=2)
with session_scope() as s:
    exp = s.get(SeenItem, ("upwork", "posts", "p1")).expires_at
ok(timedelta(days=1, hours=23) < exp - utcnow() <= timedelta(days=2), "seen with ttl_days=2 expires in 2 days")
with session_scope() as s:
    s.execute(update(SeenItem).where(SeenItem.item_id == "p1").values(expires_at=utcnow() - timedelta(seconds=1)))
ok(call(service.seen, "upwork", "posts", ["p1"], False)["new"] == ["p1"] and call(service.seen, "upwork", "posts", ["p1"])["new"] == ["p1"]
   and call(service.seen, "upwork", "posts", ["p1"])["new"] == [], "an expired id is new again (and marked again) before the nightly purge")
res = parallel(10, lambda: call(service.seen, "upwork", "jobs", ["z1", "z2"]))
ok(sorted(i for r in res for i in r["new"]) == ["z1", "z2"], "10 concurrent calls: each id is new exactly once")

print("due rows")
now = utcnow()
call(service.state_set, AGENT, "upwork", [{"section": "targets", "key": k, "value": k, "due": d} for k, d in
                                          [("later", "2099-01-01T00:00:00Z"), ("b", (now - timedelta(hours=1)).isoformat() + "Z"),
                                           ("a", (now - timedelta(hours=2)).isoformat() + "Z"), ("undated", None)]])
call(service.state_set, AGENT, "upwork", [{"section": "targets", "key": "undated", "value": "u"}])
g = call(service.state_get, "upwork", ["targets"])["state"]["upwork"]["targets"]
ok(list(g) == ["a", "b", "later", "undated"] and "due_at" in g["a"] and "due_at" not in g["undated"],
   "state_get orders by due (earliest first, undated last) and returns due_at")
ok(list(call(service.state_get, "upwork", ["targets"], due_before="now")["state"]["upwork"]["targets"]) == ["a", "b"],
   "due_before=now keeps only rows due by now")
lim = call(service.state_get, "upwork", ["targets"], limit=2)
ok(list(lim["state"]["upwork"]["targets"]) == ["a", "b"] and lim["more"], "limit cuts the list and says more")
call(service.state_set, AGENT, "upwork", [{"section": "targets", "key": "b", "value": "b", "due": None}])
ok("due_at" not in call(service.state_get, "upwork", ["targets"], ["b"])["state"]["upwork"]["targets"]["b"], "due null clears it")
call(service.state_set, AGENT, "upwork", [{"section": "targets", "key": "b", "value": "b", "due": (now - timedelta(hours=1)).isoformat() + "Z"}])
call(service.state_set, AGENT, "upwork", [{"section": "targets", "key": "b", "value": "b2"}])
ok("due_at" in call(service.state_get, "upwork", ["targets"], ["b"])["state"]["upwork"]["targets"]["b"], "omitting due keeps it")

print("runs")
r = call(service.run_start, "upwork", "main", ["linkedin"], ["targets"], 50)
ok(r["run_id"] and r["state"]["next"]["epoch"] == 1760000040 and "s0" in r["also"]["linkedin"]
   and r["counters"]["linkedin"]["actions"]["day"] == 40 and r["lists"] == {"draft": 1, "targets": 4, "warm": 2},
   "run_start brief: own fixed sections, stops from also, counters, list sizes")
ok([x["key"] for x in r["include"]["targets"]] == ["a", "b"], "include returns only due rows, earliest first")
ok(raises(lambda: call(service.run_start, "x", "main", None, ["next"], 50)), "include refuses fixed sections")
plain = call(service.run_start, "linkedin", "main", None, None, 50)
ok("also" not in plain, "without also, no other namespace's stops leak into the brief")
call(service.state_set, OWNER, "brief", [{"section": "stop", "key": "halt", "value": "Owner says stop"}])
call(service.state_set, AGENT, "brief", [{"section": "next", "key": "cursor", "value": 1}])
call(service.state_set, OWNER, "brief-shared", [{"section": "stop", "key": "pause", "value": "Shared pause"}])
b = call(service.run_start, "brief", "main", ["brief-shared"], None, 50)
ok(b["owner"] == {"brief": {"stop": ["halt"]}, "brief-shared": {"stop": ["pause"]}} and b["state"]["next"] == {"cursor": 1},
   "the brief names the owner's rows, its own and in `also`")
ok(len(str(r)) < 2048, f"brief is small ({len(str(r))} chars)")
busy = parallel(5, lambda: call(service.run_start, "upwork", "main", None, None, 50))
ok(all(b.get("busy") for b in busy), "while it's live, run_start (5 at once) says busy")
ok(call(service.run_start, "upwork", "finder", None, None, 50).get("run_id"), "another worker in the same ns isn't blocked")
with session_scope() as s:
    s.execute(update(AgentRun).where(AgentRun.id == r["run_id"]).values(lease_until=utcnow() - timedelta(seconds=1)))
r2 = call(service.run_start, "upwork", "main", None, None, 50)
ok(r2.get("run_id") and r2["last"]["status"] == "error" and "lease" in r2["last"]["summary"],
   "a crashed run frees the lease when it runs out and is recorded as an error")
e = call(service.run_end, AGENT, r2["run_id"], "attention", "Found 2\nroles", {"applied": 2},
         [{"section": "next", "key": "epoch", "op": "max", "value": 1770000000}, {"section": "lesson", "key": "tone", "value": "x"}])
ok(e["ended"] and e["applied"] and not e.get("rejected"), "run_end applies its changes")
replays = parallel(3, lambda: call(service.run_end, AGENT, r2["run_id"], "error", "retry", None,
                                   [{"section": "next", "key": "epoch", "value": 1}]))
ok(all(x == e for x in replays) and cur()["epoch"]["value"] == 1770000000
   and next(x for x in call(service.runs, ns="upwork") if x["id"] == r2["run_id"])["summary"] == "Found 2 roles",
   "run_end replay (3 concurrent) returns the first reply and applies nothing")
digest = call(service.state_get, "*", runs_since="1h")
g = digest["runs"]["upwork"]["main"]
ok("state" not in digest and g["runs"] == 2 and g["status"] == {"error": 1, "attention": 1}
   and g["counts"] == {"applied": 2} and g["notes"][1]["summary"] == "Found 2 roles"
   and digest["runs"]["upwork"]["finder"] == {"runs": 1, "status": {"running": 1}}, "runs_since digest per ns and worker")
ok(raises(lambda: call(service.run_end, AGENT, 999999, "routine")) and raises(lambda: call(service.run_end, AGENT, r2["run_id"], "done")),
   "unknown run id / status refused")

print("re-review regressions")
r = call(service.state_set, AGENT, "edge", [
    {"section": "todo", "key": "far", "value": 1, "due": "9999-12-31T23:00:00-05:00"},
    {"section": "todo", "key": "nan", "value": float("nan")},
    {"section": "todo", "key": "deep", "value": __import__("functools").reduce(lambda v, _: [v], range(40), 1)},
    {"section": "todo", "key": "fine", "value": 1}])
ok([a["key"] for a in r["applied"]] == ["fine"] and "years 1-9999" in r["rejected"][0]["reason"]
   and "NaN" in r["rejected"][1]["reason"] and "nested" in r["rejected"][2]["reason"],
   "out-of-range time, NaN and deep nesting are rejected one by one, the rest applies")
run = call(service.run_start, "edge", "main", None, None, 5)
e = call(service.run_end, AGENT, run["run_id"], "routine", None, None, [{"section": "todo", "key": "x", "value": 1, "expires": "0001-01-01T00:00:00+05:00"}])
ok(e["ended"] and "years 1-9999" in e["rejected"][0]["reason"] and call(service.run_start, "edge", "main", None, None, 5).get("run_id")
   and "summary" not in call(service.run_start, "edge", "other", None, None, 5).get("last", {}),
   "a bad change in run_end is rejected but the run still ends (lease freed)")
ok("not found" in raises(lambda: call(service.run_end, AGENT, 10**30, "routine")), "a huge run_id is a clean 404")

call(service.state_set, OWNER, "edge", [{"section": "targets", "key": "acme", "value": {"note": "owner", "tier": 1}}])
r = call(service.state_set, AGENT, "edge", [{"section": "targets", "key": "acme", "op": "merge", "value": {"note": None}},
                                            {"section": "targets", "key": "acme", "op": "merge", "value": {"tier": 2, "seen": True}}])
ok(r["rejected"][0]["reason"].startswith("owner_row") and len(r["applied"]) == 1
   and call(service.state_get, "edge", ["targets"])["state"]["edge"]["targets"]["acme"]["value"] == {"note": "owner", "tier": 2, "seen": True},
   "on an owner list row agents may add or update fields, not remove them")
r = call(service.state_set, AGENT, "edge", [{"section": "targets", "key": "acme", "op": "merge", "due": "2030-01-01"}])
row = call(service.state_get, "edge", ["targets"])["state"]["edge"]["targets"]["acme"]
ok(r.get("applied") and row["due_at"].startswith("2030-01-01") and row["value"]["note"] == "owner",
   "omitting value changes only due (the value is kept)")
ok("value is required" in call(service.state_set, AGENT, "edge", [{"section": "targets", "key": "new", "due": "now"}])["rejected"][0]["reason"],
   "a new row still needs a value")

call(service.state_set, AGENT, "edge", [{"section": "next", "key": "n", "value": 10}, {"section": "next", "key": "t", "value": "2026-10-18T06:00:00Z"}])
r = call(service.state_set, AGENT, "edge", [{"section": "next", "key": "n", "op": "max", "value": "9"},
                                            {"section": "next", "key": "n", "op": "max", "value": True},
                                            {"section": "next", "key": "t", "op": "max", "value": "2026-10-18T10:00:00+05:00"}])
nx = call(service.state_get, "edge", ["next"])["state"]["edge"]["next"]
ok(len(r["rejected"]) == 2 and "same kind" in r["rejected"][0]["reason"] and nx["n"]["value"] == 10
   and nx["t"]["value"] == "2026-10-18T06:00:00Z", "max refuses mixed kinds and compares ISO times with offsets as times")

call(service.state_set, AGENT, "edge", [{"section": "notes", "key": "j", "value": {"who": "JOSÉ García", "text": 'He said "hi"\nnext'}}])
found = lambda q: list(call(service.state_get, "edge", ["notes"], q=q)["state"].get("edge", {}).get("notes", {}))  # noqa: E731
ok(found("josé") == ["j"] and found('said "hi"') == ["j"] and found('hi"\nnext') == ["j"],
   "q is Unicode case-insensitive and finds text with quotes and newlines")

idem_items = [{"ns": "idem-a", "key": "apply", "limit": 5}]
call(service.count, idem_items, "job-1")
other = call(service.count, [{"ns": "idem-b", "key": "email", "limit": 5}], "job-1")
ok(other["counters"][0]["ns"] == "idem-b" and other["counters"][0]["value"] == 1, "the same idem in a different call is a new spend")

ok(call(service.state_set, Actor("agent", "Owner"), "edge", [{"section": "notes", "key": "spoof", "value": 1}]).get("applied")
   and call(service.state_get, "edge", ["notes"], ["spoof"])["state"]["edge"]["notes"]["spoof"]["by"] == "Owner (agent)",
   "an agent named 'owner' can't pass as the owner")
page = call(service.state_page, "EDGE", "Targets", None, 1)
ok(page["rows"][0]["key"] == "acme" and page["more"] is False and call(service.state_page, "edge", None, None, 1)["more"],
   "State page read: filters normalized, `more` when cut")
ok(call(service.runs, ns="EDGE") and call(service.state_get, "edge", ["notes"], [" spoof "])["state"]["edge"]["notes"],
   "runs ns filter and state_get keys are normalized like writes")

print("nightly purge")
with session_scope() as s:
    s.execute(update(SeenItem).where(SeenItem.item_id == "a").values(expires_at=utcnow() - timedelta(seconds=1)))
    s.execute(update(StateRow).where(StateRow.key == "d1").values(expires_at=utcnow() - timedelta(seconds=1)))
    s.execute(update(AgentRun).where(AgentRun.worker == "finder").values(lease_until=utcnow() - timedelta(seconds=1)))
    s.execute(update(IdemKey).values(created_at=utcnow() - timedelta(hours=24, seconds=1)))
call(service.purge_state)
with session_scope() as s:
    ok(not s.get(SeenItem, ("upwork", "jobs", "a")) and s.get(SeenItem, ("upwork", "jobs", "b"))
       and not s.query(StateRow).filter_by(key="d1").count(), "expired seen ids and expired rows are deleted")
    ok(not s.query(IdemKey).count(), "idem keys older than 24 hours are deleted")
    ok(s.query(AgentRun).filter_by(worker="finder").one().status == "error", "a crashed run nobody restarted is closed")
print("ALL PASSED")
