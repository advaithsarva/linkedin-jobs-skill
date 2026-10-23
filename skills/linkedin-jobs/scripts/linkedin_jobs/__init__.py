"""LinkedIn job scraper (no login, no API key): library, CLI and MCP server."""
from .client import LinkedInClient, RateLimitedError
from .filters import ExperienceLevel, JobType, TimePosted, WorkMode
from .models import Job, JobDetails
from .scraper import get_job, get_jobs, search_jobs

__all__ = [
    "ExperienceLevel", "Job", "JobDetails", "JobType", "LinkedInClient", "RateLimitedError",
    "TimePosted", "WorkMode", "get_job", "get_jobs", "search_jobs",
]
__version__ = "0.1.0"
