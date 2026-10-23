"""Polite async HTTP client for LinkedIn's public guest endpoints.

Built in: minimum delay with jitter between requests, bounded concurrency, exponential
backoff honouring Retry-After on 429/403/999/5xx, optional disk cache, optional proxy.
"""
from __future__ import annotations

import asyncio
import json
import random
import time

import httpx

from .cache import DiskCache
from .config import Config, load_config

BASE = "https://www.linkedin.com/jobs-guest"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]
_RETRYABLE = {403, 429, 999}


class RateLimitedError(RuntimeError):
    """LinkedIn kept refusing after all retries. Slow down, wait, or use a proxy."""


class LinkedInClient:
    def __init__(
        self,
        config: Config | None = None,
        *,
        min_delay: float | None = None,
        concurrency: int | None = None,
        proxy: str | None = None,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        cfg = config or load_config()
        self.config = cfg
        self.min_delay = cfg.min_delay if min_delay is None else min_delay
        self.max_retries = cfg.max_retries
        self._concurrency = concurrency or cfg.concurrency
        self._sem: asyncio.Semaphore | None = None  # created lazily inside the running loop
        self._lock: asyncio.Lock | None = None
        self._last = 0.0
        self.cache = DiskCache(cfg.cache_dir, cfg.cache_ttl_hours) if cfg.cache_dir else None
        self.requests_made = 0
        self._mem: dict[str, str] = {}  # in-memory page cache for this client's lifetime
        self._http = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, proxy=proxy or cfg.proxy, transport=transport,
            headers={"Accept-Language": "en-US,en;q=0.9", "Accept": "text/html,application/xhtml+xml,application/json"},
        )

    async def __aenter__(self) -> "LinkedInClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _pace(self) -> None:
        self._lock = self._lock or asyncio.Lock()
        async with self._lock:
            wait = self._last + self.min_delay + random.uniform(0, self.min_delay * 0.5) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()

    async def get(self, path: str, params: dict[str, str] | None = None, *, cache: bool = False) -> str | None:
        """GET a LinkedIn guest endpoint. Returns the body, or None on a definitive 404/410 (job removed)."""
        return await self.fetch(f"{BASE}/{path}", params, cache=cache)

    async def fetch(self, url: str, params: dict[str, str] | None = None, *, method: str = "GET",
                    json_body: dict | None = None, cache: bool = False) -> str | None:
        """Paced, retried request to any URL (LinkedIn guest endpoints and public ATS job-board APIs)."""
        key = f"{method} {url}?" + json.dumps([params or {}, json_body or {}], sort_keys=True)
        if cache and key in self._mem:
            return self._mem[key] or None
        if cache and self.cache and (hit := self.cache.get(key)) is not None:
            self._mem[key] = hit
            return hit or None
        self._sem = self._sem or asyncio.Semaphore(self._concurrency)
        async with self._sem:
            for attempt in range(self.max_retries + 1):
                await self._pace()
                self.requests_made += 1
                try:
                    r = await self._http.request(method, url, params=params, json=json_body,
                                                 headers={"User-Agent": random.choice(USER_AGENTS)})
                except httpx.TransportError:
                    r = None
                if r is not None:
                    if r.status_code == 200:
                        self._store(key, r.text, cache)
                        return r.text
                    if r.status_code in (404, 410):
                        self._store(key, "", cache)
                        return None
                    if r.status_code not in _RETRYABLE and r.status_code < 500:
                        raise httpx.HTTPStatusError(f"HTTP {r.status_code} for {url}", request=r.request, response=r)
                if attempt == self.max_retries:
                    break
                ra = r.headers.get("Retry-After") if r is not None else None
                delay = float(ra) if ra and ra.isdigit() else 2 ** (attempt + 1)
                await asyncio.sleep(min(delay, 60) + random.uniform(0, 1))
        raise RateLimitedError(
            "The server is rate limiting this IP (HTTP 429/403/999). Wait a few minutes, raise min_delay, "
            "lower concurrency, enable cache_dir, or set LINKEDIN_JOBS_PROXY."
        )

    def _store(self, key: str, value: str, cache: bool) -> None:
        if cache:
            self._mem[key] = value
            if self.cache:
                self.cache.set(key, value)
