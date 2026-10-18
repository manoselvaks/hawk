"""Bank Rate: parse the IADB daily series and reduce it to change dates."""

from __future__ import annotations

import io

import pandas as pd

from hawk.market.sources import MPC_FIRST_DECISION, UNSCHEDULED_DECISIONS


def parse_iadb_csv(text: str, series: str) -> pd.Series:
    """Parse an IADB CSV download (``DATE,<code>`` columns) into a dated series.

    IADB answers bad requests with an HTML page rather than an HTTP error,
    so anything that does not look like the expected CSV raises.
    """
    if "<html" in text[:500].lower():
        raise ValueError(f"IADB returned an HTML page instead of CSV for {series}")
    frame = pd.read_csv(io.StringIO(text), skip_blank_lines=True)
    frame.columns = [str(c).strip() for c in frame.columns]
    if list(frame.columns) != ["DATE", series]:
        raise ValueError(
            f"unexpected IADB columns {list(frame.columns)}, wanted DATE,{series}"
        )

    dates = pd.to_datetime(frame["DATE"].str.strip(), format="%d %b %Y")
    values = pd.to_numeric(frame[series], errors="coerce")
    out = pd.Series(
        values.to_numpy(), index=pd.DatetimeIndex(dates, name="date"), name=series
    )
    return out.dropna().sort_index()


def bank_rate_changes(daily: pd.Series, start: pd.Timestamp) -> pd.DataFrame:
    """Return one row per Bank Rate change on or after ``start``.

    ``daily`` should begin before ``start`` so the first change in the window
    has a known previous rate.
    """
    previous = daily.shift(1)
    changed = previous.notna() & (daily != previous)
    out = pd.DataFrame(
        {
            "date": daily.index[changed],
            "rate_pct": daily[changed].to_numpy(),
            "prev_rate_pct": previous[changed].to_numpy(),
        }
    )
    out["change_bp"] = (
        ((out["rate_pct"] - out["prev_rate_pct"]) * 100).round().astype(int)
    )
    return out[out["date"] >= start].reset_index(drop=True)


def rate_in_force_before(daily: pd.Series, dates: pd.Series) -> pd.Series:
    """Bank Rate on the last observation strictly before each date."""
    positions = daily.index.searchsorted(pd.DatetimeIndex(dates), side="left") - 1
    values = [daily.iloc[p] if p >= 0 else float("nan") for p in positions]
    return pd.Series(values, index=dates.index, dtype=float)


def classify_changes(changes: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Label each Bank Rate change by the MPC decision behind it.

    ``mpc_match`` is one of:

    * ``scheduled``: an MPC decision on the same day set the same rate;
    * ``unscheduled``: as above, but taken outside the meeting calendar
      (for example the March 2020 emergency cuts);
    * ``pre_mpc``: before the MPC's first decision on 6 June 1997;
    * ``unmatched``: no MPC decision explains it. Validation fails on these.
    """
    decided = dict(zip(decisions["date"], decisions["rate_pct"], strict=True))

    def label(row: pd.Series) -> str:
        day = row["date"]
        if day.date() < MPC_FIRST_DECISION:
            return "pre_mpc"
        if day not in decided or abs(decided[day] - row["rate_pct"]) > 1e-9:
            return "unmatched"
        return "unscheduled" if day.date() in UNSCHEDULED_DECISIONS else "scheduled"

    out = changes.copy()
    out["mpc_match"] = out.apply(label, axis=1) if len(out) else pd.Series(dtype=str)
    return out
