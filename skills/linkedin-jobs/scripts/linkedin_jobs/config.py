"""User configuration: defaults, blocklists, custom skills, scoring weights.

Resolution order (later wins): built-in defaults < config file < environment variables < explicit arguments.
Config file: $LINKEDIN_JOBS_CONFIG, else ./linkedin-jobs.toml, else ~/.config/linkedin-jobs/config.toml.
See examples/linkedin-jobs.toml.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    try:
        import tomli as tomllib
    except ImportError:  # config file is optional; env vars still work
        tomllib = None


class Weights(BaseModel):
    skills: float = 0.55
    title: float = 0.25
    seniority: float = 0.12
    recency: float = 0.08


class Config(BaseModel):
    min_delay: float = Field(0.5, description="Minimum seconds between requests (~2 req/s; raise if you get 429s)")
    concurrency: int = 4
    max_retries: int = 4
    proxy: str | None = None
    cache_dir: str | None = Field(None, description="Disk cache for job pages; None disables")
    cache_ttl_hours: float = 24.0
    default_location: str = ""
    max_description_chars: int = 4000
    max_scan: int = Field(300, description="Max cards inspected per search when filtering client-side")
    blocked_companies: list[str] = []
    blocked_title_patterns: list[str] = []
    extra_skills: dict[str, list[str]] = Field(
        default_factory=dict, description='Custom skills: {"CanonicalName": ["alias", ...]}')
    weights: Weights = Weights()


def _config_path() -> Path | None:
    for c in (os.environ.get("LINKEDIN_JOBS_CONFIG"), "linkedin-jobs.toml",
              str(Path.home() / ".config" / "linkedin-jobs" / "config.toml")):
        if c and Path(c).is_file():
            return Path(c)
    return None


_cached: Config | None = None


def load_config(reload: bool = False) -> Config:
    global _cached
    if _cached is not None and not reload:
        return _cached
    data: dict = {}
    path = _config_path()
    if path and tomllib:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    env = os.environ
    mapping = {"LINKEDIN_JOBS_DELAY": ("min_delay", float), "LINKEDIN_JOBS_CONCURRENCY": ("concurrency", int),
               "LINKEDIN_JOBS_PROXY": ("proxy", str), "LINKEDIN_JOBS_CACHE_DIR": ("cache_dir", str),
               "LINKEDIN_JOBS_LOCATION": ("default_location", str)}
    for var, (key, cast) in mapping.items():
        if env.get(var):
            data[key] = cast(env[var])
    _cached = Config(**data)
    return _cached
