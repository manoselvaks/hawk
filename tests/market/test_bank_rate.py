from __future__ import annotations

import pandas as pd
import pytest

from hawk.market import bank_rate

START = pd.Timestamp("1997-01-01")


def test_parse_bank_rate_table(rate_history: pd.Series) -> None:
    assert rate_history.index.is_monotonic_increasing
    # Two-digit years on the page: "30 Oct 96" is 1996, "19 Mar 20" is 2020.
    assert rate_history.index[0] == pd.Timestamp("1996-10-30")
    assert rate_history.loc["2020-03-19"] == pytest.approx(0.1)
    assert rate_history.loc["2023-08-03"] == pytest.approx(5.25)


def test_parse_bank_rate_table_rejects_other_pages() -> None:
    with pytest.raises(ValueError, match="no Bank Rate table"):
        bank_rate.parse_bank_rate_table("<html><title>Error</title></html>")
    wrong = '<table id="stats-table"><tr><th>Date</th><th>Yield</th></tr></table>'
    with pytest.raises(ValueError, match="unexpected Bank Rate table header"):
        bank_rate.parse_bank_rate_table(wrong)


def test_bank_rate_changes(rate_history: pd.Series) -> None:
    changes = bank_rate.bank_rate_changes(rate_history, START).set_index("date")
    assert changes.index[0] == pd.Timestamp("1997-05-06")  # 1996 is before the window
    assert changes.loc["1997-05-06", "prev_rate_pct"] == pytest.approx(5.94)
    assert changes.loc["2008-11-06", "change_bp"] == -150
    assert changes.loc["2020-03-19", "change_bp"] == -15
    assert changes.loc["2020-03-19", "prev_rate_pct"] == pytest.approx(0.25)


def test_bank_rate_changes_respects_start(rate_history: pd.Series) -> None:
    changes = bank_rate.bank_rate_changes(rate_history, pd.Timestamp("2020-01-01"))
    assert changes["date"].dt.year.unique().tolist() == [2020, 2023]


def test_rate_in_force_before(rate_history: pd.Series) -> None:
    days = pd.Series(pd.to_datetime(["2020-03-19", "2020-03-20", "1990-01-01"]))
    before = bank_rate.rate_in_force_before(rate_history, days)
    assert before.iloc[0] == pytest.approx(0.25)  # the day of a change: the old rate
    assert before.iloc[1] == pytest.approx(0.1)
    assert pd.isna(before.iloc[2])


def test_classify_changes(rate_history: pd.Series, decisions: pd.DataFrame) -> None:
    changes = bank_rate.classify_changes(
        bank_rate.bank_rate_changes(rate_history, START), decisions
    )
    labels = dict(zip(changes["date"].dt.strftime("%Y-%m-%d"), changes["mpc_match"], strict=True))
    assert labels["1997-05-06"] == "pre_mpc"
    assert labels["1997-06-06"] == "scheduled"
    unscheduled = sorted(day for day, label in labels.items() if label == "unscheduled")
    assert unscheduled == ["2001-09-18", "2008-10-08", "2020-03-11", "2020-03-19"]


def test_classify_changes_flags_unmatched(rate_history: pd.Series, decisions: pd.DataFrame) -> None:
    changes = bank_rate.bank_rate_changes(rate_history, START)
    without_june_1997 = decisions[decisions["date"] != pd.Timestamp("1997-06-06")]
    labels = bank_rate.classify_changes(changes, without_june_1997)["mpc_match"]
    assert labels.iloc[1] == "unmatched"
