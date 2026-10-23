"""Client-side filtering. LinkedIn's guest API ignores most filters, so we enforce them ourselves."""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field

from .filters import ExperienceLevel, JobType, WorkMode
from .models import Job, JobDetails

_SENIORITY_LABELS = {
    "internship": ExperienceLevel.INTERNSHIP, "entry level": ExperienceLevel.ENTRY,
    "associate": ExperienceLevel.ASSOCIATE, "mid-senior level": ExperienceLevel.MID_SENIOR,
    "director": ExperienceLevel.DIRECTOR, "executive": ExperienceLevel.EXECUTIVE,
}
_TYPE_LABELS = {
    "full-time": JobType.FULL_TIME, "part-time": JobType.PART_TIME, "contract": JobType.CONTRACT,
    "temporary": JobType.TEMPORARY, "volunteer": JobType.VOLUNTEER, "internship": JobType.INTERNSHIP,
    "other": JobType.OTHER,
}
_T_INTERN = re.compile(r"\b(intern(ship)?s?|trainee|apprentice|co-?op|working student|werkstudent|praktikum|"
                       r"praktikant(in)?|stagiaire|stage|alternance|pasante|practicante|becario|estagi[aá]rio|"
                       r"est[aá]gio|stagista|tirocinio)\b", re.I)
_T_ENTRY = re.compile(r"\b(graduate|new grad|entry[- ]level|junior|jr\.?|fresher|campus|early career|"
                      r"engineer (i|1)|developer (i|1)|sde[- ]?1|associate)\b", re.I)
_T_SENIOR = re.compile(r"\b(senior|sr\.?|s[eê]nior|lead|staff|principal|architect|iii|iv|sde[- ]?[3-9]|"
                       r"engineer (iii|iv|3|4)|5\+? years|7\+? years|10\+? years)\b", re.I)
_T_DIRECTOR = re.compile(r"\b(manager|director|head of|vp|vice president|chief|cto|ceo|leiter(in)?|"
                         r"directeur|responsable|gerente|jefe)\b", re.I)
_REMOTE = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_NOT_REMOTE = re.compile(r"\b(not remote|no remote|non-remote|onsite only|on-site only)\b", re.I)


def infer_experience(title: str, details: JobDetails | None = None) -> ExperienceLevel | None:
    """Best-effort seniority. Prefers LinkedIn's own 'Seniority level' field, falls back to the title."""
    if details and details.seniority_level:
        lvl = _SENIORITY_LABELS.get(details.seniority_level.strip().lower())
        if lvl:
            # LinkedIn's field is often "Entry level" on senior-titled roles; trust explicit title words first.
            if _T_DIRECTOR.search(title):
                return ExperienceLevel.DIRECTOR
            if _T_SENIOR.search(title) and lvl in (ExperienceLevel.ENTRY, ExperienceLevel.ASSOCIATE):
                return ExperienceLevel.MID_SENIOR
            return lvl
    if _T_INTERN.search(title):
        return ExperienceLevel.INTERNSHIP
    if _T_DIRECTOR.search(title):
        return ExperienceLevel.DIRECTOR
    if _T_SENIOR.search(title):
        return ExperienceLevel.MID_SENIOR
    if _T_ENTRY.search(title):
        return ExperienceLevel.ENTRY
    return None


def infer_job_type(title: str, details: JobDetails | None = None) -> JobType | None:
    if details and details.employment_type:
        t = _TYPE_LABELS.get(details.employment_type.strip().lower())
        if t:
            return t
    return JobType.INTERNSHIP if _T_INTERN.search(title) else None


_REQ_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*(?:\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b[^.\n]{0,40}?"
    r"(?:experience|exp\b|background|working)", re.I)


def required_years(description: str) -> float | None:
    """Largest 'N+ years of experience' lower bound in a posting, or None if it names none."""
    nums = [int(m.group(1)) for m in _REQ_YEARS.finditer(description or "")]
    return float(max(nums)) if nums else None


def infer_work_mode(job: Job) -> WorkMode | None:
    """Heuristic from title/location/description: LinkedIn's guest pages don't expose the work-mode field."""
    blob = f"{job.title} {job.location}"
    desc = getattr(job, "description", "") or ""
    if _HYBRID.search(blob):
        return WorkMode.HYBRID
    if _REMOTE.search(blob):
        return WorkMode.REMOTE
    head = desc[:1500]
    if _NOT_REMOTE.search(head):
        return WorkMode.ONSITE
    if _HYBRID.search(head):
        return WorkMode.HYBRID
    if _REMOTE.search(head):
        return WorkMode.REMOTE
    return WorkMode.ONSITE if desc else None


class Criteria(BaseModel):
    """Everything the user cares about. All fields optional; empty Criteria matches every job."""

    title_include: list[str] = Field(default_factory=list, description="Regexes; job title must match at least one")
    title_exclude: list[str] = Field(default_factory=list, description="Regexes; reject if the title matches any")
    company_include: list[str] = Field(default_factory=list, description="Substrings; company must match one")
    company_exclude: list[str] = Field(default_factory=list)
    location_include: list[str] = Field(default_factory=list, description="Substrings, e.g. ['Bengaluru','Remote']")
    experience: list[ExperienceLevel] = Field(default_factory=list)
    job_types: list[JobType] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    require_terms: list[str] = Field(default_factory=list, description="All must appear in the description")
    avoid_terms: list[str] = Field(default_factory=list,
                                   description='Reject if any appears, e.g. "security clearance", "no sponsorship"')
    max_age_days: float | None = None
    max_required_years: float | None = Field(None, description="Reject postings whose description asks for more years")
    strict: bool = Field(False, description="Treat unknown seniority/type/work-mode as a non-match")

    @property
    def needs_details(self) -> bool:
        return bool(self.experience or self.job_types or self.work_modes or self.require_terms or self.avoid_terms)

    def cheap_reject(self, job: Job) -> str | None:
        """Checks that need only the search card. Returns a rejection reason or None."""
        if self.title_include and not any(re.search(p, job.title, re.I) for p in self.title_include):
            return "title"
        if any(re.search(p, job.title, re.I) for p in self.title_exclude):
            return "title_excluded"
        co = job.company.lower()
        if self.company_include and not any(c.lower() in co for c in self.company_include):
            return "company"
        if any(c.lower() in co for c in self.company_exclude):
            return "company_excluded"
        loc = job.location.lower()
        if self.location_include and not any(s.lower() in loc for s in self.location_include):
            return "location"
        if self.max_age_days is not None and job.posted_date:
            try:
                if (date.today() - date.fromisoformat(job.posted_date[:10])).days > self.max_age_days:
                    return "too_old"
            except ValueError:
                pass
        if self.experience:
            # Explicit title words ("Senior", "Intern") are strong evidence; reject early to save detail requests.
            lvl = infer_experience(job.title)
            if lvl in (ExperienceLevel.MID_SENIOR, ExperienceLevel.DIRECTOR, ExperienceLevel.INTERNSHIP) \
                    and lvl not in self.experience:
                return "experience"
        return None

    def full_reject(self, job: Job | JobDetails) -> str | None:
        details = job if isinstance(job, JobDetails) else None
        desc = (details.description if details else "").lower()
        if self.experience:
            lvl = infer_experience(job.title, details)
            if lvl is None:
                if self.strict:
                    return "experience_unknown"
            elif lvl not in self.experience:
                return "experience"
        if self.job_types:
            jt = infer_job_type(job.title, details)
            if jt is None:
                if self.strict:
                    return "job_type_unknown"
            elif jt not in self.job_types:
                return "job_type"
        if self.work_modes:
            wm = infer_work_mode(job)
            if wm is None:
                if self.strict:
                    return "work_mode_unknown"
            elif wm not in self.work_modes:
                return "work_mode"
        if details and self.max_required_years is not None:
            need = required_years(details.description)
            if need is not None and need > self.max_required_years:
                return "years_required"
        if details:
            if any(t.lower() not in desc for t in self.require_terms):
                return "missing_required_term"
            if any(t.lower() in desc for t in self.avoid_terms):
                return "avoid_term"
        return None
