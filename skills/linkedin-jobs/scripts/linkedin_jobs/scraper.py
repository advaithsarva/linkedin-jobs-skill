"""High-level API: search (with client-side filtering), details, company lookup."""
from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from .client import LinkedInClient, RateLimitedError
from .config import load_config
from .criteria import Criteria
from .filters import ExperienceLevel, JobType, TimePosted, WorkMode, build_params
from .models import Job, JobDetails
from .parser import extract_job_id, parse_detail, parse_search
from .query import compose, has_boolean

MAX_START = 1000  # LinkedIn's guest search returns nothing past ~1000


class SearchStats(BaseModel):
    pages: int = 0
    scanned: int = 0
    detail_fetches: int = 0
    rejected: dict[str, int] = {}


async def search_jobs(
    keywords: str,
    location: str = "",
    *,
    limit: int = 25,
    time_posted: TimePosted | None = None,
    easy_apply: bool = False,
    company_ids: list[str] | None = None,
    geo_id: str | None = None,
    experience: list[ExperienceLevel] | None = None,
    job_types: list[JobType] | None = None,
    work_modes: list[WorkMode] | None = None,
    criteria: Criteria | None = None,
    include_details: bool = False,
    smart_query: bool = True,
    level_mode: str = "auto",
    max_scan: int | None = None,
    client: LinkedInClient | None = None,
    stats: SearchStats | None = None,
) -> list[Job] | list[JobDetails]:
    """Search public LinkedIn jobs.

    Pages until `limit` jobs pass every filter or `max_scan` cards were inspected. Filters LinkedIn ignores
    (experience, job type, work mode, title/company/skill rules) are applied here, fetching job details only
    for cards that survive the cheap title/company/location checks.
    """
    cfg = load_config()
    c = (criteria or Criteria()).model_copy(deep=True)
    c.experience = list({*c.experience, *(experience or [])})
    c.job_types = list({*c.job_types, *(job_types or [])})
    c.work_modes = list({*c.work_modes, *(work_modes or [])})
    c.company_exclude = [*c.company_exclude, *cfg.blocked_companies]
    c.title_exclude = [*c.title_exclude, *cfg.blocked_title_patterns]
    if c.max_required_years is None and c.experience and set(c.experience) <= {
            ExperienceLevel.INTERNSHIP, ExperienceLevel.ENTRY}:
        c.max_required_years = 2  # a "junior" posting asking for 5+ years is mislabeled
    if smart_query and not has_boolean(keywords):
        keywords = compose(keywords, experience=c.experience, level_mode=level_mode, exclude=c.title_exclude)
    location = location or cfg.default_location
    if location.strip().lower() in ("remote", "anywhere", "worldwide"):
        location = ""  # LinkedIn's location box has no true "remote"; enforce it from the posting instead
        c.work_modes = list({*c.work_modes, WorkMode.REMOTE})
    max_scan = max_scan or cfg.max_scan
    stats = stats if stats is not None else SearchStats()
    want_details = include_details or c.needs_details

    own = client is None
    client = client or LinkedInClient()
    try:
        out: list[Job] = []
        seen: set[str] = set()
        start = empty = 0
        while len(out) < limit and start < MAX_START and stats.scanned < max_scan and empty < 2:
            params = build_params(keywords, location, time_posted=time_posted, easy_apply=easy_apply,
                                  company_ids=company_ids, geo_id=geo_id, start=start)
            page = parse_search(await client.get("jobs/api/seeMoreJobPostings/search", params) or "")
            stats.pages += 1
            fresh = [j for j in page if j.id not in seen]
            seen.update(j.id for j in fresh)
            empty = 0 if fresh else empty + 1
            start += max(len(page), 10)
            stats.scanned += len(fresh)

            survivors = []
            for j in fresh:
                why = c.cheap_reject(j)
                if why:
                    stats.rejected[why] = stats.rejected.get(why, 0) + 1
                else:
                    survivors.append(j)
            if want_details and survivors:
                room = limit - len(out)
                # fetch in small waves so we don't over-fetch once the limit is reachable
                for i in range(0, len(survivors), max(room, 3)):
                    wave = survivors[i:i + max(room, 3)]
                    detailed = await _enrich(wave, client)
                    stats.detail_fetches += len(wave)
                    for d in detailed:
                        why = c.full_reject(d)
                        if why:
                            stats.rejected[why] = stats.rejected.get(why, 0) + 1
                        else:
                            out.append(d)
                    if len(out) >= limit:
                        break
            else:
                out.extend(survivors)
        return out[:limit]
    finally:
        if own:
            await client.aclose()


async def get_job(job: str, *, client: LinkedInClient | None = None) -> JobDetails | None:
    """Full details for one job id or URL. Returns None if the posting no longer exists."""
    own = client is None
    client = client or LinkedInClient()
    try:
        job_id = extract_job_id(job)
        html = await client.get(f"jobs/api/jobPosting/{job_id}", cache=True)
        return parse_detail(html, job_id) if html else None
    finally:
        if own:
            await client.aclose()


async def get_jobs(jobs: Iterable[str], *, client: LinkedInClient | None = None) -> list[JobDetails]:
    own = client is None
    client = client or LinkedInClient()
    try:
        results = await asyncio.gather(*(get_job(j, client=client) for j in jobs))
        return [r for r in results if r]
    finally:
        if own:
            await client.aclose()


async def find_companies(name: str, *, client: LinkedInClient | None = None) -> list[dict[str, str]]:
    """Resolve a company name to LinkedIn company ids (usable as company_ids to restrict a search)."""
    own = client is None
    client = client or LinkedInClient()
    try:
        raw = await client.get("api/typeaheadHits", {"typeaheadType": "COMPANY", "query": name})
        hits = json.loads(raw) if raw else []
        return [{"id": h["id"], "name": h.get("displayName", "")} for h in hits if h.get("id")]
    finally:
        if own:
            await client.aclose()


async def resolve_company(slug_or_url: str, *, client: LinkedInClient | None = None) -> tuple[str | None, str]:
    """LinkedIn company id (for company_ids=) and display name from a /company/<slug> URL or slug."""
    slug = slug_or_url.strip()
    if slug.startswith("http"):
        m = re.match(r"^/(?:company|school)/([^/]+)", urlparse(slug).path)
        slug = m.group(1) if m else slug
    own = client is None
    client = client or LinkedInClient()
    try:
        try:
            page = await client.fetch(f"https://www.linkedin.com/company/{slug}", cache=True)
        except (RateLimitedError, httpx.HTTPError):
            page = None  # the company page is the most aggressively throttled; typeahead below is the fallback
        if page:
            m = re.search(r"f_C=(\d+)", page)
            t = re.search(r"<title>([^<|]+)", page)
            if m:
                return m.group(1), (t.group(1).strip() if t else slug)
        hits = await find_companies(slug.replace("-", " "), client=client)
        return (hits[0]["id"], hits[0]["name"]) if hits else (None, slug)
    finally:
        if own:
            await client.aclose()


async def _enrich(jobs: list[Job], client: LinkedInClient) -> list[JobDetails]:
    details = await asyncio.gather(*(get_job(j.id, client=client) for j in jobs))
    out: list[JobDetails] = []
    for card, d in zip(jobs, details):
        if d is None:
            continue  # posting removed between search and fetch; don't return a dead job
        merged = card.model_dump() | {k: v for k, v in d.model_dump().items() if v not in (None, "")}
        out.append(JobDetails(**merged))
    return out
