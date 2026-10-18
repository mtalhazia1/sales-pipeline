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
# Agent state (durable memory for scheduled agents): how a run went, and counter windows.
RunStatus = Literal["quiet", "routine", "attention", "error"]
CounterPeriod = Literal["day", "week", "month", "total"]
StateOp = Literal["set", "merge", "max", "delete"]

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

# Agent state sections. These fixed ones come back in every run_start, so each is capped to keep that
# brief small; any other section name is a list (one row per key), read on demand with state_get.
STATE_SECTIONS: list[tuple[str, str, int]] = [
    ("next", "Cursors, due times, statuses", 30),
    ("stop", "Flags that halt an activity", 5),
    ("blocker", "Stuck: what the owner must do", 20),
    ("waiting", "Waiting on the owner", 20),
    ("lesson", "Short learned rules", 15),
    ("platform", "How a site behaves", 10),
    ("proposal", "Suggested changes for the owner", 10),
]
LIST_CAP = 500  # rows per list section per namespace
# Longest value (characters; JSON text for non-strings): fixed rows stay short so the brief stays small,
# list rows can hold a draft.
FIXED_VALUE_MAX, LIST_VALUE_MAX = 500, 16_000

RUN_STATUSES: list[tuple[str, str]] = [
    ("quiet", "Quiet"),  # nothing happened
    ("routine", "Routine"),  # did its normal work
    ("attention", "Attention"),  # the owner should look
    ("error", "Error"),
]

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
        "channel_by_host": CHANNEL_BY_HOST,
        "state_sections": [{"value": k, "label": v, "cap": cap} for k, v, cap in STATE_SECTIONS],
        "run_statuses": as_list(RUN_STATUSES),
    }
