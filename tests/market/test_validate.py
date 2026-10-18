from __future__ import annotations

import pandas as pd
import pytest

from hawk.market import bank_rate
from hawk.market.validate import validate

TODAY = pd.Timestamp("2026-10-18")


@pytest.fixture
def tables(daily_rate: pd.Series, decisions: pd.DataFrame) -> dict[str, pd.DataFrame]:
    changes = bank_rate.bank_rate_changes(daily_rate, pd.Timestamp("1997-01-01"))
    gilts = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-03-18", "2020-03-19"]),
            "gilt_2y": [0.4, 0.3],
            "gilt_10y": [1.2, 1.1],
        }
    )
    return {
        "bank_rate": bank_rate.classify_changes(changes, decisions),
        "decisions": decisions,
        "gilts": gilts,
    }


def run(tables: dict[str, pd.DataFrame]):  # type: ignore[no-untyped-def]
    return validate(
        tables["bank_rate"], tables["decisions"], tables["gilts"], today=TODAY
    )


def test_clean_data_passes_with_emergency_moves_flagged(
    tables: dict[str, pd.DataFrame],
) -> None:
    report = run(tables)
    assert report.ok, report.errors
    assert sum("Unscheduled" in f for f in report.flags) == 3
    assert any("2020-03-11" in f for f in report.flags)
    assert any("before the MPC" in f for f in report.flags)


def test_duplicate_dates_fail(tables: dict[str, pd.DataFrame]) -> None:
    gilts = tables["gilts"]
    tables["gilts"] = pd.concat([gilts, gilts.tail(1)], ignore_index=True)
    assert any("duplicate dates" in e for e in run(tables).errors)


def test_out_of_bounds_rates_fail(tables: dict[str, pd.DataFrame]) -> None:
    tables["gilts"].loc[0, "gilt_10y"] = 45.0
    assert any("gilt_yields.gilt_10y" in e for e in run(tables).errors)


def test_weekend_gilt_dates_fail(tables: dict[str, pd.DataFrame]) -> None:
    tables["gilts"].loc[1, "date"] = pd.Timestamp("2020-03-21")
    assert any("weekend" in e for e in run(tables).errors)


def test_unmatched_change_fails(tables: dict[str, pd.DataFrame]) -> None:
    tables["bank_rate"].loc[1, "mpc_match"] = "unmatched"
    assert any("no matching MPC decision" in e for e in run(tables).errors)


def test_decision_without_rate_change_fails(tables: dict[str, pd.DataFrame]) -> None:
    br = tables["bank_rate"]
    tables["bank_rate"] = br[br["date"] != pd.Timestamp("2001-09-18")].reset_index(
        drop=True
    )
    assert any(
        "cut on 2001-09-18 has no Bank Rate change" in e for e in run(tables).errors
    )
