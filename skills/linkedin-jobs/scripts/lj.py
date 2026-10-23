# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx>=0.27", "beautifulsoup4>=4.12", "lxml>=5", "pydantic>=2", "typer>=0.12"]
# ///
"""Entry point for the linkedin-jobs skill.

Run with:  uv run lj.py <command> ...     (installs dependencies automatically)
      or:  python lj.py <command> ...     (after: pip install httpx beautifulsoup4 lxml pydantic typer)
"""
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252 and garble non-ASCII
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from linkedin_jobs.cli import app  # noqa: E402

if __name__ == "__main__":
    app()
