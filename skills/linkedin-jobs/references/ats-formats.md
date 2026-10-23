# How employers post jobs (ATS formats) and how applications are taken

Most jobs on LinkedIn originate in an **applicant tracking system (ATS)**. LinkedIn either hosts the application
("Easy Apply") or sends you to the employer's ATS form. Knowing which ATS is behind a link tells you how the application
is processed and whether the employer's own board can be queried directly.

## Public, queryable boards (no login)

| ATS | URL pattern | Public API used here | Gives you |
|---|---|---|---|
| **Greenhouse** | `boards.greenhouse.io/<token>/jobs/<id>`, `job-boards.greenhouse.io/<token>/jobs/<id>`, `?gh_jid=<id>` on company pages | `boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true`; single job `.../jobs/<id>?pay_transparency=true` | title, location, departments, full description, `first_published`/`updated_at`, **pay ranges** (`pay_input_ranges`) when the employer enabled them |
| **Lever** | `jobs.lever.co/<company>/<uuid>` (EU: `jobs.eu.lever.co`) | `api.lever.co/v0/postings/<company>?mode=json` (EU: `api.eu.lever.co`) | team, location, commitment, `createdAt`, plain description + requirement lists, `salaryRange` when present |
| **Ashby** | `jobs.ashbyhq.com/<org>/<uuid>` | `api.ashbyhq.com/posting-api/job-board/<org>?includeCompensation=true` | department, employment type, remote flag, `publishedAt`, description, **compensation summary** |
| **Workday** | `<tenant>.wd<N>.myworkdayjobs.com/<locale>/<site>/job/...` | POST `https://<host>/wday/cxs/<tenant>/<site>/jobs` (search) and GET `.../job/...` (detail) | title, location, "Posted N days ago", description, time type |
| **SmartRecruiters** | `jobs.smartrecruiters.com/<company>/<id>` | `api.smartrecruiters.com/v1/companies/<company>/postings` | title, location, function, employment type, release date |

A Greenhouse `?gh_jid=` on a custom careers domain tells you the ATS but not the board token; search the company name.

## Recognised but not publicly queryable

iCIMS, Taleo (Oracle), SAP SuccessFactors, Oracle Cloud HCM, BambooHR, Jobvite, Teamtailor, Recruitee, Workable,
Breezy, Personio. The skill still identifies them and explains how the application works.

## What each application flow means for you

- **Greenhouse / Lever / Ashby / SmartRecruiters:** one form, resume upload, short custom questions, usually no account.
  Free-text answers are read by a human; do not paste generic text.
- **Workday / iCIMS / Taleo / SuccessFactors:** account per employer; the resume is **parsed into fields** that you must
  re-check. Use a plain single-column resume (no tables, text boxes, icons) and mirror the posting's wording.
- **LinkedIn Easy Apply:** fastest, highest volume. The recruiter sees your LinkedIn profile, so keep headline, skills and
  dates consistent with the resume. Competition is typically higher than on a direct ATS form.
- **Email / "apply on our site":** treat as a referral-style application: short note, resume attached as PDF.

## Posting fields that carry real signal

| Field | Meaning | Where |
|---|---|---|
| Posted date / "N days ago" | Freshness. Fresh postings are reviewed first. | LinkedIn card, ATS `published/updated/created` |
| Applicant count ("Over 200", "early applicant") | Competition proxy. | LinkedIn detail page |
| Seniority level, employment type, job function | Employer-set criteria; use to verify level. | LinkedIn detail page |
| Apply URL | Reveals the ATS; the employer listing is the source of truth. | LinkedIn `applyUrl` block |
| Pay range | Legally required in some places (e.g. several US states, EU pay-transparency rules); appears in ATS first. | Greenhouse/Ashby/Lever payloads |
| `application_deadline`, requisition id | Real roles have these; evergreen postings often do not. | Greenhouse |

## Ghost-job signals (what `lj verify` actually uses)

Strongest: the apply link or company name resolves to an employer board that **does not list the role** (or lists it as
gone). Supporting: open 30/60/90+ days, evergreen wording ("talent pool", "future opportunities", "always hiring"), a very
thin description, the same role reposted under several ids, an employer board with zero open roles.
Positive evidence: the role is on the employer's own board. Absence of a board means **unverified**, not fake.
