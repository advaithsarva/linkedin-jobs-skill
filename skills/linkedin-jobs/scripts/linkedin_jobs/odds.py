"""Odds engine: rank by expected return on effort, not by keyword relevance.

The numbers are *relative indices* for ordering your options, not real probabilities. Inputs are all observable:
fit (skills/title/level), competition (applicant count, age, application channel), ghost risk, your learned taste,
and the effort the application channel demands.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from .ats import detect_ats
from .match import ScoredJob
from .verify import Verdict

_N = re.compile(r"(\d[\d,]*)")


class Odds(BaseModel):
    job_id: str
    title: str
    company: str
    url: str
    fit: float
    competition: int  # 0 (empty) .. 100 (flooded)
    effort_hours: float
    ghost_score: int | None = None
    taste: float = 0.0
    index: float  # relative chance of getting a response (0..100)
    roi: float  # index per hour of effort
    tier: Literal["target", "reach", "long_shot"]
    channel: str
    notes: list[str] = []


def applicants(text: str | None) -> int | None:
    if not text:
        return None
    if "early applicant" in text.lower():
        return 5
    m = _N.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def competition(job: ScoredJob) -> tuple[int, list[str]]:
    n = applicants(job.applicants)
    notes: list[str] = []
    if n is None:
        idx = 45
        notes.append("applicant count not shown; assumed average competition")
    else:
        idx = round(100 * n / (n + 60))
        notes.append(f"{job.applicants}")
    if job.apply_url is None and job.source == "linkedin":
        idx = min(100, idx + 10)  # LinkedIn-hosted quick apply draws more volume
        notes.append("LinkedIn-hosted apply flow attracts volume")
    return idx, notes


def effort(job: ScoredJob) -> tuple[float, str]:
    ref = detect_ats(job.apply_url or "")
    if ref and ref.ats == "workday":
        base, ch = 0.9, "workday (account + long form)"
    elif ref and ref.ats in ("greenhouse", "lever", "ashby", "smartrecruiters"):
        base, ch = 0.5, f"{ref.ats} form"
    elif job.apply_url:
        base, ch = 0.7, "external site"
    else:
        base, ch = 0.25, "linkedin"
    if len(job.missing_skills) >= 3:
        base += 0.5  # needs real tailoring
    return base + 0.25, ch  # +outreach message


def evaluate(job: ScoredJob, verdict: Verdict | None = None, taste: float = 0.0) -> Odds:
    comp, notes = competition(job)
    hours, channel = effort(job)
    ghost = verdict.ghost_score if verdict else None
    fit = job.score / 100
    idx = 100 * (fit ** 1.5) * (1 - comp / 130) * (1 - (ghost or 0) / 100) * (1 + 0.3 * taste)
    idx = max(0.0, min(100.0, idx))
    if verdict and verdict.label == "likely_ghost":
        notes.append("likely ghost job; index heavily discounted")
    if taste:
        notes.append(f"taste {taste:+.2f}")
    tier = "target" if job.score >= 65 else "reach" if job.score >= 45 else "long_shot"
    return Odds(job_id=job.id, title=job.title, company=job.company, url=job.url, fit=job.score, competition=comp,
                effort_hours=round(hours, 2), ghost_score=ghost, taste=round(taste, 2), index=round(idx, 1),
                roi=round(idx / hours, 1), tier=tier, channel=channel, notes=notes)


def portfolio(odds: list[Odds], budget: dict[str, int] | None = None) -> dict[str, list[Odds]]:
    """Pick this week's applications: best ROI first inside each tier (default 6 target, 3 reach, 1 long shot)."""
    budget = budget or {"target": 6, "reach": 3, "long_shot": 1}
    out: dict[str, list[Odds]] = {t: [] for t in budget}
    for o in sorted(odds, key=lambda o: -o.roi):
        if o.ghost_score is not None and o.ghost_score >= 60:
            continue
        if len(out[o.tier]) < budget[o.tier]:
            out[o.tier].append(o)
    return out
