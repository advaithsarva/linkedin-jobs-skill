"""Skill-gap ROI from live postings: which missing skill unlocks the most jobs, and what to build to prove it."""
from __future__ import annotations

from pydantic import BaseModel

from .models import JobDetails
from .profile import Profile, extract_profile
from .skills import GENERIC_SKILLS


class GapItem(BaseModel):
    skill: str
    demand_pct: float  # % of analysed postings that require it
    unlocks: int  # postings where this is your ONLY missing required skill
    closer: int  # postings where it is one of two missing
    example_titles: list[str] = []
    proof_task: str = ""


# concrete, small, portfolio-grade tasks. Anything missing falls back to a generic template.
PROOF: dict[str, str] = {
    "Docker": "Containerise one of your existing projects with a multi-stage Dockerfile + docker-compose; "
              "README shows image size before/after.",
    "Kubernetes": "Deploy a small service to a local kind/minikube cluster with a Deployment, Service and "
                  "readiness probe; document how you rolled out an update.",
    "SQL": "Take a public dataset, write 10 analytical queries (window functions, CTEs), and publish them with "
           "the question each answers.",
    "AWS": "Deploy a small app on AWS (EC2/Lambda + S3), and write down the monthly cost and how you secured it.",
    "RAG": "Build a retrieval-augmented Q&A over a document set you know, with an eval of 30 questions and a "
           "hit-rate number.",
    "LangChain": "Rebuild a tiny pipeline in LangChain and in plain Python; write down what the framework bought you.",
    "PyTorch": "Reimplement a small paper result in PyTorch and report a metric next to the paper's.",
    "React": "Ship a small data-driven React app (routing, state, API calls) with a public demo link.",
    "TypeScript": "Convert one JS project to strict TypeScript and note the bugs the compiler caught.",
    "Excel": "Build a dashboard workbook (pivot tables, lookups, a scenario toggle) from a public dataset.",
    "Tableau": "Publish a dashboard to Tableau Public answering one business question end to end.",
    "Power BI": "Publish a report with a star-schema model and 3 DAX measures; explain each in the README.",
    "Terraform": "Describe a small cloud stack in Terraform with remote state; destroy and recreate it from scratch.",
    "Git": "Contribute one reviewed pull request to an open-source project, however small.",
    "CI/CD": "Add a pipeline to a repo that lints, tests and deploys on merge; show the green run.",
    "Statistics": "Run an A/B-test analysis on a public dataset: power calc, test choice, effect size, caveats.",
}


def proof_task(skill: str) -> str:
    return PROOF.get(skill) or f"Ship one small finished {skill} project with a README that states a measurable result."


def analyse(jobs: list[JobDetails], profile: Profile, *, top: int = 8) -> list[GapItem]:
    """Rank missing skills by how many analysed postings each one would unlock."""
    have = set(profile.skills)
    stats: dict[str, dict] = {}
    n_jobs = 0
    for j in jobs:
        if not j.description:
            continue
        n_jobs += 1
        jp = extract_profile(j.description, "jd")
        req = jp.required_skills or list(jp.skills)
        missing = [s for s in req if s not in have]
        for s in req:
            d = stats.setdefault(s, {"req": 0, "unlocks": 0, "closer": 0, "titles": []})
            d["req"] += 1
        for s in missing:
            d = stats[s]
            if len(missing) == 1:
                d["unlocks"] += 1
                if len(d["titles"]) < 3:
                    d["titles"].append(f"{j.title} @ {j.company}")
            elif len(missing) == 2:
                d["closer"] += 1
    items = [GapItem(skill=s, demand_pct=round(100 * d["req"] / max(n_jobs, 1), 1), unlocks=d["unlocks"],
                     closer=d["closer"], example_titles=d["titles"], proof_task=proof_task(s))
             for s, d in stats.items() if s not in have and s not in GENERIC_SKILLS]
    items.sort(key=lambda g: (-g.unlocks, -g.closer, -g.demand_pct))
    return items[:top]
