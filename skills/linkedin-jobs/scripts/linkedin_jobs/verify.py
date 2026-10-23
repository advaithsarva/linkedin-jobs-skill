"""Truth layer: is this posting real, what does it pay, and where is the employer's own listing?

Everything here is heuristic and says so. The strongest signal is a cross-check against the employer's own ATS
board (Greenhouse / Lever / Ashby / Workday / SmartRecruiters), which is public JSON.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel

from . import ats
from .client import LinkedInClient
from .models import JobDetails

# ---------------------------------------------------------------- salary (any currency / period)
_CUR = r"(?:US\$|CA\$|A\$|R\$|\$|£|€|₹|¥|₩|CHF|AED|SEK|NOK|DKK|PLN|ZAR|SGD|USD|EUR|GBP|INR|CAD|AUD|JPY|BRL|MXN|RS\.?|Rs\.?)"
_NUM = r"\d{1,3}(?:[.,\s]\d{3})+|\d+(?:[.,]\d+)?"
_RANGE = re.compile(rf"({_CUR})\s?({_NUM})\s?([kKmM])?\s?(?:-|–|—|to)\s?(?:{_CUR})?\s?({_NUM})\s?([kKmM])?"
                    r"(?:\s?(LPA|lakhs?|per (?:year|annum|month|hour|week)|/\s?(?:yr|year|mo|month|hr|hour)|a year|annually|"
                    r"p\.a\.|pa))?", re.I)
_LPA = re.compile(r"(\d{1,2}(?:\.\d)?)\s?(?:-|–|to)\s?(\d{1,2}(?:\.\d)?)\s?(LPA|lakhs?)", re.I)
_SINGLE = re.compile(rf"(?:salary|compensation|pay|ctc|stipend)[^.\n]{{0,40}}?({_CUR}\s?{_NUM}\s?[kKmM]?)(?:\s?(per (?:year|annum|month|hour)|/\s?(?:yr|mo|hr)|a year|LPA))?", re.I)


def find_salary(text: str) -> str | None:
    """First pay range or figure mentioned in a posting, or None. Multi-currency, never invents numbers."""
    if not text:
        return None
    m = _LPA.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)} {m.group(3).upper()}"
    for m in _RANGE.finditer(text):
        lo = float(re.sub(r"[.,\s](?=\d{3})", "", m.group(2)).replace(",", ".") or 0)
        hi = float(re.sub(r"[.,\s](?=\d{3})", "", m.group(4)).replace(",", ".") or 0)
        if m.group(3):
            lo *= 1000 if m.group(3).lower() == "k" else 1_000_000
        if m.group(5):
            hi *= 1000 if m.group(5).lower() == "k" else 1_000_000
        if hi > lo > 0 and (hi >= 500 or m.group(6)):  # skip "$1-2 billion revenue" style noise
            return re.sub(r"\s+", " ", m.group(0)).strip()
    m = _SINGLE.search(text)
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


# ---------------------------------------------------------------- resolution to the employer's board
class Resolution(BaseModel):
    status: Literal["matched", "not_on_board", "no_public_board", "closed_on_board"]
    method: str
    confidence: float
    posting: JobDetails | None = None
    board: str | None = None
    board_open_roles: int | None = None
    notes: list[str] = []


def _tok(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", s.lower()) if len(t) > 1}


def _same_role(a: JobDetails, b: JobDetails) -> float:
    ta, tb = _tok(a.title), _tok(b.title)
    if not ta or not tb:
        return 0.0
    title = len(ta & tb) / len(ta | tb)
    la, lb = _tok(a.location), _tok(b.location)
    loc = 1.0 if not la or not lb or la & lb else 0.0
    return title * (0.5 + 0.5 * loc)


async def resolve_to_ats(job: JobDetails, *, client: LinkedInClient) -> Resolution:
    """Find the same job on the employer's own ATS board (exact via apply URL, else fuzzy via company boards)."""
    if job.apply_url:
        ref, posting = await ats.get_posting(job.apply_url, client=client)
        if ref and ref.queryable:
            if posting:
                return Resolution(status="matched", method="apply_url", confidence=0.97, posting=posting,
                                  board=ref.ats)
            return Resolution(status="closed_on_board", method="apply_url", confidence=0.9, board=ref.ats,
                              notes=[f"The apply link points at a {ref.ats} posting that no longer exists."])
    boards = await ats.find_boards(job.company, client=client)
    if not boards:
        return Resolution(status="no_public_board", method="company_name", confidence=0.0,
                          notes=["No public Greenhouse/Lever/Ashby board found for this company name."])
    best: tuple[float, JobDetails, ats.BoardHit] | None = None
    total = 0
    for b in boards:
        ref = ats.AtsRef(ats=b.ats, org=b.org, queryable=True)
        listing = await ats.list_board(ref, limit=500, full=False, client=client)
        total += len(listing)
        for p in listing:
            s = _same_role(job, p)
            if s > (best[0] if best else 0):
                best = (s, p, b)
    if best and best[0] >= 0.6:
        return Resolution(status="matched", method="fuzzy_title", confidence=round(min(0.9, best[0]), 2),
                          posting=best[1], board=best[2].ats, board_open_roles=total)
    return Resolution(status="not_on_board", method="fuzzy_title", confidence=0.7, board=boards[0].ats,
                      board_open_roles=total,
                      notes=[f"Company's own board lists {total} open roles; none match this title."])


# ---------------------------------------------------------------- ghost-job scoring
_EVERGREEN = re.compile(r"(talent (?:pool|community|network|pipeline)|future opportunities|continuous(?:ly)? hiring|"
                        r"always (?:looking|hiring)|general application|not (?:a )?specific (?:role|opening)|"
                        r"evergreen|expression of interest|register your interest)", re.I)


class Verdict(BaseModel):
    ghost_score: int
    label: Literal["verified_listing", "no_red_flags", "uncertain", "likely_ghost"]
    reasons: list[str]
    salary: str | None = None
    salary_source: str | None = None
    employer_listing: str | None = None
    resolution: Resolution | None = None
    caveat: str = "Heuristic. Strongest evidence is the employer-board cross-check; treat the rest as hints."


def score_ghost(job: JobDetails, res: Resolution | None, *, reposts: int = 0) -> Verdict:
    s = 25  # prior: most postings are real
    why: list[str] = []
    age = None
    if job.posted_date:
        try:
            age = (date.today() - date.fromisoformat(job.posted_date[:10])).days
        except ValueError:
            pass
    if age is not None:
        if age > 90:
            s += 30; why.append(f"open {age} days")
        elif age > 60:
            s += 20; why.append(f"open {age} days")
        elif age > 30:
            s += 10; why.append(f"open {age} days")
        elif age <= 7:
            s -= 8; why.append("posted this week")
    if res:
        if res.status == "matched":
            s -= 30; why.append(f"also listed on the employer's {res.board} board ({res.method})")
        elif res.status in ("closed_on_board", "not_on_board"):
            s += 40 if res.status == "closed_on_board" else 30
            why.append(res.notes[0] if res.notes else "not found on the employer's own board")
        if res.board_open_roles == 0:
            s += 15; why.append("employer board shows zero open roles")
    if _EVERGREEN.search(job.description):
        s += 15; why.append("evergreen/talent-pool wording")
    if 0 < len(job.description) < 400:
        s += 8; why.append("very thin description")
    if reposts >= 2:
        s += min(20, 8 * reposts); why.append(f"same role reposted {reposts + 1} times")
    s = max(0, min(100, s))
    if res and res.status == "matched":
        label = "verified_listing"  # positive evidence: the employer's own board lists it
    else:
        label = "no_red_flags" if s < 35 else "uncertain" if s < 60 else "likely_ghost"
        if label == "no_red_flags":
            why.append("not cross-checked against an employer board (none found), so treat as unverified")
    salary, src = job.salary, "linkedin posting" if job.salary else None
    if res and res.posting and res.posting.salary:
        salary, src = res.posting.salary, f"{res.board} employer posting"
    if not salary:
        salary = find_salary(job.description)
        src = "stated in description" if salary else None
    return Verdict(ghost_score=s, label=label, reasons=why, salary=salary, salary_source=src,
                   employer_listing=res.posting.url if res and res.posting else None, resolution=res)


async def verify_job(job: JobDetails, *, client: LinkedInClient, reposts: int = 0, deep: bool = True) -> Verdict:
    """deep=False skips the board cross-check (zero extra requests) and uses text/age signals only."""
    res = await resolve_to_ats(job, client=client) if deep else None
    return score_ghost(job, res, reposts=reposts)
