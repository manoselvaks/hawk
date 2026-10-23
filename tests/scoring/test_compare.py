from __future__ import annotations

import numpy as np
import pandas as pd

from hawk.scoring.compare import bootstrap_stance, choose, interval


def test_bootstrap_is_paired_and_keeps_missing() -> None:
    human = pd.Series([2.0, 1, 0, -1, -2, 1, 0, None])
    models = {
        "same": human.copy(),
        "gappy": pd.Series([2.0, None, 0, -1, -2, 1, 0, 1]),
    }
    draws = bootstrap_stance(human, models, n_boot=200, seed=1)
    assert draws["same"].shape == (200, 3)
    # A perfect scorer is exact on every resample.
    assert np.all(draws["same"][:, 1] == 1.0)
    lo, hi = interval(draws["gappy"][:, 1])
    assert lo is not None and hi == 1.0


def test_choose_keeps_a_clear_winner() -> None:
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 0.1, (500, 3))
    draws = {"a": noise + 0.50, "b": noise + 0.48, "c": noise * 0 + 0.05}
    chosen, why = choose({"a": 0.50, "b": 0.48, "c": 0.05}, draws, {"a": 2.0, "b": 1.0, "c": 0.1})
    # a and b move together (paired draws), so their difference is exactly 0.02 every
    # time and a "wins"; c is clearly worse.
    assert why["best_rho"] == "a" and chosen == "a" and "c" not in why["tied_with_best"]


def test_choose_ties_when_interval_includes_zero() -> None:
    rng = np.random.default_rng(0)
    draws = {"a": rng.normal(0.5, 0.15, (500, 3)), "b": rng.normal(0.45, 0.15, (500, 3))}
    chosen, why = choose({"a": 0.5, "b": 0.45}, draws, {"a": 2.0, "b": 1.0})
    assert why["tied_with_best"] == ["a", "b"] and chosen == "b"
