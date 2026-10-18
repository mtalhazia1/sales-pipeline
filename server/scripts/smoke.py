"""End-to-end smoke test against a running server: REST (human) + MCP (agent, both protocol eras)
+ the full OAuth connect flow an MCP client like Claude performs.

    python scripts/smoke.py http://localhost:8100 EMAIL PASSWORD

Creates records named "Smoke Test …" and state namespaces "smoke-test-…", and deletes them at the end."""

import asyncio
import base64
import hashlib
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

import httpx2
import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE, EMAIL, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
ok = lambda cond, msg: print(("  ✓ " if cond else "  ✗ FAIL ") + msg) or (cond or sys.exit(1))  # noqa: E731


URLS: dict[int, str] = {}
NOTIFS: list[int] = []
TEMPLATE: dict = {}


def structured(result):
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    # Agents must get JSON objects, not a text blob: a bare `-> dict` tool annotation silently drops them.
    if result.structured_content is None:
        raise RuntimeError("tool returned no structuredContent")
    return result.structured_content


async def mcp_calls(token: str, mode: str) -> list[int]:
    created = []
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode=mode) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        ok({"add_opportunity", "log_activity", "get_agenda", "run_start", "run_end", "state_get", "state_set", "count", "seen"} <= tools, f"[{mode}] tools listed: {len(tools)}")
        url = f"https://www.upwork.com/jobs/Smoke-Test-AI-agent_~01{secrets.token_hex(8)}/?referrer_url_path=x"
        r = structured(await c.call_tool("add_opportunity", {
            "company": f"Smoke Test {mode}", "title": "AI agent build", "application_url": url,
            "budget": "$60/hr", "fit": 4, "reminder_at": "2030-01-02", "reminder_note": "Check",
            "resume_url": "https://docs.google.com/document/d/smoke-resume", "resume_version": "Smoke base",
            "cover_letter_url": "docs.google.com/document/d/smoke-cover"}))
        opp = r["opportunity"]
        created.append(opp["id"])
        URLS[opp["id"]] = url
        ok(r["created"] and opp["channel"] == "upwork" and opp["needs_review"], f"[{mode}] add: channel inferred, review flagged")
        r2 = structured(await c.call_tool("add_opportunity", {"company": "dup", "application_url": url.split("?")[0].replace("Smoke-Test-AI-agent_", "")}))
        ok(not r2["created"] and r2["opportunity"]["id"] == opp["id"], f"[{mode}] same posting (different URL form) deduplicated")
        bad = await c.call_tool("add_opportunity", {"company": f"Smoke Test bad date {mode}", "reminder_at": "next friday"})
        found = structured(await c.call_tool("find_opportunities", {"query": f"Smoke Test bad date {mode}"}))
        ok(bad.is_error and found["count"] == 0, f"[{mode}] a refused add (bad reminder_at) saves nothing")
        lib = structured(await c.call_tool("list_message_templates", {"category": TEMPLATE["cat"]}))["categories"]
        ok(len(lib) == 1 and lib[0]["purpose"] and {m["id"] for m in lib[0]["messages"]} == {TEMPLATE["id"], TEMPLATE["other"]},
           f"[{mode}] list_message_templates: category purpose + its messages")
        cur = structured(await c.call_tool("get_message_template", {"category": TEMPLATE["cat"]}))
        ok(cur["id"] == TEMPLATE["id"] and cur["is_current"] and cur["placeholders"] == ["first_name"] and cur["purpose"],
           f"[{mode}] get_message_template returns the category's current message and its purpose")
        bad = await c.call_tool("get_message_template", {"category": TEMPLATE["mail"]})
        ok(bad.is_error and "notify_owner" in bad.content[0].text, f"[{mode}] no current message: told not to write one")
        nm = structured(await c.call_tool("save_message_template", {"category": TEMPLATE["mail"], "name": f"Smoke Test agent mail {mode}",
                                                                    "subject": "s", "body": "b"}))
        ok(not nm["message"]["is_current"], f"[{mode}] an agent's message doesn't go live where the owner left none current")
        TEMPLATE["agent"].append((None, nm["message"]["id"]))
        bad = await c.call_tool("get_message_template", {"category": "smoke_nope"})
        ok(bad.is_error and TEMPLATE["cat"] in bad.content[0].text, f"[{mode}] unknown category: error lists the keys")
        nc = structured(await c.call_tool("save_message_category", {"name": f"Smoke Test agent {mode}", "purpose": "Smoke test only"}))
        ok(nc["created"] and nc["category"]["needs_review"] and nc["category"]["updated_by"] == "Smoke key",
           f"[{mode}] agent creates a category (flagged for review)")
        nm = structured(await c.call_tool("save_message_template", {"category": nc["category"]["key"], "name": "Smoke Test agent msg",
                                                                    "body": "Hello {company}"}))
        ok(nm["created"] and nm["message"]["is_current"] and nm["message"]["needs_review"], f"[{mode}] agent adds a message (first = current)")
        ed = structured(await c.call_tool("save_message_template", {"template_id": nm["message"]["id"], "body": "Hello there {company}"}))
        ok(not ed["created"] and ed["message"]["body"] == "Hello there {company}" and ed["message"]["name"] == "Smoke Test agent msg",
           f"[{mode}] agent edits only the fields it passes")
        bad = await c.call_tool("save_message_template", {"template_id": nm["message"]["id"]})
        ok(bad.is_error, f"[{mode}] edit with nothing to change refused")
        bad = await c.call_tool("save_message_template", {"template_id": nm["message"]["id"], "make_current": False})
        ok(bad.is_error and "owner" in bad.content[0].text, f"[{mode}] an agent can't leave a category with no current message")
        TEMPLATE["agent"].append((nc["category"]["key"], nm["message"]["id"]))
        bad = await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "note", "summary": "x", "template_id": TEMPLATE["id"]})
        ok(bad.is_error and "my_message" in bad.content[0].text, f"[{mode}] template_id refused on a note")
        r3 = structured(await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "my_message",
                                                           "summary": "Sent proposal", "template_id": TEMPLATE["id"]}))
        ok(r3["stage"] == "applied" and r3["waiting_on"] == "client" and r3["template_id"] == TEMPLATE["id"],
           f"[{mode}] my_message: lead→applied, their move, first message in the summary")
        r3 = structured(await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "my_message", "summary": "again",
                                                           "template_id": TEMPLATE["other"], "channel": "email"}))
        ok(r3["template_id"] == TEMPLATE["id"], f"[{mode}] a second template is counted but keeps the first message")
        d = structured(await c.call_tool("get_opportunity", {"opportunity_id": opp["id"]}))
        ok(d["template"]["id"] == TEMPLATE["id"] and d["resume_url"].endswith("smoke-resume")
           and d["cover_letter_url"] and d["resume_version"] == "Smoke base", f"[{mode}] resume, cover letter, first message stored")
        ok(d["events"][0]["template"]["id"] == TEMPLATE["other"] and d["events"][0]["channel"] == "email"
           and d["events"][1]["channel"] == "upwork", f"[{mode}] each sent message records its template and platform")
        r4 = structured(await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "client_message", "summary": "Interested!"}))
        ok(r4["stage"] == "replied" and r4["waiting_on"] == "me", f"[{mode}] client_message: →replied, your move")
        bad = await c.call_tool("update_opportunity", {"opportunity_id": opp["id"], "stage": "matcher"})
        ok(bad.is_error and "toptal" in bad.content[0].text, f"[{mode}] matcher refused for non-Toptal")
        bad = await c.call_tool("update_opportunity", {"opportunity_id": opp["id"], "stage": "lost"})
        ok(bad.is_error and "lost_reason" in bad.content[0].text, f"[{mode}] lost without a reason refused")
        rem_id = structured(await c.call_tool("get_opportunity", {"opportunity_id": opp["id"]}))["reminders"][0]["id"]
        moved = structured(await c.call_tool("update_reminder", {"reminder_id": rem_id, "due": "2030-01-05"}))
        ok(moved["due_at"].startswith("2030-01-0"), f"[{mode}] update_reminder reschedules")
        ag = structured(await c.call_tool("get_agenda", {}))
        ok(any(o["id"] == opp["id"] for o in ag["your_move"]), f"[{mode}] agenda: shows under your move")
        st = structured(await c.call_tool("pipeline_stats", {"days": 30}))
        ok(st["overall"]["applied"] >= 1, f"[{mode}] stats: applied counted")
        d = structured(await c.call_tool("get_opportunity", {"opportunity_id": opp["id"]}))
        ok(len(d["events"]) >= 4 and d["events"][0]["actor_type"] == "agent", f"[{mode}] timeline has agent events")
        alert = {"title": f"Smoke Test {mode}: confirm call time", "message": "They proposed Thu 3pm.",
                 "opportunity_id": opp["id"], "url": "mail.google.com/mail/u/0/#inbox/abc"}
        n = structured(await c.call_tool("notify_owner", alert))
        ok(n["created"] and n["notification"]["opportunity"]["id"] == opp["id"], f"[{mode}] notify_owner: alert sent")
        n2 = structured(await c.call_tool("notify_owner", alert))
        ok(not n2["created"] and n2["notification"]["id"] == n["notification"]["id"], f"[{mode}] same unread alert not sent twice")
        bad = await c.call_tool("notify_owner", {"title": "x", "url": "javascript:alert(1)"})
        ok(bad.is_error and "web address" in bad.content[0].text, f"[{mode}] notify_owner: non-web link refused")
        ok(structured(await c.call_tool("get_agenda", {}))["unread_notifications"] >= 1, f"[{mode}] agenda counts unread alerts")
        NOTIFS.append(n["notification"]["id"])
        await state_calls(c, mode)
    return created


async def state_calls(c, mode: str) -> None:
    """Agent state: a run's lease, brief, seen, counters (concurrently), ops, locked rows, digest."""
    ns = f"smoke-test-{mode}"
    run = structured(await c.call_tool("run_start", {"ns": ns, "also": ["smoke-test-shared"], "lease_min": 5}))
    ok(run["run_id"] and run["state"]["lesson"]["tone"] == "Smoke Test rule" and run["also"]["smoke-test-shared"]["halt"] == "paused",
       f"[{mode}] run_start: brief has the owner's row and the shared stop")
    busy = structured(await c.call_tool("run_start", {"ns": ns}))
    ok(busy.get("busy") and "run_id" not in busy, f"[{mode}] second run_start on a live ns+worker: busy")
    r = structured(await c.call_tool("seen", {"ns": ns, "source": "jobs", "ids": ["j1", "j2", "j1"]}))
    r2 = structured(await c.call_tool("seen", {"ns": ns, "source": "jobs", "ids": ["j2", "j3"]}))
    ok(r["new"] == ["j1", "j2"] and r2["new"] == ["j3"], f"[{mode}] seen: repeats once, known ids skipped")
    spend = {"items": [{"ns": ns, "key": "emails", "period": "day", "limit": 3}, {"ns": "smoke-test-budget", "key": "actions", "limit": 100}]}
    res = await asyncio.gather(*(c.call_tool("count", spend) for _ in range(5)))
    res = [structured(x) for x in res]
    ok(sum(x["ok"] for x in res) == 3 and any("emails (day) is at 3 of 3" in x.get("refused", "") for x in res),
       f"[{mode}] count: 5 concurrent spends, limit 3 → exactly 3 pass")
    st = structured(await c.call_tool("state_set", {"ns": ns, "changes": [
        {"section": "next", "key": "cursor", "value": 100}, {"section": "next", "key": "cursor", "op": "max", "value": 50},
        {"section": "lesson", "key": "tone", "value": "overwrite"},
        {"section": "contacts", "key": "jane@example.com", "value": {"company": "Smoke Test Acme", "stage": "new"}, "due": "2000-01-01"}]}))
    ok(len(st["applied"]) == 3 and st["applied"][1]["value"] == 100 and st["rejected"][0]["reason"].startswith("owner_row"),
       f"[{mode}] state_set: max keeps the larger, owner row rejected")
    mixed = structured(await c.call_tool("state_set", {"ns": ns, "changes": [
        {"section": "next", "key": "a", "op": "increment", "value": 1}, {"section": "next", "key": "b", "value": 1, "due_at": "x"},
        {"section": "next", "key": "c", "value": 1}, "not an object"]}))
    ok([a["key"] for a in mixed["applied"]] == ["c"] and "op must be" in mixed["rejected"][0]["reason"]
       and "Unknown field" in mixed["rejected"][1]["reason"] and "object" in mixed["rejected"][2]["reason"],
       f"[{mode}] one bad change (even a non-object) is rejected alone; unknown fields aren't dropped silently")
    got = structured(await c.call_tool("state_get", {"ns": ns, "q": "smoke test acme"}))
    ok(list(got["state"][ns]["contacts"]) == ["jane@example.com"], f"[{mode}] state_get q finds a list row by its value")
    due = structured(await c.call_tool("state_get", {"ns": ns, "sections": ["contacts"], "due_before": "now", "limit": 5}))
    ok(due["state"][ns]["contacts"]["jane@example.com"]["due_at"].startswith("2000-01-01"), f"[{mode}] state_get due_before + limit")
    once = {"items": [{"ns": ns, "key": "replies", "limit": 5}], "idem": f"smoke-{mode}-reply-1"}
    a, b = structured(await c.call_tool("count", once)), structured(await c.call_tool("count", once))
    ok(a == b and a["counters"][0]["value"] == 1, f"[{mode}] count with idem: a retry replays, spends once")
    r = structured(await c.call_tool("seen", {"ns": ns, "source": "posts", "ids": ["p1"], "ttl_days": 3}))
    ok(r["new"] == ["p1"], f"[{mode}] seen with ttl_days")
    end = structured(await c.call_tool("run_end", {"run_id": run["run_id"], "status": "routine", "summary": "Smoke Test run",
                                                   "counts": {"emailed": 3}, "changes": [
                                                       {"section": "contacts", "key": "jane@example.com", "op": "merge", "value": {"stage": "sent"}}]}))
    ok(end["ended"] and end["applied"], f"[{mode}] run_end applies its changes and frees the lease")
    replay = structured(await c.call_tool("run_end", {"run_id": run["run_id"], "status": "error", "summary": "retry"}))
    ok(replay == end, f"[{mode}] run_end retry returns the first reply")
    again = structured(await c.call_tool("run_start", {"ns": ns, "include": ["contacts"]}))
    ok(again["last"]["summary"] == "Smoke Test run" and again["lists"] == {"contacts": 1}
       and again["include"]["contacts"][0]["key"] == "jane@example.com" and again["owner"] == {ns: {"lesson": ["tone"]}},
       f"[{mode}] next run_start: last run, due rows of `include`, owner rows named")
    stopped = structured(await c.call_tool("count", {"items": [{"ns": ns, "key": "x"}, {"ns": "smoke-test-shared", "key": "actions"}]}))
    ok(not stopped["ok"] and stopped["stopped"] == "smoke-test-shared halt: paused", f"[{mode}] count refused while a stop row is set")
    structured(await c.call_tool("run_end", {"run_id": again["run_id"], "status": "quiet"}))
    dig = structured(await c.call_tool("state_get", {"ns": ns, "runs_since": "1h"}))
    ok("state" not in dig and dig["runs"][ns]["main"]["runs"] == 2 and dig["runs"][ns]["main"]["counts"] == {"emailed": 3},
       f"[{mode}] runs_since digest per worker")
    bad = await c.call_tool("run_end", {"run_id": 0, "status": "routine"})
    ok(bad.is_error and "run_start" in bad.content[0].text, f"[{mode}] unknown run_id: an error the agent can act on")


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def main():
    web = httpx.Client(base_url=BASE, timeout=30)
    print("REST (human)")
    r = web.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    ok(r.status_code == 200, "login")
    ok(web.get("/api/agenda").status_code == 200, "agenda")
    key = web.post("/api/agents/keys", json={"name": "Smoke key"}).json()
    ok(key["token"].startswith("sp_"), "API key created")

    # Smoke templates live in their own categories, so the real ones agents send from are never touched.
    cat = web.post("/api/template-categories", json={"name": "Smoke Test outreach", "purpose": "Smoke test only — never send."}).json()
    ok(cat["key"].startswith("smoke_test_outreach") and not cat["has_subject"] and not cat["needs_review"],
       "category created by a person (key from the name, no review flag)")
    dup = web.post("/api/template-categories", json={"name": "smoke test OUTREACH"})
    ok(dup.status_code == 400 and cat["key"] in dup.json()["detail"], "duplicate category name refused")
    mail = web.post("/api/template-categories", json={"name": "Smoke Test email", "has_subject": True}).json()
    TEMPLATE.update(cat=cat["key"], mail=mail["key"], agent=[])
    TEMPLATE.update(web.post("/api/templates", json={"category": cat["key"], "name": "Smoke Test variant",
                                                     "body": "Hi {first_name}", "subject": "dropped"}).json())
    ok(TEMPLATE.get("id") and TEMPLATE["subject"] is None and TEMPLATE["placeholders"] == ["first_name"] and TEMPLATE["is_current"],
       "message created (no subject in a subject-less category, placeholders listed, first one is current)")
    TEMPLATE["other"] = web.post("/api/templates", json={"category": cat["key"], "name": "Smoke Test variant 2", "body": "Yo"}).json()["id"]
    bad = web.post("/api/templates", json={"category": mail["key"], "name": "Smoke Test x", "body": "y"})
    ok(bad.status_code == 400 and "subject" in bad.json()["detail"], "an email without a subject is refused")
    bad = web.post("/api/templates", json={"category": cat["key"], "name": "Smoke Test x", "body": "y", "is_current": "false"})
    ok(bad.status_code == 400, "is_current must be a real boolean")
    bad = web.patch(f"/api/template-categories/{cat['key']}", json={"has_subject": True})
    ok(bad.status_code == 400, "subject line setting is fixed once a category has messages")
    bad = httpx.post(f"{BASE}/api/templates", json={"category": cat["key"], "name": "x", "body": "y"},
                     headers={"Authorization": f"Bearer {key['token']}"})
    ok(bad.status_code == 403, "agents write templates through MCP, not REST")
    gone = web.post("/api/templates", json={"category": mail["key"], "name": "Smoke Test gone", "subject": "s", "body": "b"}).json()
    web.delete(f"/api/templates/{gone['id']}")
    held = web.post("/api/templates", json={"category": mail["key"], "name": "Smoke Test held", "subject": "s", "body": "b"}).json()
    ok(held["id"] > gone["id"], "a removed message's id is never reused (agents keep ids)")
    TEMPLATE["held"] = held["id"]
    unpicked = web.patch(f"/api/templates/{held['id']}", json={"is_current": False, "updated_at": held["updated_at"]})
    ok(unpicked.status_code == 200 and not unpicked.json()["is_current"], "the owner can leave a category with no current message")
    stale = web.patch(f"/api/templates/{held['id']}", json={"updated_at": held["updated_at"]})
    ok(stale.status_code == 409, "\"Looks good\" on an older version than the server's is refused")

    for mode in ("auto", "legacy"):  # the owner's rules the agents must obey (smoke namespaces only)
        r = web.post("/api/state", json={"ns": f"smoke-test-{mode}", "changes": [{"section": "lesson", "key": "tone", "value": "Smoke Test rule"}]})
        ok(r.status_code == 200 and r.json()["applied"], f"owner adds a (locked) state row for {mode}")
    r = web.post("/api/state", json={"ns": "smoke-test-shared", "changes": [{"section": "stop", "key": "halt", "value": "paused", "expires": "1h"}]})
    ok(r.json().get("applied"), "owner sets a shared stop that expires")

    created = []
    print("MCP with API key — 2026-07-28 (modern) and handshake (legacy) clients")
    created += await mcp_calls(key["token"], "auto")
    created += await mcp_calls(key["token"], "legacy")

    feed = web.get("/api/activity", params={"actor_type": "agent", "limit": 5}).json()
    ok(feed and feed[0]["actor_name"] == "Smoke key", "activity feed attributes the agent by key name")
    st = web.get("/api/stats", params={"days": 30}).json()
    ok(any(r["key"] == str(TEMPLATE["id"]) and r["applied"] == 2 for r in st["by_template"]), "Insights: funnel per first message")
    ok(any(r["key"] == "Smoke base" for r in st["by_resume_version"]), "Insights: funnel per resume version")
    usage = {r["key"]: r for r in st["template_usage"]}
    ok(usage[str(TEMPLATE["id"])]["uses"] == 2 and usage[str(TEMPLATE["id"])]["by_channel"] == [{"key": "upwork", "label": "Upwork", "count": 2}]
       and usage[str(TEMPLATE["other"])]["by_channel"][0]["key"] == "email", "Insights: template uses per platform")
    lst = {t["id"]: t["usage"] for t in web.get("/api/templates").json()}
    ok(lst[TEMPLATE["id"]]["sent"] == 2 and lst[TEMPLATE["id"]]["replied"] == 2 and lst[TEMPLATE["id"]]["uses"] == 2
       and lst[TEMPLATE["other"]]["by_channel"] == {"email": 2} and lst[TEMPLATE["other"]]["sent"] == 0,
       "Messages page: uses per platform + first-message reply counts")
    ok(web.get("/api/agenda").json()["messages_need_review"] >= 4, "agent-written categories and messages counted for review")
    agent_cat, agent_msg = next(x for x in TEMPLATE["agent"] if x[0])
    ok(not web.patch(f"/api/template-categories/{agent_cat}", json={}).json()["needs_review"]
       and not web.patch(f"/api/templates/{agent_msg}", json={}).json()["needs_review"], "a person saving it clears the review flag")
    bad = web.delete(f"/api/template-categories/{cat['key']}")
    ok(bad.status_code == 400, "a category with messages can't be deleted")
    rv = web.post(f"/api/opportunities/{created[0]}/review").json()
    ok(rv["reviewed"] == 1, "human review clears the flag")
    unread = web.get("/api/notifications", params={"unread": "true"}).json()
    ok({*NOTIFS} <= {n["id"] for n in unread}, "alerts listed in the inbox")
    ok(web.post("/api/notifications/read", json={"ids": NOTIFS}).json()["updated"] == len(NOTIFS), "alerts marked read")
    ok(not {*NOTIFS} & {n["id"] for n in web.get("/api/notifications", params={"unread": "true"}).json()}, "read alerts leave the unread list")

    view = web.get("/api/state", params={"ns": "smoke-test-auto"}).json()
    row = next(r for r in view["rows"] if r["section"] == "contacts")
    ok(row["value"] == {"company": "Smoke Test Acme", "stage": "sent"} and row["by"] == "Smoke key"
       and view["counters"]["smoke-test-auto"]["emails"]["day"] == 3 and "smoke-test-shared" in view["namespaces"],
       "State page: rows, agent attribution, counters, namespaces")
    runs = web.get("/api/state/runs", params={"ns": "smoke-test-auto", "status": "routine"}).json()
    ok(len(runs) == 1 and runs[0]["counts"] == {"emailed": 3} and runs[0]["ended_at"], "Runs list filtered by status")
    bad = httpx.delete(f"{BASE}/api/state/namespaces/smoke-test-auto", headers={"Authorization": f"Bearer {key['token']}"})
    ok(bad.status_code == 403, "agents can't forget a namespace")

    print("OAuth (what Claude does when you add the connector)")
    unauth = httpx.post(f"{BASE}/mcp", json={})
    ok(unauth.status_code == 401 and "resource_metadata" in unauth.headers.get("www-authenticate", ""), "401 points to resource metadata")
    prm = httpx.get(f"{BASE}/.well-known/oauth-protected-resource/mcp").json()
    asm = httpx.get(prm["authorization_servers"][0].rstrip("/") + "/.well-known/oauth-authorization-server").json()
    reg = httpx.post(asm["registration_endpoint"], json={
        "client_name": "Smoke Claude", "redirect_uris": ["http://localhost:9999/cb"],
        "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"]}).json()
    verifier, challenge = pkce()
    a = httpx.get(asm["authorization_endpoint"], params={
        "response_type": "code", "client_id": reg["client_id"], "redirect_uri": "http://localhost:9999/cb",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "xyz",
        "resource": prm["resource"]}, follow_redirects=False)
    consent = a.headers["location"]
    ok("/oauth/consent?request=" in consent, "authorize → consent page")
    req_id = parse_qs(urlsplit(consent).query)["request"][0]
    info = web.get(f"/api/oauth/requests/{req_id}").json()
    ok(info["client_name"] == "Smoke Claude", "consent shows the client's name")
    back = web.post(f"/api/oauth/requests/{req_id}", json={"allow": True}).json()["redirect_to"]
    q = parse_qs(urlsplit(back).query)
    ok(q["state"] == ["xyz"] and "code" in q, "approve → redirect with code + state")
    tok = httpx.post(asm["token_endpoint"], data={
        "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": "http://localhost:9999/cb",
        "client_id": reg["client_id"], "code_verifier": verifier, "resource": prm["resource"]}).json()
    ok("access_token" in tok and "refresh_token" in tok, "code exchanged for tokens")
    again = httpx.post(asm["token_endpoint"], data={
        "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": "http://localhost:9999/cb",
        "client_id": reg["client_id"], "code_verifier": verifier})
    ok(again.status_code == 400, "code is single-use")
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30)
    async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http)) as c:
        r = structured(await c.call_tool("log_activity", {"opportunity_id": created[0], "kind": "note", "summary": "via OAuth"}))
        ok(r["id"] == created[0], "OAuth access token works on MCP")
    feed = web.get("/api/activity", params={"limit": 1}).json()
    ok(feed[0]["actor_name"] == "Smoke Claude", "OAuth agent attributed by client name")
    ref = httpx.post(asm["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                  "client_id": reg["client_id"]}).json()
    ok("access_token" in ref, "refresh works")
    reuse = httpx.post(asm["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                                    "client_id": reg["client_id"]})
    ok(reuse.status_code == 400, "refresh token rotated (old one refused)")
    agents = web.get("/api/agents").json()
    ok(any(a["name"] == "Smoke Claude" for a in agents["apps"]), "connected app listed in Settings")
    web.delete(f"/api/agents/apps/{reg['client_id']}")
    after = httpx.get(f"{BASE}/api/agenda", headers={"Authorization": f"Bearer {ref['access_token']}"})
    ok(after.status_code == 401, "disconnect revokes the app's tokens")

    evil = httpx.post(asm["registration_endpoint"], json={"client_name": "Evil", "redirect_uris": ["javascript:alert(1)"],
                                                         "token_endpoint_auth_method": "none"})
    ok(evil.status_code == 400, "javascript: redirect URI refused at registration")

    print("Cleanup")
    for oid in created:
        web.delete(f"/api/opportunities/{oid}")
    again = web.post("/api/opportunities", json={"company": "x", "application_url": URLS[created[0]]}).json()
    ok(not again["created"] and again["opportunity"]["deleted"], "re-adding a deleted posting does not revive it")
    feed = web.get("/api/activity", params={"limit": 50}).json()
    ok(all(e["opportunity_id"] not in created for e in feed), "deleted deals are hidden from the activity feed")
    ids = [TEMPLATE["id"], TEMPLATE["other"], TEMPLATE["held"], *(m for _, m in TEMPLATE["agent"])]
    for tid in ids:
        web.delete(f"/api/templates/{tid}")
    ok(all(t["id"] not in ids for t in web.get("/api/templates", params={"include_archived": "true"}).json()),
       "template only used by deleted deals is removed outright")
    keys = [TEMPLATE["cat"], TEMPLATE["mail"], *(k for k, _ in TEMPLATE["agent"] if k)]
    ok(all(web.delete(f"/api/template-categories/{k}").status_code == 200 for k in keys)
       and not {*keys} & {c["key"] for c in web.get("/api/template-categories", params={"include_archived": "true"}).json()},
       "empty categories are removed outright")
    smoke_ns = {"smoke-test-auto", "smoke-test-legacy", "smoke-test-shared", "smoke-test-budget"}
    for ns in smoke_ns:
        web.delete(f"/api/state/namespaces/{ns}")
    ok(not smoke_ns & set(web.get("/api/state").json()["namespaces"]),
       "smoke state namespaces forgotten")
    web.delete(f"/api/agents/keys/{key['id']}")
    after = httpx.get(f"{BASE}/api/agenda", headers={"Authorization": f"Bearer {key['token']}"})
    ok(after.status_code == 401, "revoked key refused")
    print("ALL PASSED")


asyncio.run(main())
