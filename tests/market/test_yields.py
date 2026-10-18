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
    return [
        yields.parse_spot_curve(book, GILT_MATURITIES_YEARS) for book in books.values()
    ]


def test_glc_workbooks_keeps_only_nominal_daily(fixtures: Path) -> None:
    books = yields.glc_workbooks((fixtures / "glc_archive_sample.zip").read_bytes())
    assert list(books) == ["GLC Nominal daily data_2016 to 2024.xlsx"]


def test_parse_spot_curve_reads_requested_maturities(fixtures: Path) -> None:
    archive = _frames(fixtures)[0]
    row = archive[archive["date"] == pd.Timestamp("2020-03-18")].iloc[0]
    assert row["gilt_2y"] == pytest.approx(0.4)
    assert row["gilt_10y"] == pytest.approx(1.2)


def test_parse_spot_curve_missing_maturity_is_nan(fixtures: Path) -> None:
    books = yields.glc_workbooks((fixtures / "glc_latest_sample.zip").read_bytes())
    frame = yields.parse_spot_curve(
        next(iter(books.values())), {"gilt_2y": 2.0, "gilt_30y": 30.0}
    )
    assert frame["gilt_30y"].isna().all()
    assert frame["gilt_2y"].notna().all()


def test_combine_yields_drops_weekends_and_prefers_latest_file(fixtures: Path) -> None:
    combined = yields.combine_yields(_frames(fixtures), pd.Timestamp("1997-01-01"))
    assert combined["date"].dt.strftime("%Y-%m-%d").tolist() == [
        "2020-03-18",
        "2020-03-19",
        "2020-03-20",
    ]
    # 19 Mar 2020 appears in both files; the current-month file wins.
    assert combined.loc[1, "gilt_2y"] == pytest.approx(0.35)
