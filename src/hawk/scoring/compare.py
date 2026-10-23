"""Compare several LLM scorers and the baseline against the hand labels, with
bootstrap confidence intervals, and choose the production model.

Usage::

    python -m hawk.scoring.compare --labels labelling/labels.csv \\
        --models openai/gpt-6-luna anthropic/claude-haiku-5.5 deepseek/deepseek-v4.1-flash

It reads LLM scores from the cache only (``data/llm_cache/``, filled by
``python -m hawk.scoring.evaluate --model ...``) and never calls the API, so it is
free to re-run. A model is compared only if every labelled item has a cached first
run; self-consistency uses the items that also have a second run.

**How the model is chosen** (fixed in advance, see ``docs/evaluation.md``): the
primary measure is Spearman's rho against the hand labels. With about 33 scored
items the intervals are wide, so the best model only "wins" if a paired bootstrap
of the rho difference excludes zero against every other model. Models it cannot be
separated from count as tied, and the cheapest of the tied models (full-corpus cost
from the pilot) is chosen.

Writes ``docs/evaluation.md`` and ``data/analysis/evaluation.json`` (the contract in
``docs/data-contract.md``, plus extra fields: ``*_ci`` intervals, per-model
consistency and cost, ``selection``).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hawk.scoring import baseline
from hawk.scoring.evaluate import (
    LLM_RELEVANCE_THRESHOLD,
    SCALE,
    Consistency,
    build_json,
    read_labels,
    relevance_metrics,
    round_half_away,
    self_consistency,
    spearman,
    stance_metrics,
)
from hawk.scoring.llm import DEFAULT_INPUT_MODE, InputMode, LLMScorer
from hawk.scoring.make_labelling_set import OUT_DIR, SET_FILE
from hawk.scoring.pilot import SCORES_PATH as PILOT_SCORES

log = logging.getLogger("hawk.scoring.compare")

N_BOOT = 4000
SEED = 20261023


@dataclass
class ModelRun:
    model: str
    first: pd.DataFrame  # item, stance, relevance
    second: pd.DataFrame | None  # same, items with a second run only
    cost_per_doc: float | None  # mean pilot cost, full text
    corpus_cost: float | None


def _stats(h: np.ndarray, m: np.ndarray) -> tuple[float, float, float]:
    """Spearman, exact and within-one on aligned arrays (no NaN)."""
    if len(h) == 0:
        return (float("nan"),) * 3
    rounded = np.array([round_half_away(float(x)) for x in m])
    return (
        spearman(pd.Series(h), pd.Series(m)),
        float((rounded == h).mean()),
        float((np.abs(m - h) <= 1).mean()),
    )


def bootstrap_stance(
    human: pd.Series,
    models: dict[str, pd.Series],
    n_boot: int = N_BOOT,
    seed: int = SEED,
) -> dict[str, np.ndarray]:
    """Resample the human-scored items with replacement (the same draw for every
    scorer, so differences are paired); returns an ``(n_boot, 3)`` array per scorer
    of (Spearman, exact, within-one). A scorer's missing stances stay missing."""
    rng = np.random.default_rng(seed)
    scored = human.notna().to_numpy()
    h_all = human.to_numpy(dtype=float)[scored]
    cols = {k: v.to_numpy(dtype=float)[scored] for k, v in models.items()}
    out = {k: np.empty((n_boot, 3)) for k in models}
    n = len(h_all)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        h = h_all[idx]
        for k, col in cols.items():
            m = col[idx]
            ok = ~np.isnan(m)
            out[k][b] = _stats(h[ok], m[ok])
    return out


def interval(draws: np.ndarray) -> tuple[float | None, float | None]:
    d = draws[~np.isnan(draws)]
    if len(d) < 10:
        return None, None
    lo, hi = np.percentile(d, [2.5, 97.5])
    return round(float(lo), 4), round(float(hi), 4)


def choose(
    point_rho: dict[str, float],
    draws: dict[str, np.ndarray],
    cost: dict[str, float | None],
) -> tuple[str, dict[str, Any]]:
    """Apply the rule in the module docstring. Returns the model and a record of why."""
    best = max(point_rho, key=lambda k: -math.inf if math.isnan(point_rho[k]) else point_rho[k])
    tied = [best]
    diffs: dict[str, Any] = {}
    for other in point_rho:
        if other == best:
            continue
        d = draws[best][:, 0] - draws[other][:, 0]
        lo, hi = interval(d)
        diffs[other] = {
            "rho_difference": round(point_rho[best] - point_rho[other], 4),
            "ci_low": lo,
            "ci_high": hi,
        }
        if lo is None or lo <= 0:
            tied.append(other)
    priced = [m for m in tied if cost.get(m) is not None]
    chosen = min(priced, key=lambda m: cost[m] or 0.0) if priced else best
    return chosen, {
        "rule": "highest Spearman rho; models whose paired-bootstrap rho difference "
        "includes zero count as tied; cheapest tied model wins",
        "best_rho": best,
        "tied_with_best": tied,
        "rho_difference_vs_best": diffs,
        "chosen": chosen,
    }


# -- loading -------------------------------------------------------------------


def pilot_cost(model: str, input_mode: str, path: Path = PILOT_SCORES) -> float | None:
    if not path.exists():
        return None
    p = pd.read_csv(path)
    p = p[(p["model"] == model) & (p["input_mode"] == input_mode)]
    return None if p.empty else float(p["cost_usd"].mean())


def load_run(
    model: str, items: pd.DataFrame, input_mode: InputMode, n_docs: int
) -> ModelRun | None:
    """Cached scores for every item, or ``None`` if any first run is missing."""
    scorer = LLMScorer(model, input_mode=input_mode)
    first, second = [], []
    for row in items.to_dict("records"):
        a = scorer.cached(row["kind"], row["text"], 0)
        if a is None:
            return None
        first.append({"item": row["item"], "stance": a["stance"], "relevance": a["relevance"]})
        b = scorer.cached(row["kind"], row["text"], 1)
        if b is not None:
            second.append({"item": row["item"], "stance": b["stance"], "relevance": b["relevance"]})
    f = pd.DataFrame(first).astype({"stance": "float64"})
    s = pd.DataFrame(second).astype({"stance": "float64"}) if second else None
    per_doc = pilot_cost(model, input_mode)
    return ModelRun(model, f, s, per_doc, per_doc * n_docs if per_doc is not None else None)


def consistency_of(run: ModelRun) -> Consistency | None:
    if run.second is None:
        return None
    a = run.first.set_index("item").loc[run.second["item"]].reset_index()
    return self_consistency(a, run.second)


# -- output --------------------------------------------------------------------


def _f(x: float | None, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2013"
    return f"{100 * x:.0f}%" if pct else f"{x:.2f}"


def _ci(lo: float | None, hi: float | None, pct: bool = False) -> str:
    if lo is None or hi is None:
        return ""
    return f" ({_f(lo, pct)} to {_f(hi, pct)})"


def _confusion_md(table: pd.DataFrame) -> list[str]:
    cols = [str(c) for c in table.columns]
    lines = [
        "| human \\ model | " + " | ".join(cols) + " |",
        "| ---: | " + " | ".join("---:" for _ in cols) + " |",
    ]
    for label, row in table.iterrows():
        name = f"{label:+d}" if label else "0"
        lines.append(f"| {name} | " + " | ".join(str(int(v)) for v in row) + " |")
    return lines


def run(
    labels: pd.DataFrame,
    items: pd.DataFrame,
    models: list[str],
    input_mode: InputMode,
    n_docs: int,
) -> tuple[dict[str, Any], str]:
    """Everything the CLI writes: the evaluation JSON and the markdown tables."""
    runs = {m: load_run(m, items, input_mode, n_docs) for m in models}
    missing = [m for m, r in runs.items() if r is None]
    ok = {m: r for m, r in runs.items() if r is not None}
    if not ok:
        raise SystemExit("no model has cached scores for every labelled item")

    df = labels.copy()
    base = [baseline.score_text(t) for t in items.set_index("item").loc[df["item"], "text"]]
    df["baseline_stance"] = [b.stance for b in base]
    df["baseline_relevant"] = [b.is_relevant for b in base]
    for m, r in ok.items():
        f = r.first.set_index("item").loc[df["item"]]
        df[f"{m}|stance"] = f["stance"].to_numpy()
        df[f"{m}|relevance"] = f["relevance"].to_numpy()

    names = {"baseline": "Baseline (word lists)"} | {m: f"LLM ({m}, {input_mode})" for m in ok}
    stance_cols = {"baseline": df["baseline_stance"]} | {m: df[f"{m}|stance"] for m in ok}
    relevant_cols = {"baseline": df["baseline_relevant"]} | {
        m: df[f"{m}|relevance"] >= LLM_RELEVANCE_THRESHOLD for m in ok
    }
    draws = bootstrap_stance(df["human_stance"], stance_cols)
    stance = {k: stance_metrics(df["human_stance"], v) for k, v in stance_cols.items()}
    relevance = {k: relevance_metrics(df["human_relevant"], v) for k, v in relevant_cols.items()}
    cons = {m: consistency_of(r) for m, r in ok.items()}

    chosen, selection = choose(
        {m: stance[m].spearman for m in ok},
        {m: draws[m] for m in ok},
        {m: r.corpus_cost for m, r in ok.items()},
    )
    selection["not_compared"] = {
        m: "no cached score for every labelled item (scoring was blocked)" for m in missing
    }

    # The contract's core JSON for the chosen model, then the others appended.
    preds = pd.DataFrame(
        {
            "item": df["item"],
            "baseline_stance": df["baseline_stance"],
            "baseline_relevant": df["baseline_relevant"],
            "llm_stance": df[f"{chosen}|stance"],
            "llm_relevance": df[f"{chosen}|relevance"],
        }
    )
    out = build_json(labels, preds, cons[chosen], model=chosen, input_mode=input_mode)
    scorers: list[dict[str, Any]] = []
    for key in ["baseline", chosen, *[m for m in ok if m != chosen]]:
        sm, rm = stance[key], relevance[key]
        entry = next((s for s in out["scorers"] if s["name"] == names[key]), None)
        if entry is None:
            conf = sm.confusion
            entry = {
                "name": names[key],
                "kind": "llm",
                "stance": {
                    "n_scored": sm.n_scored,
                    "n_compared": sm.n_compared,
                    "spearman": _num(sm.spearman),
                    "exact": _num(sm.exact),
                    "within_one": _num(sm.within_one),
                    "confusion": {
                        "labels": SCALE,
                        "rows": conf[SCALE].astype(int).values.tolist(),
                        "no_stance": conf["no stance"].astype(int).tolist(),
                    },
                },
                "relevance": {
                    "n": rm.n,
                    "precision": _num(rm.precision),
                    "recall": _num(rm.recall),
                    "accuracy": _num(rm.accuracy),
                },
            }
        for j, metric in enumerate(["spearman", "exact", "within_one"]):
            entry["stance"][f"{metric}_ci"] = list(interval(draws[key][:, j]))
        if key != "baseline":
            entry["model"] = key
            entry["chosen"] = key == chosen
            c = cons[key]
            entry["consistency"] = None if c is None else _consistency_json(c)
            entry["cost_per_doc_usd"] = _num(ok[key].cost_per_doc, 6)
            entry["corpus_cost_usd"] = _num(ok[key].corpus_cost, 3)
        scorers.append(entry)
    out["scorers"] = scorers
    out["selection"] = selection
    out["n_bootstrap"] = N_BOOT

    md = _tables(df, names, stance, relevance, draws, cons, ok, selection)
    return out, md


def _num(x: float | None, digits: int = 4) -> float | None:
    return None if x is None or math.isnan(x) else round(float(x), digits)


def _consistency_json(c: Consistency) -> dict[str, Any]:
    return {
        "n": c.n,
        "exact": _num(c.exact),
        "within_half": _num(c.within_half),
        "mean_abs_diff": _num(c.mean_abs_diff),
        "relevance_agree": _num(c.relevance_agree),
    }


def _tables(
    df: pd.DataFrame,
    names: dict[str, str],
    stance: dict[str, Any],
    relevance: dict[str, Any],
    draws: dict[str, np.ndarray],
    cons: dict[str, Consistency | None],
    ok: dict[str, ModelRun],
    selection: dict[str, Any],
) -> str:
    lines = [
        "| scorer | compared | Spearman \u03c1 (95% CI) | exact (95% CI) | within 1 (95% CI) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for k, name in names.items():
        m = stance[k]
        r, e, w = (interval(draws[k][:, j]) for j in range(3))
        lines.append(
            f"| {name} | {m.n_compared} of {m.n_scored} | {_f(m.spearman)}{_ci(*r)} | "
            f"{_f(m.exact, True)}{_ci(*e, pct=True)} | {_f(m.within_one, True)}"
            f"{_ci(*w, pct=True)} |"
        )
    lines += [
        "",
        "RELEVANCE",
        "",
        "| scorer | items | precision | recall | accuracy |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for k, name in names.items():
        r = relevance[k]
        lines.append(
            f"| {name} | {r.n} | {_f(r.precision, True)} | {_f(r.recall, True)} | "
            f"{_f(r.accuracy, True)} |"
        )
    lines += [
        "",
        "CONSISTENCY",
        "",
        "| model | items run twice | identical stance | within 0.5 | mean abs. diff. "
        "| same relevance call | cost per doc | full corpus |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for m, run_ in ok.items():
        c = cons[m]
        cost = "\u2013" if run_.cost_per_doc is None else f"${run_.cost_per_doc:.5f}"
        corpus = "\u2013" if run_.corpus_cost is None else f"${run_.corpus_cost:.2f}"
        if c is None:
            lines.append(f"| {m} | 0 | \u2013 | \u2013 | \u2013 | \u2013 | {cost} | {corpus} |")
        else:
            lines.append(
                f"| {m} | {c.n} | {_f(c.exact, True)} | {_f(c.within_half, True)} | "
                f"{_f(c.mean_abs_diff)} | {_f(c.relevance_agree, True)} | {cost} | {corpus} |"
            )
    lines += ["", "SELECTION", "", "```", json.dumps(selection, indent=2), "```"]
    for k, name in names.items():
        lines += ["", f"CONFUSION {name}", "", *_confusion_md(stance[k].confusion)]
    item_cols = ["item", "human_stance", "baseline_stance"] + [f"{m}|stance" for m in ok]
    lines += ["", "ITEMS", "", "| " + " | ".join(item_cols) + " |"]
    lines.append("|" + " ---: |" * len(item_cols))
    for row in df[item_cols].itertuples(index=False):
        lines.append(
            "| " + " | ".join(_f(float(v)) if pd.notna(v) else "\u2013" for v in row) + " |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--labelling-set", type=Path, default=OUT_DIR / SET_FILE)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--input-mode", choices=["passages", "full"], default=DEFAULT_INPUT_MODE)
    parser.add_argument("--json-out", type=Path, default=Path("data/analysis/evaluation.json"))
    parser.add_argument("--tables-out", type=Path, default=None, help="markdown tables")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from hawk.scoring.corpus import load_documents  # slow; keep out of import time

    labels = read_labels(args.labels)
    chosen = pd.read_csv(args.labelling_set)
    mismatch = labels.merge(chosen, on="item", suffixes=("", "_set")).query("doc_id != doc_id_set")
    if not mismatch.empty:
        raise SystemExit(f"labels do not match the labelling set for items {list(mismatch.item)}")
    docs = load_documents()
    items = chosen[chosen["item"].isin(labels["item"])].merge(docs[["doc_id", "text"]], on="doc_id")
    out, md = run(labels, items, args.models, args.input_mode, len(docs))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    if args.tables_out:
        args.tables_out.write_text(md)
    print(md)
    log.info("chosen model: %s", out["selection"]["chosen"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
