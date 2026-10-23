import pytest
from conftest import fixture
from linkedin_jobs.filters import ExperienceLevel as E
from linkedin_jobs.parser import extract_job_id, parse_detail, parse_search
from linkedin_jobs.query import compose
from linkedin_jobs.url import classify, parse_search_url


def test_search_cards_parsed_and_malformed_skipped():
    jobs = parse_search(fixture("search_page.html"))
    assert [j.id for j in jobs] == ["1111111111", "2222222222"]
    a, b = jobs
    assert a.title == "Machine Learning Intern" and a.company == "Acme Labs"
    assert a.company_url == "https://in.linkedin.com/company/acme"
    assert a.posted_date == "2026-10-21" and a.early_applicant is True
    assert a.url == "https://www.linkedin.com/jobs/view/1111111111"
    assert b.title == "Senior Data Scientist & Lead"  # entities decoded
    assert b.salary == "$120K - $150K" and b.location == "Remote"


def test_detail_parsed():
    d = parse_detail(fixture("detail_page.html"), "1111111111")
    assert d.title == "Machine Learning Intern" and d.company == "Acme Labs"
    assert d.location == "Bengaluru, Karnataka, India"
    assert d.seniority_level == "Internship" and d.employment_type == "Internship"
    assert d.applicants == "Over 200 applicants" and d.posted_text == "2 days ago"
    assert d.apply_url == "https://boards.greenhouse.io/acme/jobs/5551234?utm=li&x=1"
    assert "RAG pipelines" in d.description and "- Docker is a plus" in d.description


@pytest.mark.parametrize("value,expected", [
    ("4478984742", "4478984742"),
    ("https://in.linkedin.com/jobs/view/software-engineer-intern-at-digiplus-it-4478984742?position=1", "4478984742"),
    ("https://www.linkedin.com/jobs/view/4478984742/", "4478984742"),
    ("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=4478984742", "4478984742"),
])
def test_extract_job_id(value, expected):
    assert extract_job_id(value) == expected


def test_extract_job_id_rejects_garbage():
    with pytest.raises(ValueError):
        extract_job_id("https://example.com/nothing-here")


def test_compose_precise_internship():
    q = compose("machine learning", experience=[E.INTERNSHIP])
    assert q.startswith("machine learning AND (intern OR internship")
    assert "NOT (senior" in q


def test_compose_entry_is_broad_by_default():
    q = compose("python developer", experience=[E.ENTRY], exclude=["staff"])
    assert "AND (" not in q  # broad: only excludes senior words, keeps unlabeled roles
    assert "NOT (staff OR senior" in q


def test_compose_preserves_user_boolean_and_caps_length():
    q = compose('("data scientist" OR "ml engineer") AND python')
    assert q == '("data scientist" OR "ml engineer") AND python'
    assert len(compose("x", skills_any=[f"skill{i}" for i in range(400)])) <= 900


def test_parse_search_url_maps_ignored_filters_to_criteria():
    s = parse_search_url("https://www.linkedin.com/jobs/search/?keywords=ml%20intern&location=India"
                         "&f_E=1%2C2&f_TPR=r86400&f_WT=2&f_SB2=3&currentJobId=99")
    assert s.keywords == "ml intern" and s.location == "India"
    assert [e.value for e in s.experience] == ["internship", "entry"]
    assert s.time_posted.value == "past_24h" and s.work_modes[0].value == "remote"
    assert s.current_job_id == "99" and any("f_SB2" in n for n in s.notes)


def test_classify_urls():
    assert classify("https://www.linkedin.com/company/anthropicresearch/jobs/") == ("company", "anthropicresearch")
    assert classify("https://in.linkedin.com/jobs/view/foo-at-bar-123456789") == ("job", "123456789")
    assert classify("https://www.linkedin.com/jobs/search/?keywords=x")[0] == "search"
