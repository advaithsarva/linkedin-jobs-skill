"""Human/agent-readable renderings. JSON stays the source of truth; this is the compact view."""
from __future__ import annotations

from collections.abc import Sequence

from .models import Job, JobDetails


def _cell(s: object, n: int = 60) -> str:
    t = str(s or "").replace("|", "/").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _when(j: Job) -> str:
    if isinstance(j, JobDetails) and j.posted_text:
        return j.posted_text
    return j.posted_date or ""


def jobs_table(jobs: Sequence[Job]) -> str:
    if not jobs:
        return "_No jobs matched._"
    scored = any(hasattr(j, "score") and getattr(j, "score") for j in jobs)
    head = "| # | " + ("Fit | " if scored else "") + "Role | Company | Where | Posted | Link |"
    rows = [head, "|" + "---|" * (head.count("|") - 1)]
    for i, j in enumerate(jobs, 1):
        fit = f"{getattr(j, 'score', 0):.0f} | " if scored else ""
        rows.append(f"| {i} | {fit}{_cell(j.title)} | {_cell(j.company, 28)} | {_cell(j.location, 26)} | "
                    f"{_cell(_when(j), 18)} | [open]({j.url}) |")
    return "\n".join(rows)


def job_card(j: JobDetails, description_chars: int = 1500) -> str:
    meta = " · ".join(x for x in (j.company, j.location, j.employment_type, j.seniority_level, j.posted_text,
                                  j.applicants, j.salary) if x)
    out = [f"### {j.title}", meta, f"{j.url}" + (f"\nApply: {j.apply_url}" if j.apply_url else "")]
    if j.description:
        d = j.description[:description_chars]
        out += ["", d + ("…" if len(j.description) > description_chars else "")]
    return "\n".join(out)


def discovery_md(d) -> str:  # d: discover.Discovery
    lines = [f"Queries run: {' | '.join(d.queries)}  ·  requests: {d.requests_made}"]
    lines += [f"Note: {n}" for n in d.notes]
    lines += ["", jobs_table([r.job for r in d.results])]
    for i, r in enumerate(d.results, 1):
        if not r.plan:
            continue
        j = r.job
        lines += ["", f"#### {i}. {j.title} — {j.company}", f"why: {'; '.join(j.reasons) or 'n/a'}", "",
                  r.plan.to_markdown()]
    return "\n".join(lines)
