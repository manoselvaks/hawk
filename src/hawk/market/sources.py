"""Bank of England source URLs, series codes and reference dates."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

IADB_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
"""Statistical Interactive Database (IADB) CSV endpoint."""

BANK_RATE_SERIES = "IUDBEDR"
"""IADB code for the daily official Bank Rate, in percent."""

MPC_VOTING_URL = (
    "https://www.bankofengland.co.uk/-/media/boe/files/"
    "monetary-policy-summary-and-minutes/mpcvoting.xlsx"
)
"""Workbook with every member's Bank Rate vote at every MPC decision."""

MPC_VOTING_SHEET = "Bank Rate Decisions"

_YIELD_CURVE_BASE = (
    "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves"
)
YIELD_ARCHIVE_URL = f"{_YIELD_CURVE_BASE}/glcnominalddata.zip"
"""Daily nominal government liability curve (GLC) archive, all years."""

YIELD_LATEST_URL = f"{_YIELD_CURVE_BASE}/latest-yield-curve-data.zip"
"""Current-month curves, which the archive may not include yet."""

GILT_MATURITIES_YEARS: dict[str, float] = {"gilt_2y": 2.0, "gilt_10y": 10.0}
"""Output column -> maturity read off the nominal spot curve."""

MPC_FIRST_DECISION = date(1997, 6, 6)
"""First Bank Rate decision announced by the Monetary Policy Committee."""

UNSCHEDULED_DECISIONS: dict[date, str] = {
    date(2001, 9, 18): "Unscheduled meeting after the 11 September attacks",
    date(2008, 10, 8): "Unscheduled meeting, coordinated central bank cut",
    date(2020, 3, 11): "Emergency Covid-19 cut",
    date(2020, 3, 19): "Emergency Covid-19 cut",
}
"""MPC decisions taken outside the published meeting calendar."""


def iadb_csv_url(series: str, start: date, end: date) -> str:
    """Build the IADB CSV download URL for one series between two dates."""
    query = {
        "csv.x": "yes",
        "Datefrom": start.strftime("%d/%b/%Y"),
        "Dateto": end.strftime("%d/%b/%Y"),
        "SeriesCodes": series,
        "CSVF": "TN",
        "UsingCodes": "Y",
        "VPD": "Y",
        "VFD": "N",
    }
    return f"{IADB_URL}?{urlencode(query, safe='/')}"
