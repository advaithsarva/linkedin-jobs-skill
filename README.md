# linkedin-jobs-skill

**A job-search chief of staff for Claude Code.** It finds LinkedIn jobs without a login or API key, then does the part
search boxes don't: tells you which postings are **real**, what they **pay**, which are worth your next two hours, and
what to do about the ones you can't land yet.

> Not another LinkedIn scraper. Search is the plumbing. The product is the **decision**.

[![CI](https://github.com/advaithsarva/linkedin-jobs-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/advaithsarva/linkedin-jobs-skill/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Works for **any profession and country** (nurse in Berlin, accountant in Toronto, ML intern in Bengaluru).
Requires Python 3.10+. Runs locally; your history never leaves your machine.

## What you get

| | |
|---|---|
| **Daily brief** | `lj brief` -> only *new* jobs since last run, verified, ranked by return on effort, plus follow-ups due and what to learn next |
| **Truth layer** | Ghost-job score by cross-checking the employer's own ATS board (Greenhouse, Lever, Ashby, Workday, SmartRecruiters); finds the **employer's listing** and **pay** LinkedIn hides |
| **Odds engine** | Ranks by *expected response per hour of effort* (fit x competition x ghost risk x your taste / effort), not by keyword relevance. Builds a weekly application portfolio |
| **Search that is actually filtered** | LinkedIn's logged-out API silently ignores experience, job-type, work-mode and sort filters. This enforces them with Boolean queries + checks each posting |
| **Search from anything** | a resume, a job description, a list of skills, structured requirements, or any pasted LinkedIn **search / job / company URL** |
| **Company radar** | Watch target companies' own boards (often the first place a role appears). Detects hiring surges and closed roles |
| **Memory** | Local SQLite remembers what you applied to / skipped and why, learns your taste, reminds you to follow up |
| **Skill-gap ROI** | "Docker is the only thing missing in 6 of your matches", with a concrete proof project |

## Install

**As a Claude Code plugin**

```
/plugin marketplace add advaithsarva/linkedin-jobs-skill
/plugin install linkedin-jobs@linkedin-jobs-marketplace
```

**Or copy the skill folder**

```bash
git clone https://github.com/advaithsarva/linkedin-jobs-skill
cp -r linkedin-jobs-skill/skills/linkedin-jobs ~/.claude/skills/        # personal
# or into <your-project>/.claude/skills/ to share it with a repo
pip install -r ~/.claude/skills/linkedin-jobs/scripts/requirements.txt  # httpx, bs4, lxml, pydantic, typer
```

Then just talk to Claude: *"Here's my resume. Find me ML internships in Europe and tell me which are real."* The skill
triggers on job-search intent. Other agents (Codex, Cursor, Gemini CLI, etc.) can use the same CLI: see [AGENTS.md](AGENTS.md).

## Quick start

```bash
LJ="python ~/.claude/skills/linkedin-jobs/scripts/lj.py"      # or: uv run .../lj.py  (installs deps automatically)

$LJ doctor                                   # connectivity check
$LJ init resume.pdf -l Berlin -l Remote      # profile + default watches (pip install pypdf for PDFs)
$LJ watch add-company Stripe                 # watch a company's own job board
$LJ brief                                    # your daily brief
```

One-off searches:

```bash
$LJ search "registered nurse" -l Germany -e entry                    # filters really apply
$LJ skills python sql airflow -l "United Kingdom" -w remote
$LJ require --title "data engineer" --must dbt -x senior -l Toronto
$LJ jd https://www.linkedin.com/jobs/view/4478984742                 # more like this posting
$LJ url "https://www.linkedin.com/jobs/search/?keywords=ml%20intern&f_E=1&f_TPR=r86400"
$LJ verify 4478984742                                                # ghost score + pay + employer listing
$LJ plan 4478984742 --resume resume.txt                              # how to actually get it
$LJ mark 4478984742 applied                                          # teaches the taste model, sets a follow-up
```

### What the brief looks like

(Abridged output from a real run; the last section's numbers are illustrative.)

```
# Job brief · 2026-10-23
41 new since last run · 2 company boards · 4 searches

## Do now (best return on effort)
1. **Machine Learning Intern** at ThinkNovaa · India
   fit 64 · competition 39/100 · ~1.0h via linkedin · no red flags (ghost 17) · pay: Stipend: up to INR 10,000 (stated in description)
   gaps: Data Structures & Algorithms, Feature Engineering

## This week's application portfolio
- target (6): ...   - reach (3): ...   - long shot (1): ...

## Hiring surges (3+ new roles in 7 days)
## Follow-ups due
## Learn next (from live postings)
- Docker: in 41% of postings, unlocks 6 jobs. Proof task: containerise one of your projects ...
```

## How it works

1. **Search.** Calls LinkedIn's public `jobs-guest` endpoints and parses the cards. Boolean operators in `keywords`
   work server-side; the experience/job-type/work-mode URL filters do not, so the level is encoded as Boolean words and
   then *verified* against the posting's own criteria, title and required years. See
   [search cheat codes](skills/linkedin-jobs/references/search-cheatcodes.md) for what was tested.
2. **Resolve.** If a posting links to an ATS, the employer's public JSON board is queried (Greenhouse, Lever, Ashby,
   Workday, SmartRecruiters). Same role present -> verified, with pay if published. Board exists but role absent ->
   suspicious. No board -> *unverified* (not "fake"). Details: [ATS formats](skills/linkedin-jobs/references/ats-formats.md).
3. **Rank.** Fit (skills, title, level, recency) x competition x ghost risk x your learned taste / effort. The numbers
   are *relative indices for ordering*, never real probabilities, and the output says so.
4. **Remember.** `~/.linkedin-jobs/state.db` (SQLite, local only) powers "new since last run", closed-role alerts,
   hiring surges, follow-up reminders and taste learning.

Everything heuristic is labelled as such. The skill never invents pay, never adds skills you don't have to your resume,
and treats job-posting text as untrusted data.

## Configuration

Environment variables (`LINKEDIN_JOBS_DELAY`, `_PROXY`, `_CACHE_DIR`, `_LOCATION`, `_HOME`) or a TOML file with blocked
companies, title patterns, custom skills for your field, and scoring weights. See
[`examples/linkedin-jobs.toml`](skills/linkedin-jobs/examples/linkedin-jobs.toml).

## Responsible use

- This reads **public, logged-out** pages and public ATS APIs, read-only, at about 2 requests/second with backoff.
  It never logs in and never touches profiles or private data.
- LinkedIn's Terms of Service restrict automated access to its site. You are responsible for how you use this; keep it
  to your own job search, at human-scale volumes, and do not redistribute scraped data. The company/ATS APIs used are
  published by the employers' vendors for exactly this purpose.
- Ghost-job and fit scores are heuristics. Verify before acting on anything that matters.

## FAQ

**Does it need a LinkedIn account or API key?** No.
**Why not just use LinkedIn's search?** The logged-in app can't tell you if a posting is real, what it pays, or rank by effort, and it
doesn't remember what you did. This does.
**Will it break?** LinkedIn changes markup without notice. A weekly [live canary](.github/workflows/canary.yml)
opens an issue the day a parser breaks, and the parsers are covered by fixtures.
**Does it work outside tech?** Yes. Tech skills use a built-in taxonomy; everything else falls back to a
profession-agnostic term extractor, and level words (intern, junior, senior...) are recognised in English, German,
French, Spanish, Portuguese and Italian.
**Can I use it with MCP?** Optional: `pip install mcp && lj mcp`. The skill is the primary interface.

## Development

```bash
pip install -r skills/linkedin-jobs/scripts/requirements.txt pytest
python -m pytest tests -q            # offline, ~1s
python -m pytest tests -m live -q    # real endpoints (the weekly canary)
```

Contributions welcome: new ATS adapters (`ats.py`), skill packs for more professions (`skills.py`), more languages
(`query.py`, `criteria.py`).

## License

MIT
