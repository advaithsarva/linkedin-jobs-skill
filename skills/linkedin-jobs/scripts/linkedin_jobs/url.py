"""Understand LinkedIn URLs: replay a pasted search URL, or resolve a job-view URL.

Accepted:
  https://www.linkedin.com/jobs/search/?keywords=ml%20intern&location=India&f_E=1%2C2&f_TPR=r86400&f_WT=2
  https://www.linkedin.com/jobs/search-results/?keywords=...&currentJobId=123
  https://in.linkedin.com/jobs/view/some-title-at-company-4478984742
  https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4478984742
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from .filters import ExperienceLevel, JobType, TimePosted, WorkMode
from .parser import extract_job_id

_E = {"1": ExperienceLevel.INTERNSHIP, "2": ExperienceLevel.ENTRY, "3": ExperienceLevel.ASSOCIATE,
      "4": ExperienceLevel.MID_SENIOR, "5": ExperienceLevel.DIRECTOR, "6": ExperienceLevel.EXECUTIVE}
_JT = {"F": JobType.FULL_TIME, "P": JobType.PART_TIME, "C": JobType.CONTRACT, "T": JobType.TEMPORARY,
       "V": JobType.VOLUNTEER, "I": JobType.INTERNSHIP, "O": JobType.OTHER}
_WT = {"1": WorkMode.ONSITE, "2": WorkMode.REMOTE, "3": WorkMode.HYBRID}


class SearchSpec(BaseModel):
    keywords: str = ""
    location: str = ""
    geo_id: str | None = None
    time_posted: TimePosted | None = None
    max_age_days: float | None = None
    easy_apply: bool = False
    company_ids: list[str] = Field(default_factory=list)
    experience: list[ExperienceLevel] = Field(default_factory=list)
    job_types: list[JobType] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    current_job_id: str | None = Field(None, description="Job pinned in the URL (currentJobId)")
    notes: list[str] = Field(default_factory=list, description="Parameters that could not be honoured")


def _csv(v: str) -> list[str]:
    return [x for x in v.replace("%2C", ",").split(",") if x]


def is_linkedin_url(value: str) -> bool:
    return "linkedin." in (urlparse(value.strip()).hostname or "") and value.strip().lower().startswith("http")


def parse_search_url(url: str) -> SearchSpec:
    """Convert a LinkedIn jobs search URL into a SearchSpec. Never raises on unknown parameters."""
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    s = SearchSpec(keywords=q.get("keywords", ""), location=q.get("location", ""), geo_id=q.get("geoId"),
                   easy_apply=q.get("f_AL", "").lower() == "true", company_ids=_csv(q.get("f_C", "")),
                   current_job_id=q.get("currentJobId"))
    s.experience = [_E[x] for x in _csv(q.get("f_E", "")) if x in _E]
    s.job_types = [_JT[x] for x in _csv(q.get("f_JT", "")) if x in _JT]
    s.work_modes = [_WT[x] for x in _csv(q.get("f_WT", "")) if x in _WT]
    tpr = q.get("f_TPR", "")
    if tpr.startswith("r") and tpr[1:].isdigit():
        secs = int(tpr[1:])
        for limit, tp in ((3600, TimePosted.PAST_HOUR), (86400, TimePosted.PAST_24H),
                          (604800, TimePosted.PAST_WEEK), (2592000, TimePosted.PAST_MONTH)):
            if secs <= limit:
                s.time_posted = tp
                break
        s.max_age_days = secs / 86400
    for key, why in (("f_SB2", "salary filter is not available to logged-out search"),
                     ("f_JIYN", "'in your network' needs a login"), ("f_VJ", "verified-jobs filter ignored"),
                     ("distance", "radius ignored; use a more specific location")):
        if key in q:
            s.notes.append(f"{key}: {why}")
    if q.get("sortBy") == "DD":
        s.notes.append("sortBy=DD: results are returned in LinkedIn's guest order, then sorted newest first")
    return s


def classify(url: str) -> tuple[str, str | None]:
    """('job', id) for a single posting, ('search', None) for a search/collection URL."""
    path = urlparse(url).path
    m = re.match(r"^/(?:company|school)/([^/]+)", path)
    if m:
        return "company", m.group(1)
    if "/jobs/view/" in path:
        return "job", extract_job_id(url)
    q = parse_qs(urlparse(url).query)
    if "/jobs/search" in path or "/jobs/collections" in path or "keywords" in q:
        return "search", q.get("currentJobId", [None])[0]
    if "currentJobId" in q:
        return "job", q["currentJobId"][0]
    raise ValueError(f"Not a LinkedIn jobs URL I understand: {url}")
