"""Tiny on-disk cache so repeated runs and agent retries don't re-hit LinkedIn."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path


class DiskCache:
    def __init__(self, directory: str | Path, ttl_hours: float = 24.0) -> None:
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl_hours * 3600

    def _path(self, key: str) -> Path:
        return self.dir / (hashlib.sha1(key.encode()).hexdigest() + ".html")

    def get(self, key: str) -> str | None:
        p = self._path(key)
        try:
            if p.exists() and time.time() - p.stat().st_mtime < self.ttl:
                return p.read_text(encoding="utf-8")
        except OSError:
            pass
        return None

    def set(self, key: str, value: str) -> None:
        try:
            self._path(key).write_text(value, encoding="utf-8")
        except OSError:
            pass
