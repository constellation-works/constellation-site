"""Shared snapshot constants, allowlists and projection helpers."""

import collections
import json
import re


SCHEMA_VERSION = 1
WINDOW = "30d"
SETTLED_UNTIL = "30d"
MIN_SUPPORT_DEFAULT = 10
MIN_CONFIDENT_SAMPLE = 20
PUBLIC_KEYS = ("scorecards", "metrics", "reliability", "experiments", "rank", "meta")
# Snapshots written before the rank board existed have no rank.json; a replay
# of such a bundle stays valid and the site renders /ranking/ without Model rank.
OPTIONAL_KEYS = ("rank",)
RANK_EXECUTION = "managed"
RANK_SOURCE = "GET /api/agents/rank?window=30d&execution=managed"
RANK_MEASURE_FIELDS = ("weight", "units", "actual", "expected", "residual", "contribution")
RANK_RULES = (
    "shrinkage_k",
    "min_tasks",
    "min_tiers",
    "min_tier_tasks",
    "min_eligible_models",
    "band_probability",
    "min_cost_coverage",
    "draws",
)
RANK_TIERS = ("low", "medium", "hard", "xhard", "unassessed")
ROLES = ("implementers", "reviewers", "pilots")
GAP_CREWS = {"crew unknown", "crew unavailable", "unknown"}
# Orbit attributes system-run work to this name. It is not a configured crew
# (`orbit config get crews.system.model` is null). Rank crew lists drop it
# and count it with the other dropped gap crews. It is not in GAP_CREWS:
# metrics still records it, and a bundle written before this still replays.
RANK_NON_CREW = "system"
GAP_MODELS = {"model unknown"}
TIER_ORDER = ("low", "medium", "hard", "xhard")
DEFECT_LINEAGES = ("fix_for_fix", "regression", "unattributed")
DEFECT_ORIGINS = (
    "code-review",
    "full-code-review",
    "delivery-code-review",
    "qa-sweep",
    "qa-full-sweep",
    "security-review",
    "ci-failure-sweep",
    "scanning-sweep",
    "review-reconciliation",
    "friction-curation",
    "other",
)
DIFF_MEASURES = (
    "code_added",
    "code_deleted",
    "tests_added",
    "tests_deleted",
    "other_added",
    "other_deleted",
    "net",
)
FRICTION_FAMILIES = (
    "step_recovery",
    "final_recovery",
    "auto_fix",
    "merge_conflict",
    "failed_ci",
    "cost",
)
FRICTION_PARTS = (
    "recovered",
    "failed",
    "resume",
    "settled",
    "escalated",
    "other",
    "failed_checks",
    "conflict",
    "landing_review",
    "pr_head",
    "sweep_filing",
    "invocations",
)
OUTCOME_COUNTS = (
    "total",
    "succeeded",
    "failed",
    "cascaded",
    "upgrade_paused",
    "cancelled",
    "skipped",
    "held",
    "in_flight",
    "unknown",
)
TOKEN_CELL = (
    "n",
    "sum",
    "mean",
    "median",
    "thin",
    "excluded_uncovered",
    "excluded_no_invocations",
)
TURNS_CELL = (
    "n",
    "mean_turns",
    "median_turns",
    "mean_result_bytes",
    "median_result_bytes",
    "thin",
    "excluded_no_edit",
    "excluded_empty_trace",
    "excluded_incomplete_trace",
    "excluded_no_detectable_edit",
    "excluded_no_invocation",
    "tasks",
)
TURNS_COVERAGE = (
    "tasks",
    "measured",
    "empty_trace",
    "incomplete_trace",
    "no_detectable_edit",
    "no_invocation",
    "trace_rate",
    "measured_rate",
)
COMPLETION_DONE = ("total", "low", "medium", "hard", "other")
FAILURE_RATE_LABEL = (
    "settled deliveries (success + one count per failed delivery; "
    "wrapper echoes rolled into the leaf)"
)
# Experiments kept off the public page on purpose, each with a one-line public
# reason. An omitted experiment is counted in dropped.experiments_omitted, is
# never projected and has its readout skipped. Changing this list changes the
# public snapshot only when the snapshot is regenerated or replayed.
EXPERIMENT_OMITS = {
    "exp-2b6d910d": "void: treatment not reliably applied and the explorer was removed mid-run",
    "exp-00c7ef1f": "stopped early by Daniel after 14h (4 tasks, min sample 40 per arm); no verdict possible",
}

SAFE_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_@.+-]{1,80}$")
SAFE_LABEL = re.compile(r"^[A-Za-z0-9 .,'()%/+-]{1,180}$")
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z$")
TASK_ID = re.compile(r"ORB-[0-9]+")
RUN_ID = re.compile(r"jrun-[0-9A-Za-z-]+")
_PATH_SEGMENT = r"[A-Za-z0-9._~%+@\-]+"
_API_ROUTE = r"api/(?:diagnostics|metrics|tasks|agents)(?:/|\?|#|$)"
# Preserve closing-tag syntax, including single-segment paths like
# "</workspace>"; multi-segment paths after "<" are not exempt.
ABS_PATH = re.compile(
    r"(?<![\w./\\\-])/(?!(?<=</)[A-Za-z][A-Za-z0-9._:-]*\s*>)(?!"
    + _API_ROUTE + r")" + _PATH_SEGMENT + r"(?:/" + _PATH_SEGMENT + r")*/?"
)
FILE_URI = re.compile(r"\bfile:/+[^\s\"'<>]*", re.IGNORECASE)
WINDOWS_PATH = re.compile(r"(?:(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'<>]*|\\\\[^\s\"'<>]+)")
RELATIVE_PATH = re.compile(
    r"(?<![\w./\\\-])(?!\d{4}[\\/]\d{1,2}[\\/]\d{1,2}(?:\b|$))"
    r"(?:\.{1,2}[\\/])?(?:"
    r"(?:" + _PATH_SEGMENT + r"[\\/])+[A-Za-z0-9._~%+\-]*\.[A-Za-z][A-Za-z0-9]{0,9}(?![A-Za-z0-9])"
    r"|(?:" + _PATH_SEGMENT + r"[\\/]){2,}" + _PATH_SEGMENT + r"/?"
    r")"
)
HOME_PATH = re.compile(r"(?<!\S)~[A-Za-z0-9._\-]*/[^\s\"']*")
WORKSPACE_ID = re.compile(r"\bws_[A-Za-z0-9_-]+\b")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_gap_crew(crew):
    return isinstance(crew, str) and crew in GAP_CREWS


def is_rank_dropped_crew(crew):
    """A rank crew-list entry that is not a public crew.

    Attribution gaps, plus ``system`` (Orbit's name for system-run work).
    """
    return crew == RANK_NON_CREW or is_gap_crew(crew)


def is_gap_model(model):
    return isinstance(model, str) and model in GAP_MODELS


def is_gap_actor(actor):
    if not isinstance(actor, str):
        return False
    if is_gap_crew(actor) or is_gap_model(actor):
        return True
    if " / " in actor:
        crew, model = actor.split(" / ", 1)
        return is_gap_crew(crew) or is_gap_model(model)
    return False


def numeric_map(obj):
    """Copy a map whose keys are snake_case and whose values are numbers or null."""
    if not isinstance(obj, dict):
        return None
    out = {}
    for key, value in obj.items():
        if not isinstance(key, str) or not SAFE_KEY.fullmatch(key):
            continue
        if value is None or is_number(value):
            out[key] = value
    return out


def whole(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def project_usage(breakdown, dropped, board):
    if not isinstance(breakdown, list) or not breakdown:
        return None
    totals = {
        "invocations": 0,
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "provider_cost_count": 0,
    }
    cost = 0.0
    efforts = collections.Counter()
    kept = 0
    for entry in breakdown:
        if not isinstance(entry, dict):
            continue
        if is_gap_crew(entry.get("crew")) or is_gap_model(entry.get("model")):
            dropped[board] += 1
            continue
        kept += 1
        for key in totals:
            amount = whole(entry.get(key))
            if amount is not None:
                totals[key] += amount
        if is_number(entry.get("provider_cost_usd")):
            cost += entry["provider_cost_usd"]
        effort = entry.get("reasoning_effort")
        if isinstance(effort, str) and effort not in ("", "unknown") and SAFE_TOKEN.fullmatch(effort):
            efforts[effort] += whole(entry.get("invocations")) or 1
    if not kept:
        return None
    totals["provider_cost_usd"] = cost
    totals["efforts"] = ", ".join(name for name, _count in efforts.most_common())
    return totals


def window_of(card):
    since = card.get("since") if isinstance(card.get("since"), str) else None
    until = card.get("until") if isinstance(card.get("until"), str) else None
    if until is None and isinstance(card.get("computed_at"), str):
        until = card["computed_at"]
    key = card.get("window") if isinstance(card.get("window"), str) else card.get("requested_window")
    return {"key": key, "since": since, "until": until}


def number_list(values, size=None):
    if not isinstance(values, list) or not all(is_number(item) for item in values):
        return None
    if size is not None and len(values) != size:
        return None
    return values


def experiment_omitted(definition):
    ident = definition.get("id") if isinstance(definition, dict) else None
    return isinstance(ident, str) and ident in EXPERIMENT_OMITS


def empty_dropped():
    return {
        "experiments": 0,
        "experiments_omitted": 0,
        "implementers": 0,
        "implementers_by_tier": 0,
        "metrics_diff": 0,
        "metrics_durations": 0,
        "metrics_friction": 0,
        "metrics_tokens": 0,
        "pilots": 0,
        "rank": 0,
        "reliability": 0,
        "reviewers_provisional": 0,
        "reviewers_settled": 0,
    }
