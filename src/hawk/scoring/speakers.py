"""Speaker names and MPC membership.

The collector keeps speaker names as the pages print them, so one person can appear
under several spellings ("Andy Haldane", "Andrew Haldane"), and a few early PDFs give
only a first name or a title ("The Rt Hon Sir"). ``normalise_speaker`` maps these to
one canonical name, falling back to the name in the page title when the parsed
speaker is clearly incomplete.

MPC membership comes from ``data/market/mpc_members.csv``: each member's first and
last Bank Rate vote, built from the Bank's voting workbook by
``python -m hawk.scoring.mpc_members``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

MEMBERS_PATH = Path("data/market/mpc_members.csv")

# Variant spelling -> canonical name. Canonical names follow the voting workbook
# where the person sat on the MPC, so speeches and votes join on the same string.
SPEAKER_ALIASES: dict[str, str] = {
    "Andy Haldane": "Andrew Haldane",
    "Adam S. Posen": "Adam Posen",
    "Andrew Sentence": "Andrew Sentance",
    "Charlie Bean": "Charles Bean",
    "Catherine L. Mann": "Catherine L Mann",
    "Catherine Mann": "Catherine L Mann",
    "Edward George": "Eddie George",
    "Minouche Shafik": "Nemat Shafik",
    "Timothy Besley": "Tim Besley",
    "Willem H. Buiter": "Willem Buiter",
    "Don Kohn": "Donald Kohn",
    "Randall S. Kroszner": "Randall Kroszner",
    "Randy Kroszner": "Randall Kroszner",
    "Robert Jenkins": "Bob Jenkins",
    "Vicky Saporta": "Victoria Saporta",
    "Carolyn A Wilkins": "Carolyn Wilkins",
}

# Speeches whose page names no usable speaker, resolved by reading the text.
SPEAKER_OVERRIDES: dict[str, str] = {
    # Co-authored MPC paper; the 2007 Blanchflower, Saleheen and Shadforth migration paper.
    "https://www.bankofengland.co.uk/speech/2007/the-impact-of-the-recent-migration-from-"
    "eastern-europe-on-the-uk-economy": "David Blanchflower",
    # The parser picked up "Liao" from a cited paper; the text is by Mann and co-authors.
    "https://www.bankofengland.co.uk/speech/2026/october/financial-innovation-dollar-"
    "dominance-and-their-uk-monetary-policy-implications": "Catherine L Mann",
}

# Parsed "speakers" that are not a full name: honorifics, or a first name only.
_INCOMPLETE = {"the rt hon sir", "sir", "professor", "dr"}
_TITLE_SPEAKER = re.compile(
    r"(?:speech|slides|remarks|lecture|address)(?: given)? by\s+(.+)$", re.I
)
_TITLE_TAIL = re.compile(r"\s[-\u2013\u2014]\s+([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){1,3})\s*$")
_HONORIFIC = re.compile(r"^(?:the rt hon\.?\s+|sir\s+|dame\s+|dr\.?\s+|professor\s+)+", re.I)


def _tidy(name: str) -> str:
    """First line only, honorifics dropped, whitespace collapsed, alias applied."""
    first_line = name.strip().splitlines()[0] if name.strip() else ""
    cleaned = " ".join(_HONORIFIC.sub("", first_line).split())
    if cleaned.isupper():
        cleaned = cleaned.title()
    return SPEAKER_ALIASES.get(cleaned, cleaned)


def _from_title(title: str | None) -> str | None:
    if not title:
        return None
    for pattern in (_TITLE_SPEAKER, _TITLE_TAIL):
        match = pattern.search(title.strip())
        if match:
            candidate = _tidy(match.group(1))
            if len(candidate.split()) >= 2:
                return candidate
    return None


def normalise_speaker(
    speaker: str | None, title: str | None = None, url: str | None = None
) -> str | None:
    """Canonical speaker name, or ``None`` when neither the field nor the title names one.

    >>> normalise_speaker("Andy Haldane")
    'Andrew Haldane'
    >>> normalise_speaker("Catherine", "On inflation - speech by Catherine L Mann")
    'Catherine L Mann'
    """
    if url in SPEAKER_OVERRIDES:
        return SPEAKER_OVERRIDES[url]
    name = _tidy(speaker) if isinstance(speaker, str) else ""
    if len(name.split()) >= 2 and name.lower() not in _INCOMPLETE:
        return name
    return _from_title(title) or (name or None)


@dataclass(frozen=True)
class Tenure:
    member: str
    start: pd.Timestamp  # day after the decision before the member's first vote
    end: pd.Timestamp | None  # day before the decision after their last vote; None = serving


def load_tenures(
    members_path: Path = MEMBERS_PATH, decisions: pd.DataFrame | None = None
) -> list[Tenure]:
    """Read membership windows from the members file and the decision calendar.

    A member's appointment falls somewhere between the meeting before their first
    vote and that first vote, and their term ends between their last vote and the
    next meeting. The window is taken as that whole span, so a speech given in the
    weeks after appointment but before the first vote counts as an MPC speech.
    """
    members = pd.read_csv(members_path, parse_dates=["first_vote", "last_vote"])
    if decisions is None:
        decisions = pd.read_parquet("data/market/mpc_decisions.parquet")
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(decisions["date"]).unique()))
    latest = dates.max()
    tenures = []
    for row in members.to_dict("records"):
        first, last = pd.Timestamp(row["first_vote"]), pd.Timestamp(row["last_vote"])
        before = dates[dates < first]
        after = dates[dates > last]
        start = before.max() + pd.Timedelta(days=1) if len(before) else pd.Timestamp("1997-05-06")
        end: pd.Timestamp | None
        if last >= latest:
            end = None
        elif len(after):
            end = after.min() - pd.Timedelta(days=1)
        else:
            end = last
        tenures.append(Tenure(_tidy(str(row["member"])), start, end))
    return tenures


def is_mpc_member(speaker: str | None, when: pd.Timestamp, tenures: list[Tenure]) -> bool:
    """Whether ``speaker`` (canonical name) sat on the MPC on day ``when``."""
    if not speaker or pd.isna(when):
        return False
    return any(
        t.member == speaker and t.start <= when and (t.end is None or when <= t.end)
        for t in tenures
    )
