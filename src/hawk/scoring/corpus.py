"""Load speeches and minutes into one table of documents ready to score.

``load_documents`` returns one row per document with cleaned text, a canonical
speaker name, the MPC-membership flag and the look-ahead-safe ``date``. Documents
that cannot be scored are dropped with a logged warning saying why:

* no ``published_date`` (we would not know when the market could have read it);
* under 1,000 characters of text (video or slide pages without a transcript, and
  the August 1997 minutes, a scan with no text layer).

The raw parquet files are only read, never written.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd

from hawk.scoring import speakers
from hawk.scoring.textprep import clean_text, policy_density

log = logging.getLogger(__name__)

SPEECHES_PATH = Path("data/speeches.parquet")
MINUTES_PATH = Path("data/minutes.parquet")
MIN_CHARS = 1_000

COLUMNS = [
    "doc_id",
    "kind",
    "url",
    "title",
    "speaker",
    "role",
    "is_mpc_member",
    "date",
    "speech_date",
    "meeting_date",
    "n_chars",
    "policy_density",
    "text",
]


def doc_id(kind: str, url: str) -> str:
    """Short stable identifier, e.g. ``speech-3f9a0c1b2d``."""
    return f"{kind}-{hashlib.sha256(url.encode()).hexdigest()[:10]}"


def _exclusion_reason(row: pd.Series) -> str | None:
    if pd.isna(row["date"]):
        return "no published_date, so its timing is unknown"
    if len(row["raw_text"] or "") < MIN_CHARS:
        return f"text under {MIN_CHARS:,} characters ({len(row['raw_text'] or '')})"
    return None


def build_documents(
    speeches: pd.DataFrame,
    minutes: pd.DataFrame,
    tenures: list[speakers.Tenure],
) -> pd.DataFrame:
    """Combine, clean and filter the two tables (pure function, for tests)."""
    sp = pd.DataFrame(
        {
            "kind": "speech",
            "url": speeches["url"],
            "title": speeches["title"],
            "speaker": [
                speakers.normalise_speaker(s, t, u)
                for s, t, u in zip(
                    speeches["speaker"], speeches["title"], speeches["url"], strict=True
                )
            ],
            "role": speeches["role"],
            "date": pd.to_datetime(speeches["published_date"]),
            "speech_date": pd.to_datetime(speeches["speech_date"]),
            "meeting_date": pd.NaT,
            "raw_text": speeches["text"],
        }
    )
    mi = pd.DataFrame(
        {
            "kind": "minutes",
            "url": minutes["url"],
            "title": minutes["title"],
            "speaker": None,
            "role": None,
            "date": pd.to_datetime(minutes["published_date"]),
            "speech_date": pd.NaT,
            "meeting_date": pd.to_datetime(minutes["meeting_date"]),
            "raw_text": minutes["text"],
        }
    )
    docs = pd.concat([sp, mi], ignore_index=True)

    reasons = [_exclusion_reason(row) for _, row in docs.iterrows()]
    for row, reason in zip(docs.itertuples(), reasons, strict=True):
        if reason:
            log.warning("excluded %s %s: %s", row.kind, row.url, reason)
    docs = docs[[r is None for r in reasons]].reset_index(drop=True)

    docs["doc_id"] = [doc_id(k, u) for k, u in zip(docs["kind"], docs["url"], strict=True)]
    # Minutes speak for the whole committee, so the per-speaker flag does not apply.
    docs["is_mpc_member"] = pd.array(
        [
            speakers.is_mpc_member(s, d, tenures) if k == "speech" else pd.NA
            for k, s, d in zip(docs["kind"], docs["speaker"], docs["date"], strict=True)
        ],
        dtype="boolean",
    )
    docs["text"] = docs["raw_text"].map(clean_text)
    docs["n_chars"] = docs["text"].str.len()
    docs["policy_density"] = docs["text"].map(policy_density).round(3)
    return docs[COLUMNS].sort_values(["date", "kind", "url"]).reset_index(drop=True)


def load_documents(
    speeches_path: Path = SPEECHES_PATH,
    minutes_path: Path = MINUTES_PATH,
    members_path: Path = speakers.MEMBERS_PATH,
) -> pd.DataFrame:
    """Every scorable document, cleaned. See the module docstring for exclusions."""
    tenures = speakers.load_tenures(members_path)
    docs = build_documents(pd.read_parquet(speeches_path), pd.read_parquet(minutes_path), tenures)
    log.info(
        "loaded %d documents (%d speeches, %d of them by MPC members; %d minutes)",
        len(docs),
        (docs["kind"] == "speech").sum(),
        docs["is_mpc_member"].fillna(False).sum(),
        (docs["kind"] == "minutes").sum(),
    )
    return docs
