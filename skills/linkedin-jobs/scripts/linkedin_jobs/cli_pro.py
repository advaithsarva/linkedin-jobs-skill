"""Commands for the 'chief of staff' layer: memory, watches, brief, verification, gap analysis."""
from __future__ import annotations

from typing import Optional

import typer

from . import ats as atsmod
from . import discover, scraper
from .brief import build_brief
from .cli import AV, EXP, FMT, LOC, WM, XC, XT, _json, _read_text, _run, app
from .client import LinkedInClient
from .filters import ExperienceLevel, TimePosted, WorkMode
from .gap import analyse
from .profile import Profile, extract_profile, profile_from_skills
from .state import ACTIONS, State
from .url import is_linkedin_url
from .verify import verify_job

watch_app = typer.Typer(help="Saved searches and target companies the radar monitors.", no_args_is_help=True)
app.add_typer(watch_app, name="watch")


def _profile(state: State) -> Profile:
    raw = state.get("profile")
    if not raw:
        typer.echo("No profile yet. Run: lj init <resume file>   (or: lj init --skills python sql ...)", err=True)
        raise typer.Exit(1)
    return Profile.model_validate(raw)


@app.command()
def init(
    resume_: Optional[str] = typer.Argument(None, metavar="[RESUME]", help="Resume file/text (.txt .md .pdf .docx)"),
    skills_: Optional[list[str]] = typer.Option(None, "--skills", "-s", help="Or give skills directly"),
    title: Optional[list[str]] = typer.Option(None, "--title", help="Target titles (overrides inferred)"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    work_mode: Optional[list[WorkMode]] = WM,
    exclude: Optional[list[str]] = XT,
) -> None:
    """Set up your profile and default watches. Everything stays in ~/.linkedin-jobs/ on this machine."""
    if resume_:
        prof = extract_profile(_read_text(resume_), "resume")
        if title:
            prof = prof.model_copy(update={"titles": title})
            from .profile import suggest_queries

            prof.suggested_queries = suggest_queries(prof)
    elif skills_:
        prof = profile_from_skills(skills_, title)
    else:
        typer.echo("Give a resume file or --skills.", err=True)
        raise typer.Exit(1)
    st = State()
    st.set("profile", prof.model_dump(mode="json"))
    st.set("prefs", {"locations": location or [], "level": [e.value for e in level or []],
                     "work_modes": [w.value for w in work_mode or []], "exclude": exclude or []})
    lvl = level or ([prof.seniority] if prof.seniority else [])
    for i, q in enumerate(prof.suggested_queries[:4], 1):
        st.add_watch(f"auto-{i}", {"keywords": q, "locations": location or [], "level": [e.value for e in lvl],
                                   "work_modes": [w.value for w in work_mode or []], "exclude": exclude or [],
                                   "time": "past_24h"})
    typer.echo(_json({"profile": prof, "watches": list(st.watches())}))


@watch_app.command("add-query")
def watch_add_query(
    name: str, keywords: str = typer.Argument(..., help="Boolean ok"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    work_mode: Optional[list[WorkMode]] = WM, time: TimePosted = typer.Option(TimePosted.PAST_24H, "--time", "-t"),
    exclude: Optional[list[str]] = XT, exclude_company: Optional[list[str]] = XC, avoid: Optional[list[str]] = AV,
) -> None:
    """Add a saved search. The radar reports only postings you haven't seen before."""
    State().add_watch(name, {"keywords": keywords, "locations": location or [], "level": [e.value for e in level or []],
                             "work_modes": [w.value for w in work_mode or []], "exclude": exclude or [],
                             "exclude_company": exclude_company or [], "avoid": avoid or [], "time": time.value})
    typer.echo(f"Saved watch '{name}'.")


@watch_app.command("add-company")
def watch_add_company(name_or_url: str = typer.Argument(..., help="Company name or linkedin.com/company URL")) -> None:
    """Watch a company's own job board. Boards publish before LinkedIn syndicates, so you see roles on day 0."""

    async def go() -> dict:
        async with LinkedInClient() as c:
            if is_linkedin_url(name_or_url):
                cid, name = await scraper.resolve_company(name_or_url, client=c)
            else:
                hits = await scraper.find_companies(name_or_url, client=c)
                cid, name = (hits[0]["id"], hits[0]["name"]) if hits else (None, name_or_url)
            boards = await atsmod.find_boards(name, client=c)
            return {"name": name, "linkedin_id": cid, "boards": boards}

    r = _run(go())
    st = State()
    if r["boards"]:
        b = r["boards"][0]
        st.add_company(r["name"], linkedin_id=r["linkedin_id"], ats=b.ats, org=b.org)
        typer.echo(f"Watching {r['name']} via {b.ats}:{b.org} ({b.open_jobs} open roles).")
    else:
        st.add_company(r["name"], linkedin_id=r["linkedin_id"])
        typer.echo(f"Saved {r['name']} (LinkedIn id {r['linkedin_id']}). No public ATS board found, so the radar "
                   "will use LinkedIn only for it.")


@watch_app.command("list")
def watch_list() -> None:
    st = State()
    typer.echo(_json({"searches": st.watches(), "companies": st.companies()}))


@watch_app.command("remove")
def watch_remove(name: str) -> None:
    State().remove_watch(name)
    typer.echo(f"Removed '{name}'.")


@app.command()
def brief(
    verify: int = typer.Option(6, "--verify", help="How many top jobs get the full truth check"),
    no_deep: bool = typer.Option(False, "--no-deep", help="Skip employer-board cross-check (faster)"),
    fmt: str = FMT,
) -> None:
    """Your daily brief: new real jobs worth your time, ranked by return on effort, plus follow-ups and what to learn."""
    st = State()
    prof = _profile(st)

    async def go():
        async with LinkedInClient() as c:
            return await build_brief(st, c, prof, verify_top=verify, deep=not no_deep)

    b = _run(go())
    typer.echo(_json(b) if fmt == "json" else b.to_markdown())


@app.command()
def mark(
    job_: str = typer.Argument(..., metavar="JOB", help="Job id or URL"),
    action: str = typer.Argument(..., help="|".join(ACTIONS)),
    reason: str = typer.Option("", "--reason", "-r", help='Why. Teaches the taste model, e.g. "onsite only"'),
    followup_days: Optional[int] = typer.Option(None, "--followup-days", help="Remind me after N days (applied)"),
) -> None:
    """Record what you did with a job. The skill learns from it and will remind you to follow up."""
    st = State()

    async def go():
        from .parser import extract_job_id

        jid = extract_job_id(job_)
        if not st.get_job(jid):
            d = await scraper.get_job(jid)
            if d:
                st.upsert_jobs([d])
        return jid

    jid = _run(go())
    st.mark(jid, action, reason, followup_days if followup_days else (7 if action == "applied" else None))
    typer.echo(f"Recorded {action} for {jid}.")


@app.command()
def history(limit: int = typer.Option(30, "--limit", "-n")) -> None:
    """What you've done, newest first, plus the preferences the skill has learned."""
    st = State()
    taste = {k: round(v, 2) for k, v in sorted(st.taste_model().items(), key=lambda kv: kv[1]) if abs(v) >= 0.2}
    typer.echo(_json({"actions": st.history(limit), "learned_taste": taste}))


@app.command()
def verify(
    ids: list[str] = typer.Argument(..., help="Job ids or URLs"),
    no_deep: bool = typer.Option(False, "--no-deep", help="Skip employer-board cross-check"),
) -> None:
    """Truth check: ghost-job score, employer's own listing, and pay if it is published anywhere."""

    async def go():
        out = []
        async with LinkedInClient() as c:
            for d in await scraper.get_jobs(ids, client=c):
                st = State()
                v = await verify_job(d, client=c, reposts=max(0, st.repost_count(d.company, d.title) - 1),
                                     deep=not no_deep)
                out.append({"job": d.model_dump(mode="json", exclude={"description_html", "description"}),
                            "verdict": v.model_dump(mode="json")})
        return out

    typer.echo(_json(_run(go())))


@app.command()
def gap(
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    sample: int = typer.Option(40, "--sample", help="How many live postings to analyse"),
) -> None:
    """Which missing skill would unlock the most jobs for you, and a proof project for each."""
    st = State()
    prof = _profile(st)
    d = _run(discover.find_jobs(prof, locations=location, experience=level, limit=sample, with_plans=0))
    items = analyse([r.job for r in d.results], prof)
    typer.echo(_json({"analysed_postings": len(d.results), "gaps": items}))


@app.command()
def doctor() -> None:
    """Check connectivity to LinkedIn and the public ATS APIs, and show where local state lives."""
    from .state import home

    async def go() -> dict:
        res: dict = {"state_dir": str(home())}
        async with LinkedInClient(min_delay=0.2) as c:
            try:
                html = await c.get("jobs/api/seeMoreJobPostings/search", {"keywords": "engineer", "start": "0"})
                from .parser import parse_search

                res["linkedin_search"] = f"ok ({len(parse_search(html or ''))} cards parsed)"
            except Exception as e:
                res["linkedin_search"] = f"FAILED: {e}"
            for name, url in (("greenhouse", "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs"),
                              ("lever", "https://api.lever.co/v0/postings/palantir?limit=1"),
                              ("ashby", "https://api.ashbyhq.com/posting-api/job-board/openai")):
                try:
                    res[name] = "ok" if await c.fetch(url) else "empty"
                except Exception as e:
                    res[name] = f"FAILED: {e}"
        return res

    typer.echo(_json(_run(go())))
