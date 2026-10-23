"""Discovery: find and rank jobs from skills, a resume, a JD, structured requirements, or a pasted URL."""
from __future__ import annotations

import math
import re

from pydantic import BaseModel

from .client import LinkedInClient
from .criteria import Criteria
from .filters import ExperienceLevel, JobType, TimePosted, WorkMode
from .match import ScoredJob, rank
from .models import JobDetails
from .plan import ApplyPlan, build_plan
from .profile import Profile, extract_profile, profile_from_skills
from .scraper import get_job, resolve_company, search_jobs
from .url import classify, parse_search_url


class Recommendation(BaseModel):
    job: ScoredJob
    plan: ApplyPlan | None = None


class Discovery(BaseModel):
    results: list[Recommendation]
    queries: list[str]
    profile: Profile | None = None
    requests_made: int = 0
    notes: list[str] = []


def _default_levels(p: Profile | None) -> list[ExperienceLevel]:
    if not p or p.kind != "resume" or not p.seniority:
        return []
    if p.seniority is ExperienceLevel.INTERNSHIP:
        return [ExperienceLevel.INTERNSHIP, ExperienceLevel.ENTRY]
    return [ExperienceLevel.ENTRY] if p.seniority is ExperienceLevel.ENTRY else []


async def find_jobs(
    profile: Profile | None = None,
    *,
    queries: list[str] | None = None,
    skills: list[str] | None = None,
    titles: list[str] | None = None,
    locations: list[str] | None = None,
    criteria: Criteria | None = None,
    experience: list[ExperienceLevel] | None = None,
    job_types: list[JobType] | None = None,
    work_modes: list[WorkMode] | None = None,
    time_posted: TimePosted | None = None,
    company_ids: list[str] | None = None,
    limit: int = 15,
    with_plans: int = 5,
    level_mode: str = "auto",
    client: LinkedInClient | None = None,
) -> Discovery:
    """Run several targeted searches, merge, dedupe reposts, rank by fit, attach apply plans to the best."""
    notes: list[str] = []
    if profile is None and skills:
        profile = profile_from_skills(skills, titles)
    elif profile is not None and titles:
        profile = profile.model_copy(update={"titles": titles})
    qs = queries or (profile.suggested_queries if profile else [])
    if not qs:
        raise ValueError("Give at least one of: queries, skills, or a resume/JD profile.")
    exp = experience if experience is not None else _default_levels(profile)
    if experience is None and exp:
        notes.append(f"Level inferred from the profile: {[e.value for e in exp]} (override with experience=...)")
    locs = locations or [""]
    per_query = max(6, math.ceil(limit * 2.5 / (len(qs) * len(locs))))

    own = client is None
    client = client or LinkedInClient()
    try:
        merged: dict[str, JobDetails] = {}
        seen_keys: set[tuple[str, str, str]] = set()
        for q in qs:
            for loc in locs:
                found = await search_jobs(
                    q, loc, limit=per_query, time_posted=time_posted, company_ids=company_ids, experience=exp,
                    job_types=job_types, work_modes=work_modes, criteria=criteria, include_details=True,
                    level_mode=level_mode, client=client)
                for j in found:
                    key = (j.company.lower(), re.sub(r"\W+", "", j.title.lower()), j.location.lower())
                    if j.id in merged or key in seen_keys:  # same job reposted under a new id
                        continue
                    merged[j.id] = j  # type: ignore[assignment]
                    seen_keys.add(key)
        jobs = list(merged.values())
        if profile:
            ranked = rank(jobs, profile)
        else:
            ranked = [ScoredJob(**j.model_dump())
                      for j in sorted(jobs, key=lambda j: j.posted_date or "", reverse=True)]
        recs = [Recommendation(job=j, plan=build_plan(j, profile) if i < with_plans else None)
                for i, j in enumerate(ranked[:limit])]
        if not recs:
            notes.append("No jobs passed the filters. Loosen experience, use level_mode='broad', widen "
                         "time_posted, or drop require_terms.")
        return Discovery(results=recs, queries=qs, profile=profile, requests_made=client.requests_made, notes=notes)
    finally:
        if own:
            await client.aclose()


async def find_jobs_for_resume(resume_text: str, **kw: object) -> Discovery:
    return await find_jobs(extract_profile(resume_text, "resume"), **kw)  # type: ignore[arg-type]


async def find_jobs_like_jd(jd_text: str, **kw: object) -> Discovery:
    return await find_jobs(extract_profile(jd_text, "jd"), **kw)  # type: ignore[arg-type]


async def search_from_url(url: str, *, limit: int = 25, include_details: bool = False,
                          profile: Profile | None = None, client: LinkedInClient | None = None) -> dict:
    """Replay a pasted LinkedIn URL: a job posting, a jobs search, or a company page (its open jobs)."""
    own = client is None
    client = client or LinkedInClient()
    try:
        kind, ident = classify(url)
        if kind == "job":
            d = await get_job(ident or url, client=client)
            return {"kind": "job", "job": d, "plan": build_plan(d, profile) if d else None}
        if kind == "company":
            cid, name = await resolve_company(ident or url, client=client)
            jobs = []
            if cid:
                jobs = await search_jobs("", "", limit=limit, company_ids=[cid], include_details=include_details,
                                         smart_query=False, client=client)
            return {"kind": "company", "company": name, "company_id": cid, "jobs": jobs,
                    "notes": [] if cid else ["Could not resolve the company id from that page."]}
        spec = parse_search_url(url)
        jobs = await search_jobs(
            spec.keywords, spec.location, limit=limit, time_posted=spec.time_posted, easy_apply=spec.easy_apply,
            company_ids=spec.company_ids or None, geo_id=spec.geo_id, experience=spec.experience or None,
            job_types=spec.job_types or None, work_modes=spec.work_modes or None,
            criteria=Criteria(max_age_days=spec.max_age_days) if spec.max_age_days else None,
            include_details=include_details, client=client)
        pinned = await get_job(spec.current_job_id, client=client) if spec.current_job_id else None
        return {"kind": "search", "spec": spec, "jobs": jobs, "pinned_job": pinned, "notes": spec.notes}
    finally:
        if own:
            await client.aclose()
