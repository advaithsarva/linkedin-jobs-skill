from datetime import date, timedelta

import pytest
from conftest import fixture
from linkedin_jobs import ats
from linkedin_jobs.criteria import Criteria, infer_experience, required_years
from linkedin_jobs.filters import ExperienceLevel as E
from linkedin_jobs.gap import analyse
from linkedin_jobs.match import score_job
from linkedin_jobs.models import Job, JobDetails
from linkedin_jobs.odds import evaluate, portfolio
from linkedin_jobs.parser import parse_detail
from linkedin_jobs.plan import build_plan
from linkedin_jobs.profile import extract_profile, profile_from_skills
from linkedin_jobs.skills import extract_skills, extract_terms
from linkedin_jobs.state import State
from linkedin_jobs.verify import Resolution, find_salary, score_ghost

RESUME = """Alex Doe
B.Tech Computer Science student, expected graduation 2027.
Machine Learning Intern 2025 - Present: built RAG pipelines with LangChain, FastAPI, Docker, PyTorch.
Skills: Python, SQL, Git, Linux, AWS, scikit-learn"""


def job(title="Engineer", company="Acme", desc="", **kw) -> JobDetails:
    d = dict(id="1", title=title, company=company, location="Berlin, Germany", url="https://www.linkedin.com/jobs/view/1",
             description=desc)
    return JobDetails(**{**d, **kw})


# ---- skills / profile
def test_skill_extraction_respects_boundaries_and_case():
    got = extract_skills("Rust is rusty. We use Rust, C++, C#, Node.js and React.js; the rust on the car is irrelevant.")
    assert {"Rust", "C++", "C#", "Node.js", "React"} <= set(got)
    assert got["Rust"] == 2  # the two capitalised uses count; lowercase "rust" is just English


def test_resume_profile_student():
    p = extract_profile(RESUME, "resume")
    assert p.seniority == E.INTERNSHIP and p.education == "bachelors"
    assert {"Python", "PyTorch", "RAG", "Docker"} <= set(p.skills)
    assert p.titles[0] == "machine learning engineer" or "machine learning" in " ".join(p.titles)


def test_non_tech_resume_still_gets_titles_and_terms():
    nurse = ("Maria Gonzalez\nRegistered Nurse, 6 years of experience in emergency care.\n"
             "Triage, IV therapy, ACLS certified, BLS certified, Epic, wound care.")
    p = extract_profile(nurse, "resume")
    assert "registered nurse" in p.titles and "gonzalez" not in " ".join(p.titles)
    assert {"ACLS", "BLS", "Epic"} <= set(p.skills)


def test_extract_terms_phrases_do_not_cross_punctuation():
    terms = extract_terms("IV therapy, ACLS certified, wound care.")
    assert "Therapy Acls" not in terms and "Iv Therapy" in terms


def test_jd_splits_required_and_preferred():
    jd = "Requirements\n- Python\n- SQL\nNice to have\n- Docker\n- Kubernetes"
    p = extract_profile(jd, "jd")
    assert {"Python", "SQL"} <= set(p.required_skills) and {"Docker", "Kubernetes"} <= set(p.preferred_skills)


def test_profile_from_skills_normalises_aliases():
    p = profile_from_skills(["pytorch", "React.js", "sql"])
    assert {"PyTorch", "React", "SQL"} <= set(p.skills) and p.titles


# ---- criteria
@pytest.mark.parametrize("title,expected", [
    ("Software Engineering Intern", E.INTERNSHIP), ("Senior Backend Engineer", E.MID_SENIOR),
    ("Junior Python Developer", E.ENTRY), ("Praktikant Softwareentwicklung", E.INTERNSHIP),
    ("Engineering Manager", E.DIRECTOR), ("Software Engineer", None)])
def test_infer_experience(title, expected):
    assert infer_experience(title) == expected


def test_required_years_and_rejection():
    assert required_years("3-5 years of experience in Python") == 3
    assert required_years("no numbers") is None
    c = Criteria(experience=[E.ENTRY], max_required_years=2)
    assert c.full_reject(job("Software Engineer", desc="Requires 5+ years of experience")) == "years_required"
    assert c.full_reject(job("Software Engineer", desc="0-1 years of experience")) is None


def test_cheap_reject_title_company_and_seniority():
    c = Criteria(title_exclude=[r"\bsales\b"], company_exclude=["staffing"], experience=[E.ENTRY])
    assert c.cheap_reject(job("Sales Engineer")) == "title_excluded"
    assert c.cheap_reject(job("Dev", company="Acme Staffing")) == "company_excluded"
    assert c.cheap_reject(job("Senior Dev")) == "experience"
    assert c.cheap_reject(job("Dev")) is None


# ---- scoring / plan
def test_skill_coverage_scoring_and_phd_penalty():
    p = extract_profile(RESUME, "resume")
    good = job("Machine Learning Engineer Intern", desc="Requirements\n- Python\n- PyTorch\n- Docker\n- FastAPI",
               posted_date=date.today().isoformat())
    gap = job("Machine Learning Engineer Intern", desc="Requirements\n- Python\n- Spark\n- Kafka\n- Airflow",
              posted_date=date.today().isoformat())
    phd = job("Machine Learning Research Intern (PhD)", desc=good.description, posted_date=date.today().isoformat())
    sg, sp, sd = score_job(good, p), score_job(gap, p), score_job(phd, p)
    assert sg.score > sp.score and sd.score < sg.score
    assert {"Spark", "Kafka"} <= set(sp.missing_skills)


def test_plan_flags_work_authorization_and_old_postings():
    old = (date.today() - timedelta(days=45)).isoformat()
    j = job("Engineer", desc="We cannot offer visa sponsorship. Must be authorized to work.", posted_date=old)
    plan = build_plan(j, extract_profile(RESUME, "resume"))
    assert plan.verdict == "check_eligibility_first"
    assert any("authorization" in f.lower() for f in plan.red_flags)
    assert any("45 days" in f for f in plan.red_flags)


def test_plan_on_fixture_detects_ats_and_outreach():
    d = parse_detail(fixture("detail_page.html"), "1111111111")
    plan = build_plan(d, extract_profile(RESUME, "resume"))
    assert plan.channel == "external_ats" and plan.ats and plan.ats.ats == "greenhouse"
    assert "recruiters_at_company" in plan.outreach and plan.urgency in ("today", "this_week")


# ---- verify
@pytest.mark.parametrize("text,needle", [
    ("Salary: $120,000 - $150,000 per year", "120,000"),
    ("Pay range £45k to £55k", "£45k"),
    ("CTC 12-18 LPA", "12-18 LPA"),
    ("Stipend: INR 25,000 - 40,000 per month", "25,000"),
    ("Annual revenue of $1-2 billion", None),
    ("", None)])
def test_find_salary(text, needle):
    got = find_salary(text)
    assert (needle in got) if needle else got is None


def test_ghost_scoring_uses_employer_board_as_strongest_evidence():
    old = (date.today() - timedelta(days=100)).isoformat()
    j = job("Data Scientist", desc="Join our talent pool for future opportunities.", posted_date=old)
    ghost = score_ghost(j, Resolution(status="not_on_board", method="fuzzy_title", confidence=0.7,
                                       board="greenhouse", board_open_roles=40, notes=["not on board"]))
    real = score_ghost(job("Data Scientist", posted_date=date.today().isoformat()),
                       Resolution(status="matched", method="apply_url", confidence=0.97, board="greenhouse",
                                  posting=job("Data Scientist", salary="USD 100,000-120,000")))
    assert ghost.label == "likely_ghost" and real.label == "verified_listing"
    assert real.salary == "USD 100,000-120,000" and "employer" in real.salary_source
    assert score_ghost(job(posted_date=date.today().isoformat()), None).label == "no_red_flags"


# ---- ats
@pytest.mark.parametrize("url,ats_name,org", [
    ("https://boards.greenhouse.io/anthropic/jobs/5456619008", "greenhouse", "anthropic"),
    ("https://job-boards.greenhouse.io/acme/jobs/1", "greenhouse", "acme"),
    ("https://jobs.lever.co/palantir/5e1b-uuid", "lever", "palantir"),
    ("https://jobs.ashbyhq.com/openai/240d459b", "ashby", "openai"),
    ("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/X/Intern_JR1", "workday", "nvidia"),
    ("https://careers-acme.icims.com/jobs/123", "icims", None)])
def test_detect_ats(url, ats_name, org):
    r = ats.detect_ats(url)
    assert r and r.ats == ats_name and (org is None or r.org == org)


def test_detect_ats_workday_site_and_unknown():
    r = ats.detect_ats("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/X/Intern_JR1")
    assert r.site == "NVIDIAExternalCareerSite" and r.queryable
    assert ats.detect_ats("https://example.com/careers") is None


# ---- odds / gap / state
def test_odds_prefers_low_competition_and_drops_ghosts():
    p = extract_profile(RESUME, "resume")
    base = dict(desc="Requirements\n- Python\n- PyTorch", posted_date=date.today().isoformat())
    crowded = score_job(job("ML Intern", applicants="Over 200 applicants", id="a", **base), p)
    quiet = score_job(job("ML Intern", applicants="12 applicants", id="b", **base), p)
    assert evaluate(quiet).roi > evaluate(crowded).roi
    ghosty = evaluate(quiet)
    ghosty.ghost_score = 80
    assert ghosty not in sum(portfolio([ghosty]).values(), [])


def test_gap_ranks_single_missing_skill_first():
    p = profile_from_skills(["Python", "SQL"])
    jobs = [job(f"Role{i}", desc="Requirements\n- Python\n- SQL\n- Docker", id=str(i)) for i in range(3)]
    jobs.append(job("Other", desc="Requirements\n- Python\n- Spark\n- Kafka", id="9"))
    top = analyse(jobs, p)[0]
    assert top.skill == "Docker" and top.unlocks == 3 and top.proof_task


def test_state_new_detection_taste_and_followups(tmp_path):
    st = State(tmp_path / "s.db")
    a = Job(id="1", title="Backend Engineer", company="Acme", location="Berlin", url="u1")
    assert [j.id for j in st.upsert_jobs([a])] == ["1"]
    assert st.upsert_jobs([a]) == []  # already seen
    st.upsert_jobs([Job(id="2", title="Onsite Engineer", company="Globex", location="Berlin", url="u2")])
    st.mark("2", "skipped", "onsite")
    st.mark("1", "applied", followup_days=-1)  # follow-up was due yesterday
    assert [f["job_id"] for f in st.followups_due()] == ["1"]
    assert st.get_job("1").title == "Backend Engineer"
    st.mark("1", "interview")  # progress cancels the follow-up
    assert st.followups_due() == []
    baseline = st.upsert_jobs([Job(id="3", title="X", company="Old", location="", url="u3")], baseline=True)
    assert baseline == [] and "Old" not in st.first_seen_counts(7)
