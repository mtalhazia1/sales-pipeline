"""Fill a LOCAL dev database with realistic demo data (never run against production).

    SP_DATA_DIR=... python scripts/seed_demo.py"""

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import service  # noqa: E402
from app.db import session_scope, utcnow  # noqa: E402
from app.models import Event, Opportunity  # noqa: E402
from app.service import Actor  # noqa: E402

me = Actor("human", "Talha")
scout = Actor("agent", "Upwork scout")
inbox = Actor("agent", "Inbox agent")

DEALS = [
    # company, title, channel, network, stage, value, budget, fit, days_ago, waiting
    ("Northwind Labs", "LLM agent for support triage", "upwork", "none", "replied", 12000, "$60-80/hr", 5, 3, "me"),
    ("Acme Robotics", "Senior Next.js + FastAPI engineer", "linkedin", "linkedin", "call", 18000, None, 4, 1, None),
    ("Helios Health", "RAG over clinical docs", "toptal", "none", "matcher", None, "$90/hr", 4, 6, "client"),
    ("Brightpath", "AI onboarding assistant MVP", "website", "firstglance", "proposal", 9500, "$10k fixed", 5, 4, "client"),
    ("Lumen Data", "Data pipeline + dashboard", "email", "referral", "won", 22000, None, 4, 12, None),
    ("Orbital Pay", "Stripe billing migration", "upwork", "none", "applied", None, "$45/hr", 3, 8, "client"),
    ("Kestrel AI", "Voice agent prototype", "upwork", "none", "applied", 6000, "$5-7k", 4, 2, "client"),
    ("Mosaic HR", "Fractional CTO (3 months)", "linkedin", "firstglance", "replied", 30000, None, 5, 1, "client"),
    ("Tandem Logistics", "Route optimisation API", "toptal", "none", "lost", None, "$70/hr", 3, 20, None),
    ("Quill Legal", "Contract review copilot", "email", "none", "applied", None, None, 4, 9, "client"),
    ("Sundial", "React Native → web migration", "upwork", "none", "lost", None, "$3k fixed", 2, 15, None),
]
LEADS = [
    ("Fernway", "Build an evaluation harness for our LLM app", "upwork", 5, "$70-95/hr"),
    ("Pixelcraft Studio", "Shopify + AI product descriptions", "upwork", 2, "$800 fixed"),
    ("Cobalt Security", "Python backend engineer (contract)", "linkedin", 4, None),
    ("Atlas Ventures", "Internal deal-flow tool", "website", 4, "$15k"),
]

with session_scope() as s:
    now = utcnow()
    for i, (company, title, ch, net, stage, value, budget, fit, days, waiting) in enumerate(DEALS):
        actor = scout if ch == "upwork" else me
        opp, _ = service.create(s, actor, {
            "company": company, "title": title, "channel": ch, "network": net, "stage": "applied" if stage != "matcher" else "matcher",
            "value": value, "budget": budget, "fit": fit,
            "application_url": f"https://www.upwork.com/jobs/~01demo{i:04d}" if ch == "upwork" else None,
            "contact_name": random.choice(["Sara Malik", "James Chen", "Priya Nair", "Tom Becker", None]),
        })
        s.flush()
        back = now - timedelta(days=days + random.randint(3, 10))
        opp.created_at = opp.applied_at = back
        if stage in ("replied", "call", "proposal", "won"):
            service.log_activity(s, inbox, opp.id, "client_message", "Thanks — interested, can you share relevant work?", back + timedelta(days=2))
        if stage in ("call", "proposal", "won"):
            service.log_activity(s, me, opp.id, "call", "Intro call, 30 min. Good fit; they want to start this month.", back + timedelta(days=4))
        if stage in ("proposal", "won", "lost"):
            service.update(s, me, opp.id, {"stage": stage} | ({"lost_reason": "rejected"} if stage == "lost" else {}))
        if waiting:
            opp.waiting_on = waiting
        opp.last_activity_at = now - timedelta(days=days)
        if stage == "won":
            opp.closed_at = now - timedelta(days=days)
        if stage in ("applied", "proposal") and i % 2 == 0:
            service.add_reminder(s, me, opp.id, (now + timedelta(days=random.choice([-1, 0, 2, 5]))).isoformat() + "+00:00", "Follow up if no reply")
        if stage == "call":
            service.add_reminder(s, me, opp.id, (now + timedelta(days=1, hours=5)).isoformat() + "+00:00", "Technical call with CTO")
    for j, (company, title, ch, fit, budget) in enumerate(LEADS):
        service.create(s, scout, {"company": company, "title": title, "channel": ch, "fit": fit, "budget": budget,
                                  "application_url": f"https://www.upwork.com/jobs/~01lead{j:04d}" if ch == "upwork" else None,
                                  "notes": "Matches AI/full-stack profile; client has 4.9★ and verified payment."})
    # spread events so the weekly chart has shape
    for e in s.query(Event).all():
        e.occurred_at = min(e.occurred_at, now)
    for o in s.query(Opportunity).filter(Opportunity.stage == "won").all():
        o.needs_review = False
print("seeded")
