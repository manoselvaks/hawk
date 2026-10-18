"""Daily nominal gilt yields from the Bank of England yield curve files.

The Bank publishes its fitted nominal government liability curve (GLC) as
zipped Excel workbooks. Sheet ``4. spot curve`` holds zero-coupon (spot)
yields: maturities in years along one header row, one row per business day
underneath, dates in column A.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping

import pandas as pd

_SPOT_SHEET = re.compile(r"spot curve$", re.IGNORECASE)
_GLC_DAILY_FILE = re.compile(r"GLC Nominal daily.*\.xlsx?$", re.IGNORECASE)


def glc_workbooks(zip_bytes: bytes) -> dict[str, bytes]:
    """Extract the daily nominal GLC workbooks from a yield curve zip."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        return {
            name: archive.read(name)
            for name in sorted(archive.namelist())
            if _GLC_DAILY_FILE.search(name.rsplit("/", 1)[-1])
        }


def _maturity_row(raw: pd.DataFrame) -> int:
    """Find the header row of maturities: at least five rising positive numbers."""
    for idx in range(min(10, len(raw))):
        values = pd.to_numeric(raw.iloc[idx, 1:], errors="coerce").dropna()
        if len(values) >= 5 and (values > 0).all() and values.is_monotonic_increasing:
            return idx
    raise ValueError("could not find the maturity row in the spot curve sheet")


def parse_spot_curve(workbook: bytes, maturities: Mapping[str, float]) -> pd.DataFrame:
    """Read the chosen maturities from one GLC workbook.

    Returns ``date`` plus one column per entry in ``maturities``; a maturity
    the workbook does not cover comes back as missing values.
    """
    excel = pd.ExcelFile(io.BytesIO(workbook), engine="openpyxl")
    sheet = next((s for s in excel.sheet_names if _SPOT_SHEET.search(s.strip())), None)
    if sheet is None:
        raise ValueError(f"no spot curve sheet among {excel.sheet_names}")
    raw = excel.parse(sheet, header=None)

    header = _maturity_row(raw)
    years = pd.to_numeric(raw.iloc[header], errors="coerce")
    body = raw.iloc[header + 1 :]
    dates = pd.to_datetime(body.iloc[:, 0], errors="coerce")

    out = pd.DataFrame({"date": dates.dt.normalize()})
    for column, maturity in maturities.items():
        matches = years.index[(years - maturity).abs() < 1e-9]
        out[column] = (
            pd.to_numeric(body[matches[0]], errors="coerce")
            if len(matches)
            else float("nan")
        )
    out = out.dropna(subset=["date"])
    return out.dropna(how="all", subset=list(maturities)).reset_index(drop=True)


def combine_yields(frames: Iterable[pd.DataFrame], start: pd.Timestamp) -> pd.DataFrame:
    """Stack workbooks and keep business days from ``start``; later files win."""
    stacked = pd.concat(list(frames), ignore_index=True)
    stacked = stacked[(stacked["date"] >= start) & (stacked["date"].dt.dayofweek < 5)]
    stacked = stacked.drop_duplicates(subset="date", keep="last")
    return stacked.sort_values("date").reset_index(drop=True)
