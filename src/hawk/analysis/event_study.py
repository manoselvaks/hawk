"""Event study: average tone in the 12 weeks before hikes, cuts and holds.

Week ``0`` is the seven days *before* the announcement (``D-7`` to ``D-1``), week
``-1`` the seven days before that, and so on to ``-12``. A document published on the
announcement day itself is never used, and neither are the minutes of that meeting.

For each decision and week the tone is the mean stance of MPC-relevant documents
published that week (missing if there were none). The curve for a decision type is
the mean across its decisions of those weekly values; the 95% band comes from a
bootstrap over decisions (resampling whole decisions keeps each one's weeks
together). Windows of neighbouring decisions overlap, since the MPC meets every four
to six weeks, so the three curves are not independent samples.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hawk.analysis.dataset import add_own_decision, relevant

WEEKS = 12
DECISIONS = ["hike", "hold", "cut"]
N_BOOT = 2000
SEED = 7


def weekly_tone(
    docs: pd.DataFrame, decisions: pd.DataFrame, weeks: int = WEEKS, mpc_only: bool = False
) -> pd.DataFrame:
    """``(n_decisions, weeks + 1)`` frame of mean stance; columns ``-weeks .. 0``.

    ``docs`` is ``relevant(scores)`` output; ``own_decision`` is added here.
    """
    d = add_own_decision(docs, decisions)
    if mpc_only:
        d = d[d["is_mpc"]]
    pub = d["published_date"].to_numpy()
    stance = d["llm_stance"].to_numpy(dtype=float)
    own = d["own_decision"].to_numpy()
    rows = []
    for date in pd.to_datetime(decisions["date"]):
        t = np.datetime64(date)
        row = []
        for k in range(weeks, -1, -1):
            lo = t - np.timedelta64(7 * (k + 1), "D")
            hi = t - np.timedelta64(7 * k, "D")
            mask = (pub >= lo) & (pub < hi) & (own != t)
            row.append(float(stance[mask].mean()) if mask.any() else np.nan)
        rows.append(row)
    return pd.DataFrame(rows, columns=list(range(-weeks, 1)), index=decisions.index)


def _boot_mean(values: np.ndarray, rng: np.random.Generator, n_boot: int) -> tuple[float, float]:
    """95% percentile interval of the nan-mean of rows of ``values`` (events x weeks
    collapsed to one value per event before calling)."""
    v = values[~np.isnan(values)]
    if len(v) < 3:
        return float("nan"), float("nan")
    draws = rng.choice(v, size=(n_boot, len(v)), replace=True).mean(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(lo), float(hi)


def event_study(
    scores: pd.DataFrame,
    decisions: pd.DataFrame,
    weeks: int = WEEKS,
    n_boot: int = N_BOOT,
    seed: int = SEED,
    mpc_only: bool = False,
) -> dict[str, Any]:
    """Series and summary table in the shape of ``findings.json``'s ``event_study``.

    Table columns: ``mean_tone_before`` is each decision's mean weekly tone over all
    13 weeks, averaged across decisions; ``tone_change`` is the last four weeks
    (``-3..0``) minus the first four (``-12..-9``), per decision, averaged.
    """
    rng = np.random.default_rng(seed)
    tone = weekly_tone(relevant(scores), decisions, weeks, mpc_only=mpc_only)
    offsets = list(range(-weeks, 1))
    series, table = [], []
    for kind in DECISIONS:
        sel = tone[(decisions["decision"] == kind).to_numpy()]
        mean, lo, hi = [], [], []
        for w in offsets:
            col = sel[w].to_numpy()
            m = np.nanmean(col) if np.isfinite(col).any() else np.nan
            a, b = _boot_mean(col, rng, n_boot)
            mean.append(_r(m))
            lo.append(_r(a))
            hi.append(_r(b))
        series.append(
            {"decision": kind, "n_events": len(sel), "mean": mean, "ci_low": lo, "ci_high": hi}
        )
        per_event = sel.mean(axis=1, skipna=True).to_numpy()
        late = sel[[w for w in offsets if w >= -3]].mean(axis=1, skipna=True)
        early = sel[[w for w in offsets if w <= -weeks + 3]].mean(axis=1, skipna=True)
        change = (late - early).to_numpy()
        a, b = _boot_mean(per_event, rng, n_boot)
        c_lo, c_hi = _boot_mean(change, rng, n_boot)
        table.append(
            {
                "decision": kind,
                "n_events": len(sel),
                "mean_tone_before": (
                    _r(np.nanmean(per_event)) if np.isfinite(per_event).any() else None
                ),
                "ci_low": _r(a),
                "ci_high": _r(b),
                "tone_change": _r(np.nanmean(change)) if np.isfinite(change).any() else None,
                "tone_change_ci_low": _r(c_lo),
                "tone_change_ci_high": _r(c_hi),
                "n_with_change": int(np.isfinite(change).sum()),
            }
        )
    return {"offsets_weeks": offsets, "series": series, "table": table}


def difference_test(
    scores: pd.DataFrame,
    decisions: pd.DataFrame,
    a: str = "hike",
    b: str = "cut",
    weeks: int = WEEKS,
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, float | None]:
    """Mean pre-decision tone before ``a`` minus before ``b``, with a bootstrap 95%
    interval (decisions resampled within each group)."""
    rng = np.random.default_rng(seed)
    tone = weekly_tone(relevant(scores), decisions, weeks).mean(axis=1, skipna=True)
    x = tone[(decisions["decision"] == a).to_numpy()].dropna().to_numpy()
    y = tone[(decisions["decision"] == b).to_numpy()].dropna().to_numpy()
    if len(x) < 3 or len(y) < 3:
        return {"difference": None, "ci_low": None, "ci_high": None}
    draws = rng.choice(x, (n_boot, len(x))).mean(axis=1) - rng.choice(y, (n_boot, len(y))).mean(
        axis=1
    )
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"difference": _r(x.mean() - y.mean()), "ci_low": _r(lo), "ci_high": _r(hi)}


def _r(x: float, digits: int = 3) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), digits)
