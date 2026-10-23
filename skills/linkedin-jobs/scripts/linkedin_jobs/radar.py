"""Radar: watch saved searches and target-company boards; report only what is NEW, CLOSED, or SURGING."""
from __future__ import annotations

import re

from pydantic import BaseModel

from . import ats
from .client import LinkedInClient
from .criteria import Criteria
from .filters import ExperienceLevel, TimePosted, WorkMode
from .models import Job
from .scraper import search_jobs
from .state import State

SURGE_MIN_ROLES = 3  # new roles at one company within a week


class RadarReport(BaseModel):
    new_jobs: list[Job] = []
    closed: list[dict] = []
    surges: list[dict] = []
    watches_run: list[str] = []
    companies_scanned: int = 0
    baselined: list[str] = []
    errors: list[str] = []
    first_run: bool = False


def _criteria(spec: dict) -> Criteria:
    return Criteria(title_exclude=[rf"\b{re.escape(w)}\b" for w in spec.get("exclude", [])],
                    company_exclude=spec.get("exclude_company", []), avoid_terms=spec.get("avoid", []))


async def _run_watch(spec: dict, client: LinkedInClient) -> list[Job]:
    out: list[Job] = []
    for loc in spec.get("locations") or [""]:
        out += await search_jobs(
            spec["keywords"], loc, limit=spec.get("limit", 30),
            time_posted=TimePosted(spec["time"]) if spec.get("time") else TimePosted.PAST_24H,
            experience=[ExperienceLevel(e) for e in spec.get("level", [])] or None,
            work_modes=[WorkMode(w) for w in spec.get("work_modes", [])] or None,
            criteria=_criteria(spec), client=client)
    return out


async def run_radar(state: State, client: LinkedInClient) -> RadarReport:
    rep = RadarReport(first_run=not state.get("radar_runs"))
    # 1) saved searches
    for name, spec in state.watches().items():
        try:
            found = await _run_watch(spec, client)
        except Exception as e:  # keep the radar running if one watch fails
            rep.errors.append(f"watch {name}: {e}")
            continue
        rep.new_jobs += state.upsert_jobs(found)
        rep.watches_run.append(name)
    # 2) target-company boards (these publish before LinkedIn syndicates)
    for c in state.companies():
        if not c["ats"] or not c["org"]:
            continue
        ref = ats.AtsRef(ats=c["ats"], org=c["org"], host=c["host"], site=c["site"], queryable=True)
        try:
            board = await ats.list_board(ref, limit=500, client=client)
        except Exception as e:
            rep.errors.append(f"company {c['name']}: {e}")
            continue
        rep.companies_scanned += 1
        for j in board:
            j.company = c["name"]  # one display name across LinkedIn/ATS so dedupe + surges line up
        if not state.known_ids(c["ats"], c["name"]):  # first sight of this board: record, don't announce
            state.upsert_jobs(board, baseline=True)
            rep.baselined.append(f"{c['name']} ({len(board)} open roles recorded as baseline)")
            continue
        rep.new_jobs += state.upsert_jobs(board)
        gone = [i for i in state.known_ids(c["ats"], c["name"]) if i not in {j.id for j in board}]
        if gone:
            state.mark_closed(gone)
            rep.closed += [{"id": i, "title": (state.get_job(i).title if state.get_job(i) else i),
                            "company": c["name"]} for i in gone]
    state.set("radar_runs", (state.get("radar_runs") or 0) + 1)
    # 3) hiring surges (meaningless on the first run: everything looks new)
    for company, n in sorted(state.first_seen_counts(7).items(), key=lambda kv: -kv[1]):
        if n >= SURGE_MIN_ROLES and not rep.first_run:
            rep.surges.append({"company": company, "new_roles_7d": n})
    return rep
