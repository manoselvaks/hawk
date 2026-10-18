"""Find speech and MPC-minutes URLs by walking the Bank of England's XML sitemaps.

The sitemaps are discovered from robots.txt (with ``/sitemap.xml`` as a fallback),
which is the cleanest and most complete way to enumerate the site without
paging through search listings.
"""

from __future__ import annotations

import gzip
import logging
import re
from collections import deque
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from hawk.speeches.fetch import FetchError, PoliteFetcher

log = logging.getLogger(__name__)

BASE_URL = "https://www.bankofengland.co.uk"
FIRST_YEAR = 1997

SPEECH_URL = re.compile(r"^https?://www\.bankofengland\.co\.uk/speech/(?P<year>\d{4})/[^?#]+$")
_MONTH_SLUG = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
# Since August 2015 the minutes are published with the Monetary Policy Summary.
MINUTES_URL = re.compile(
    r"^https?://www\.bankofengland\.co\.uk/monetary-policy-summary-and-minutes/"
    r"(?P<year>\d{4})/[^?#]+$"
)
# Earlier MPC minutes live under /minutes/, next to those of a dozen other committees
# (Court, FXJSC, ...), so only the MPC slugs are matched: "monetary-policy-committee-june-1997",
# "minutes-april-2003" (2003-05) and "monetary-policy-committee-18-september-2001".
OLD_MINUTES_URL = re.compile(
    r"^https?://www\.bankofengland\.co\.uk/minutes/(?P<year>\d{4})/"
    rf"(?:monetary-policy-committee|minutes)-(?:\d{{1,2}}-)?(?:{_MONTH_SLUG})-\d{{4}}$"
)


@dataclass
class Sitemap:
    """The contents of one sitemap file: links to other sitemaps, and page URLs."""

    sitemaps: list[str] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)


@dataclass
class Discovered:
    speeches: list[str] = field(default_factory=list)
    minutes: list[str] = field(default_factory=list)


def parse_sitemap(body: bytes) -> Sitemap:
    """Parse a sitemap or sitemap index (optionally gzipped)."""
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    soup = BeautifulSoup(body, "xml")
    result = Sitemap()
    for loc in soup.select("sitemap > loc"):
        result.sitemaps.append(loc.get_text(strip=True))
    for loc in soup.select("url > loc"):
        result.pages.append(loc.get_text(strip=True))
    return result


def classify(url: str) -> str | None:
    """Return ``"speech"``, ``"minutes"`` or ``None`` for an arbitrary site URL."""
    url = url.rstrip("/")
    patterns = (("speech", SPEECH_URL), ("minutes", MINUTES_URL), ("minutes", OLD_MINUTES_URL))
    for kind, pattern in patterns:
        match = pattern.match(url)
        if match and int(match["year"]) >= FIRST_YEAR:
            return kind
    return None


def discover(fetcher: PoliteFetcher, roots: list[str] | None = None) -> Discovered:
    """Walk the sitemap tree breadth-first and collect speech and minutes URLs.

    Sitemaps are always re-downloaded (never served from the cache) so that a
    re-run picks up newly published speeches.
    """
    queue = deque(roots or fetcher.sitemaps(BASE_URL) or [f"{BASE_URL}/sitemap.xml"])
    seen: set[str] = set()
    speeches: set[str] = set()
    minutes: set[str] = set()

    while queue:
        sitemap_url = queue.popleft()
        if sitemap_url in seen:
            continue
        seen.add(sitemap_url)
        try:
            sitemap = parse_sitemap(fetcher.get(sitemap_url, use_cache=False))
        except FetchError as exc:
            log.warning("skipping sitemap %s: %s", sitemap_url, exc)
            continue
        queue.extend(sitemap.sitemaps)
        for page in sitemap.pages:
            kind = classify(page)
            if kind == "speech":
                speeches.add(page.rstrip("/"))
            elif kind == "minutes":
                minutes.add(page.rstrip("/"))

    log.info(
        "read %d sitemaps: %d speech URLs, %d minutes URLs",
        len(seen),
        len(speeches),
        len(minutes),
    )
    return Discovered(speeches=sorted(speeches), minutes=sorted(minutes))
