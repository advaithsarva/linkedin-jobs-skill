"""Concrete, per-posting application plan. Deterministic: built only from the posting's own data."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal
from urllib.parse import quote, quote_plus, urlparse

from pydantic import BaseModel, Field

from .ats import AtsRef, detect_ats
from .criteria import required_years
from .match import ScoredJob, score_job
from .models import JobDetails
from .profile import Profile

_SPONSOR = re.compile(r"(no|not (?:able|offer\w*|provid\w*)|unable to|without|cannot|can't|do(?:es)? not)\W+(?:\w+\W+){0,4}?"
                      r"(visa )?sponsorship|must be (?:legally )?authori[sz]ed to work|(?:us|u\.s\.) citizen|"
                      r"permanent resident|work authori[sz]ation (?:is )?required|right to work|work permit|"
                      r"eligible to work in|must (?:currently )?(?:reside|be based|live) in|eu citizen|"
                      r"citizen(?:ship)? (?:of|required)", re.I)
_CLEARANCE = re.compile(r"(security clearance|ts/sci|secret clearance|public trust|clearance required)", re.I)
_NUM = re.compile(r"(\d[\d,]*)")


class ApplyPlan(BaseModel):
    verdict: Literal["apply_now", "apply_stretch", "low_odds", "check_eligibility_first"]
    headline: str
    score: float | None = None
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    urgency: Literal["today", "this_week", "no_rush"] = "no_rush"
    age_days: int | None = None
    applicants: str | None = None
    channel: Literal["easy_apply_or_linkedin", "external_ats", "unknown"] = "unknown"
    apply_url: str | None = None
    ats: AtsRef | None = None
    red_flags: list[str] = []
    resume_changes: list[str] = []
    outreach: dict[str, str] = Field(default_factory=dict, description="Ready-to-open search URLs")
    next_steps: list[str] = []

    def to_markdown(self) -> str:
        out = [f"**{self.headline}**"]
        if self.score is not None:
            out.append(f"Fit {self.score:.0f}/100 · matches: {', '.join(self.matched_skills[:8]) or 'none detected'}"
                       f" · gaps: {', '.join(self.missing_skills[:8]) or 'none detected'}")
        if self.red_flags:
            out += ["", "Red flags:", *[f"- {f}" for f in self.red_flags]]
        if self.resume_changes:
            out += ["", "Resume edits:", *[f"- {c}" for c in self.resume_changes]]
        out += ["", "Do this:", *[f"{i}. {s}" for i, s in enumerate(self.next_steps, 1)]]
        if self.outreach:
            out += ["", "Reach people:", *[f"- {k}: {v}" for k, v in self.outreach.items()]]
        return "\n".join(out)


def _age(job: JobDetails) -> int | None:
    if job.posted_date:
        try:
            return (date.today() - date.fromisoformat(job.posted_date[:10])).days
        except ValueError:
            pass
    t = (job.posted_text or "").lower()
    m = re.search(r"(\d+)\s*(hour|day|week|month)", t)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return {"hour": 0, "day": n, "week": n * 7, "month": n * 30}[unit]
    return None


def _applicant_count(text: str | None) -> int | None:
    m = _NUM.search(text or "")
    return int(m.group(1).replace(",", "")) if m else None


def _company_slug(url: str | None) -> str | None:
    if url and "/company/" in url:
        return urlparse(url).path.split("/company/")[1].split("/")[0] or None
    return None


def build_plan(job: JobDetails, profile: Profile | None = None) -> ApplyPlan:
    scored: ScoredJob | None = None
    if profile:
        scored = job if isinstance(job, ScoredJob) else score_job(job, profile)
    desc = job.description
    age = _age(job)
    n_app = _applicant_count(job.applicants)
    ats = detect_ats(job.apply_url or "") if job.apply_url else None

    flags: list[str] = []
    blocking = False
    if _SPONSOR.search(desc):
        flags.append("Work-authorization language found (no sponsorship / must be authorized / citizen). "
                     "Confirm you are eligible before spending time.")
        blocking = True
    if _CLEARANCE.search(desc):
        flags.append("Security clearance mentioned; usually requires citizenship of the posting country.")
        blocking = True
    need = required_years(desc)
    if need is not None and profile and profile.years_experience is not None and need > profile.years_experience + 1.5:
        flags.append(f"Asks for ~{need:.0f}+ years; your resume shows ~{profile.years_experience:.0f}. "
                     "Apply only if the rest is a strong match.")
    if age is not None and age > 30:
        flags.append(f"Posted {age} days ago; old postings are often filled, evergreen, or ghost jobs.")
    if n_app is not None and n_app >= 200:
        flags.append(f"{job.applicants}: heavy competition, so a referral or direct recruiter note matters more here.")

    urgency = "no_rush"
    if age is not None and age <= 2 or (n_app is not None and n_app < 25) or job.early_applicant:
        urgency = "today"
    elif age is not None and age <= 7:
        urgency = "this_week"

    channel = "unknown"
    if job.apply_url:
        channel = "external_ats"
    elif job.easy_apply_hint or "linkedin.com" in (job.url or ""):
        channel = "easy_apply_or_linkedin"

    score = scored.score if scored else None
    if blocking:
        verdict = "check_eligibility_first"
    elif score is None or score >= 65:
        verdict = "apply_now"
    elif score >= 45:
        verdict = "apply_stretch"
    else:
        verdict = "low_odds"

    matched = scored.matched_skills if scored else []
    missing = scored.missing_skills if scored else []
    changes: list[str] = []
    if matched:
        changes.append(f"Put these matched skills in the top third of your resume, in the posting's wording: "
                       f"{', '.join(matched[:8])}.")
    if missing:
        changes.append(f"Required but not on your resume: {', '.join(missing[:6])}. Add each ONLY where you truly "
                       "have evidence (project, coursework, tool used); a one-line project beats a skills-list entry.")
    changes.append(f'Mirror the title: use "{job.title}" language in your summary line.')

    company = job.company
    role_words = " ".join(re.sub(r"[^\w+#. -]", " ", job.title.split("|")[0].split(":")[0]).split()[:4])
    slug = _company_slug(job.company_url)
    outreach = {
        "recruiters_at_company": "https://www.linkedin.com/search/results/people/?keywords="
                                 + quote_plus(f"{company} recruiter"),
        "team_members_in_role": "https://www.linkedin.com/search/results/people/?keywords="
                                + quote_plus(f"{company} {role_words}"),
        "hiring_posts": "https://www.linkedin.com/search/results/content/?keywords="
                        + quote_plus(f'hiring "{company}" {role_words}'),
        "google_xray_recruiters": "https://www.google.com/search?q="
                                  + quote(f'site:linkedin.com/in "{company}" ("recruiter" OR "talent acquisition" '
                                          f'OR "campus recruiter")'),
    }
    if slug:
        outreach["company_people"] = f"https://www.linkedin.com/company/{slug}/people/?keywords=recruiter"
    if not ats or not ats.queryable:
        outreach["employer_careers_page"] = "https://www.google.com/search?q=" + quote(f'"{company}" careers {job.title}')

    steps: list[str] = []
    if blocking:
        steps.append("Verify work-authorization/clearance requirements first (see red flags); skip if you can't meet them.")
    if channel == "external_ats":
        steps.append(f"Apply on the employer's own form ({ats.ats if ats else 'external site'}): {job.apply_url}. "
                     "Direct applications reach the ATS, not just LinkedIn.")
        if ats and ats.advice:
            steps.append(ats.advice)
    elif channel == "easy_apply_or_linkedin":
        steps.append(f"Apply via LinkedIn: {job.url}. Keep your profile headline and skills consistent with the resume.")
    if urgency == "today":
        steps.append("Apply within 24 hours. Early applications are reviewed first, before the pile builds.")
    elif urgency == "this_week":
        steps.append("Apply this week; the posting is recent enough that review has likely not finished.")
    steps.append("Tailor the resume with the edits above before submitting; name the file "
                 "Firstname_Lastname_Role.pdf.")
    steps.append("After applying, message one recruiter or team member (links below) with 3 lines: who you are, "
                 "the one project that matches the top required skill, and that you applied. Do not attach the resume.")
    if age is not None and age >= 7:
        steps.append(f"Re-check the posting is still open before applying: lj open {job.url}")

    headline = {
        "apply_now": f"Apply: {job.title} at {company}",
        "apply_stretch": f"Stretch but worth it: {job.title} at {company} (close the gaps below first)",
        "low_odds": f"Low odds: {job.title} at {company}; prioritise better-fitting roles",
        "check_eligibility_first": f"Check eligibility first: {job.title} at {company}",
    }[verdict]
    return ApplyPlan(verdict=verdict, headline=headline, score=score, matched_skills=matched, missing_skills=missing,
                     urgency=urgency, age_days=age, applicants=job.applicants, channel=channel,
                     apply_url=job.apply_url or job.url, ats=ats, red_flags=flags, resume_changes=changes,
                     outreach=outreach, next_steps=steps)
