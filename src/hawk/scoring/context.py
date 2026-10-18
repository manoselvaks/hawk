"""Era and policy context of a document, used to stratify samples.

* **Era**: pre-2008, 2008-2015, 2016-2021, 2022+ (by publication date). Roughly: the
  inflation-targeting decade, the crisis and zero-bound years, Brexit and Covid,
  and the post-2021 inflation surge.
* **Policy context**: whether the relevant MPC decision was a hike, cut or hold.
  For a speech it is the next decision announced after the speech was published;
  for minutes it is the decision those minutes record.

The context uses information from after the document (the next decision), so it is
only for choosing a balanced sample to label and must never be used as a feature
in the prediction tests.
"""

from __future__ import annotations

import pandas as pd

ERAS: list[tuple[str, pd.Timestamp, pd.Timestamp]] = [
    ("pre-2008", pd.Timestamp("1997-01-01"), pd.Timestamp("2007-12-31")),
    ("2008-2015", pd.Timestamp("2008-01-01"), pd.Timestamp("2015-12-31")),
    ("2016-2021", pd.Timestamp("2016-01-01"), pd.Timestamp("2021-12-31")),
    ("2022+", pd.Timestamp("2022-01-01"), pd.Timestamp("2100-01-01")),
]
ERA_NAMES = [name for name, _, _ in ERAS]
CONTEXTS = ["hike", "cut", "hold"]


def era(date: pd.Timestamp) -> str:
    for name, start, end in ERAS:
        if start <= date <= end:
            return name
    raise ValueError(f"date {date} is outside every era")


def next_decision(date: pd.Timestamp, decisions: pd.DataFrame) -> str | None:
    """Decision type at the first MPC announcement strictly after ``date``."""
    later = decisions[decisions["date"] > date]
    return None if later.empty else str(later.sort_values("date").iloc[0]["decision"])


def minutes_decision(
    meeting_date: pd.Timestamp | None, published_date: pd.Timestamp, decisions: pd.DataFrame
) -> str | None:
    """Decision recorded by a set of minutes.

    Uses the announcement within two days of the meeting's final day (the MPC has
    announced the day after it finished since 2015); without a meeting date, the
    latest announcement on or before publication.
    """
    if meeting_date is not None and pd.notna(meeting_date):
        window = decisions[
            (decisions["date"] >= meeting_date)
            & (decisions["date"] <= meeting_date + pd.Timedelta(days=2))
        ]
        if not window.empty:
            return str(window.sort_values("date").iloc[0]["decision"])
    earlier = decisions[decisions["date"] <= published_date]
    return None if earlier.empty else str(earlier.sort_values("date").iloc[-1]["decision"])


def add_context(docs: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``docs`` with ``era`` and ``policy_context`` columns."""
    decisions = decisions.assign(date=pd.to_datetime(decisions["date"]))
    out = docs.copy()
    out["era"] = out["date"].map(era)
    out["policy_context"] = [
        minutes_decision(row["meeting_date"], row["date"], decisions)
        if row["kind"] == "minutes"
        else next_decision(row["date"], decisions)
        for row in out.to_dict("records")
    ]
    return out
