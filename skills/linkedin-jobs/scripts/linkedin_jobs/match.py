"""Explainable job ranking against a Profile (resume or JD). Deterministic, offline, tunable via config weights."""
from __future__ import annotations

import re
from datetime import date

from pydantic import Field

from .config import Weights, load_config
from .criteria import infer_experience
from .filters import ExperienceLevel
from .models import JobDetails
from .profile import Profile, extract_profile

_ORDER = [ExperienceLevel.INTERNSHIP, ExperienceLevel.ENTRY, ExperienceLevel.ASSOCIATE,
          ExperienceLevel.MID_SENIOR, ExperienceLevel.DIRECTOR, ExperienceLevel.EXECUTIVE]
_STOP = {"and", "the", "of", "for", "a", "an", "in", "at", "to", "with", "or", "i", "ii", "iii"}


class ScoredJob(JobDetails):
    score: float = Field(0, description="0-100 fit score")
    matched_skills: list[str] = []
    missing_skills: list[str] = Field([], description="Skills the job asks for that the reference lacks")
    inferred_level: str | None = None
    reasons: list[str] = []


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", s.lower()) if t not in _STOP}


def _title_score(title: str, profile: Profile, queries: list[str]) -> float:
    jt = _tokens(title)
    if not jt:
        return 0.0
    best = 0.0
    for ref in [*profile.titles, *queries]:
        rt = _tokens(ref)
        if rt:
            best = max(best, len(jt & rt) / len(rt))
    return min(best, 1.0)


def _level_fit(job_level: ExperienceLevel | None, want: ExperienceLevel | None) -> float:
    if job_level is None or want is None:
        return 0.5
    d = abs(_ORDER.index(job_level) - _ORDER.index(want))
    return {0: 1.0, 1: 0.55}.get(d, 0.0)


def _recency(posted: str | None) -> float:
    if not posted:
        return 0.5
    try:
        age = (date.today() - date.fromisoformat(posted[:10])).days
    except ValueError:
        return 0.5
    return max(0.0, 1 - age / 30)


def score_job(job: JobDetails, profile: Profile, weights: Weights | None = None) -> ScoredJob:
    cfg = load_config()
    w = weights or cfg.weights
    jp = extract_profile(job.description, "jd") if job.description else None
    job_req = jp.required_skills if jp else []
    job_pref = jp.preferred_skills if jp else []
    ref = set(profile.skills)

    reasons: list[str] = []
    if profile.kind == "resume":
        total = len(job_req) + 0.5 * len(job_pref)
        have = sum(1 for s in job_req if s in ref) + 0.5 * sum(1 for s in job_pref if s in ref)
        # smoothed: a posting naming 1 skill you have is weaker evidence than one naming 8 you have
        skill_s = have / (total + 2.0) * 1.35 if total else 0.3
        skill_s = min(skill_s, 1.0)
        matched = [s for s in [*job_req, *job_pref] if s in ref]
        missing = [s for s in job_req if s not in ref]
    else:  # "find jobs like this JD": symmetric weighted overlap
        mine = set(profile.required_skills) | set(profile.preferred_skills) or ref
        theirs = set(job_req) | set(job_pref)
        union = mine | theirs
        skill_s = len(mine & theirs) / len(union) if union else 0.35
        matched = sorted(mine & theirs)
        missing = sorted(theirs - mine)

    level = infer_experience(job.title, job)
    title_s = _title_score(job.title, profile, profile.suggested_queries)
    level_s = _level_fit(level, profile.seniority)
    rec_s = _recency(job.posted_date)

    total_w = w.skills + w.title + w.seniority + w.recency
    degree_pen = 1.0
    wants_phd = re.search(r"\b(ph\.?d\.?|doctorate)\b", job.title, re.I) or re.search(
        r"\b(ph\.?d\.?|doctorate)\b[^.\n]{0,30}(required|preferred|candidate|student|degree)",
        job.description[:1500], re.I)
    if profile.kind == "resume" and profile.education and profile.education != "phd" and wants_phd:
        degree_pen = 0.6
        reasons.append("asks for a PhD; you list " + profile.education)
    score = degree_pen * 100 * (w.skills * skill_s + w.title * title_s + w.seniority * level_s
                               + w.recency * rec_s) / total_w
    if matched:
        reasons.append(f"matches {len(matched)} skills: {', '.join(matched[:6])}")
    if missing:
        reasons.append(f"missing {len(missing)} required: {', '.join(missing[:6])}")
    if title_s >= 0.6:
        reasons.append("title closely matches")
    if level and profile.seniority and level != profile.seniority:
        reasons.append(f"level looks like {level.value} vs your {profile.seniority.value}")
    base = job.model_dump(exclude={"score", "matched_skills", "missing_skills", "inferred_level", "reasons"})
    return ScoredJob(**base, score=round(score, 1), matched_skills=matched[:15],
                     missing_skills=missing[:15], inferred_level=level.value if level else None, reasons=reasons)


def rank(jobs: list[JobDetails], profile: Profile, weights: Weights | None = None) -> list[ScoredJob]:
    return sorted((score_job(j, profile, weights) for j in jobs), key=lambda s: -s.score)
