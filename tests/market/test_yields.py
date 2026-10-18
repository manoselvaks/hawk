from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hawk.market import yields
from hawk.market.sources import GILT_MATURITIES_YEARS


def _frames(fixtures: Path) -> list[pd.DataFrame]:
    books: dict[str, bytes] = {}
    for name in ("glc_archive_sample.zip", "glc_latest_sample.zip"):
        books.update(yields.glc_workbooks((fixtures / name).read_bytes()))
    return [yields.parse_spot_curve(book, GILT_MATURITIES_YEARS) for book in books.values()]


def test_glc_workbooks_keeps_only_nominal_daily(fixtures: Path) -> None:
    books = yields.glc_workbooks((fixtures / "glc_archive_sample.zip").read_bytes())
    assert list(books) == [
        "GLC Nominal daily data_1995 to 1999.xlsx",
        "GLC Nominal daily data_2016 to 2024.xlsx",
    ]


def test_parse_spot_curve_reads_requested_maturities(fixtures: Path) -> None:
    frames = pd.concat(_frames(fixtures)).set_index("date")
    # 27 Sep 2022, the peak of the mini-budget sell-off.
    assert frames.loc["2022-09-27", "gilt_2y"] == pytest.approx(4.5326, abs=1e-4)
    assert frames.loc["2022-09-27", "gilt_10y"] == pytest.approx(4.4341, abs=1e-4)
    assert frames.loc["1997-01-02", "gilt_2y"] == pytest.approx(6.6, abs=0.5)


def test_parse_spot_curve_missing_maturity_is_nan(fixtures: Path) -> None:
    books = yields.glc_workbooks((fixtures / "glc_latest_sample.zip").read_bytes())
    frame = yields.parse_spot_curve(next(iter(books.values())), {"gilt_2y": 2.0, "gilt_99y": 99.0})
    assert frame["gilt_99y"].isna().all()
    assert frame["gilt_2y"].notna().all()


def test_combine_yields_starts_in_1997(fixtures: Path) -> None:
    combined = yields.combine_yields(_frames(fixtures), pd.Timestamp("1997-01-01"))
    assert combined["date"].min() == pd.Timestamp("1997-01-02")  # 31 Dec 1996 dropped
    assert combined["date"].is_monotonic_increasing
    assert len(combined) == 2 + 4 + 2


def test_combine_yields_drops_weekends_and_prefers_later_files() -> None:
    days = pd.to_datetime(["2020-03-19", "2020-03-20", "2020-03-21"])  # Thu, Fri, Sat
    archive = pd.DataFrame({"date": days, "gilt_2y": [0.2, 0.1, 0.1]})
    latest = pd.DataFrame({"date": days[:1], "gilt_2y": [0.15]})
    combined = yields.combine_yields([archive, latest], pd.Timestamp("1997-01-01"))
    assert combined["date"].tolist() == list(days[:2])
    assert combined["gilt_2y"].tolist() == [0.15, 0.1]
