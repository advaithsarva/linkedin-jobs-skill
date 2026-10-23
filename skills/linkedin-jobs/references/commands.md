# `lj` command reference

Run as `python scripts/lj.py <command>` (or `uv run scripts/lj.py ...`). Results go to stdout, progress/notes to stderr.
Common options: `-f md|json|csv` (default md), `-o FILE`, `-l LOCATION` (repeatable), `-e LEVEL` (repeatable),
`-w remote|hybrid|onsite`, `-t past_hour|past_24h|past_week|past_month`, `-x TITLEWORD` (exclude), `--exclude-company`,
`--avoid PHRASE`, `-n LIMIT`.

## Find

| Command | Purpose |
|---|---|
| `search KEYWORDS` | Keyword search (Boolean ok). `--require TERM` (must be in description), `--details`, `--easy-apply`, `--level-mode auto|precise|broad`, `--delay SEC` |
| `skills SKILL...` | Skills -> role titles -> several Boolean searches -> ranked, with plans. `--title` overrides inferred titles, `--plans N` |
| `resume FILE` | Extract skills/titles/seniority/education from a resume (txt, md, pdf, docx, `-` stdin), search, rank by coverage with gaps |
| `jd SOURCE` | Jobs like a JD (file, text, LinkedIn job URL or id) |
| `require --title T ... --must S --nice S` | Structured requirements; `--must` terms are enforced, `--nice` boosts rank; `--company-id`, `--max-age-days` |
| `url LINK` | Replay a LinkedIn search URL, job URL or company URL. `--resume` adds fit + plan for a job URL |
| `job ID_OR_URL...` | Full details |
| `company NAME_OR_URL` | LinkedIn company id(s) and the employer's public ATS boards |
| `board ATS ORG -k "a OR b"` | Search an employer's own board (greenhouse, lever, ashby, smartrecruiters, workday with `--workday-host/--workday-site`) |

## Decide

| Command | Purpose |
|---|---|
| `plan JOB [--resume FILE]` | Channel, timing, red flags, resume edits, people-search links |
| `verify JOB... [--no-deep]` | Ghost score, employer listing, pay. `--no-deep` skips the board cross-check |
| `open URL` | Is the LinkedIn/ATS posting still live? |
| `apply-channel URL` | Which ATS, and how that application works |
| `gap [--sample N]` | Missing skills ranked by jobs unlocked, with a proof project each |
| `profile FILE [--kind resume|jd]` | Offline analysis, no requests |

## Remember and monitor (local state in `~/.linkedin-jobs/`, override with `LINKEDIN_JOBS_HOME`)

| Command | Purpose |
|---|---|
| `init [RESUME] [--skills S...]` | Save profile and create default watches |
| `watch add-query NAME KEYWORDS`, `watch add-company NAME`, `watch list`, `watch remove NAME` | Radar targets |
| `brief [--verify N] [--no-deep]` | New jobs only, verified, ranked by return on effort, portfolio, follow-ups, learn-next |
| `mark JOB ACTION [-r REASON] [--followup-days N]` | `saved applied interview offer rejected skipped closed`. The taste model learns from these |
| `history` | Your actions and the learned preferences |
| `doctor` | Connectivity check |
| `options` | Valid enum values; which filters are server- vs client-side |
| `mcp` | Optional: serve the same capabilities over MCP (`pip install mcp`) |

## Configuration

Environment: `LINKEDIN_JOBS_DELAY` (seconds between requests, default 0.5), `LINKEDIN_JOBS_CONCURRENCY`,
`LINKEDIN_JOBS_PROXY`, `LINKEDIN_JOBS_CACHE_DIR`, `LINKEDIN_JOBS_LOCATION`, `LINKEDIN_JOBS_HOME`, `LINKEDIN_JOBS_CONFIG`.
Config file (`linkedin-jobs.toml` in the working dir, or `~/.config/linkedin-jobs/config.toml`; Python 3.11+): see
`examples/linkedin-jobs.toml` for blocked companies/title patterns, custom skills and scoring weights.
