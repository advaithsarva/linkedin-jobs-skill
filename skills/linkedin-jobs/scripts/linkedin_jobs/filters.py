"""Filter vocabulary and the query parameters LinkedIn's public guest API honours.

Verified empirically (Oct 2026): the logged-out endpoint honours ONLY keywords, location/geoId,
f_TPR (time posted), f_AL (easy apply) and f_C (company id). It silently ignores f_E (experience),
f_JT (job type), f_WT (work mode), f_JIYN, f_SB2, distance and sortBy. This library therefore applies
those filters client-side (see criteria.py) instead of pretending the server did.
"""
from __future__ import annotations

from enum import Enum


class TimePosted(str, Enum):
    PAST_HOUR = "past_hour"
    PAST_24H = "past_24h"
    PAST_WEEK = "past_week"
    PAST_MONTH = "past_month"


class ExperienceLevel(str, Enum):
    INTERNSHIP = "internship"
    ENTRY = "entry"
    ASSOCIATE = "associate"
    MID_SENIOR = "mid_senior"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


class JobType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    VOLUNTEER = "volunteer"
    INTERNSHIP = "internship"
    OTHER = "other"


class WorkMode(str, Enum):
    ONSITE = "onsite"
    REMOTE = "remote"
    HYBRID = "hybrid"


_TPR = {TimePosted.PAST_HOUR: "r3600", TimePosted.PAST_24H: "r86400",
        TimePosted.PAST_WEEK: "r604800", TimePosted.PAST_MONTH: "r2592000"}

TIME_POSTED_DAYS = {TimePosted.PAST_HOUR: 1 / 24, TimePosted.PAST_24H: 1, TimePosted.PAST_WEEK: 7,
                    TimePosted.PAST_MONTH: 30}


def build_params(
    keywords: str,
    location: str = "",
    *,
    time_posted: TimePosted | None = None,
    easy_apply: bool = False,
    company_ids: list[str] | None = None,
    geo_id: str | None = None,
    start: int = 0,
) -> dict[str, str]:
    p: dict[str, str] = {"keywords": keywords, "start": str(start)}
    if geo_id:
        p["geoId"] = geo_id
    elif location:
        p["location"] = location
    if time_posted:
        p["f_TPR"] = _TPR[time_posted]
    if easy_apply:
        p["f_AL"] = "true"
    if company_ids:
        p["f_C"] = ",".join(company_ids)
    return p


def options() -> dict[str, object]:
    return {
        "time_posted": [m.value for m in TimePosted],
        "experience_levels": [m.value for m in ExperienceLevel],
        "job_types": [m.value for m in JobType],
        "work_modes": [m.value for m in WorkMode],
        "note": "time_posted, easy_apply, company and location are applied by LinkedIn; experience_levels, "
                "job_types, work_modes, title/company/skill filters are applied client-side after fetching "
                "job details, so they cost extra requests but are accurate.",
    }
