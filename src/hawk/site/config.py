"""Site-wide constants: where it lives, who made it, and the eras shaded on charts."""

from __future__ import annotations

from dataclasses import dataclass

SITE_NAME = "Hawk"
SITE_URL = "https://manoselvaks.github.io/hawk/"  # GitHub Pages project site
REPO_URL = "https://github.com/manoselvaks/hawk"
GITHUB_PROFILE = "https://github.com/manoselvaks"
AUTHOR = "Manoj"
# TODO(Manoj): set to your LinkedIn profile URL; the About page shows the link only when set.
LINKEDIN_URL: str | None = None
BOE_URL_PREFIX = "https://www.bankofengland.co.uk/"

TAGLINE = "Reading the Bank of England's tone, 1997 to today."
DESCRIPTION = (
    "Hawk scores every Bank of England speech and set of MPC minutes since 1997 from "
    "dovish to hawkish, and tests whether tone predicted Bank Rate decisions and "
    "2-year gilt moves."
)

# Documents with at least this LLM relevance count as "about monetary policy" (the
# threshold the evaluation uses, see docs/methodology.md).
RELEVANCE_THRESHOLD = 0.5
# The tone index is a trailing (backward-looking) mean, so it never uses later documents.
TONE_WINDOW_DAYS = 182
TONE_MIN_DOCS = 3


@dataclass(frozen=True)
class Era:
    label: str
    start: str
    end: str


ERAS = [
    Era("Financial crisis", "2007-08-09", "2009-06-30"),
    Era("Brexit vote", "2016-06-23", "2016-11-30"),
    Era("COVID", "2020-03-01", "2021-06-30"),
    Era("Inflation surge", "2021-10-01", "2023-10-31"),
]
