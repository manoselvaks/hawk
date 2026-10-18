"""A polite, caching HTTP client for the Bank of England website.

Every download is cached on disk, keyed by URL, so a run that is interrupted can
simply be restarted: anything already fetched is read back from the cache without
touching the network. Live requests identify themselves with a User-Agent, obey
robots.txt and are spaced at least ``min_interval`` seconds apart.
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.robotparser
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "hawk-research/0.1 (open-source research project; +https://github.com/manoselvaks/hawk)"
)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A URL could not be downloaded; ``status`` is the HTTP status, if there was one."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DisallowedByRobots(FetchError):
    """robots.txt forbids fetching this URL."""


class PoliteFetcher:
    """Fetch URLs with a disk cache, robots.txt checks and rate limiting."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str = USER_AGENT,
        min_interval: float = 1.0,
        max_attempts: int = 3,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache_dir = cache_dir
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self.network_requests = 0

    def cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()
        return self.cache_dir / digest[:2] / digest

    def get(self, url: str, *, use_cache: bool = True) -> bytes:
        """Return the body of ``url``, from the cache when possible."""
        path = self.cache_path(url)
        if use_cache and path.exists():
            return path.read_bytes()

        if not self.robots_for(url).can_fetch(self.user_agent, url):
            raise DisallowedByRobots(f"robots.txt disallows {url}")

        body = self._download(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)  # atomic, so a crash never leaves a half-written cache entry
        return body

    def sitemaps(self, url: str) -> list[str]:
        """Sitemap URLs advertised in the robots.txt of ``url``'s host."""
        return list(self.robots_for(url).site_maps() or [])

    def robots_for(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser = urllib.robotparser.RobotFileParser(f"{origin}/robots.txt")
            try:
                text = self._download(f"{origin}/robots.txt").decode("utf-8", "replace")
            except FetchError as exc:
                # RFC 9309: a missing robots.txt (4xx) allows everything, but an
                # unreachable one (network error or 5xx) means crawl nothing.
                missing = exc.status is not None and 400 <= exc.status < 500
                log.warning("could not read robots.txt for %s: %s", origin, exc)
                text = "" if missing else "User-agent: *\nDisallow: /"
            parser.parse(text.splitlines())
            delay = parser.crawl_delay(self.user_agent)
            if delay is not None:
                self.min_interval = max(self.min_interval, float(delay))
            self._robots[origin] = parser
        return self._robots[origin]

    def _download(self, url: str) -> bytes:
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            self.network_requests += 1
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                error, status = f"{type(exc).__name__}: {exc}", None
            else:
                status = response.status_code
                if response.status_code == 200:
                    return response.content
                error = f"HTTP {response.status_code}"
                if response.status_code not in RETRY_STATUSES:
                    break
            if attempt < self.max_attempts:
                backoff = 2.0**attempt
                log.info("%s for %s, retrying in %.0fs", error, url, backoff)
                self._sleep(backoff)
        raise FetchError(f"{error} for {url}", status)

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self.min_interval - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request = now
