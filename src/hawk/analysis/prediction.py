"""Prediction test: does tone before a meeting predict the decision (cut / hold / hike)
beyond what was already known?

Models (ordered logit on ``y`` = -1 cut, 0 hold, +1 hike):

* **Same as last time**: predicts the previous decision (no estimation).
* **Always hold**: the majority class.
* **Previous decision**: ordered logit on dummies for the previous decision.
* **+ tone**: adds the tone level and change since the previous meeting.
* **+ market**: previous decision plus the 2-year gilt yield minus Bank Rate the
  day before, and its change since the previous meeting (what markets expected).
* **+ market + tone**.

**Out of sample, expanding window.** For every scheduled decision from
``OOS_START``, each model is re-estimated on decisions announced before it (whose
features, in turn, use only documents published before *their* announcements) and
predicts the next one. Probabilities are scored by accuracy, log loss and Brier
score, on all decisions and on those that changed Bank Rate. The four unscheduled
(emergency) decisions are left out of the evaluation, since their timing itself gives
the answer away, but they still count as "the previous decision" for the next one.

The model with tone is compared with its benchmark by the mean per-decision
difference in log loss, with a bootstrap interval over decisions: the one primary
test, so the multiple-testing problem stays small.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.miscmodels.ordinal_model import OrderedModel

CLASSES = [-1, 0, 1]
OOS_START = pd.Timestamp("2003-01-01")
EPS = 1e-6
N_BOOT = 4000
SEED = 11

TONE = ["tone", "tone_change"]
MARKET = ["spread_2y", "d2y_since_last"]
PREV = ["prev_cut", "prev_hike"]


@dataclass(frozen=True)
class Spec:
    name: str
    features: list[str]
    uses_tone: bool


SPECS = [
    Spec("Previous decision", PREV, False),
    Spec("Previous decision + tone", PREV + TONE, True),
    Spec("Previous decision + market", PREV + MARKET, False),
    Spec("Previous decision + market + tone", PREV + MARKET + TONE, True),
]
LABELS = {
    "prev_cut": "Previous decision: cut",
    "prev_hike": "Previous decision: hike",
    "tone": "Tone since last meeting",
    "tone_change": "Change in tone vs previous window",
    "tone_mpc": "Tone, MPC documents only",
    "tone_mpc_change": "Change in tone, MPC documents only",
    "tone_w": "Tone, weighted by relevance x confidence",
    "tone_w_change": "Change in weighted tone",
    "spread_2y": "2y gilt minus Bank Rate (pp)",
    "d2y_since_last": "Change in 2y gilt since last meeting (pp)",
}


def design(meetings: pd.DataFrame) -> pd.DataFrame:
    """Meetings with the previous-decision dummies, minus the first (no previous)."""
    out = meetings.copy()
    out["prev_cut"] = (out["prev_y"] == -1).astype(float)
    out["prev_hike"] = (out["prev_y"] == 1).astype(float)
    return out[out["prev_y"].notna()].reset_index(drop=True)


def fit(train: pd.DataFrame, features: list[str]) -> Any:
    """Ordered logit (statsmodels); ``None`` if it cannot be estimated."""
    y = pd.Categorical(train["y"], categories=CLASSES, ordered=True)
    if len(set(train["y"])) < 3:
        return None
    model = OrderedModel(y, train[features].astype(float), distr="logit")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return model.fit(method="bfgs", disp=False, maxiter=2000)
        except (np.linalg.LinAlgError, ValueError):
            return None


def predict_proba(result: Any, rows: pd.DataFrame, features: list[str]) -> np.ndarray:
    p = np.asarray(result.model.predict(result.params, exog=rows[features].astype(float)))
    p = np.clip(p, EPS, 1)
    return np.asarray(p / p.sum(axis=1, keepdims=True))


def one_hot(y: np.ndarray) -> np.ndarray:
    return np.asarray(np.asarray(y)[:, None] == np.array(CLASSES)[None, :]).astype(float)


def scores(p: np.ndarray, y: np.ndarray) -> dict[str, float]:
    """Accuracy, log loss and (multi-class) Brier score of probabilities ``p``."""
    if len(y) == 0:
        return {"accuracy": float("nan"), "log_loss": float("nan"), "brier": float("nan")}
    oh = one_hot(y)
    pred = np.array(CLASSES)[p.argmax(axis=1)]
    return {
        "accuracy": float((pred == y).mean()),
        "log_loss": float(-np.log(np.clip((p * oh).sum(axis=1), EPS, 1)).mean()),
        "brier": float(((p - oh) ** 2).sum(axis=1).mean()),
    }


def rule_proba(y_pred: np.ndarray, confidence: float = 1 - 2 * EPS) -> np.ndarray:
    """Near-certain probabilities for a rule that names one class."""
    p = np.full((len(y_pred), 3), (1 - confidence) / 2)
    p[np.arange(len(y_pred)), [CLASSES.index(int(v)) for v in y_pred]] = confidence
    return p


def expanding_window(
    data: pd.DataFrame,
    specs: list[Spec] = SPECS,
    start: pd.Timestamp = OOS_START,
) -> pd.DataFrame:
    """One row per evaluated decision with each model's predicted probabilities
    (columns ``<name>|p-1``, ``|p0``, ``|p1``), re-fitted before every decision on the
    decisions announced strictly before it."""
    data = data.sort_values("date").reset_index(drop=True)
    targets = data[(data["date"] >= start) & data["scheduled"]]
    out = []
    for i in targets.index:
        row = data.loc[i]
        train = data.iloc[: int(i)]
        rec: dict[str, Any] = {"date": row["date"], "y": int(row["y"]), "prev_y": row["prev_y"]}
        for spec in specs:
            tr = train.dropna(subset=spec.features)
            res = fit(tr, spec.features)
            if res is None or row[spec.features].isna().any():
                p = np.full(3, np.nan)
            else:
                p = predict_proba(res, data.iloc[[int(i)]], spec.features)[0]
            for c, v in zip(CLASSES, p, strict=True):
                rec[f"{spec.name}|p{c}"] = v
        out.append(rec)
    return pd.DataFrame(out)


def evaluate(oos: pd.DataFrame, specs: list[Spec] = SPECS) -> list[dict[str, Any]]:
    """Scores for each model and the two rules, on all decisions and on rate changes."""
    y = oos["y"].to_numpy()
    changed = y != 0
    rows: list[dict[str, Any]] = []
    rules = {
        "Same as last time": rule_proba(oos["prev_y"].to_numpy()),
        "Always hold": rule_proba(np.zeros(len(y))),
    }
    candidates: list[tuple[str, np.ndarray, list[str], bool]] = [
        (n, p, [], False) for n, p in rules.items()
    ]
    for spec in specs:
        p = oos[[f"{spec.name}|p{c}" for c in CLASSES]].to_numpy(dtype=float)
        candidates.append((spec.name, p, spec.features, spec.uses_tone))
    for name, p, features, uses_tone in candidates:
        ok = ~np.isnan(p).any(axis=1)
        s_all = scores(p[ok], y[ok])
        s_chg = scores(p[ok & changed], y[ok & changed])
        if name in rules:  # a rule gives no probabilities, so log loss is undefined
            s_all["log_loss"] = s_chg["log_loss"] = float("nan")
        rows.append(
            {
                "name": name,
                "features": features,
                "uses_tone": uses_tone,
                "is_rule": name in rules,
                "n": int(ok.sum()),
                **s_all,
                "n_changes": int((ok & changed).sum()),
                "accuracy_changes": s_chg["accuracy"],
                "log_loss_changes": s_chg["log_loss"],
                "brier_changes": s_chg["brier"],
            }
        )
    return rows


def compare_log_loss(
    oos: pd.DataFrame, base: str, other: str, n_boot: int = N_BOOT, seed: int = SEED
) -> dict[str, float]:
    """Mean per-decision log-loss gain of ``other`` over ``base`` (positive = ``other``
    better) with a bootstrap 95% interval over decisions, and the share of draws
    with no gain (a one-sided bootstrap p-value)."""
    y = oos["y"].to_numpy()
    oh = one_hot(y)

    def ll(name: str) -> np.ndarray:
        p = oos[[f"{name}|p{c}" for c in CLASSES]].to_numpy(dtype=float)
        return np.asarray(-np.log(np.clip((p * oh).sum(axis=1), EPS, 1)))

    gain = ll(base) - ll(other)
    gain = gain[~np.isnan(gain)]
    rng = np.random.default_rng(seed)
    draws = rng.choice(gain, (n_boot, len(gain))).mean(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "mean_gain": float(gain.mean()),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "p_one_sided": float((draws <= 0).mean()),
        "n": len(gain),
    }


def full_sample(data: pd.DataFrame, features: list[str]) -> tuple[list[dict[str, Any]], float]:
    """In-sample ordered-logit coefficients (with 95% intervals) and McFadden's
    pseudo-R² over all decisions, for the coefficient table. The cut-points are
    left out."""
    d = data.dropna(subset=features)
    res = fit(d, features)
    if res is None:
        return [], float("nan")
    ci = res.conf_int()
    rows = []
    for term in features:
        rows.append(
            {
                "term": term,
                "label": LABELS.get(term, term),
                "estimate": float(res.params[term]),
                "std_error": float(res.bse[term]),
                "p_value": float(res.pvalues[term]),
                "ci_low": float(ci.loc[term, 0]),
                "ci_high": float(ci.loc[term, 1]),
            }
        )
    return rows, float(res.prsquared)


def in_sample_pseudo_r2(data: pd.DataFrame, specs: list[Spec] = SPECS) -> dict[str, float]:
    out = {}
    for spec in specs:
        d = data.dropna(subset=spec.features)
        res = fit(d, spec.features)
        out[spec.name] = float(res.prsquared) if res is not None else float("nan")
    return out
