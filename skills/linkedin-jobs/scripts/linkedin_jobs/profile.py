"""Turn a resume or job description into a structured Profile and ready-to-run LinkedIn queries."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .config import load_config
from .filters import ExperienceLevel
from .skills import extract_skills, extract_terms

TITLES = [
    "machine learning engineer", "ml engineer", "ai engineer", "ai research engineer", "research scientist",
    "research engineer", "applied scientist", "data scientist", "data analyst", "data engineer",
    "analytics engineer", "business analyst", "software engineer", "software developer", "backend engineer",
    "backend developer", "frontend engineer", "frontend developer", "full stack developer",
    "full stack engineer", "fullstack developer", "mobile developer", "android developer", "ios developer",
    "devops engineer", "site reliability engineer", "cloud engineer", "platform engineer", "security engineer",
    "qa engineer", "test engineer", "embedded engineer", "firmware engineer", "solutions engineer",
    "product manager", "nlp engineer", "computer vision engineer", "mlops engineer", "quantum engineer",
    "quantum researcher", "quantitative researcher", "quantitative analyst", "prompt engineer",
    "llm engineer", "generative ai engineer", "python developer", "java developer", "data science intern",
]
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b(?:\s+of)?\s+(?:\w+\s+){0,3}?experience", re.I)
_RANGE = re.compile(r"((?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now|ongoing)", re.I)
_STUDENT = re.compile(r"\b(pursuing|currently enrolled|expected graduation|expected\s+\w*\s*20\d{2}|"
                      r"b\.?\s?tech|b\.?e\.?\b|bachelor|b\.?s\.?c|undergraduate|student|m\.?s\.? in|master)\b", re.I)
_PREFERRED = re.compile(r"(preferred|nice to have|good to have|bonus|plus|desirable|optional)", re.I)
_REQUIRED = re.compile(r"(required|requirements|must have|qualifications|what you.?ll need|you have|minimum)", re.I)


class Profile(BaseModel):
    kind: Literal["resume", "jd"]
    titles: list[str] = Field(default_factory=list, description="Job titles found, best first")
    skills: dict[str, int] = Field(default_factory=dict, description="skill -> mentions")
    required_skills: list[str] = Field(default_factory=list, description="JD only: skills in required sections")
    preferred_skills: list[str] = Field(default_factory=list, description="JD only: nice-to-have skills")
    years_experience: float | None = None
    seniority: ExperienceLevel | None = None
    education: str | None = Field(None, description="phd | masters | bachelors")
    suggested_queries: list[str] = Field(default_factory=list)


def _years(text: str) -> float | None:
    stated = [int(m.group(1)) for m in _YEARS.finditer(text)]
    this = date.today().year
    spans = []
    for m in _RANGE.finditer(text):
        a = int(m.group(1))
        b = this if m.group(2).lower() in ("present", "current", "now", "ongoing") else int(m.group(2))
        if 1990 <= a <= b <= this + 1:
            spans.append((a, b))
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    from_ranges = float(sum(b - a for a, b in merged)) if merged else None
    return float(max(stated)) if stated else from_ranges


def _seniority(years: float | None, text: str, kind: str) -> ExperienceLevel | None:
    if kind == "jd":
        if years is None:
            return None
        return ExperienceLevel.ENTRY if years <= 2 else ExperienceLevel.MID_SENIOR
    if _STUDENT.search(text) and (years is None or years <= 2):
        return ExperienceLevel.INTERNSHIP  # students with an internship or two are still intern/new-grad candidates
    if years is None or years < 1:
        return ExperienceLevel.ENTRY
    if years <= 2.5:
        return ExperienceLevel.ENTRY
    return ExperienceLevel.MID_SENIOR if years < 12 else ExperienceLevel.DIRECTOR


def _education(text: str) -> str | None:
    if re.search(r"\b(ph\.?\s?d|doctorate|doctor of philosophy)\b", text, re.I):
        return "phd"
    if re.search(r"\b(m\.?\s?sc?\.?|m\.?\s?tech|m\.?\s?eng|master'?s?|mba)\b", text, re.I):
        return "masters"
    if re.search(r"\b(b\.?\s?tech|b\.?\s?e\.?|b\.?\s?sc?\.?|bachelor'?s?|undergraduate)\b", text, re.I):
        return "bachelors"
    return None


_TITLE_NOUNS = (r"nurse|manager|engineer|developer|analyst|designer|accountant|teacher|specialist|coordinator|"
                r"consultant|technician|administrator|assistant|associate|officer|director|architect|scientist|"
                r"representative|recruiter|writer|editor|pharmacist|therapist|electrician|mechanic|driver|chef|cook|"
                r"operator|supervisor|auditor|lawyer|paralegal|researcher|physician|dentist|planner|buyer|clerk|"
                r"cashier|receptionist|marketer|strategist|producer|illustrator|translator|surveyor|inspector")
_GENERIC_TITLE = re.compile(rf"\b((?:[A-Z][\w&/-]+\s){{0,3}}(?:{_TITLE_NOUNS}))\b", re.I)


def _find_titles(text: str) -> list[str]:
    low = text.lower()
    hits = [(low.count(t), t) for t in TITLES if t in low]
    if not hits:  # outside the built-in tech list: look for "<words> <profession noun>" anywhere (any industry)
        generic: dict[str, int] = {}
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        name_tokens = set(re.findall(r"[\w'-]+", first.lower())) if len(first.split()) <= 4 else set()
        for m in _GENERIC_TITLE.finditer(text):
            t = " ".join(w for w in m.group(1).lower().split() if w not in name_tokens)
            if 1 <= len(t.split()) <= 4:
                generic[t] = generic.get(t, 0) + 1
        hits = [(n, t) for t, n in generic.items()]
    first = {t: low.find(t) for _, t in hits}
    return [t for _, t in sorted(hits, key=lambda h: (-h[0], first[h[1]]))]


def _split_jd_skills(text: str, extra: dict) -> tuple[list[str], list[str]]:
    """Skills mentioned under 'preferred/nice to have' headings vs the rest."""
    req, pref = [], []
    section = "req"
    for line in re.split(r"\n+", text):
        s = line.strip()
        if 0 < len(s) < 80 and not s.endswith("."):
            if _PREFERRED.search(s):
                section = "pref"
            elif _REQUIRED.search(s):
                section = "req"
        for sk in extract_skills(line, extra):
            # "preferred"/"plus" inline on a bullet also demotes it
            target = pref if (section == "pref" or re.search(r"\((?:a )?plus\)|nice to have|preferred", s, re.I)) else req
            if sk not in req and sk not in pref:
                target.append(sk)
    # a skill that appears in both required and preferred places stays required
    return req, [p for p in pref if p not in req]


def extract_profile(text: str, kind: Literal["resume", "jd"] = "resume") -> Profile:
    cfg = load_config()
    skills = extract_skills(text, cfg.extra_skills)
    if len(skills) < 3:  # not a tech document: fall back to profession-agnostic key terms
        skills = {**skills, **extract_terms(text, 12)}
    years = _years(text)
    titles = _find_titles(text)
    if not titles and kind == "resume":
        titles = titles_for_skills(list(skills))  # e.g. "RAG, LangChain" -> "ai engineer"; [] for non-tech terms
    p = Profile(kind=kind, titles=titles[:5], skills=skills, years_experience=years,
                seniority=_seniority(years, text, kind), education=_education(text) if kind == "resume" else None)
    if kind == "jd":
        p.required_skills, p.preferred_skills = _split_jd_skills(text, cfg.extra_skills)
    p.suggested_queries = suggest_queries(p)
    return p


# which role titles a skill points toward (used when the user gives only skills)
SKILL_ROLES: dict[str, list[str]] = {
    "Machine Learning": ["machine learning engineer", "data scientist"], "Deep Learning": ["machine learning engineer"],
    "PyTorch": ["machine learning engineer"], "TensorFlow": ["machine learning engineer"],
    "NLP": ["nlp engineer", "machine learning engineer"], "LLMs": ["llm engineer", "ai engineer"],
    "Generative AI": ["generative ai engineer", "ai engineer"], "RAG": ["ai engineer"],
    "LangChain": ["ai engineer"], "Computer Vision": ["computer vision engineer"],
    "Pandas": ["data analyst", "data scientist"], "Tableau": ["data analyst"], "Power BI": ["data analyst"],
    "Statistics": ["data analyst", "data scientist"], "Spark": ["data engineer"], "Airflow": ["data engineer"],
    "ETL": ["data engineer"], "dbt": ["analytics engineer"], "SQL": ["data analyst"],
    "React": ["frontend developer"], "Next.js": ["frontend developer"], "Vue": ["frontend developer"],
    "Angular": ["frontend developer"], "Node.js": ["backend developer", "full stack developer"],
    "Django": ["python developer", "backend developer"], "Flask": ["python developer"],
    "FastAPI": ["python developer", "backend developer"], "Spring Boot": ["java developer", "backend developer"],
    "Java": ["java developer", "software engineer"], "Python": ["python developer", "software engineer"],
    "Docker": ["devops engineer"], "Kubernetes": ["devops engineer", "platform engineer"],
    "Terraform": ["devops engineer", "cloud engineer"], "AWS": ["cloud engineer", "software engineer"],
    "Android": ["android developer"], "iOS": ["ios developer"], "Flutter": ["mobile developer"],
    "Cybersecurity": ["security engineer"], "Embedded": ["embedded engineer"],
    "Quantum Computing": ["quantum engineer", "quantum researcher"], "Testing": ["qa engineer"],
}


def titles_for_skills(skills: list[str], max_titles: int = 3) -> list[str]:
    votes: dict[str, int] = {}
    for sk in skills:
        for i, t in enumerate(SKILL_ROLES.get(sk, [])):
            votes[t] = votes.get(t, 0) + (2 - min(i, 1))
    return [t for t, _ in sorted(votes.items(), key=lambda kv: -kv[1])][:max_titles]


def profile_from_skills(skills: list[str], titles: list[str] | None = None,
                        seniority: ExperienceLevel | None = None) -> Profile:
    """Profile from a plain skill list; aliases ('pytorch', 'React.js') are normalised to canonical names."""
    canon: dict[str, int] = {}
    for s in skills:
        hit = extract_skills(s, load_config().extra_skills)
        for k in (hit or {s.strip(): 1}):
            canon[k] = canon.get(k, 0) + 1
    p = Profile(kind="resume", skills=canon, titles=titles or titles_for_skills(list(canon)), seniority=seniority)
    p.suggested_queries = suggest_queries(p)
    return p


def suggest_queries(p: Profile, max_queries: int = 6) -> list[str]:
    """Search strings: best titles alone, then title + top skill. Seniority words are added for juniors."""
    skills = list(p.required_skills or p.skills)
    titles = p.titles[:3]
    if not titles and skills:  # no recognisable title: search on the top skills themselves, in any profession
        return [" ".join(skills[:2]), skills[0]] if len(skills) > 1 else [skills[0]]
    out: list[str] = []
    for t in titles:
        out.append(t)
        # pair a title only with skills that belong to that role ("frontend developer react", not "... pytorch")
        related = [s for s in skills if t in SKILL_ROLES.get(s, [])] or \
                  ([s for s in skills[:2] if s not in SKILL_ROLES] if p.kind == "jd" else [])
        for s in related[:2]:
            if s.lower() not in t:
                out.append(f"{t} {s}")
    if len(out) < 4:
        out += [f"{s} developer" for s in skills[:3] if s in SKILL_ROLES]
    seen: dict[str, None] = {}
    for q in out:
        seen.setdefault(q.strip().lower(), None)
    return list(seen)[:max_queries]
