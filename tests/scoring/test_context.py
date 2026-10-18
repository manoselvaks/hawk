from __future__ import annotations

import pandas as pd
import pytest

from hawk.scoring.context import add_context, era, minutes_decision, next_decision


def test_era_boundaries() -> None:
    assert era(pd.Timestamp("2007-12-31")) == "pre-2008"
    assert era(pd.Timestamp("2008-01-01")) == "2008-2015"
    assert era(pd.Timestamp("2021-12-31")) == "2016-2021"
    assert era(pd.Timestamp("2026-10-01")) == "2022+"
    with pytest.raises(ValueError):
        era(pd.Timestamp("1990-01-01"))


def test_next_decision_is_strictly_after(decisions: pd.DataFrame) -> None:
    assert next_decision(pd.Timestamp("2021-11-04"), decisions) == "hike"
    assert next_decision(pd.Timestamp("2021-11-01"), decisions) == "hold"
    assert next_decision(pd.Timestamp("2023-01-01"), decisions) is None


def test_minutes_decision(decisions: pd.DataFrame) -> None:
    # Meeting ended on the Wednesday, announced on the Thursday.
    assert (
        minutes_decision(pd.Timestamp("2021-11-03"), pd.Timestamp("2021-11-04"), decisions)
        == "hold"
    )
    # No meeting date: latest announcement on or before publication.
    assert minutes_decision(None, pd.Timestamp("2022-02-10"), decisions) == "hike"


def test_add_context(decisions: pd.DataFrame) -> None:
    docs = pd.DataFrame(
        {
            "kind": ["speech", "minutes"],
            "date": pd.to_datetime(["2021-11-20", "2021-11-04"]),
            "meeting_date": [pd.NaT, pd.Timestamp("2021-11-03")],
        }
    )
    out = add_context(docs, decisions)
    assert list(out["policy_context"]) == ["hike", "hold"]
    assert list(out["era"]) == ["2016-2021", "2016-2021"]
