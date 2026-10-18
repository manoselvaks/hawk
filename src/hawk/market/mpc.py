"""MPC decisions and vote splits from the Bank of England voting workbook.

The ``Bank Rate Decisions`` sheet of ``mpcvoting.xlsx`` has one row per
decision: the announcement date in column B, the agreed Bank Rate in column C
and each member's preferred rate in the columns that follow, under member
names on row 3. Rates are stored as fractions (0.0525 means 5.25%).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import IO

import pandas as pd

from hawk.market.bank_rate import rate_in_force_before
from hawk.market.sources import MPC_VOTING_SHEET, UNSCHEDULED_DECISIONS

_NAME_ROW = 2
_DATE_COL, _RATE_COL, _FIRST_MEMBER_COL = 1, 2, 3
_NOT_NAMES = {"current members", "past members"}
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _to_date(cell: object) -> pd.Timestamp | None:
    """Read an Excel cell holding either a datetime or a date serial number."""
    if isinstance(cell, dt.datetime | dt.date):
        return pd.Timestamp(cell).normalize()
    if isinstance(cell, int | float) and 30000 < cell < 80000:
        return _EXCEL_EPOCH + pd.Timedelta(days=int(cell))
    return None


def parse_mpc_voting(source: str | Path | IO[bytes]) -> pd.DataFrame:
    """Return the voting record in long form: ``date, rate_pct, member, vote_pct``.

    One row per member per decision; members not on the committee at a given
    decision are left out.
    """
    raw = pd.read_excel(
        source, sheet_name=MPC_VOTING_SHEET, header=None, engine="openpyxl"
    )
    names = {
        col: str(raw.iat[_NAME_ROW, col]).strip()
        for col in range(_FIRST_MEMBER_COL, raw.shape[1])
        if pd.notna(raw.iat[_NAME_ROW, col])
        and str(raw.iat[_NAME_ROW, col]).strip().lower() not in _NOT_NAMES | {""}
    }
    if not names:
        raise ValueError("no MPC member names found on row 3 of the voting sheet")

    records = []
    for _, row in raw.iterrows():
        day = _to_date(row.iloc[_DATE_COL])
        rate = pd.to_numeric(row.iloc[_RATE_COL], errors="coerce")
        if day is None or pd.isna(rate):
            continue
        for col, member in names.items():
            vote = pd.to_numeric(row.iloc[col], errors="coerce")
            if pd.notna(vote):
                records.append((day, float(rate), member, float(vote)))
    if not records:
        raise ValueError("no decision rows found in the voting sheet")

    votes = pd.DataFrame(records, columns=["date", "rate_pct", "member", "vote_pct"])
    # The sheet stores fractions; Bank Rate has been above 1% for most of the
    # sample, so a maximum below 1 tells us the units are fractions.
    if votes["rate_pct"].max() < 1:
        votes[["rate_pct", "vote_pct"]] = (votes[["rate_pct", "vote_pct"]] * 100).round(
            4
        )
    return votes.sort_values(["date", "member"]).reset_index(drop=True)


def _direction(bp: int) -> str:
    return "hike" if bp > 0 else "cut" if bp < 0 else "hold"


def _describe_vote(member: str, bp: int) -> str:
    return f"{member} (hold)" if bp == 0 else f"{member} ({_direction(bp)} {abs(bp)}bp)"


def build_mpc_decisions(
    votes: pd.DataFrame, daily_bank_rate: pd.Series
) -> pd.DataFrame:
    """Summarise each decision: size, direction, vote split and dissenters.

    The previous rate is the Bank Rate in force the day before the
    announcement, so members' votes and the decision are both expressed as
    a move from the rate the committee inherited.
    """
    rows = []
    for day, group in votes.groupby("date", sort=True):
        rate = group["rate_pct"].iat[0]
        rows.append({"date": day, "rate_pct": rate, "group": group})
    out = pd.DataFrame(rows)
    out["prev_rate_pct"] = rate_in_force_before(daily_bank_rate, out["date"])

    def summarise(row: pd.Series) -> pd.Series:
        group: pd.DataFrame = row["group"]
        vote_bp = ((group["vote_pct"] - row["prev_rate_pct"]) * 100).round().astype(int)
        majority = (group["vote_pct"] - row["rate_pct"]).abs() < 1e-9
        dissent = group.loc[~majority, "member"]
        return pd.Series(
            {
                "votes_hike": int((vote_bp > 0).sum()),
                "votes_hold": int((vote_bp == 0).sum()),
                "votes_cut": int((vote_bp < 0).sum()),
                "dissent_higher": int(
                    (group["vote_pct"] > row["rate_pct"] + 1e-9).sum()
                ),
                "dissent_lower": int(
                    (group["vote_pct"] < row["rate_pct"] - 1e-9).sum()
                ),
                "vote_split": f"{int(majority.sum())}-{len(dissent)}",
                "dissenters": "; ".join(
                    _describe_vote(m, int(bp))
                    for m, bp in zip(dissent, vote_bp[~majority], strict=True)
                ),
            }
        )

    out["change_bp"] = (
        ((out["rate_pct"] - out["prev_rate_pct"]) * 100).round().astype("Int64")
    )
    out["decision"] = out["change_bp"].map(
        lambda bp: _direction(int(bp)) if pd.notna(bp) else pd.NA
    )
    out["scheduled"] = ~out["date"].dt.date.isin(UNSCHEDULED_DECISIONS.keys())
    out = pd.concat([out, out.apply(summarise, axis=1)], axis=1)
    columns = [
        "date", "decision", "change_bp", "rate_pct", "prev_rate_pct", "scheduled",
        "vote_split", "votes_hike", "votes_hold", "votes_cut",
        "dissent_higher", "dissent_lower", "dissenters",
    ]  # fmt: skip
    return out[columns]
