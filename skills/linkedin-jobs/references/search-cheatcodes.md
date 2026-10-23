# Search cheat codes (verified against LinkedIn's logged-out endpoints, Oct 2026)

LinkedIn's public (no-login) job search is `jobs-guest/jobs/api/seeMoreJobPostings/search`. It is the same data as the
web search page, with different rules from the logged-in app. Everything below was tested, not copied from blogs.

## What actually works server-side

| Parameter | Effect | Notes |
|---|---|---|
| `keywords` | yes | **Boolean works**: `AND`, `OR`, `NOT` (capitals), `"exact phrase"`, `( )`. |
| `location` | yes | Free text ("Berlin", "India", "Greater Chennai Area"). "Remote" is NOT a real location; enforce remote from the posting instead. |
| `geoId` | yes | Numeric place id; same result as the matching `location` text. |
| `f_TPR` | yes | `r3600` hour, `r86400` day, `r604800` week, `r2592000` month. Biggest lever for freshness. |
| `f_AL=true` | yes | Easy Apply only. |
| `f_C` | yes | Company id(s), comma separated. Get ids from the company typeahead or the `/company/<slug>` page (`f_C=` link). |
| `start` | yes | Paging. Pages hold ~10 cards; step by the number returned. Nothing past ~1000. |

## What is silently ignored (the response looks normal, the filter did nothing)

`f_E` (experience level), `f_JT` (job type), `f_WT` (work mode), `f_JIYN`, `f_SB2` (salary), `f_VJ`, `distance`,
`sortBy`. Scrapers that pass these return unfiltered results and never say so. This skill replaces them:

- **Level** -> Boolean words in `keywords` (`(intern OR internship OR trainee)`, or `NOT (senior OR lead OR ...)`),
  then verifies each posting's own "Seniority level", its title, and the years its description requires.
- **Job type / work mode** -> read from the posting; work mode is a heuristic from title/location/description.
- **Freshness ordering** -> use `f_TPR`; ordering within results is LinkedIn's.

## Boolean recipes

```
("data scientist" OR "machine learning engineer") AND python
python NOT (senior OR lead OR principal OR staff OR manager)
(intern OR internship OR werkstudent OR praktikum) AND "machine learning"
"registered nurse" AND (icu OR "intensive care")
```

Not supported: `-word`, `+word`, `*` wildcards, `title:`, `NEAR`, curly quotes (use straight `"`). Long queries are fine
(1,300+ characters worked); keep under ~900 to be safe. More than ~3 ANDed skills often returns nothing.

## Level: precise vs broad

- `precise` requires level words in the title. Few false positives, but it misses roles titled just "Software Engineer"
  that are really entry level.
- `broad` only excludes senior-sounding words. Keeps unlabelled roles; client-side checks then read the posting.
- `auto` uses precise for internships, broad for entry level.

## Beyond the search box

- **Employer boards first.** Greenhouse/Lever/Ashby/Workday boards publish before LinkedIn syndicates and include
  salary ranges on some. `lj company X`, `lj board ...`, `lj watch add-company X`.
- **Company page = its jobs.** `https://www.linkedin.com/company/<slug>` exposes the company id (`f_C=`); `lj url` accepts it.
- **Saved-search URLs replay.** Paste any `linkedin.com/jobs/search/?...` URL into `lj url`; filters LinkedIn ignores are
  re-applied client-side and the output notes what could not be honoured.
- **X-ray people search (no login):** `site:linkedin.com/in "<Company>" ("recruiter" OR "talent acquisition")`; add
  `"<your university>"` for alumni. `lj plan` builds these links.
- **Hiring posts:** LinkedIn content search for `hiring "<Company>" <role>` finds managers announcing roles that may
  never be formally posted (needs login to open; the links are generated for you).
- **Other public sources worth checking:** Hacker News "Who is hiring" (Algolia API, often lists a hiring contact),
  SimplifyJobs internship/new-grad lists on GitHub (`listings.json` has an `active` flag), RemoteOK's JSON API.

## Etiquette and limits

Read-only requests to public pages, ~2 requests/second by default with backoff. If you see HTTP 429/999, wait a few
minutes, raise `--delay`, or set `LINKEDIN_JOBS_PROXY`. Use for your own job search, not bulk collection.
