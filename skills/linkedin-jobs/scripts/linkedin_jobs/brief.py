"""The daily brief: what is new, what is real, what to apply to first, what to learn next."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from . import scraper
from .client import LinkedInClient
from .gap import GapItem, analyse
from .match import ScoredJob, rank
from .models import JobDetails
from .odds import Odds, evaluate, portfolio
from .profile import Profile
from .radar import RadarReport, run_radar
from .state import State
from .verify import Verdict, verify_job


class BriefItem(BaseModel):
    job: ScoredJob
    odds: Odds
    verdict: Verdict | None = None
    taste_notes: list[str] = []


class Brief(BaseModel):
    generated: str
    radar: RadarReport
    do_now: list[BriefItem] = []
    portfolio: dict[str, list[Odds]] = {}
    followups: list[dict] = []
    gaps: list[GapItem] = []
    notes: list[str] = []

    def to_markdown(self) -> str:
        r = self.radar
        out = [f"# Job brief · {self.generated[:10]}",
               f"{len(r.new_jobs)} new since last run · {r.companies_scanned} company boards · "
               f"{len(r.watches_run)} searches"]
        out += [f"_{n}_" for n in self.notes]
        if self.do_now:
            out += ["", "## Do now (best return on effort)"]
            for i, it in enumerate(self.do_now, 1):
                o, v, j = it.odds, it.verdict, it.job
                real = f"{v.label.replace('_', ' ')} (ghost {v.ghost_score})" if v else "unverified"
                pay = f" · pay: {v.salary} ({v.salary_source})" if v and v.salary else ""
                out += [f"{i}. **{j.title}** at {j.company} · {j.location}",
                        f"   fit {o.fit:.0f} · competition {o.competition}/100 · ~{o.effort_hours}h via {o.channel} · "
                        f"{real}{pay}",
                        f"   {j.url}" + (f"\n   employer listing: {v.employer_listing}" if v and v.employer_listing else "")]
                if j.missing_skills:
                    out.append(f"   gaps: {', '.join(j.missing_skills[:4])}")
                if it.taste_notes:
                    out.append(f"   you tend to: {', '.join(it.taste_notes)}")
        if any(self.portfolio.values()):
            out += ["", "## This week's application portfolio"]
            for tier, items in self.portfolio.items():
                if items:
                    out.append(f"- **{tier.replace('_', ' ')}** ({len(items)}): " +
                               "; ".join(f"{o.title} @ {o.company}" for o in items))
        if r.surges:
            out += ["", "## Hiring surges (3+ new roles in 7 days)"]
            out += [f"- {s['company']}: {s['new_roles_7d']} new roles. Reach out before the pile builds." for s in r.surges[:6]]
        if r.closed:
            out += ["", "## Closed since last run"] + [f"- {c['title']} at {c['company']}" for c in r.closed[:8]]
        if self.followups:
            out += ["", "## Follow-ups due"] + [f"- {f['title']} at {f['company']} (applied; follow-up {f['followup']}) {f['url']}"
                                                 for f in self.followups]
        if self.gaps:
            out += ["", "## Learn next (from live postings)"]
            for g in self.gaps[:4]:
                eff = (f"unlocks {g.unlocks} job{'s' if g.unlocks != 1 else ''}" if g.unlocks else "") + \
                      (f"{', ' if g.unlocks else ''}brings {g.closer} within one skill" if g.closer else "")
                out += [f"- **{g.skill}**: in {g.demand_pct:.0f}% of postings" + (f", {eff}" if eff else "") +
                        f". Proof task: {g.proof_task}"]
        if r.errors:
            out += ["", "## Warnings"] + [f"- {e}" for e in r.errors]
        return "\n".join(out)


async def build_brief(state: State, client: LinkedInClient, profile: Profile, *, verify_top: int = 6,
                      deep: bool = True, detail_cap: int = 25) -> Brief:
    radar = await run_radar(state, client)
    notes: list[str] = []
    if radar.first_run:
        notes.append("First run: everything is new, so hiring-surge detection starts next run.")
    acted = state.acted_ids()
    cands = [j for j in radar.new_jobs if j.id not in acted]
    if not cands:
        notes.append("Nothing new matched. Widen your watches (lj watch add-query) or add target companies.")

    # details for the most promising cards (cheap pre-rank by title overlap), then full ranking
    from .match import _title_score  # local import: private helper, same package

    cands.sort(key=lambda j: -_title_score(j.title, profile, profile.suggested_queries))
    detailed: list[JobDetails] = []
    for j in cands[:detail_cap]:
        if isinstance(j, JobDetails) and j.description:
            detailed.append(j)
    need = [j.id for j in cands[:detail_cap] if not (isinstance(j, JobDetails) and j.description)]
    detailed += await scraper.get_jobs(need, client=client) if need else []
    state.upsert_jobs(detailed)
    ranked = rank(detailed, profile)

    taste = state.taste_model()
    items: list[BriefItem] = []
    all_odds: list[Odds] = []
    import asyncio

    verdicts = await asyncio.gather(*(
        verify_job(sj, client=client, reposts=max(0, state.repost_count(sj.company, sj.title) - 1), deep=deep)
        for sj in ranked[:verify_top]))
    for k, sj in enumerate(ranked):
        t, why = state.taste_score(sj, taste)
        verdict = verdicts[k] if k < verify_top else None
        o = evaluate(sj, verdict, t)
        all_odds.append(o)
        if k < verify_top:
            items.append(BriefItem(job=sj, odds=o, verdict=verdict, taste_notes=why))
    items.sort(key=lambda it: -it.odds.roi)
    return Brief(generated=datetime.now(timezone.utc).isoformat(timespec="seconds"), radar=radar,
                 do_now=[it for it in items if not it.verdict or it.verdict.label != "likely_ghost"][:5],
                 portfolio=portfolio(all_odds), followups=state.followups_due(),
                 gaps=analyse(detailed, profile), notes=notes)
