"""Direct access to employers' applicant-tracking systems (ATS).

Most LinkedIn postings that apply off-site link to one of a handful of ATS vendors. Greenhouse, Lever, Ashby
and Workday expose their public job boards as unauthenticated JSON, which is fresher, more complete and far
cheaper to filter than LinkedIn's HTML. Detect the ATS from an apply URL, then query the employer's board.
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel

from .client import LinkedInClient
from .models import JobDetails
from .parser import html_to_text

# vendors we recognise but cannot query publicly (still useful: tells the agent how the application works)
OPAQUE = {
    "icims": r"\.icims\.com$", "taleo": r"\.taleo\.net$", "successfactors": r"successfactors\.(com|eu)$",
    "oracle": r"\.oraclecloud\.com$", "bamboohr": r"\.bamboohr\.com$", "jobvite": r"jobs\.jobvite\.com$",
    "teamtailor": r"\.teamtailor\.com$", "recruitee": r"\.recruitee\.com$", "workable": r"apply\.workable\.com$",
    "breezy": r"\.breezy\.hr$", "personio": r"\.jobs\.personio\.(de|com)$", "linkedin": r"(^|\.)linkedin\.com$",
}
APPLY_ADVICE = {
    "greenhouse": "Applies via a Greenhouse form: resume upload + custom questions; no account needed. Answer every "
                  "question; free-text answers are read by humans.",
    "lever": "Applies via a Lever form; resume parsed automatically, then read by a recruiter. No account needed.",
    "ashby": "Applies via an Ashby form; resume + short questions, often reviewed within days.",
    "workday": "Workday requires creating an account per employer; resume is parsed into fields, so use a "
               "plain single-column resume and re-check the parsed fields.",
    "smartrecruiters": "SmartRecruiters form, resume parsed automatically; no account needed.",
    "icims": "iCIMS needs an account and parses the resume into fields; check the parsed result before submitting.",
    "taleo": "Taleo (Oracle) needs an account and is strict about keyword matches; mirror the posting's wording.",
    "linkedin": "Easy Apply / LinkedIn-hosted. The recruiter sees your LinkedIn profile, so keep it consistent "
                "with the resume.",
}


class AtsRef(BaseModel):
    ats: str
    org: str | None = None  # board token / company slug / tenant
    job_id: str | None = None
    host: str | None = None  # needed for Workday
    site: str | None = None  # Workday career site
    queryable: bool = False
    advice: str = ""


def detect_ats(url: str) -> AtsRef | None:
    """Identify the ATS behind an apply/job URL, extracting org + job id where possible."""
    if not url:
        return None
    u = urlparse(url)
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    q = parse_qs(u.query)

    def ref(ats: str, **kw: object) -> AtsRef:
        return AtsRef(ats=ats, advice=APPLY_ADVICE.get(ats, ""), **kw)  # type: ignore[arg-type]

    if host.endswith("greenhouse.io"):
        org = parts[0] if parts and parts[0] not in ("embed",) else q.get("for", [None])[0]
        jid = parts[2] if len(parts) >= 3 and parts[1] == "jobs" else q.get("token", [None])[0]
        return ref("greenhouse", org=org, job_id=jid, queryable=bool(org))
    if "gh_jid" in q:  # company-hosted careers page embedding Greenhouse
        return ref("greenhouse", job_id=q["gh_jid"][0], queryable=False)
    if host.endswith("lever.co") and parts:
        return ref("lever", org=parts[0], job_id=parts[1] if len(parts) > 1 else None, host=host, queryable=True)
    if host == "jobs.ashbyhq.com" and parts:
        return ref("ashby", org=parts[0], job_id=parts[1] if len(parts) > 1 else None, queryable=True)
    if host.endswith("smartrecruiters.com") and parts:
        return ref("smartrecruiters", org=parts[0], job_id=parts[1].split("-")[0] if len(parts) > 1 else None,
                   queryable=True)
    m = re.match(r"^([\w-]+)\.wd\d+\.myworkdayjobs\.com$", host)
    if m:
        segs = [p for p in parts if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", p)]
        site = segs[0] if segs else None
        return ref("workday", org=m.group(1), host=host, site=site, job_id=u.path, queryable=bool(site))
    for name, pat in OPAQUE.items():
        if re.search(pat, host):
            return ref(name, org=host.split(".")[0] if name not in ("workable", "linkedin") else (parts[0] if parts else None))
    return None


def _iso(ts: object) -> str | None:
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
    return str(ts)[:10]


def _match(job: JobDetails, keywords: str | None) -> bool:
    if not keywords:
        return True
    blob = f"{job.title} {job.location} {job.description}".lower()
    # "a OR b" groups of AND-ed words; same mental model as LinkedIn's search box
    return any(all(w in blob for w in re.findall(r"[\w+#.]+", g.lower()) if w not in ("and", "not"))
               for g in re.split(r"\bOR\b", keywords))


async def _json(client: LinkedInClient, url: str, params: dict | None = None, **kw: object) -> object | None:
    """Fetch + parse JSON. Cached per client so verify/radar loops don't re-download a company board."""
    raw = await client.fetch(url, params, cache=True, **kw)  # type: ignore[arg-type]
    return json.loads(raw) if raw else None


# ---------------------------------------------------------------- per-vendor adapters

def _money(cents_or_units: float, cents: bool) -> str:
    v = cents_or_units / 100 if cents else cents_or_units
    return f"{v:,.0f}"


def _greenhouse_pay(j: dict) -> str | None:
    """Pay range from Greenhouse's pay_input_ranges (present when the employer enabled pay transparency)."""
    parts = []
    for r in j.get("pay_input_ranges") or []:
        if r.get("min_cents") is not None and r.get("max_cents") is not None:
            parts.append(f"{r.get('currency_type', '')} {_money(r['min_cents'], True)}-{_money(r['max_cents'], True)}"
                         f" ({(r.get('title') or 'range').strip(' :')})")
    return "; ".join(parts) or None


def _greenhouse_job(j: dict, org: str) -> JobDetails:
    desc_html = _html.unescape(j.get("content", ""))
    loc = (j.get("location") or {}).get("name", "")
    return JobDetails(
        id=f"greenhouse:{j['id']}", title=j.get("title", ""), company=j.get("company_name") or org, location=loc,
        url=j.get("absolute_url", ""),
        posted_date=_iso(j.get("first_published") or j.get("updated_at")), source="greenhouse",
        description=html_to_text(desc_html), description_html=desc_html, apply_url=j.get("absolute_url"),
        salary=_greenhouse_pay(j),
        job_function=", ".join(d["name"] for d in j.get("departments", []) if d.get("name")) or None)


def _lever_job(j: dict, org: str) -> JobDetails:
    cat = j.get("categories") or {}
    lists = "\n".join(f"{x.get('text', '')}\n{html_to_text(x.get('content', ''))}" for x in j.get("lists", []))
    desc = "\n\n".join(p for p in (j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")) if p)
    return JobDetails(
        id=f"lever:{j['id']}", title=j.get("text", ""), company=org, location=cat.get("location", ""),
        url=j.get("hostedUrl", ""), posted_date=_iso(j.get("createdAt")), source="lever", description=desc,
        employment_type=cat.get("commitment"), job_function=cat.get("team") or cat.get("department"),
        salary=(f"{sr.get('currency', '')} {sr['min']:,.0f}-{sr['max']:,.0f} per {sr.get('interval', 'year')}"
                if (sr := j.get("salaryRange")) and sr.get("min") and sr.get("max") else None),
        apply_url=j.get("applyUrl") or j.get("hostedUrl"))


def _ashby_job(j: dict, org: str) -> JobDetails:
    comp = (j.get("compensation") or {}).get("compensationTierSummary")
    return JobDetails(
        id=f"ashby:{j['id']}", title=j.get("title", ""), company=org, location=j.get("location", ""),
        url=j.get("jobUrl", ""), posted_date=_iso(j.get("publishedAt")), source="ashby",
        description=j.get("descriptionPlain", ""), description_html=j.get("descriptionHtml", ""),
        employment_type=j.get("employmentType"), job_function=j.get("department") or j.get("team"),
        salary=comp, apply_url=j.get("applyUrl") or j.get("jobUrl"))


async def _list_greenhouse(c: LinkedInClient, org: str, full: bool = True, **_: object) -> list[JobDetails]:
    d = await _json(c, f"https://boards-api.greenhouse.io/v1/boards/{org}/jobs", {"content": "true" if full else "false"})
    return [_greenhouse_job(j, org) for j in (d or {}).get("jobs", [])]


async def _list_lever(c: LinkedInClient, org: str, host: str | None = None, **_: object) -> list[JobDetails]:
    api = "api.eu.lever.co" if host and ".eu." in host else "api.lever.co"
    d = await _json(c, f"https://{api}/v0/postings/{org}", {"mode": "json"})
    return [_lever_job(j, org) for j in (d or [])]


async def _list_ashby(c: LinkedInClient, org: str, **_: object) -> list[JobDetails]:
    d = await _json(c, f"https://api.ashbyhq.com/posting-api/job-board/{org}", {"includeCompensation": "true"})
    return [_ashby_job(j, org) for j in (d or {}).get("jobs", []) if j.get("isListed", True)]


async def _list_smartrecruiters(c: LinkedInClient, org: str, **_: object) -> list[JobDetails]:
    d = await _json(c, f"https://api.smartrecruiters.com/v1/companies/{org}/postings", {"limit": "100"})
    out = []
    for j in (d or {}).get("content", []):
        loc = j.get("location") or {}
        out.append(JobDetails(
            id=f"smartrecruiters:{j['id']}", title=j.get("name", ""), company=org,
            location=", ".join(x for x in (loc.get("city"), loc.get("country", "").upper()) if x),
            url=f"https://jobs.smartrecruiters.com/{org}/{j['id']}", posted_date=_iso(j.get("releasedDate")),
            source="smartrecruiters", employment_type=(j.get("typeOfEmployment") or {}).get("label"),
            job_function=(j.get("function") or {}).get("label")))
    return out


async def _list_workday(c: LinkedInClient, org: str, host: str, site: str, keywords: str | None = None,
                        limit: int = 40, **_: object) -> list[JobDetails]:
    out: list[JobDetails] = []
    base = f"https://{host}/wday/cxs/{org}/{site}"
    search = re.sub(r"\b(AND|OR|NOT)\b|[()\"]", " ", keywords or "").strip()
    offset = 0
    while len(out) < limit:
        body = {"limit": 20, "offset": offset, "searchText": search, "appliedFacets": {}}
        d = await _json(c, f"{base}/jobs", method="POST", json_body=body)
        posts = (d or {}).get("jobPostings", [])
        if not posts:
            break
        for p in posts:
            out.append(JobDetails(
                id=f"workday:{org}:{p['externalPath']}", title=p.get("title", ""), company=org,
                location=p.get("locationsText", ""), url=f"https://{host}/{site}{p['externalPath']}",
                posted_date=None, posted_text=p.get("postedOn"), source="workday"))
        offset += 20
    return out[:limit]


_LISTERS = {"greenhouse": _list_greenhouse, "lever": _list_lever, "ashby": _list_ashby,
            "smartrecruiters": _list_smartrecruiters, "workday": _list_workday}


async def list_board(ref: AtsRef, *, keywords: str | None = None, limit: int = 50, full: bool = True,
                     client: LinkedInClient | None = None) -> list[JobDetails]:
    """All open jobs on an employer's board, optionally filtered by keywords ("a b OR c" syntax)."""
    if ref.ats not in _LISTERS or not ref.org:
        raise ValueError(f"{ref.ats} boards cannot be queried publicly; use the apply link instead.")
    own = client is None
    client = client or LinkedInClient()
    try:
        kw = dict(org=ref.org, host=ref.host, site=ref.site, keywords=keywords, limit=limit, full=full)
        jobs = await _LISTERS[ref.ats](client, **kw)  # type: ignore[arg-type]
        if ref.ats == "workday":  # Workday searched server-side; descriptions need a second call per job
            jobs = jobs[:limit]
            return jobs
        return [j for j in jobs if _match(j, keywords)][:limit]
    finally:
        if own:
            await client.aclose()


async def get_posting(url: str, *, client: LinkedInClient | None = None) -> tuple[AtsRef | None, JobDetails | None]:
    """Resolve an ATS job URL to (ats info, full posting). posting is None if closed/removed or unsupported."""
    ref = detect_ats(url)
    if not ref or not ref.queryable or ref.ats not in _LISTERS:
        return ref, None
    own = client is None
    client = client or LinkedInClient()
    try:
        if ref.ats == "workday":
            base = f"https://{ref.host}/wday/cxs/{ref.org}/{ref.site}"
            path = re.sub(rf"^/(?:[a-z]{{2}}-[A-Z]{{2}}/)?{re.escape(ref.site or '')}", "", ref.job_id or "")
            d = await _json(client, base + path)
            info = (d or {}).get("jobPostingInfo")
            if not info:
                return ref, None
            return ref, JobDetails(
                id=f"workday:{ref.org}:{path}", title=info.get("title", ""), company=ref.org or "",
                location=info.get("location", ""), url=info.get("externalUrl", url),
                posted_date=_iso(info.get("startDate")), source="workday", employment_type=info.get("timeType"),
                description=html_to_text(info.get("jobDescription", "")), apply_url=info.get("externalUrl", url))
        if ref.ats == "greenhouse" and ref.job_id and ref.job_id.isdigit():  # one call, and it carries pay ranges
            raw = await client.fetch(f"https://boards-api.greenhouse.io/v1/boards/{ref.org}/jobs/{ref.job_id}",
                                     {"pay_transparency": "true"})
            return ref, (_greenhouse_job(json.loads(raw), ref.org or "") if raw else None)
        jobs = await _LISTERS[ref.ats](client, org=ref.org, host=ref.host)  # type: ignore[arg-type]
        want = (ref.job_id or "").lower()
        return ref, next((j for j in jobs if j.id.split(":")[-1].lower() == want or want in j.url.lower()), None)
    finally:
        if own:
            await client.aclose()


class BoardHit(BaseModel):
    ats: str
    org: str
    open_jobs: int
    board_url: str


def _slugs(company: str) -> list[str]:
    base = re.sub(r"\b(inc|llc|ltd|limited|corp|corporation|pvt|private|technologies|technology|labs)\b\.?", "",
                  company.lower())
    words = re.findall(r"[a-z0-9]+", base)
    cands = ["".join(words), "-".join(words), words[0] if words else ""]
    return list(dict.fromkeys(c for c in cands if c))


async def find_boards(company: str, *, client: LinkedInClient | None = None) -> list[BoardHit]:
    """Guess and verify a company's public Greenhouse / Lever / Ashby boards from its name."""
    own = client is None
    client = client or LinkedInClient()
    try:
        memo: dict = client.__dict__.setdefault("_board_memo", {})
        if company.lower() in memo:
            return memo[company.lower()]

        async def probe(ats: str, slug: str) -> BoardHit | None:
            try:
                jobs = await _LISTERS[ats](client, org=slug, host=None, full=False)  # type: ignore[arg-type]
            except (httpx.HTTPError, ValueError):  # 404/400 for a wrong slug is normal; real bugs must surface
                return None
            if not jobs:
                return None
            url = {"greenhouse": f"https://boards.greenhouse.io/{slug}", "lever": f"https://jobs.lever.co/{slug}",
                   "ashby": f"https://jobs.ashbyhq.com/{slug}"}[ats]
            return BoardHit(ats=ats, org=slug, open_jobs=len(jobs), board_url=url)

        res = await asyncio.gather(*(probe(a, s) for s in _slugs(company) for a in ("greenhouse", "lever", "ashby")))
        found = [h for h in res if h]
        memo[company.lower()] = found
        return found
    finally:
        if own:
            await client.aclose()
