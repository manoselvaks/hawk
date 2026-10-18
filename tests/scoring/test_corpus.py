from __future__ import annotations

import logging

import pandas as pd
import pytest

from hawk.scoring.corpus import build_documents
from hawk.scoring.speakers import Tenure

LONG = "Inflation is above target. Bank of England Page 2\n" + "The MPC raised Bank Rate. " * 60


def speeches() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "url": ["u1", "u2", "u3", "u4"],
            "title": ["A - speech by Andy Haldane", "B", "C", "D"],
            "speaker": ["Andy Haldane", "Sam Woods", "Andy Haldane", "X Y"],
            "role": [None] * 4,
            "speech_date": pd.Series([pd.NaT] * 4, dtype="datetime64[ns]"),
            "published_date": [pd.Timestamp("2016-01-01")] * 2
            + [pd.NaT, pd.Timestamp("2016-01-01")],
            "text": [LONG, LONG, LONG, "too short"],
        }
    )


def minutes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "url": ["m1"],
            "title": ["Minutes"],
            "meeting_date": pd.to_datetime(["2016-01-13"]),
            "published_date": pd.to_datetime(["2016-01-14"]),
            "text": [LONG],
        }
    )


def test_build_documents(tenures: list[Tenure], caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        docs = build_documents(speeches(), minutes(), tenures)
    assert list(docs["url"]) == ["u1", "u2", "m1"]
    assert "no published_date" in caplog.text and "under 1,000 characters" in caplog.text
    by_url = docs.set_index("url")
    assert by_url.loc["u1", "speaker"] == "Andrew Haldane"
    assert bool(by_url.loc["u1", "is_mpc_member"]) is True
    assert bool(by_url.loc["u2", "is_mpc_member"]) is False
    assert pd.isna(by_url.loc["m1", "is_mpc_member"])
    assert "Page 2" not in by_url.loc["u1", "text"]
    assert by_url.loc["u1", "doc_id"].startswith("speech-")
