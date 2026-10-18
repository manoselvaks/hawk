from __future__ import annotations

import pandas as pd
import pytest

from hawk.market import bank_rate
from hawk.market.sources import BANK_RATE_SERIES

START = pd.Timestamp("1997-01-01")


def test_parse_iadb_csv(daily_rate: pd.Series) -> None:
    assert daily_rate.index[0] == pd.Timestamp("1997-05-02")
    assert daily_rate.loc["2020-03-19"] == pytest.approx(5.6)
    assert daily_rate.index.is_monotonic_increasing


def test_parse_iadb_csv_rejects_html_error_page() -> None:
    with pytest.raises(ValueError, match="HTML"):
        bank_rate.parse_iadb_csv("<html><title>Error</title></html>", BANK_RATE_SERIES)


def test_parse_iadb_csv_rejects_wrong_series() -> None:
    with pytest.raises(ValueError, match="unexpected IADB columns"):
        bank_rate.parse_iadb_csv("DATE,IUDMNZC\n02 Jan 2020,0.8\n", BANK_RATE_SERIES)


def test_bank_rate_changes(daily_rate: pd.Series) -> None:
    changes = bank_rate.bank_rate_changes(daily_rate, START)
    assert changes["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "1997-05-06", "1997-06-06", "2001-09-18", "2020-03-11", "2020-03-19",
    ]  # fmt: skip
    assert changes["change_bp"].tolist() == [25, 25, -25, -50, -15]
    assert changes.loc[4, "prev_rate_pct"] == pytest.approx(5.75)


def test_bank_rate_changes_respects_start(daily_rate: pd.Series) -> None:
    changes = bank_rate.bank_rate_changes(daily_rate, pd.Timestamp("2020-01-01"))
    assert len(changes) == 2


def test_classify_changes(daily_rate: pd.Series, decisions: pd.DataFrame) -> None:
    changes = bank_rate.classify_changes(
        bank_rate.bank_rate_changes(daily_rate, START), decisions
    )
    assert changes["mpc_match"].tolist() == [
        "pre_mpc", "scheduled", "unscheduled", "unscheduled", "unscheduled",
    ]  # fmt: skip


def test_classify_changes_flags_unmatched(
    daily_rate: pd.Series, decisions: pd.DataFrame
) -> None:
    changes = bank_rate.bank_rate_changes(daily_rate, START)
    without_june_1997 = decisions[decisions["date"] != pd.Timestamp("1997-06-06")]
    labels = bank_rate.classify_changes(changes, without_june_1997)["mpc_match"]
    assert labels.iloc[1] == "unmatched"
