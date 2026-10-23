"""HTML parsing for LinkedIn's public guest job endpoints. Pure functions, no network."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from .models import Job, JobDetails

_URN_RE = re.compile(r"jobPosting:(\d+)")
_VIEW_RE = re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})")
_CURRENT_RE = re.compile(r"currentJobId=(\d+)")


def canonical_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}"


def extract_job_id(value: str) -> str:
    """Accept a bare id, a /jobs/view/ URL (any country subdomain, with or without slug), or a currentJobId URL."""
    value = value.strip()
    if value.isdigit():
        return value
    m = _VIEW_RE.search(value) or _CURRENT_RE.search(value)
    if not m:
        raise ValueError(f"Could not find a LinkedIn job id in {value!r}")
    return m.group(1)


def _text(el: Tag | None) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else ""


def parse_search(html: str) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[Job] = []
    for card in soup.select("div.base-search-card, div.job-search-card"):
        m = _URN_RE.search(card.get("data-entity-urn", ""))
        job_id = m.group(1) if m else None
        if not job_id:
            link = card.select_one("a.base-card__full-link")
            try:
                job_id = extract_job_id(link.get("href", "")) if link else None
            except ValueError:
                job_id = None
        title = _text(card.select_one(".base-search-card__title"))
        if not job_id or not title:
            continue
        company_a = card.select_one(".base-search-card__subtitle a")
        company_url = company_a.get("href", "").split("?")[0] if company_a else None
        time_el = card.select_one("time")
        jobs.append(Job(
            id=job_id,
            title=title,
            company=_text(card.select_one(".base-search-card__subtitle")),
            company_url=company_url or None,
            location=_text(card.select_one(".job-search-card__location")),
            url=canonical_url(job_id),
            posted_date=time_el.get("datetime") if time_el else None,
            salary=_text(card.select_one(".job-search-card__salary-info")) or None,
            easy_apply_hint=bool(card.select_one(".job-search-card__easy-apply-label")),
            early_applicant="early applicant" in _text(card.select_one(".job-posting-benefits")).lower(),
        ))
    return jobs


def _html_to_text(markup: Tag) -> str:
    markup = BeautifulSoup(str(markup), "lxml").find()  # work on a copy
    for br in markup.find_all("br"):
        br.replace_with("\n")
    for li in markup.find_all("li"):
        li.insert_before("\n- ")
    for blk in markup.find_all(["p", "div", "ul", "ol", "h1", "h2", "h3", "h4"]):
        blk.append("\n")
    text = re.sub(r"[ \t]+\n", "\n", markup.get_text())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_detail(html: str, job_id: str) -> JobDetails:
    soup = BeautifulSoup(html, "lxml")
    markup = soup.select_one(".show-more-less-html__markup")
    description = _html_to_text(markup) if markup else ""
    description_html = markup.decode_contents().strip() if markup else ""

    crit: dict[str, str] = {}
    for li in soup.select("li.description__job-criteria-item"):
        key = _text(li.select_one(".description__job-criteria-subheader")).lower()
        crit[key] = _text(li.select_one(".description__job-criteria-text"))

    org = soup.select_one(".topcard__org-name-link")
    location = ""
    for f in soup.select(".topcard__flavor--bullet"):
        t = _text(f)
        if t and "applicant" not in t.lower():
            location = t
            break

    apply_url = None
    code = soup.select_one("code#applyUrl")
    if code:
        m = re.search(r'"(https?://[^"]+)"', str(code))
        if m:
            apply_url = m.group(1).replace("&amp;", "&")

    return JobDetails(
        id=job_id,
        title=_text(soup.select_one(".top-card-layout__title, .topcard__title")),
        company=_text(org) or _text(soup.select_one(".topcard__flavor")),
        company_url=(org.get("href", "").split("?")[0] if org else None) or None,
        location=location,
        url=canonical_url(job_id),
        posted_text=_text(soup.select_one(".posted-time-ago__text")) or None,
        applicants=_text(soup.select_one(".num-applicants__caption")) or None,
        seniority_level=crit.get("seniority level"),
        employment_type=crit.get("employment type"),
        job_function=crit.get("job function"),
        industries=crit.get("industries"),
        description=description,
        description_html=description_html,
        apply_url=apply_url,
    )


def html_to_text(html: str) -> str:
    """Plain text from an HTML fragment (ATS descriptions), keeping list bullets and paragraph breaks."""
    root = BeautifulSoup(f"<div>{html}</div>", "lxml").find("div")
    return _html_to_text(root) if root else ""
