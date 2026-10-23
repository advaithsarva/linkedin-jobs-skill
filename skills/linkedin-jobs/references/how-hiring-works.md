# How a posting becomes a hire (and where you can actually change the odds)

Facts here come from how ATS products and public job data behave, not from folklore. Where something is a judgement
call, it says so.

## The pipeline behind a posting

1. **Requisition opens** (budget approved). Employers publish to their own ATS board; LinkedIn and other boards pick
   it up by syndication or manual posting, which can lag. A company board can therefore show a role before LinkedIn
   does (it varies by employer).
2. **Applications arrive.** An ATS stores them; recruiters filter by hand and by knock-out questions (work
   authorization, location, years, degree). Keyword search inside the ATS is common, so wording matters.
3. **Screen -> hiring-manager review -> interviews -> offer.** Roles frequently close well before the posting is taken
   down, and some postings never had an open headcount (evergreen or "pipeline" listings).

Implications that follow from the mechanics:

- **Early is a cheap advantage.** Some teams review in arrival order and stop once they have enough qualified
  candidates; others read everything. You cannot know which, and applying early costs nothing, so `lj brief` surfaces
  postings by age and applicant count, and a company board watch (`watch add-company`) shows roles on day 0.
- **Knock-outs decide before humans do.** Work authorization, location and minimum years are filtered early. `lj plan`
  flags these from the posting text so you do not spend an evening on an ineligible role.
- **Parsing is lossy.** Workday/iCIMS-style systems turn your resume into fields. Tables, columns, text boxes and icons
  scramble the parse. Plain text structure with standard headings survives.
- **The posting is a spec, not a wish list.** Required skills in the first bullets, repeated terms and the title carry
  the weight. Mirror the posting's exact terms where they are true for you.

## Where outside action helps (and what to say)

- **A referral or a direct note to a recruiter/team member** puts your application on a human's desk instead of in the
  queue. Three lines is enough: who you are, the single project that matches the top requirement (with a link), and that
  you have applied (with the role id). Do not attach files to a cold message.
- **Hiring posts** ("we're hiring ...") often precede or replace formal postings. `lj plan` generates the search links.
- **Hiring surges** (several new roles at one company in a week) indicate a funded team; roles posted in a burst may well come from
  the same hiring manager. Worth a targeted note even if your exact title is not open yet.

## Judgement calls (treat as heuristics)

- Application volume per role varies by market and role type; the "competition" number here is relative to the same
  search, not a population statistic.
- "Ghost" scoring cannot see inside a company. It ranks how much evidence there is that a role is live.
- Fit scores reward skill overlap and level match; they cannot judge a strong portfolio or an unusual background. Use
  the gap list as prompts for projects, not as a verdict on you.

## Sources of public hiring data worth knowing

Employer ATS boards (JSON), the SimplifyJobs GitHub lists for internships and new grad, Hacker News "Who is hiring",
and government wage/visa datasets such as the US Department of Labor LCA disclosure files for sponsorship history.
