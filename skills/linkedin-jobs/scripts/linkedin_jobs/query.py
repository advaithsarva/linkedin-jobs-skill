"""Boolean query composer.

LinkedIn's guest search ignores its experience/job-type URL filters but DOES honour Boolean operators inside
`keywords` (verified: AND / OR / NOT in capitals, "quoted phrases", (parentheses); `-word`, `+word`, `*`,
`title:` and NEAR are not supported). Encoding the level and exclusions as Boolean text is how this library
narrows results on LinkedIn's side, before spending any detail requests.
"""
from __future__ import annotations

import re

from .filters import ExperienceLevel

LEVEL_POSITIVE: dict[ExperienceLevel, list[str]] = {
    ExperienceLevel.INTERNSHIP: ["intern", "internship", "trainee", '"summer analyst"', "praktikum", "praktikant",
                                 "werkstudent", "stagiaire", "stage", "alternance", "pasante", "practicante",
                                 "becario", "estagiario", "estagio", "stagista", "tirocinio"],
    ExperienceLevel.ENTRY: ['"entry level"', "junior", "jr", "graduate", '"new grad"', "fresher", "associate",
                            '"early career"', '"engineer I"', '"developer I"', '"SDE 1"', '"SDE I"',
                            "berufseinsteiger", "absolvent", "debutant", "recien", "egresado"],
    ExperienceLevel.ASSOCIATE: ["associate", "junior", '"engineer II"'],
    ExperienceLevel.MID_SENIOR: ["senior", "sr", "lead", '"engineer III"', '"engineer II"', "staff"],
    ExperienceLevel.DIRECTOR: ["manager", "director", '"head of"'],
    ExperienceLevel.EXECUTIVE: ["vp", '"vice president"', "chief"],
}
SENIOR_WORDS = ["senior", "sr", "lead", "staff", "principal", "manager", "director", "head", "architect", "vp",
                "leiter", "leitung", "responsable", "directeur", "gerente", "jefe", "senor", "sênior"]
_OPS = re.compile(r"\b(AND|OR|NOT)\b|[()\"]")
MAX_LEN = 900


def _q(term: str) -> str:
    term = term.strip().replace('"', "")
    return f'"{term}"' if re.search(r"\s", term) else term


def _any(terms: list[str]) -> str:
    return "(" + " OR ".join(_q(t) if not t.startswith('"') else t for t in terms) + ")"


def has_boolean(text: str) -> bool:
    return bool(_OPS.search(text))


def compose(
    keywords: str = "",
    *,
    titles: list[str] | None = None,
    skills_all: list[str] | None = None,
    skills_any: list[str] | None = None,
    experience: list[ExperienceLevel] | None = None,
    level_mode: str = "auto",
    exclude: list[str] | None = None,
) -> str:
    """Build a LinkedIn Boolean keyword string.

    level_mode:
      "precise" - require level words in the title text (intern/junior/...). Few false positives, misses
                  unlabeled roles ("Software Engineer" that is really entry level).
      "broad"   - only exclude senior-sounding words; keeps unlabeled roles (client-side checks then verify).
      "auto"    - precise for internships, broad for entry/associate.
    """
    parts: list[str] = []
    if keywords.strip():
        parts.append(f"({keywords.strip()})" if has_boolean(keywords) else keywords.strip())
    if titles:
        parts.append(_any(titles))
    if skills_any:
        parts.append(_any(skills_any))
    for s in (skills_all or [])[:3]:  # more than ~3 ANDed skills usually yields zero results
        parts.append(_q(s))

    not_words: list[str] = [w for w in (exclude or []) if re.fullmatch(r"[\w .+#-]+", w)]
    levels = set(experience or [])
    if levels:
        low = levels <= {ExperienceLevel.INTERNSHIP, ExperienceLevel.ENTRY, ExperienceLevel.ASSOCIATE}
        mode = level_mode
        if mode == "auto":
            mode = "precise" if levels == {ExperienceLevel.INTERNSHIP} else "broad"
        if low and not (levels & {ExperienceLevel.MID_SENIOR, ExperienceLevel.DIRECTOR, ExperienceLevel.EXECUTIVE}):
            if mode == "precise":
                words: list[str] = []
                for lv in levels:
                    words += LEVEL_POSITIVE[lv]
                parts.append(_any(list(dict.fromkeys(words))))
            if ExperienceLevel.INTERNSHIP not in levels or len(levels) > 1:
                not_words += SENIOR_WORDS
            else:
                not_words += ["senior", "lead", "manager", "director", "principal"]
        else:
            words = [w for lv in levels for w in LEVEL_POSITIVE[lv]]
            parts.append(_any(list(dict.fromkeys(words))))
    query = " AND ".join(parts)
    if not_words:
        query += (" " if query else "") + "NOT " + _any(list(dict.fromkeys(not_words)))
    if has_boolean(keywords) and query == f"({keywords.strip()})":
        query = keywords.strip()
    return query if len(query) <= MAX_LEN else query[:MAX_LEN].rsplit(" OR ", 1)[0] + ")"
