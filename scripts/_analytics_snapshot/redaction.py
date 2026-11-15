"""Redaction and publication guards for analytics snapshots."""

import re
import socket

from .common import (
    ABS_PATH,
    FILE_URI,
    HOME_PATH,
    RANK_EXECUTION,
    RELATIVE_PATH,
    ROLES,
    RUN_ID,
    SAFE_TOKEN,
    TASK_ID,
    WINDOW,
    WINDOWS_PATH,
    WORKSPACE_ID,
    experiment_omitted,
    is_gap_actor,
    is_gap_crew,
    is_gap_model,
)


def host_names():
    names = {"dk-server-1", "dk-server-2"}
    for probe in (socket.gethostname, socket.getfqdn):
        try:
            found = probe()
        except OSError:
            continue
        if found and found not in ("localhost", "localhost.localdomain"):
            names.add(found)
    return sorted(names)


def forbidden_patterns(hosts):
    patterns = [TASK_ID, RUN_ID, FILE_URI, WINDOWS_PATH, HOME_PATH, RELATIVE_PATH, ABS_PATH, RELATIVE_PATH, WORKSPACE_ID]
    for host in hosts:
        if len(host) >= 3:
            patterns.append(re.compile(re.escape(host)))
    return patterns


def sanitize(text, patterns, redactions):
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pattern in patterns:
        out, count = pattern.subn("[redacted]", out)
        redactions[0] += count
    return out


def scan(obj, patterns, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            scan(key, patterns, path + "." + str(key))
            scan(value, patterns, path + "." + str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            scan(value, patterns, f"{path}[{index}]")
    elif isinstance(obj, str):
        for pattern in patterns:
            if pattern.search(obj):
                raise SystemExit(f"forbidden pattern {pattern.pattern} in output at {path}")


def assert_no_gap_values(obj, path="$"):
    if isinstance(obj, dict):
        if is_gap_crew(obj.get("crew")) or is_gap_model(obj.get("model")) or is_gap_actor(obj.get("actor")):
            raise SystemExit(f"attribution-gap row survived at {path}")
        crews = obj.get("crews")
        if isinstance(crews, list) and any(is_gap_crew(crew) for crew in crews if isinstance(crew, str)):
            raise SystemExit(f"attribution-gap crew survived at {path}.crews")
        for key, value in obj.items():
            assert_no_gap_values(value, path + "." + str(key))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            assert_no_gap_values(value, f"{path}[{index}]")


def assert_unique_rows(scorecards):
    """Refuse a board with two rows for the same crew, model and reasoning effort.

    Such rows render under the same name on the public boards, so a snapshot
    that dropped the effort identity (or a scorecard that repeats a row) must
    not ship.
    """
    reviewers = scorecards.get("reviewers") if isinstance(scorecards.get("reviewers"), dict) else {}
    boards = (
        ("implementers", scorecards.get("implementers")),
        ("reviewers provisional", reviewers.get("provisional")),
        ("reviewers settled", reviewers.get("settled")),
        ("pilots", scorecards.get("pilots")),
    )
    for name, board in boards:
        if not isinstance(board, dict):
            continue
        seen = set()
        for row in board.get("rows") or []:
            if not isinstance(row, dict):
                continue
            key = (row.get("crew"), row.get("model"), row.get("reasoning_effort"))
            if key in seen:
                effort = key[2] if key[2] is not None else "no recorded effort"
                raise SystemExit(
                    f"the {name} board has two rows for crew {key[0]}, model {key[1]} and {effort}"
                )
            seen.add(key)


def guard(docs, hosts=None):
    patterns = forbidden_patterns(hosts if hosts is not None else host_names())
    scan(docs, patterns)
    assert_no_gap_values(docs)
    assert_unique_rows(docs["scorecards"])
    roles = docs["scorecards"]["roles"]
    if roles != list(ROLES) or "orchestrators" in roles:
        raise SystemExit("scorecards roles must be implementers, reviewers and pilots")
    provisional = docs["scorecards"]["reviewers"]["provisional"]
    if provisional.get("provisional") is not True:
        raise SystemExit("the trailing reviewer board must be labelled provisional")
    settled = docs["scorecards"]["reviewers"]["settled"]
    if docs["meta"]["reviewer_settled"]:
        if not isinstance(settled, dict) or settled.get("provisional") is not False or settled.get("settled") is not True:
            raise SystemExit("a settled reviewer board is required when --until is supported")
    elif settled is not None:
        raise SystemExit("settled reviewer board must be absent when --until is unsupported")
    rank = docs.get("rank")
    if rank is not None:
        if not isinstance(rank, dict):
            raise SystemExit("rank must be an object")
        # New snapshots carry the settled board. A bundle written while the
        # live board was published carries that live board, and one written
        # before it carries a settled board. Either way live and provisional agree.
        if not isinstance(rank.get("live"), bool) or rank.get("provisional") is not rank.get("live"):
            raise SystemExit("the rank board must be live and provisional, or settled and neither")
        if rank.get("execution") != RANK_EXECUTION:
            raise SystemExit("the rank board must count managed tasks")
        if (rank.get("window") or {}).get("key") != WINDOW:
            raise SystemExit(f"the rank board must be a {WINDOW} window")
        for row in rank.get("rows") or []:
            if not isinstance(row, dict) or not isinstance(row.get("model"), str) or not SAFE_TOKEN.fullmatch(row["model"]):
                raise SystemExit("rank rows must name a model")
    for experiment in docs["experiments"]["experiments"]:
        if experiment.get("status") != "concluded":
            raise SystemExit("experiments file contains an experiment that is not concluded")
        if experiment_omitted(experiment):
            raise SystemExit("experiments file contains an experiment listed in EXPERIMENT_OMITS")
