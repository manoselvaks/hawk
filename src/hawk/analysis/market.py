"""Market reaction: do 2-year gilt yields move with the tone of speeches?

Unit of observation: a business day. ``d2y`` is the change in the 2-year spot gilt
yield from the previous business day's close to this day's close, in basis points.
A **speech day** is a day on which at least one MPC-relevant speech was published
(``llm_relevance >= 0.5`` with a stance); a speech published on a weekend or bank
holiday is assigned to the next business day. Its stance is the mean stance of
that day's relevant speeches.

Excluded from every comparison: MPC announcement days and days on which minutes
were published (both carry their own news), so speech-day effects are not decision
effects. Data releases (CPI, labour market, GDP) are not controlled for: Hawk has no
release calendar, so a speech on a CPI day is counted like any other. Yields are
end-of-day and speech times are unknown, so a speech given after the close shows up
a day late; the two-day change (``d2y_2d``: close ``t-1`` to close ``t+1``) is the
check for that.

Stance surprise = the day's stance minus the mean stance of all relevant documents
published in the previous ``SURPRISE_DAYS`` days (strictly before the day): a
hawkish speech in a run of hawkish speeches is not news.

Regressions use Newey-West (HAC) standard errors with five lags. The placebo moves
the observed speech stances to randomly drawn non-speech days and re-estimates the
slope many times; if the real slope is no larger than most placebo slopes, the
"effect" is what chance alone produces.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from hawk.analysis.dataset import RELEVANCE_THRESHOLD, relevant
from hawk.scoring.context import ERAS

SURPRISE_DAYS = 60
HAC_LAGS = 5
N_PLACEBO = 1000
N_BOOT = 2000
SEED = 2026
HAWKISH, DOVISH = 0.5, -0.5


def daily_changes(yields: pd.DataFrame) -> pd.DataFrame:
    """Business days with ``d2y`` (bp, close t-1 to t) and ``d2y_2d`` (t-1 to t+1)."""
    y = yields.dropna(subset=["gilt_2y"]).sort_values("date").reset_index(drop=True)
    lvl = y["gilt_2y"] * 100
    return pd.DataFrame(
        {"date": y["date"], "d2y": lvl.diff(), "d2y_2d": lvl.shift(-1) - lvl.shift(1)}
    ).dropna(subset=["d2y"])


def _to_business_day(dates: pd.Series, days: pd.Series) -> pd.Series:
    """Map each date to the first business day on or after it (NaT past the end)."""
    d = days.sort_values().to_numpy()
    idx = np.searchsorted(d, dates.to_numpy(), side="left")
    out = np.where(idx < len(d), d[np.clip(idx, 0, len(d) - 1)], np.datetime64("NaT", "ns"))
    return pd.Series(out, index=dates.index, dtype="datetime64[ns]")


def speech_days(
    scores: pd.DataFrame,
    days: pd.DataFrame,
    threshold: float = RELEVANCE_THRESHOLD,
    surprise_days: int = SURPRISE_DAYS,
) -> pd.DataFrame:
    """One row per business day with at least one relevant speech: ``stance``,
    ``n_speeches``, ``member`` (any speaker a sitting MPC member), ``surprise``."""
    docs = relevant(scores, threshold)
    sp = docs[docs["kind"] == "speech"].copy()
    sp["day"] = _to_business_day(sp["published_date"], days["date"])
    sp = sp.dropna(subset=["day"])
    sp["member"] = sp["is_mpc_member"].fillna(False).astype(bool)
    out = (
        sp.groupby("day")
        .agg(
            stance=("llm_stance", "mean"),
            n_speeches=("llm_stance", "size"),
            member=("member", "any"),
        )
        .reset_index()
        .rename(columns={"day": "date"})
    )
    pub = docs["published_date"].sort_values().to_numpy()
    csum = np.concatenate([[0.0], np.cumsum(docs.sort_values("published_date")["llm_stance"])])
    window = np.timedelta64(surprise_days, "D")
    prior = []
    for t in out["date"].to_numpy():
        hi = np.searchsorted(pub, t, side="left")  # strictly before the day
        lo = np.searchsorted(pub, t - window, side="left")
        prior.append((csum[hi] - csum[lo]) / (hi - lo) if hi > lo else np.nan)
    out["prior_tone"] = prior
    out["surprise"] = out["stance"] - out["prior_tone"]
    return out


def event_days(scores: pd.DataFrame, decisions: pd.DataFrame, days: pd.DataFrame) -> set[Any]:
    """Business days with an MPC announcement or a minutes publication."""
    minutes = scores.loc[scores["kind"] == "minutes", "published_date"]
    dates = pd.concat([pd.Series(pd.to_datetime(decisions["date"])), minutes])
    mapped = _to_business_day(dates.reset_index(drop=True), days["date"]).dropna()
    return set(mapped.to_numpy())


def panel(scores: pd.DataFrame, decisions: pd.DataFrame, yields: pd.DataFrame) -> pd.DataFrame:
    """Every business day with ``d2y``, speech-day fields (NaN on other days), ``era``
    and ``event`` (announcement or minutes day, or the day before one for the
    two-day change)."""
    days = daily_changes(yields)
    sd = speech_days(scores, days)
    out = days.merge(sd, on="date", how="left")
    out["speech"] = out["stance"].notna()
    ev = event_days(scores, decisions, days)
    is_event = out["date"].isin(ev)
    out["event"] = is_event
    out["event_2d"] = is_event | is_event.shift(-1, fill_value=False)
    out["era"] = pd.cut(
        out["date"],
        bins=[pd.Timestamp("1900-01-01")] + [e for _, _, e in ERAS],
        labels=[name for name, _, _ in ERAS],
    ).astype(str)
    return out


def hac_ols(y: pd.Series, x: pd.DataFrame, lags: int = HAC_LAGS) -> Any:
    X = sm.add_constant(x.astype(float), has_constant="add")
    return sm.OLS(y.astype(float), X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})


def slope(frame: pd.DataFrame, x: str = "stance", y: str = "d2y") -> dict[str, Any]:
    """HAC regression of ``y`` on ``x``; the slope row for the results table."""
    f = frame.dropna(subset=[x, y]).sort_values("date")
    if len(f) < 10:
        return {"n": len(f), "estimate": None}
    res = hac_ols(f[y], f[[x]])
    ci = res.conf_int().loc[x]
    return {
        "n": len(f),
        "estimate": float(res.params[x]),
        "std_error": float(res.bse[x]),
        "p_value": float(res.pvalues[x]),
        "ci_low": float(ci.iloc[0]),
        "ci_high": float(ci.iloc[1]),
    }


def _boot_ci(v: np.ndarray, rng: np.random.Generator, n_boot: int = N_BOOT) -> tuple[float, float]:
    draws = rng.choice(v, (n_boot, len(v))).mean(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(lo), float(hi)


def placebo(
    data: pd.DataFrame,
    x: str = "stance",
    n: int = N_PLACEBO,
    seed: int = SEED,
) -> dict[str, float]:
    """Slopes from giving the speech-day stances to random non-speech days."""
    rng = np.random.default_rng(seed)
    real = data[data["speech"]].dropna(subset=[x])
    pool = data[~data["speech"]]
    xs = real[x].to_numpy(dtype=float)
    yv = pool["d2y"].to_numpy(dtype=float)
    slopes = np.empty(n)
    for i in range(n):
        idx = rng.choice(len(yv), len(xs), replace=False)
        yy = yv[idx]
        xx = rng.permutation(xs)
        slopes[i] = np.polyfit(xx, yy, 1)[0]
    actual = float(np.polyfit(xs, real["d2y"].to_numpy(dtype=float), 1)[0])
    return {
        "actual_slope": actual,
        "placebo_mean": float(slopes.mean()),
        "placebo_p95_abs": float(np.percentile(np.abs(slopes), 95)),
        "p_value": float((np.abs(slopes) >= abs(actual)).mean()),
        "n_placebo": n,
    }


def market_reaction(
    scores: pd.DataFrame, decisions: pd.DataFrame, yields: pd.DataFrame, seed: int = SEED
) -> dict[str, Any]:
    """All market-reaction results: groups, stance buckets, regressions, placebo, splits."""
    rng = np.random.default_rng(seed)
    p = panel(scores, decisions, yields)
    clean = p[~p["event"]]
    sp = clean[clean["speech"]]

    groups = []
    for label, sel in [
        ("No relevant speech", clean[~clean["speech"]]),
        ("Speech by a non-member", sp[~sp["member"].astype(bool)]),
        ("Speech by an MPC member", sp[sp["member"].astype(bool)]),
    ]:
        v = sel["d2y"].abs().to_numpy()
        lo, hi = _boot_ci(v, rng)
        groups.append(
            {"label": label, "n": len(v), "value": float(v.mean()), "ci_low": lo, "ci_high": hi}
        )

    by_stance = []
    for label, sel in [
        (f"Dovish (≤ {DOVISH:+.1f})", sp[sp["stance"] <= DOVISH]),
        ("Neutral", sp[(sp["stance"] > DOVISH) & (sp["stance"] < HAWKISH)]),
        (f"Hawkish (≥ {HAWKISH:+.1f})", sp[sp["stance"] >= HAWKISH]),
    ]:
        v = sel["d2y"].to_numpy()
        lo, hi = _boot_ci(v, rng) if len(v) > 2 else (float("nan"), float("nan"))
        by_stance.append(
            {"label": label, "n": len(v), "value": float(v.mean()), "ci_low": lo, "ci_high": hi}
        )

    clean2 = p[~p["event_2d"] & p["speech"]]
    regressions = {
        "stance": slope(sp, "stance"),
        "surprise": slope(sp, "surprise"),
        "stance_2day": slope(clean2, "stance", "d2y_2d"),
        "surprise_2day": slope(clean2, "surprise", "d2y_2d"),
        "stance_member": slope(sp[sp["member"].astype(bool)], "stance"),
        "stance_non_member": slope(sp[~sp["member"].astype(bool)], "stance"),
        "surprise_member": slope(sp[sp["member"].astype(bool)], "surprise"),
    }
    by_era = {era: slope(sp[sp["era"] == era], "stance") for era, _, _ in ERAS}
    by_era_surprise = {era: slope(sp[sp["era"] == era], "surprise") for era, _, _ in ERAS}
    return {
        "n_days": len(clean),
        "n_speech_days": len(sp),
        "n_event_days_excluded": int(p["event"].sum()),
        "groups": groups,
        "by_stance": by_stance,
        "regressions": regressions,
        "by_era": by_era,
        "by_era_surprise": by_era_surprise,
        "placebo_stance": placebo(clean, "stance", seed=seed),
        "placebo_surprise": placebo(clean, "surprise", seed=seed + 1),
    }
