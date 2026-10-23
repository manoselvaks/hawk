"""The no-look-ahead rule: a decision's features use only documents published strictly
before its announcement, and never the minutes of its own meeting."""

from __future__ import annotations

import pandas as pd
import pytest

from hawk.analysis import dataset as ds
from tests.analysis.conftest import doc, scores_frame


def test_window_excludes_announcement_day_and_later(decisions: pd.DataFrame) -> None:
    scores = scores_frame(
        [
            doc("s1", "2022-03-10", 1.0),  # before the 17 March decision: used
            doc("s2", "2022-03-17", -2.0),  # announcement day: not used
            doc("s3", "2022-03-20", -2.0),  # after: not used
        ]
    )
    m = ds.meeting_features(scores, decisions).set_index("date")
    row = m.loc[pd.Timestamp("2022-03-17")]
    assert row["n_docs"] == 1 and row["tone"] == pytest.approx(1.0)


def test_own_minutes_never_used_even_if_published_before(decisions: pd.DataFrame) -> None:
    # Minutes of the 17 March meeting with a (hypothetical) early publication date,
    # and the previous meeting's minutes, which are allowed.
    scores = scores_frame(
        [
            doc("m-own", "2022-03-16", 2.0, kind="minutes", meeting="2022-03-16"),
            doc("m-prev", "2022-02-17", -1.0, kind="minutes", meeting="2022-02-02"),
        ]
    )
    m = ds.meeting_features(scores, decisions).set_index("date")
    row = m.loc[pd.Timestamp("2022-03-17")]
    assert row["n_docs"] == 1 and row["tone"] == pytest.approx(-1.0)


def test_minutes_map_to_their_decision(decisions: pd.DataFrame) -> None:
    minutes = scores_frame(
        [
            doc("a", "2022-03-17", 0.0, kind="minutes", meeting="2022-03-16"),  # Wed -> Thu
            doc("b", "2022-02-16", 0.0, kind="minutes", meeting="2022-02-03"),  # same day
            doc("c", "2022-03-20", 0.0, kind="minutes"),  # no meeting date
        ]
    )
    got = ds.minutes_decision_dates(minutes, decisions["date"])
    assert list(got) == [
        pd.Timestamp("2022-03-17"),
        pd.Timestamp("2022-02-03"),
        pd.Timestamp("2022-03-17"),
    ]


def test_window_starts_at_previous_decision(decisions: pd.DataFrame) -> None:
    scores = scores_frame([doc("old", "2022-01-20", 2.0), doc("new", "2022-04-01", -1.0)])
    m = ds.meeting_features(scores, decisions).set_index("date")
    may = m.loc[pd.Timestamp("2022-05-05")]
    assert may["n_docs"] == 1 and may["tone"] == pytest.approx(-1.0)
    # The empty March window carries February's value forward, which is still past data.
    mar = m.loc[pd.Timestamp("2022-03-17")]
    assert bool(mar["tone_empty"]) and mar["tone"] == pytest.approx(2.0)
    assert may["tone_change"] == pytest.approx(-3.0)


def test_relevance_filter_and_mpc_only(decisions: pd.DataFrame) -> None:
    scores = scores_frame(
        [
            doc("in", "2022-03-01", 1.0),
            doc("low", "2022-03-02", -2.0, relevance=0.4),
            doc("outsider", "2022-03-03", -1.0, member=False),
        ]
    )
    m = ds.meeting_features(scores, decisions).set_index("date")
    row = m.loc[pd.Timestamp("2022-03-17")]
    assert row["n_docs"] == 2 and row["tone"] == pytest.approx(0.0)
    assert row["tone_mpc"] == pytest.approx(1.0)


def test_features_unchanged_by_future_documents(decisions: pd.DataFrame) -> None:
    """Adding documents published on or after an announcement never changes its row."""
    base = [doc("a", "2022-01-10", 0.5), doc("b", "2022-02-20", -0.5)]
    future = [
        doc("f1", "2022-03-17", 2.0),
        doc("f2", "2022-04-30", 2.0),
        doc("f3", "2022-03-17", 2.0, kind="minutes", meeting="2022-03-16"),
    ]
    cols = ["tone", "tone_change", "tone_mpc", "tone_w", "n_docs"]
    before = ds.meeting_features(scores_frame(base), decisions)
    after = ds.meeting_features(scores_frame(base + future), decisions)
    pd.testing.assert_frame_equal(before.loc[:1, cols], after.loc[:1, cols])


def test_market_features_use_previous_close(decisions: pd.DataFrame) -> None:
    yields = pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-03-16", "2022-03-17"]).astype("datetime64[ns]"),
            "gilt_2y": [1.0, 9.0],
        }
    )
    m = ds.add_market_features(
        ds.meeting_features(scores_frame([doc("a", "2022-01-01", 0.0)]), decisions), yields
    )
    row = m.set_index("date").loc[pd.Timestamp("2022-03-17")]
    assert row["gilt_2y_before"] == pytest.approx(1.0)  # not the announcement-day close
    assert row["spread_2y"] == pytest.approx(0.5)
