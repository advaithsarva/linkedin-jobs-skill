from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence

from .models import Job


def to_json(jobs: Sequence[Job]) -> str:
    return json.dumps([j.model_dump() for j in jobs], ensure_ascii=False, indent=2)


def to_jsonl(jobs: Sequence[Job]) -> str:
    return "\n".join(json.dumps(j.model_dump(), ensure_ascii=False) for j in jobs)


def to_csv(jobs: Sequence[Job]) -> str:
    if not jobs:
        return ""
    rows = [j.model_dump(exclude={"description_html"}) for j in jobs]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def render(jobs: Sequence[Job], fmt: str) -> str:
    try:
        return {"json": to_json, "jsonl": to_jsonl, "csv": to_csv}[fmt](jobs)
    except KeyError:
        raise ValueError(f"Unknown format {fmt!r}; use json, jsonl or csv") from None
