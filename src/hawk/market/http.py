"""A small, polite HTTP client with an on-disk cache."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "hawk-research/0.1 (+https://github.com/manoselvaks/hawk; academic project)"
)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class PoliteDownloader:
    """Fetch URLs at most once per ``min_interval`` seconds and cache the bytes.

    Cached responses younger than ``ttl`` are returned without touching the
    network, so re-running the collector costs the Bank of England nothing.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        min_interval: float = 2.0,
        ttl: timedelta = timedelta(hours=24),
        refresh: bool = False,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.ttl = ttl
        self.refresh = refresh
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last_request = float("-inf")

    def cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / digest

    def get(self, url: str) -> bytes:
        """Return the body of ``url``, from cache when fresh."""
        path = self.cache_path(url)
        if not self.refresh and path.exists():
            age = time.time() - path.stat().st_mtime
            if age < self.ttl.total_seconds():
                log.info("cache hit %s", url)
                return path.read_bytes()

        body = self._fetch(url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return body

    def _fetch(self, url: str) -> bytes:
        for attempt in range(1, self.max_retries + 1):
            self._wait_turn()
            log.info("GET %s (attempt %d)", url, attempt)
            response = self.session.get(url, timeout=120)
            if (
                response.status_code not in RETRY_STATUSES
                or attempt == self.max_retries
            ):
                response.raise_for_status()
                return bytes(response.content)
            time.sleep(self.min_interval * 2**attempt)
        raise AssertionError("unreachable")

    def _wait_turn(self) -> None:
        wait = self._last_request + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()
