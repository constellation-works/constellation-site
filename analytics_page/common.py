"""Shared constants and the HTML escape helper for the analytics pages.

Moved unchanged from analytics_page.py.
"""

import html
import re

# Keep the ranking rules after the shared rules to preserve the analytics cascade.
ANALYTICS_CSS = ("analytics.css", "analytics-ranking.css")

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def crew_groups_text(labels):
    """A model's crew labels grouped by crew, each crew named once with its efforts.

    ``haiku@xhigh``, ``haiku@high`` and ``haiku · effort unknown`` read
    ``haiku: xhigh, high, effort unknown``; several crews are separated by a
    middle dot (``opus: effort unknown · sol: effort unknown``). A bare crew
    with no effort (a snapshot from before effort rows) stays its name. Crews
    keep their first-seen order, and so do recorded efforts, with ``effort unknown`` last. Shared by /ranking/ (build.py)
    and the weekly notes' Model rank table (scripts/crew_rankings.py).
    """
    groups = {}
    for label in labels:
        crew, effort = label, None
        if "@" in label:
            crew, _sep, effort = label.partition("@")
        elif " · " in label:
            crew, _sep, effort = label.partition(" · ")
        efforts = groups.setdefault(crew, [])
        if effort and effort not in efforts:
            efforts.append(effort)
    def ordered(efforts):
        return [x for x in efforts if x != "effort unknown"] + [x for x in efforts if x == "effort unknown"]

    return " · ".join(f"{crew}: {', '.join(ordered(efforts))}" if efforts else crew
                      for crew, efforts in groups.items())
LOW_ACTOR_SAMPLE = 5
CHART_W = 640
CHART_H = 168
CHART_PAD = 8
TABLE_PREVIEW_ROWS = 7

TIER_LABEL = {
    "all": "All",
    "low": "Low",
    "medium": "Medium",
    "hard": "Hard",
    "xhard": "Extra hard",
    "unset": "Unset",
    "other": "Other",
}
DURATION_LINES = ("all", "low", "medium", "hard")
VOLUME_STACK = (("low", "s-low"), ("medium", "s-medium"), ("hard", "s-hard"), ("other_runs", "s-other"))
DONE_STACK = (("low", "s-low"), ("medium", "s-medium"), ("hard", "s-hard"), ("other", "s-other"))
LINEAGE = (
    ("fix_for_fix", "Fix-for-a-fix", "s-fix"),
    ("regression", "Other regression", "s-reg"),
    ("unattributed", "Unattributed", "s-una"),
)
LINEAGE_LABEL = {key: label for key, label, _cls in LINEAGE}
ORIGIN_LABEL = {
    "code-review": "Code review",
    "full-code-review": "Full code review",
    "delivery-code-review": "Delivery review",
    "qa-sweep": "QA sweep",
    "qa-full-sweep": "Full QA sweep",
    "security-review": "Security review",
    "ci-failure-sweep": "CI failure sweep",
    "scanning-sweep": "Scanning sweeps",
    "review-reconciliation": "Review reconciliation",
    "friction-curation": "Friction curation",
    "other": "Untagged",
}
MEASURE_LABEL = {
    "code_added": "Code added",
    "code_deleted": "Code deleted",
    "tests_added": "Tests added",
    "tests_deleted": "Tests deleted",
    "other_added": "Other added",
    "other_deleted": "Other deleted",
    "net": "Net",
}
PART_LABEL = {
    "recovered": "recovered",
    "failed": "failed",
    "resume": "resumed",
    "settled": "settled",
    "escalated": "escalated",
    "other": "other",
    "failed_checks": "failed checks",
    "conflict": "conflict",
    "landing_review": "landing review",
    "pr_head": "PR heads",
    "sweep_filing": "sweep filings",
    "invocations": "invocations",
}
TOKEN_TIERS = ("low", "medium", "hard", "xhard")
# A tier average over fewer runs than this is flagged as a thin sample.
THIN_TIER_RUNS = 30
# Below this share of done tasks measured, a board carries a coverage warning.
COVERAGE_WARN_RATE = 0.5
GROUPS = (
    ("speed", "Speed", (("duration", "Duration"), ("turns", "Turns"))),
    ("throughput", "Throughput", (("completed", "Tasks completed"), ("outcomes", "Outcomes"))),
    ("quality", "Quality", (("defects", "Defects"), ("friction", "Friction"))),
    ("spend", "Spend", (("cost", "Cost"), ("tokens", "Tokens"), ("diff", "Lines"))),
)
EVENT_FAMILIES = ("step_recovery", "final_recovery", "auto_fix", "merge_conflict", "failed_ci")
SCOPE_LABEL = {"all_time": "all time"}

HEADER = """<header>
  <div class="wrap bar">
    <a class="brand" href="/">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <mask id="hm" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <rect width="100" height="100" fill="#fff"/>
          <circle cx="23.87" cy="47.41" r="7.6" fill="#000"/>
          <circle cx="74.62" cy="63.52" r="8" fill="#000"/>
        </mask>
        <g mask="url(#hm)" fill="none" stroke="currentColor" stroke-width="3.4">
          <ellipse cx="50" cy="50" rx="34" ry="19" transform="rotate(-28 50 50)"/>
          <ellipse cx="50" cy="50" rx="45" ry="25" transform="rotate(-28 50 50)"/>
        </g>
        <g fill="currentColor">
          <circle cx="23.87" cy="47.41" r="5.2"/>
          <circle cx="74.62" cy="63.52" r="5.6"/>
        </g>
      </svg>
      <b>constellation<span> works</span></b>
    </a>
    <nav>
      <a href="/notes/">Notes</a>
      <a href="/ranking/">Ranking</a>
      <a href="/analytics/" aria-current="page">Analytics</a>
      <a class="nav-orbit" href="https://orbit-cli.com">Orbit</a>
      <a href="https://github.com/constellation-works">GitHub</a>
      <button class="theme" type="button" aria-label="Switch to light theme" hidden>
        <svg class="sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
        <svg class="moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>
      </button>
    </nav>
  </div>
</header>"""


def e(value):
    return html.escape(str(value), quote=True)
