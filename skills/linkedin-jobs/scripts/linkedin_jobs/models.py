from __future__ import annotations

from pydantic import BaseModel, Field


class Job(BaseModel):
    """A job card from search results."""

    id: str
    title: str
    company: str
    company_url: str | None = None
    location: str
    url: str
    posted_date: str | None = Field(None, description="ISO date (YYYY-MM-DD) from the card")
    salary: str | None = None
    easy_apply_hint: bool = False
    early_applicant: bool = False
    source: str = Field("linkedin", description="linkedin | greenhouse | lever | ashby | workday")


class JobDetails(Job):
    """A job card plus the full posting page."""

    description: str = ""
    description_html: str = ""
    posted_text: str | None = Field(None, description='Relative text, e.g. "2 days ago"')
    applicants: str | None = None
    seniority_level: str | None = None
    employment_type: str | None = None
    job_function: str | None = None
    industries: str | None = None
    apply_url: str | None = Field(None, description="External apply link when the job applies off LinkedIn")
