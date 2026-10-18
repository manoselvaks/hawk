"""MPC decisions and vote splits from the Bank of England voting workbook.

Layout of the ``Bank Rate Decisions`` sheet of ``mpcvoting.xlsx``:

* a header row with ``Current members`` in column C and one member name per column
  from D onwards (a ``Past members`` label separates former members), followed by a
  ``First vote:`` row and summary counts (``Voted to increase`` ...) in column B;
* then one row per decision: announcement date in column B, the agreed Bank Rate in
  column C and each member's preferred rate under their name.

Rates are stored as fractions (0.0525 means 5.25%). In 1998 some dissents are
recorded only as ``Increase`` or ``Decrease``, meaning a rate above or below the one
agreed, size not given.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import IO

import pandas as pd

from hawk.market.bank_rate import rate_in_force_before
from hawk.market.sources import MPC_VOTING_SHEET, UNSCHEDULED_DECISIONS

_NAME_ROW_LABEL = "current members"
_DATE_COL, _RATE_COL = 1, 2
_NOT_NAMES = {"current members", "past members"}
_DIRECTION_ONLY = {"increase": 1, "decrease": -1}
_EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def _to_date(cell: object) -> pd.Timestamp | None:
    """Read an Excel cell holding either a datetime or a date serial number."""
    if isinstance(cell, dt.datetime | dt.date):
        return pd.Timestamp(cell).normalize()
    if isinstance(cell, int | float) and 30000 < cell < 80000:
        return _EXCEL_EPOCH + pd.Timedelta(days=int(cell))
    return None


def _clean(cell: object) -> str:
    """Cell text with line breaks and repeated spaces collapsed ("Andrew\nHaldane")."""
    return " ".join(cell.split()) if isinstance(cell, str) else ""


def _name_row(raw: pd.DataFrame) -> int:
    """Index of the row holding member names, found by its "Current members" label."""
    for idx in range(min(20, len(raw))):
        if any(_clean(cell).lower() == _NAME_ROW_LABEL for cell in raw.iloc[idx]):
            return idx
    raise ValueError("no 'Current members' header row in the voting sheet")


def parse_mpc_voting(source: str | Path | IO[bytes]) -> pd.DataFrame:
    """Return the voting record in long form.

    Columns: ``date, rate_pct, member, vote_pct, vote_dir``. ``vote_dir`` is +1, 0 or
    -1 as the member wanted a rate above, equal to or below the agreed one;
    ``vote_pct`` is missing where the workbook records only that direction. One row
    per member per decision; members not on the committee at a decision are left out.
    """
    raw = pd.read_excel(source, sheet_name=MPC_VOTING_SHEET, header=None, engine="openpyxl")
    name_row = _name_row(raw)
    names = {
        col: _clean(raw.iat[name_row, col])
        for col in range(_RATE_COL + 1, raw.shape[1])
        if _clean(raw.iat[name_row, col]).lower() not in _NOT_NAMES | {""}
    }
    if not names:
        raise ValueError(f"no MPC member names on row {name_row + 1} of the voting sheet")

    records: list[tuple[pd.Timestamp, float, str, float, str | None]] = []
    for idx in range(name_row + 1, len(raw)):
        day = _to_date(raw.iat[idx, _DATE_COL])
        rate = pd.to_numeric(raw.iat[idx, _RATE_COL], errors="coerce")
        if day is None or pd.isna(rate):
            continue  # summary counts, the column header and the pre-MPC opening rate
        for col, member in names.items():
            cell = raw.iat[idx, col]
            if isinstance(cell, int | float):
                if pd.notna(cell):
                    records.append((day, float(rate), member, float(cell), None))
            elif isinstance(cell, str) and cell.strip().lower() in _DIRECTION_ONLY:
                records.append((day, float(rate), member, float("nan"), cell.strip().lower()))
            else:
                raise ValueError(f"unexpected vote {cell!r} for {member} on {day.date()}")
    if not records:
        raise ValueError("no decision rows found in the voting sheet")

    votes = pd.DataFrame(records, columns=["date", "rate_pct", "member", "vote_pct", "word"])
    # The sheet stores fractions; Bank Rate has been above 1% for most of the
    # sample, so a maximum below 1 tells us the units are fractions.
    if votes["rate_pct"].max() < 1:
        votes[["rate_pct", "vote_pct"]] = (votes[["rate_pct", "vote_pct"]] * 100).round(4)
    gap = votes["vote_pct"] - votes["rate_pct"]
    numeric_dir = (gap > 1e-9).astype(int) - (gap < -1e-9).astype(int)
    votes["vote_dir"] = votes["word"].map(_DIRECTION_ONLY).fillna(numeric_dir).astype(int)
    votes = votes.drop(columns="word")
    return votes.sort_values(["date", "member"]).reset_index(drop=True)


def _direction(bp: int) -> str:
    return "hike" if bp > 0 else "cut" if bp < 0 else "hold"


def _describe_vote(member: str, bp: float, direction: int) -> str:
    if pd.isna(bp):
        return f"{member} ({'higher' if direction > 0 else 'lower'}, size not recorded)"
    bp = int(bp)
    return f"{member} (hold)" if bp == 0 else f"{member} ({_direction(bp)} {abs(bp)}bp)"


def build_mpc_decisions(votes: pd.DataFrame, bank_rate_history: pd.Series) -> pd.DataFrame:
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
    out["prev_rate_pct"] = rate_in_force_before(bank_rate_history, out["date"])

    def summarise(row: pd.Series) -> pd.Series:
        group: pd.DataFrame = row["group"]
        rate, prev = row["rate_pct"], row["prev_rate_pct"]
        vote_bp = ((group["vote_pct"] - prev) * 100).round()
        sized = vote_bp.notna()
        majority = group["vote_dir"] == 0
        # A direction-only vote is still a hike if the agreed rate was itself not a cut
        # (and the member wanted more), or a cut if the agreed rate was not a hike. The
        # rest (e.g. "Decrease" against a hike: a hold or a smaller hike) stay uncounted.
        word_hike = ~sized & (group["vote_dir"] > 0) & (rate >= prev)
        word_cut = ~sized & (group["vote_dir"] < 0) & (rate <= prev)
        return pd.Series(
            {
                "votes_hike": int(((vote_bp > 0) | word_hike).sum()),
                "votes_hold": int((vote_bp == 0).sum()),
                "votes_cut": int(((vote_bp < 0) | word_cut).sum()),
                "dissent_higher": int((group["vote_dir"] > 0).sum()),
                "dissent_lower": int((group["vote_dir"] < 0).sum()),
                "vote_split": f"{int(majority.sum())}-{int((~majority).sum())}",
                "dissenters": "; ".join(
                    _describe_vote(member, bp, direction)
                    for member, bp, direction in zip(
                        group.loc[~majority, "member"],
                        vote_bp[~majority],
                        group.loc[~majority, "vote_dir"],
                        strict=True,
                    )
                ),
            }
        )

    out["change_bp"] = ((out["rate_pct"] - out["prev_rate_pct"]) * 100).round().astype("Int64")
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
