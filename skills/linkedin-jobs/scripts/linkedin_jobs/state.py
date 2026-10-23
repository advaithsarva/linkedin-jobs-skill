"""Local memory (SQLite): what you've seen, applied to, skipped, and why. Stays on your machine.

Location: $LINKEDIN_JOBS_HOME or ~/.linkedin-jobs/state.db. Nothing is ever uploaded.
This is what lets the skill learn your taste and tell you what's *new* since last time.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .criteria import infer_experience, infer_work_mode, required_years
from .models import Job, JobDetails

ACTIONS = ("saved", "applied", "interview", "offer", "rejected", "skipped", "closed")
POSITIVE = {"saved", "applied", "interview", "offer"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, location TEXT, url TEXT,
  posted_date TEXT, first_seen TEXT, last_seen TEXT, seen_count INTEGER DEFAULT 1, closed_at TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, action TEXT, reason TEXT,
  ts TEXT, followup TEXT);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS watches(name TEXT PRIMARY KEY, spec TEXT);
CREATE TABLE IF NOT EXISTS companies(name TEXT PRIMARY KEY, linkedin_id TEXT, ats TEXT, org TEXT, host TEXT, site TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def home() -> Path:
    p = Path(os.environ.get("LINKEDIN_JOBS_HOME") or Path.home() / ".linkedin-jobs")
    p.mkdir(parents=True, exist_ok=True)
    return p


class State:
    def __init__(self, path: str | Path | None = None) -> None:
        self.db = sqlite3.connect(str(path or home() / "state.db"))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ---- jobs
    def upsert_jobs(self, jobs: list[Job], baseline: bool = False) -> list[Job]:
        """Record jobs; returns the ones never seen before. baseline=True records them as already-known
        history (first sight of a company board) so they don't flood the 'new' list or fake a hiring surge."""
        new: list[Job] = []
        now = _now()
        first = "1970-01-01T00:00:00+00:00" if baseline else now
        for j in jobs:
            row = self.db.execute("SELECT id FROM jobs WHERE id=?", (j.id,)).fetchone()
            data = j.model_dump_json(exclude={"description_html"})
            if row:
                self.db.execute("UPDATE jobs SET last_seen=?, seen_count=seen_count+1, data=?, closed_at=NULL "
                                "WHERE id=?", (now, data, j.id))
            else:
                self.db.execute("INSERT INTO jobs(id,source,company,title,location,url,posted_date,first_seen,"
                                "last_seen,data) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                (j.id, j.source, j.company, j.title, j.location, j.url, j.posted_date, first, now,
                                 data))
                if not baseline:
                    new.append(j)
        self.db.commit()
        return new

    def mark_closed(self, job_ids: list[str]) -> None:
        self.db.executemany("UPDATE jobs SET closed_at=? WHERE id=? AND closed_at IS NULL",
                            [(_now(), i) for i in job_ids])
        self.db.commit()

    def known_ids(self, source: str, company: str) -> list[str]:
        return [r["id"] for r in self.db.execute(
            "SELECT id FROM jobs WHERE source=? AND lower(company)=lower(?) AND closed_at IS NULL", (source, company))]

    def get_job(self, job_id: str) -> Job | None:
        r = self.db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return JobDetails.model_validate_json(r["data"]) if r else None

    def first_seen_counts(self, days: int = 7) -> dict[str, int]:
        cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return {r["company"]: r["n"] for r in self.db.execute(
            "SELECT company, COUNT(*) n FROM jobs WHERE first_seen>=? GROUP BY company", (cut,))}

    def repost_count(self, company: str, title: str) -> int:
        key = re.sub(r"\W+", "", title.lower())
        rows = self.db.execute("SELECT title FROM jobs WHERE lower(company)=lower(?)", (company,)).fetchall()
        return sum(1 for r in rows if re.sub(r"\W+", "", r["title"].lower()) == key)

    # ---- actions
    def mark(self, job_id: str, action: str, reason: str = "", followup_days: int | None = None) -> None:
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        fu = (date.today() + timedelta(days=followup_days)).isoformat() if followup_days else None
        self.db.execute("INSERT INTO actions(job_id,action,reason,ts,followup) VALUES(?,?,?,?,?)",
                        (job_id, action, reason, _now(), fu))
        self.db.commit()

    def actions_for(self, job_id: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM actions WHERE job_id=? ORDER BY id", (job_id,)).fetchall()

    def acted_ids(self, actions: tuple[str, ...] = ACTIONS) -> set[str]:
        q = ",".join("?" * len(actions))
        return {r["job_id"] for r in self.db.execute(f"SELECT DISTINCT job_id FROM actions WHERE action IN ({q})",
                                                     actions)}

    def history(self, limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            "SELECT a.action,a.reason,a.ts,a.followup,j.title,j.company,j.url,a.job_id FROM actions a "
            "LEFT JOIN jobs j ON j.id=a.job_id ORDER BY a.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def followups_due(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT a.job_id,a.followup,j.title,j.company,j.url FROM actions a LEFT JOIN jobs j ON j.id=a.job_id "
            "WHERE a.action='applied' AND a.followup IS NOT NULL AND a.followup<=? AND NOT EXISTS("
            "SELECT 1 FROM actions b WHERE b.job_id=a.job_id AND b.action IN ('interview','offer','rejected') "
            "AND b.id>a.id)", (date.today().isoformat(),)).fetchall()
        return [dict(r) for r in rows]

    # ---- key/value (profile, preferences)
    def set(self, key: str, value: object) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value)))
        self.db.commit()

    def get(self, key: str, default: object = None) -> object:
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(r["value"]) if r else default

    # ---- watches + companies
    def add_watch(self, name: str, spec: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO watches(name,spec) VALUES(?,?)", (name, json.dumps(spec)))
        self.db.commit()

    def watches(self) -> dict[str, dict]:
        return {r["name"]: json.loads(r["spec"]) for r in self.db.execute("SELECT * FROM watches")}

    def remove_watch(self, name: str) -> None:
        self.db.execute("DELETE FROM watches WHERE name=?", (name,))
        self.db.commit()

    def add_company(self, name: str, **kw: str | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO companies(name,linkedin_id,ats,org,host,site) VALUES(?,?,?,?,?,?)",
                        (name, kw.get("linkedin_id"), kw.get("ats"), kw.get("org"), kw.get("host"), kw.get("site")))
        self.db.commit()

    def companies(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM companies ORDER BY name")]

    # ---- taste learning
    def _features(self, j: Job) -> list[str]:
        d = j if isinstance(j, JobDetails) else None
        f = [f"company:{j.company.lower()}"]
        f += [f"loc:{t}" for t in re.findall(r"[a-z]{4,}", j.location.lower())[:3]]
        lvl = infer_experience(j.title, d)
        if lvl:
            f.append(f"level:{lvl.value}")
        wm = infer_work_mode(j)
        if wm:
            f.append(f"mode:{wm.value}")
        if d and d.description:
            y = required_years(d.description)
            if y is not None:
                f.append("years:" + ("0-2" if y <= 2 else "3-4" if y <= 4 else "5+"))
        return f

    def taste_model(self) -> dict[str, float]:
        """feature -> preference in [-1, 1], from your applied/saved/skipped history (smoothed)."""
        pos: dict[str, int] = {}
        neg: dict[str, int] = {}
        for r in self.db.execute("SELECT a.action, j.data FROM actions a JOIN jobs j ON j.id=a.job_id"):
            job = JobDetails.model_validate_json(r["data"])
            bucket = pos if r["action"] in POSITIVE else neg if r["action"] in ("skipped", "rejected") else None
            if bucket is None:
                continue
            for f in self._features(job):
                bucket[f] = bucket.get(f, 0) + 1
        return {f: (pos.get(f, 0) - neg.get(f, 0)) / (pos.get(f, 0) + neg.get(f, 0) + 2)
                for f in set(pos) | set(neg)}

    def taste_score(self, j: Job, model: dict[str, float] | None = None) -> tuple[float, list[str]]:
        model = model if model is not None else self.taste_model()
        hits = [(f, model[f]) for f in self._features(j) if f in model and abs(model[f]) >= 0.2]
        if not hits:
            return 0.0, []
        score = max(-1.0, min(1.0, sum(v for _, v in hits) / math.sqrt(len(hits))))
        why = [f"{'likes' if v > 0 else 'avoids'} {f.split(':', 1)[1]}" for f, v in hits[:3]]
        return score, why
