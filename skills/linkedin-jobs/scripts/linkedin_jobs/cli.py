"""`lj` command line: the interface the Claude Code skill (or any agent/human) drives via the shell.

Results go to stdout; progress and notes go to stderr. Default format is compact markdown; use
--format json for full structured data, csv for spreadsheets, and --out FILE to save.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from pydantic import BaseModel

from . import ats as atsmod
from . import discover, scraper
from .client import LinkedInClient, RateLimitedError
from .criteria import Criteria
from .export import to_csv
from .filters import ExperienceLevel, JobType, TimePosted, WorkMode, options
from .plan import build_plan
from .profile import extract_profile, profile_from_skills
from .render import discovery_md, job_card, jobs_table
from .url import is_linkedin_url

app = typer.Typer(
    help="LinkedIn job search for agents and humans. No login, no API key.",
    no_args_is_help=True, add_completion=False, pretty_exceptions_enable=False)

FMT = typer.Option("md", "--format", "-f", help="md | json | csv")
OUT = typer.Option(None, "--out", "-o", help="Write result to this file instead of stdout")
LOC = typer.Option(None, "--location", "-l", help="Repeatable. e.g. -l Bengaluru -l India -l Remote")
EXP = typer.Option(None, "--level", "-e", help="internship|entry|associate|mid_senior|director|executive")
WM = typer.Option(None, "--work-mode", "-w", help="remote|hybrid|onsite (heuristic, verified from the posting)")
TP = typer.Option(None, "--time", "-t", help="past_hour|past_24h|past_week|past_month")
TPW = typer.Option(TimePosted.PAST_WEEK, "--time", "-t", help="past_hour|past_24h|past_week|past_month")
XT = typer.Option(None, "--exclude", "-x", help="Title word to exclude (repeatable), e.g. -x senior -x lead")
XC = typer.Option(None, "--exclude-company", help="Company name substring to exclude (repeatable)")
AV = typer.Option(None, "--avoid", help='Reject if the description contains it, e.g. --avoid "no sponsorship"')


def _json(obj: Any) -> str:
    def default(o: Any) -> Any:
        if isinstance(o, BaseModel):
            return o.model_dump(mode="json")
        raise TypeError(type(o))

    return json.dumps(obj, ensure_ascii=False, indent=2, default=default)


def _read_text(src: str) -> str:
    """A file path, '-' for stdin, or literal text. PDFs/DOCX are read if pypdf/python-docx are installed."""
    if src == "-":
        return sys.stdin.read()
    p = Path(src).expanduser()
    if len(src) < 400 and p.is_file():
        suf = p.suffix.lower()
        if suf == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                typer.echo("PDF needs pypdf (pip install pypdf), or extract the text first and pass the .txt.", err=True)
                raise typer.Exit(2)
            return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)
        if suf == ".docx":
            try:
                import docx
            except ImportError:
                typer.echo("DOCX needs python-docx (pip install python-docx), or pass the text.", err=True)
                raise typer.Exit(2)
            return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
        return p.read_text(encoding="utf-8", errors="ignore")
    return src


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except RateLimitedError as e:
        typer.echo(f"RATE LIMITED: {e}", err=True)
        raise typer.Exit(2)
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


def _emit(text: str, out: Optional[Path]) -> None:
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"Wrote {out}", err=True)
    else:
        typer.echo(text)


def _criteria(exclude: Any, exclude_company: Any, require: Any, avoid: Any, max_age: float | None) -> Criteria:
    return Criteria(title_exclude=[rf"\b{re.escape(w)}\b" for w in exclude or []],
                    company_exclude=list(exclude_company or []), require_terms=list(require or []),
                    avoid_terms=list(avoid or []), max_age_days=max_age)


def _jobs_out(jobs: list, fmt: str, out: Optional[Path], detail: bool = False) -> None:
    if fmt == "json":
        _emit(_json([j.model_dump(mode="json", exclude={"description_html"}) for j in jobs]), out)
    elif fmt == "csv":
        _emit(to_csv(jobs), out)
    else:
        txt = jobs_table(jobs)
        if detail:
            txt += "\n\n" + "\n\n".join(job_card(j) for j in jobs)
        _emit(txt, out)


def _disc_out(d: discover.Discovery, fmt: str, out: Optional[Path]) -> None:
    if fmt == "json":
        rows = []
        for r in d.results:
            row = r.job.model_dump(mode="json", exclude={"description_html"})
            row["plan"] = r.plan.model_dump(mode="json") if r.plan else None
            rows.append(row)
        _emit(_json({"queries": d.queries, "notes": d.notes, "requests": d.requests_made,
                     "profile": d.profile, "results": rows}), out)
    elif fmt == "csv":
        _emit(to_csv([r.job for r in d.results]), out)
    else:
        _emit(discovery_md(d), out)


# ------------------------------------------------------------------ commands

@app.command()
def search(
    keywords: str = typer.Argument(..., help='Boolean ok: ("data scientist" OR "ml engineer") AND python'),
    location: Optional[list[str]] = LOC,
    limit: int = typer.Option(20, "--limit", "-n"),
    time: Optional[TimePosted] = TP,
    level: Optional[list[ExperienceLevel]] = EXP,
    job_type: Optional[list[JobType]] = typer.Option(None, "--job-type", "-j"),
    work_mode: Optional[list[WorkMode]] = WM,
    easy_apply: bool = typer.Option(False, "--easy-apply"),
    exclude: Optional[list[str]] = XT,
    exclude_company: Optional[list[str]] = XC,
    require: Optional[list[str]] = typer.Option(None, "--require", help="Term that must be in the description"),
    avoid: Optional[list[str]] = AV,
    level_mode: str = typer.Option("auto", "--level-mode", help="auto | precise | broad"),
    details: bool = typer.Option(False, "--details", help="Fetch + show full descriptions"),
    fmt: str = FMT, out: Optional[Path] = OUT,
    delay: float = typer.Option(0.5, "--delay", help="Min seconds between requests"),
) -> None:
    """Keyword search with accurate filters (the ones LinkedIn ignores are enforced client-side)."""

    async def go() -> list:
        stats = scraper.SearchStats()
        jobs: list = []
        seen: set[str] = set()
        async with LinkedInClient(min_delay=delay) as c:
            for loc in location or [""]:
                for j in await scraper.search_jobs(
                        keywords, loc, limit=limit, time_posted=time, easy_apply=easy_apply, experience=level,
                        job_types=job_type, work_modes=work_mode,
                        criteria=_criteria(exclude, exclude_company, require, avoid, None),
                        include_details=details, level_mode=level_mode, client=c, stats=stats):
                    if j.id not in seen:
                        seen.add(j.id)
                        jobs.append(j)
        typer.echo(f"scanned {stats.scanned} cards, {stats.detail_fetches} detail fetches, "
                   f"rejected {stats.rejected or 'none'}", err=True)
        return jobs[:limit]

    _jobs_out(_run(go()), fmt, out, detail=details)


@app.command()
def url(
    link: str = typer.Argument(..., help="LinkedIn job, search, or company URL"),
    limit: int = typer.Option(25, "--limit", "-n"),
    details: bool = typer.Option(False, "--details"),
    resume_: Optional[str] = typer.Option(None, "--resume", help="Resume file/text: adds fit + plan for a job URL"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Replay a pasted LinkedIn URL: a posting, a saved search, or a company's open jobs."""
    if not is_linkedin_url(link):
        typer.echo("That is not a linkedin.com URL.", err=True)
        raise typer.Exit(1)
    profile = extract_profile(_read_text(resume_), "resume") if resume_ else None
    r = _run(discover.search_from_url(link, limit=limit, include_details=details, profile=profile))
    for n in r.get("notes", []):
        typer.echo(f"note: {n}", err=True)
    if fmt == "json":
        _emit(_json(r), out)
    elif r["kind"] == "job":
        j = r["job"]
        _emit("Job not found." if not j else job_card(j) + ("\n\n" + r["plan"].to_markdown() if r["plan"] else ""), out)
    else:
        head = f"Company: {r['company']} (id {r['company_id']})\n\n" if r["kind"] == "company" else ""
        pinned = f"\n\nPinned in URL:\n{job_card(r['pinned_job'], 600)}" if r.get("pinned_job") else ""
        _emit(head + (jobs_table(r["jobs"]) if fmt == "md" else to_csv(r["jobs"])) + pinned, out)


@app.command()
def job(
    ids: list[str] = typer.Argument(..., help="Job ids or URLs"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Full details for one or more postings."""
    _jobs_out(_run(scraper.get_jobs(ids)), fmt, out, detail=True)


@app.command()
def skills(
    skills_: list[str] = typer.Argument(..., metavar="SKILL...", help="e.g. python pytorch sql"),
    title: Optional[list[str]] = typer.Option(None, "--title", help="Override inferred target titles"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    work_mode: Optional[list[WorkMode]] = WM, time: Optional[TimePosted] = TPW,
    exclude: Optional[list[str]] = XT, exclude_company: Optional[list[str]] = XC, avoid: Optional[list[str]] = AV,
    limit: int = typer.Option(15, "--limit", "-n"), plans: int = typer.Option(5, "--plans"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Search from a skill list: skills -> role titles -> Boolean searches -> ranked jobs + apply plans."""
    d = _run(discover.find_jobs(skills=skills_, titles=title, locations=location, experience=level,
                                work_modes=work_mode, time_posted=time, limit=limit, with_plans=plans,
                                criteria=_criteria(exclude, exclude_company, None, avoid, None)))
    _disc_out(d, fmt, out)


@app.command()
def resume(
    source: str = typer.Argument(..., help="Resume file (.txt .md .pdf .docx), '-' for stdin, or the text"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    work_mode: Optional[list[WorkMode]] = WM, time: Optional[TimePosted] = TPW,
    exclude: Optional[list[str]] = XT, exclude_company: Optional[list[str]] = XC, avoid: Optional[list[str]] = AV,
    limit: int = typer.Option(15, "--limit", "-n"), plans: int = typer.Option(5, "--plans"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Find and rank jobs for a resume, with per-job skill gaps and an action plan."""
    d = _run(discover.find_jobs_for_resume(
        _read_text(source), locations=location, experience=level, work_modes=work_mode, time_posted=time,
        limit=limit, with_plans=plans, criteria=_criteria(exclude, exclude_company, None, avoid, None)))
    _disc_out(d, fmt, out)


@app.command()
def jd(
    source: str = typer.Argument(..., help="JD file/text, '-' for stdin, or a LinkedIn job URL/id as the template"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    time: Optional[TimePosted] = typer.Option(TimePosted.PAST_MONTH, "--time", "-t"),
    exclude_company: Optional[list[str]] = XC,
    limit: int = typer.Option(15, "--limit", "-n"), plans: int = typer.Option(3, "--plans"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Find postings similar to a job description (same title family + required skills)."""

    async def go() -> discover.Discovery:
        if source.strip().isdigit() or "linkedin.com/jobs/view" in source:
            d0 = await scraper.get_job(source)
            if not d0:
                raise ValueError("Template job not found.")
            text = f"{d0.title}\n{d0.description}"
        else:
            text = _read_text(source)
        return await discover.find_jobs_like_jd(
            text, locations=location, experience=level, time_posted=time, limit=limit, with_plans=plans,
            criteria=_criteria(None, exclude_company, None, None, None))

    _disc_out(_run(go()), fmt, out)


@app.command()
def require(
    title: list[str] = typer.Option(..., "--title", help="Target title (repeatable)"),
    must: Optional[list[str]] = typer.Option(None, "--must", help="Term the posting must mention (repeatable)"),
    nice: Optional[list[str]] = typer.Option(None, "--nice", help="Skill that boosts ranking"),
    location: Optional[list[str]] = LOC, level: Optional[list[ExperienceLevel]] = EXP,
    job_type: Optional[list[JobType]] = typer.Option(None, "--job-type", "-j"),
    work_mode: Optional[list[WorkMode]] = WM, time: Optional[TimePosted] = TPW,
    exclude: Optional[list[str]] = XT, exclude_company: Optional[list[str]] = XC,
    company_id: Optional[list[str]] = typer.Option(None, "--company-id", help="From `lj company`"),
    avoid: Optional[list[str]] = AV,
    max_age: Optional[float] = typer.Option(None, "--max-age-days"),
    limit: int = typer.Option(15, "--limit", "-n"), plans: int = typer.Option(5, "--plans"),
    fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Structured requirements: titles + must/nice skills + filters. Must-haves are enforced, nice-haves rank."""
    allsk = [*(must or []), *(nice or [])]
    profile = profile_from_skills(allsk, title) if allsk else None
    d = _run(discover.find_jobs(
        profile, queries=title, titles=title, locations=location, experience=level, job_types=job_type,
        work_modes=work_mode, time_posted=time, company_ids=company_id, limit=limit, with_plans=plans,
        criteria=_criteria(exclude, exclude_company, must, avoid, max_age)))
    _disc_out(d, fmt, out)


@app.command()
def plan(
    job_: str = typer.Argument(..., metavar="JOB", help="Job id or URL"),
    resume_: Optional[str] = typer.Option(None, "--resume", help="Resume file/text for fit + gaps"),
    fmt: str = FMT,
) -> None:
    """How to actually get this job: channel, timing, red flags, resume edits, who to contact."""

    async def go() -> tuple:
        d = await scraper.get_job(job_)
        if not d:
            raise ValueError("Job not found (removed or closed).")
        return d, build_plan(d, extract_profile(_read_text(resume_), "resume") if resume_ else None)

    d, p = _run(go())
    typer.echo(_json({"job": d.model_dump(mode="json", exclude={"description_html"}), "plan": p})
               if fmt == "json" else job_card(d, 600) + "\n\n" + p.to_markdown())


@app.command()
def profile(source: str = typer.Argument(..., help="Resume/JD file or text"),
            kind: str = typer.Option("resume", "--kind", help="resume | jd")) -> None:
    """Offline analysis (no requests): skills, titles, years, seniority, suggested queries."""
    typer.echo(_json(extract_profile(_read_text(source), kind)))  # type: ignore[arg-type]


@app.command()
def company(name_or_url: str = typer.Argument(..., help="Company name or linkedin.com/company/<slug> URL")) -> None:
    """LinkedIn company ids + the employer's public ATS boards (Greenhouse/Lever/Ashby)."""

    async def go() -> dict:
        async with LinkedInClient() as c:
            if is_linkedin_url(name_or_url):
                cid, name = await scraper.resolve_company(name_or_url, client=c)
                li = [{"id": cid, "name": name}] if cid else []
            else:
                name = name_or_url
                li = (await scraper.find_companies(name, client=c))[:5]
            return {"linkedin": li, "ats_boards": await atsmod.find_boards(name, client=c)}

    typer.echo(_json(_run(go())))


@app.command()
def board(
    ats_name: str = typer.Argument(..., help="greenhouse | lever | ashby | smartrecruiters | workday"),
    org: str = typer.Argument(..., help="Board token / slug / Workday tenant"),
    keywords: Optional[str] = typer.Option(None, "--keywords", "-k", help='"python intern OR machine learning"'),
    host: Optional[str] = typer.Option(None, "--workday-host"),
    site: Optional[str] = typer.Option(None, "--workday-site"),
    limit: int = typer.Option(30, "--limit", "-n"), fmt: str = FMT, out: Optional[Path] = OUT,
) -> None:
    """Search an employer's own job board directly (fresher and more complete than LinkedIn)."""
    ref = atsmod.AtsRef(ats=ats_name, org=org, host=host, site=site, queryable=True)
    _jobs_out(_run(atsmod.list_board(ref, keywords=keywords, limit=limit)), fmt, out)


@app.command("apply-channel")
def apply_channel(link: str = typer.Argument(...)) -> None:
    """Which ATS is behind an apply URL, and how that application works."""
    typer.echo(_json(atsmod.detect_ats(link) or {"ats": None}))


@app.command("open")
def is_open(link: str = typer.Argument(..., help="LinkedIn or ATS job URL")) -> None:
    """Is the posting still open? (LinkedIn, Greenhouse, Lever, Ashby, Workday, SmartRecruiters)"""

    async def go() -> dict:
        async with LinkedInClient() as c:
            if "linkedin.com" in link:
                return {"open": (await scraper.get_job(link, client=c)) is not None, "source": "linkedin"}
            ref, post = await atsmod.get_posting(link, client=c)
            if not ref or not ref.queryable:
                return {"open": None, "reason": "ATS not publicly queryable; open the link."}
            return {"open": post is not None, "ats": ref.ats}

    typer.echo(_json(_run(go())))


@app.command("options")
def options_cmd() -> None:
    """Valid enum values and which filters run server-side vs client-side."""
    typer.echo(_json(options()))


@app.command("mcp")
def mcp_cmd(transport: str = typer.Option("stdio"), host: str = "127.0.0.1", port: int = 8000) -> None:
    """Optional: serve the same tools over MCP (needs `pip install mcp`)."""
    from .server import run

    run(transport, host, port)


from . import cli_pro  # noqa: E402,F401  (registers the memory/radar/brief commands on `app`)

if __name__ == "__main__":
    app()
