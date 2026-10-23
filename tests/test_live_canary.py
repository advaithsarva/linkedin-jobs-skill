"""Live canary: hits the real endpoints. Run weekly in CI (see .github/workflows/canary.yml) or manually:

    pytest -m live

If these fail, LinkedIn or an ATS changed its markup/API. The parser fixtures in tests/fixtures are then stale.
"""
import asyncio

import pytest
from linkedin_jobs import ats, scraper
from linkedin_jobs.client import LinkedInClient

pytestmark = pytest.mark.live


def run(coro):
    return asyncio.run(coro)


def test_linkedin_search_cards_parse():
    async def go():
        async with LinkedInClient(min_delay=0.3) as c:
            return await scraper.search_jobs("software engineer", "United States", limit=8, client=c)

    jobs = run(go())
    assert len(jobs) >= 5, "search returned too few cards: card markup or endpoint changed"
    assert all(j.id.isdigit() and j.title and j.company and j.url for j in jobs)


def test_linkedin_detail_parses_description_and_criteria():
    async def go():
        async with LinkedInClient(min_delay=0.3) as c:
            first = (await scraper.search_jobs("software engineer", "United States", limit=1, client=c))[0]
            return await scraper.get_job(first.id, client=c)

    d = run(go())
    assert d and len(d.description) > 200, "detail description markup changed"
    assert d.seniority_level or d.employment_type, "job criteria markup changed"


def test_company_typeahead_and_page_id():
    async def go():
        async with LinkedInClient(min_delay=0.3) as c:
            hits = await scraper.find_companies("google", client=c)
            cid, _ = await scraper.resolve_company("https://www.linkedin.com/company/google", client=c)
            return hits, cid

    hits, cid = run(go())
    assert hits and cid, "company id resolution changed"


@pytest.mark.parametrize("name", ["greenhouse", "lever", "ashby"])
def test_ats_boards_still_public(name):
    org = {"greenhouse": "anthropic", "lever": "palantir", "ashby": "openai"}[name]

    async def go():
        async with LinkedInClient(min_delay=0.3) as c:
            return await ats.list_board(ats.AtsRef(ats=name, org=org, queryable=True), limit=5, full=False, client=c)

    assert run(go()), f"{name} public board API changed"
