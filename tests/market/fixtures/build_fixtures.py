"""Regenerate the Excel and zip fixtures.

Run ``python tests/market/fixtures/build_fixtures.py``.

The fixtures copy the layout of the real Bank of England files but hold
only a handful of rows. Decision dates are real (so the unscheduled-meeting
list applies) but rate levels, member names and votes are synthetic: the
sample jumps from 1997 to 2001 to 2020, and a continuous path of made-up
levels keeps those jumps from looking like extra Bank Rate changes.
``iadb_bank_rate.csv`` follows the same synthetic path.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).parent

MEMBERS = ["Member A", "Member B", "Member C", "Member D", "Member E"]
# (announcement date, agreed rate, votes by member; None = not on committee)
DECISIONS: list[tuple[datetime | int, float, list[float | None]]] = [
    (datetime(1997, 6, 6), 0.065, [0.065, 0.065, 0.065, 0.0625, None]),
    (datetime(2001, 9, 18), 0.0625, [0.0625, 0.0625, 0.0625, 0.0625, None]),
    (43901, 0.0575, [0.0575] * 5),  # 11 Mar 2020 as an Excel serial number
    (datetime(2020, 3, 19), 0.056, [0.056] * 5),
    (datetime(2020, 3, 26), 0.056, [0.056, 0.056, 0.056, 0.0575, 0.0555]),
]


def build_mpc_voting() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Bank Rate Decisions"
    sheet["A1"] = "MPC voting record: Bank Rate decisions"
    sheet["D2"] = "Current members"
    for col, name in enumerate(MEMBERS, start=4):
        sheet.cell(row=3, column=col, value=name)
    sheet.cell(row=3, column=4 + len(MEMBERS), value="Past members")
    for row in range(4, 11):
        sheet.cell(row=row, column=1, value="notes")
    for row, (day, rate, votes) in enumerate(DECISIONS, start=11):
        sheet.cell(row=row, column=2, value=day)
        sheet.cell(row=row, column=3, value=rate)
        for col, vote in enumerate(votes, start=4):
            sheet.cell(row=row, column=col, value=vote)
    return _save(book)


def build_glc_workbook(rows: list[tuple[datetime, float]]) -> bytes:
    """A GLC workbook whose spot curve is flat-plus-slope: y(m) = base + 0.1 m."""
    book = Workbook()
    book.active.title = "1. fwds, short end"
    sheet = book.create_sheet("4. spot curve")
    sheet["A1"] = "UK nominal spot curve"
    sheet["A4"] = "years:"
    maturities = [m / 2 for m in range(1, 21)]  # 0.5 to 10 years
    for col, maturity in enumerate(maturities, start=2):
        sheet.cell(row=4, column=col, value=maturity)
    for row, (day, base) in enumerate(rows, start=6):
        sheet.cell(row=row, column=1, value=day)
        for col, maturity in enumerate(maturities, start=2):
            sheet.cell(row=row, column=col, value=round(base + 0.1 * maturity, 4))
    return _save(book)


def build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _save(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def main() -> None:
    (HERE / "mpcvoting_sample.xlsx").write_bytes(build_mpc_voting())
    archive = build_glc_workbook(
        [
            (datetime(1996, 12, 31), 6.0),  # before the sample, dropped
            (datetime(2020, 3, 18), 0.2),
            (datetime(2020, 3, 19), 0.1),
            (datetime(2020, 3, 21), 0.1),  # Saturday, dropped
        ]
    )
    current = build_glc_workbook(
        [(datetime(2020, 3, 19), 0.15), (datetime(2020, 3, 20), 0.05)]
    )
    (HERE / "glc_archive_sample.zip").write_bytes(
        build_zip(
            {
                "GLC Nominal daily data_2016 to 2024.xlsx": archive,
                "GLC Real daily data_2016 to 2024.xlsx": b"ignored",
            }
        )
    )
    (HERE / "glc_latest_sample.zip").write_bytes(
        build_zip({"GLC Nominal daily data current month.xlsx": current})
    )


if __name__ == "__main__":
    main()
