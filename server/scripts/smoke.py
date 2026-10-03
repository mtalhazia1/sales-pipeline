"""End-to-end smoke test against a running server: REST (human) + MCP (agent, both protocol eras)
+ the full OAuth connect flow an MCP client like Claude performs.

    python scripts/smoke.py http://localhost:8100 EMAIL PASSWORD

Creates records named "Smoke Test …" and deletes them at the end."""

import asyncio
import base64
import hashlib
import json
import secrets
import sys
from urllib.parse import parse_qs, urlsplit

import httpx2
import httpx2 as httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

BASE, EMAIL, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
ok = lambda cond, msg: print(("  ✓ " if cond else "  ✗ FAIL ") + msg) or (cond or sys.exit(1))  # noqa: E731


def structured(result):
    if result.is_error:
        raise RuntimeError(result.content[0].text)
    return result.structured_content if result.structured_content is not None else json.loads(result.content[0].text)


async def mcp_calls(token: str, mode: str) -> list[int]:
    created = []
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with Client(streamable_http_client(f"{BASE}/mcp", http_client=http), mode=mode) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        ok({"add_opportunity", "log_activity", "get_agenda"} <= tools, f"[{mode}] tools listed: {len(tools)}")
        url = f"https://www.upwork.com/jobs/Smoke-Test-AI-agent_~01{secrets.token_hex(8)}/?referrer_url_path=x"
        r = structured(await c.call_tool("add_opportunity", {
            "company": f"Smoke Test {mode}", "title": "AI agent build", "application_url": url,
            "budget": "$60/hr", "fit": 4, "reminder_at": "2030-01-02", "reminder_note": "Check"}))
        opp = r["opportunity"]
        created.append(opp["id"])
        ok(r["created"] and opp["channel"] == "upwork" and opp["needs_review"], f"[{mode}] add: channel inferred, review flagged")
        r2 = structured(await c.call_tool("add_opportunity", {"company": "dup", "application_url": url.split("?")[0].replace("Smoke-Test-AI-agent_", "")}))
        ok(not r2["created"] and r2["opportunity"]["id"] == opp["id"], f"[{mode}] same posting (different URL form) deduplicated")
        r3 = structured(await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "my_message", "summary": "Sent proposal"}))
        ok(r3["stage"] == "applied" and r3["waiting_on"] == "client", f"[{mode}] my_message: lead→applied, their move")
        r4 = structured(await c.call_tool("log_activity", {"opportunity_id": opp["id"], "kind": "client_message", "summary": "Interested!"}))
        ok(r4["stage"] == "replied" and r4["waiting_on"] == "me", f"[{mode}] client_message: →replied, your move")
        bad = await c.call_tool("update_opportunity", {"opportunity_id": opp["id"], "stage": "matcher"})
        ok(bad.is_error and "Toptal" in bad.content[0].text, f"[{mode}] matcher refused for non-Toptal")
        ag = structured(await c.call_tool("get_agenda", {}))
        ok(any(o["id"] == opp["id"] for o in ag["your_move"]), f"[{mode}] agenda: shows under your move")
        st = structured(await c.call_tool("pipeline_stats", {"days": 30}))
        ok(st["overall"]["applied"] >= 1, f"[{mode}] stats: applied counted")
        d = structured(await c.call_tool("get_opportunity", {"opportunity_id": opp["id"]}))
        ok(len(d["events"]) >= 4 and d["events"][0]["actor_type"] == "agent", f"[{mode}] timeline has agent events")
    return created


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

    created = []
    print("MCP with API key — 2026-07-28 (modern) and handshake (legacy) clients")
    created += await mcp_calls(key["token"], "auto")
    created += await mcp_calls(key["token"], "legacy")

    feed = web.get("/api/activity", params={"actor_type": "agent", "limit": 5}).json()
    ok(feed and feed[0]["actor_name"] == "Smoke key", "activity feed attributes the agent by key name")
    rv = web.post(f"/api/opportunities/{created[0]}/review").json()
    ok(rv["reviewed"] == 1, "human review clears the flag")

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
    first = web.get(f"/api/activity?limit=300").json()
    url = next(e["changes"]["application_url"][1] for e in first if e["opportunity_id"] == created[0] and e["kind"] == "created")
    again = web.post("/api/opportunities", json={"company": "x", "application_url": url}).json()
    ok(not again["created"] and again["opportunity"]["deleted"], "re-adding a deleted posting does not revive it")
    web.delete(f"/api/agents/keys/{key['id']}")
    after = httpx.get(f"{BASE}/api/agenda", headers={"Authorization": f"Bearer {key['token']}"})
    ok(after.status_code == 401, "revoked key refused")
    print("ALL PASSED")


asyncio.run(main())
