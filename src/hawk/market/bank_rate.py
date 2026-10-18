"""Bank Rate: parse the Bank's table of rate changes into a dated series."""

from __future__ import annotations

import pandas as pd
from bs4 import BeautifulSoup

from hawk.market.sources import MPC_FIRST_DECISION, UNSCHEDULED_DECISIONS

_HEADER = ["Date Changed", "Rate"]


def parse_bank_rate_table(html: str | bytes) -> pd.Series:
    """Parse the Bank Rate history page into one value per change date.

    The page (``boeapps/database/Bank-Rate.asp``) lists every change since 1975,
    newest first, as ``18 Dec 25 | 3.75``. The result is a step series: each value
    is the rate in force from its date until the next one.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="stats-table")
    if table is None:
        raise ValueError("no Bank Rate table (id='stats-table') on the page")
    header = [th.get_text(strip=True) for th in table.find_all("th")]
    if header != _HEADER:
        raise ValueError(f"unexpected Bank Rate table header {header}, wanted {_HEADER}")

    rows = [
        [td.get_text(strip=True) for td in tr.find_all("td")]
        for tr in table.find_all("tr")
        if tr.find("td")
    ]
    if not rows or any(len(row) != 2 for row in rows):
        raise ValueError("Bank Rate table rows should have exactly two cells")
    # Two-digit years: Python maps 69-99 to the 1900s, and the table starts in 1975.
    dates = pd.to_datetime([row[0] for row in rows], format="%d %b %y")
    rates = pd.to_numeric(pd.Series([row[1] for row in rows]), errors="raise")
    out = pd.Series(rates.to_numpy(), index=pd.DatetimeIndex(dates, name="date"), name="rate")
    if out.index.has_duplicates:
        raise ValueError("Bank Rate table has duplicate dates")
    return out.sort_index()


def bank_rate_changes(history: pd.Series, start: pd.Timestamp) -> pd.DataFrame:
    """Return one row per Bank Rate change on or after ``start``.

    ``history`` is a dated Bank Rate series (one value per change, or per day) that
    begins before ``start``, so the first change in the window has a known previous rate.
    """
    previous = history.shift(1)
    changed = previous.notna() & (history != previous)
    out = pd.DataFrame(
        {
            "date": history.index[changed],
            "rate_pct": history[changed].to_numpy(),
            "prev_rate_pct": previous[changed].to_numpy(),
        }
    )
    out["change_bp"] = ((out["rate_pct"] - out["prev_rate_pct"]) * 100).round().astype(int)
    return out[out["date"] >= start].reset_index(drop=True)


def rate_in_force_before(history: pd.Series, dates: pd.Series) -> pd.Series:
    """Bank Rate in force the day before each date (the last value strictly earlier)."""
    positions = history.index.searchsorted(pd.DatetimeIndex(dates), side="left") - 1
    values = [history.iloc[p] if p >= 0 else float("nan") for p in positions]
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
