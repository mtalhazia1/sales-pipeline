"""The sales vocabulary — the ONE place stages, channels, networks and activity kinds are defined.

The web UI reads these through GET /api/meta and the MCP tool schemas are built from the same
Literals, so a new value added here shows up everywhere. Order matters: STAGES is pipeline order.
"""

from typing import Literal

Kind = Literal["job", "project"]
Channel = Literal["linkedin", "email", "upwork", "toptal", "website", "referral", "other"]
Network = Literal["none", "linkedin", "firstglance", "referral"]
Stage = Literal["lead", "matcher", "applied", "replied", "call", "proposal", "won", "lost"]
LostReason = Literal["rejected", "no_response", "declined", "filled", "other"]
WaitingOn = Literal["me", "client"]
# Things that happen to an opportunity, logged by a human or an agent.
ActivityKind = Literal["client_message", "my_message", "call", "note"]
# First-contact messages the owner writes (a few variants each, one "current"); agents send the current
# one word for word. Replies are the owner's own.
TemplateCategory = Literal["linkedin", "cold_email", "warm_email"]

KINDS: list[tuple[str, str]] = [("job", "Job"), ("project", "Project")]

CHANNELS: list[tuple[str, str]] = [
    ("linkedin", "LinkedIn"),
    ("email", "Email"),
    ("upwork", "Upwork"),
    ("toptal", "Toptal"),
    ("website", "Direct / Website"),
    ("referral", "Referral"),
    ("other", "Other"),
]

NETWORKS: list[tuple[str, str]] = [
    ("none", "None"),
    ("linkedin", "LinkedIn"),
    ("firstglance", "FirstGlance"),
    ("referral", "Referral / personal"),
]

STAGES: list[tuple[str, str]] = [
    ("lead", "Lead"),
    ("matcher", "Sent to matcher"),
    ("applied", "Applied"),
    ("replied", "Replied"),
    ("call", "Call booked"),
    ("proposal", "Proposal sent"),
    ("won", "Contract done"),
    ("lost", "Lost"),
]

LOST_REASONS: list[tuple[str, str]] = [
    ("rejected", "Rejected"),
    ("no_response", "No response"),
    ("declined", "I passed"),
    ("filled", "Filled / closed"),
    ("other", "Other"),
]

ACTIVITY_KINDS: list[tuple[str, str]] = [
    ("client_message", "Client messaged"),
    ("my_message", "I messaged"),
    ("call", "Call"),
    ("note", "Note"),
]

TEMPLATE_CATEGORIES: list[tuple[str, str]] = [
    ("linkedin", "LinkedIn message"),
    ("cold_email", "Cold email"),
    ("warm_email", "Warm email"),
]
# Categories whose messages have a subject line.
EMAIL_CATEGORIES = {"cold_email", "warm_email"}

STAGE_ORDER = {key: i for i, (key, _) in enumerate(STAGES)}
OPEN_STAGES = {"lead", "matcher", "applied", "replied", "call", "proposal"}
CLOSED_STAGES = {"won", "lost"}
# First time an opportunity reaches one of these stages its milestone timestamp is stamped —
# the funnel in Insights counts milestones, so a deal that later goes to "lost" still counts
# as having replied / had a call.
MILESTONES = {"applied": "applied_at", "replied": "replied_at", "call": "call_at", "proposal": "proposal_at"}
# A later stage implies the earlier milestones happened (a deal created straight at "call"
# was obviously applied to and replied to).
MILESTONE_CHAIN = ["applied", "replied", "call", "proposal"]

# Days without activity before an open deal with no scheduled reminder is flagged "gone quiet".
# (Leads are never "quiet" — nothing has been sent yet; they wait in New leads.)
QUIET_AFTER_DAYS = {"matcher": 7, "applied": 5, "replied": 2, "call": 2, "proposal": 3}

# Hostnames → channel, so a pasted URL fills the channel by itself.
CHANNEL_BY_HOST = {
    "upwork.com": "upwork",
    "toptal.com": "toptal",
    "linkedin.com": "linkedin",
    "lnkd.in": "linkedin",
}


def label(options: list[tuple[str, str]], key: str | None) -> str | None:
    return next((lbl for k, lbl in options if k == key), key)


def meta() -> dict:
    as_list = lambda opts: [{"value": k, "label": v} for k, v in opts]  # noqa: E731
    return {
        "kinds": as_list(KINDS),
        "channels": as_list(CHANNELS),
        "networks": as_list(NETWORKS),
        "stages": as_list(STAGES),
        "open_stages": [k for k, _ in STAGES if k in OPEN_STAGES],
        "lost_reasons": as_list(LOST_REASONS),
        "activity_kinds": as_list(ACTIVITY_KINDS),
        "template_categories": as_list(TEMPLATE_CATEGORIES),
        "channel_by_host": CHANNEL_BY_HOST,
    }
