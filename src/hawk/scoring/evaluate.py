"""Compare the baseline and LLM scores with hand labels, and write a markdown report.

Usage::

    python -m hawk.scoring.evaluate --labels labels.csv [--model MODEL] [--input-mode passages]
                                    [--out docs/evaluation.md]

``labels.csv`` is the file exported by ``labelling/label.html``: one row per item
with ``score`` (-2..+2, blank when not about monetary policy) and
``not_monetary_policy`` (1 or 0). Unlabelled items are ignored.

What is reported, for each scorer:

* **Stance**, on items the human scored (i.e. judged relevant) and the scorer gave a
  stance for: Spearman rank correlation, exact accuracy and within-1 accuracy after
  rounding the scorer's stance to the nearest whole point (halves away from zero),
  and a confusion matrix. Coverage says how many human-scored items the scorer gave
  a stance for at all.
* **Relevance**, on every labelled item: precision and recall of the scorer's
  "about monetary policy" call against the human's (LLM: relevance >= 0.5;
  baseline: policy-term density above its threshold).
* **LLM self-consistency**: the same items scored a second time (``replicate=1``),
  with exact and within-0.5 agreement and the mean absolute difference.

It also writes the same numbers as JSON (``--json-out``) for the website.

The metric functions are pure and take plain frames, so they are tested with a
synthetic labels file and no network.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hawk.scoring import baseline
from hawk.scoring.llm import DEFAULT_INPUT_MODE, DEFAULT_MODEL, LLMScorer
from hawk.scoring.make_labelling_set import OUT_DIR, SET_FILE

log = logging.getLogger("hawk.scoring.evaluate")

LLM_RELEVANCE_THRESHOLD = 0.5
SCALE = [-2, -1, 0, 1, 2]


def read_labels(path: Path) -> pd.DataFrame:
    """Labelled rows of an exported labels file: ``item, doc_id, human_stance, human_relevant``."""
    raw = pd.read_csv(path, dtype={"note": str})
    not_mp = pd.to_numeric(raw["not_monetary_policy"], errors="coerce")
    score = pd.to_numeric(raw["score"], errors="coerce")
    labelled = not_mp.notna() | score.notna()
    out = pd.DataFrame(
        {
            "item": raw["item"],
            "doc_id": raw["doc_id"],
            "human_stance": score.where(not_mp != 1),
            "human_relevant": (not_mp != 1) & score.notna(),
        }
    )[labelled]
    bad = out["human_stance"].dropna()
    if not bad.isin(SCALE).all():
        raise ValueError(f"scores outside -2..+2: {sorted(set(bad) - set(SCALE))}")
    return out.reset_index(drop=True)


def round_half_away(x: float) -> int:
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman's rho: Pearson correlation of average ranks (NaN if either is constant)."""
    ra, rb = a.rank().to_numpy(), b.rank().to_numpy()
    if len(ra) < 3 or ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


@dataclass
class StanceMetrics:
    n_scored: int  # human-scored items
    n_compared: int  # ... for which the scorer also gave a stance
    spearman: float
    exact: float
    within_one: float
    confusion: pd.DataFrame


@dataclass
class RelevanceMetrics:
    n: int
    precision: float
    recall: float
    accuracy: float


def stance_metrics(human: pd.Series, model: pd.Series) -> StanceMetrics:
    """``human`` and ``model`` aligned by item; NaN in ``model`` means no stance given."""
    scored = human.notna()
    both = scored & model.notna()
    h, m = human[both], model[both]
    rounded = m.map(round_half_away)
    confusion = pd.crosstab(
        pd.Categorical(h.astype(int), categories=SCALE),
        pd.Categorical(rounded, categories=SCALE),
        rownames=["human"],
        colnames=["model"],
        dropna=False,
    )
    confusion["no stance"] = (
        human[scored & model.isna()].astype(int).value_counts().reindex(SCALE, fill_value=0)
    )
    n = int(both.sum())
    return StanceMetrics(
        n_scored=int(scored.sum()),
        n_compared=n,
        spearman=spearman(h, m),
        exact=float((rounded == h).mean()) if n else float("nan"),
        within_one=float(((m - h).abs() <= 1).mean()) if n else float("nan"),
        confusion=confusion,
    )


def relevance_metrics(human: pd.Series, model: pd.Series) -> RelevanceMetrics:
    """Both boolean, aligned by item. Positive class = "about monetary policy"."""
    h, m = human.astype(bool), model.astype(bool)
    tp = int((h & m).sum())

    def ratio(a: int, b: int) -> float:
        return a / b if b else float("nan")

    return RelevanceMetrics(
        n=len(h),
        precision=ratio(tp, int(m.sum())),
        recall=ratio(tp, int(h.sum())),
        accuracy=float((h == m).mean()) if len(h) else float("nan"),
    )


@dataclass
class Consistency:
    n: int
    exact: float
    within_half: float
    mean_abs_diff: float
    relevance_agree: float


def self_consistency(first: pd.DataFrame, second: pd.DataFrame) -> Consistency:
    """Two runs of the LLM on the same items (columns ``stance``, ``relevance``).

    A stance of ``None`` on both runs counts as agreement; on one run only, as
    disagreement (and is left out of the mean absolute difference).
    """
    s1, s2 = first["stance"], second["stance"]
    both = s1.notna() & s2.notna()
    neither = s1.isna() & s2.isna()
    diff = (s1[both] - s2[both]).abs()
    rel1 = first["relevance"] >= LLM_RELEVANCE_THRESHOLD
    rel2 = second["relevance"] >= LLM_RELEVANCE_THRESHOLD
    n = len(first)
    return Consistency(
        n=n,
        exact=float(((diff == 0).sum() + neither.sum()) / n) if n else float("nan"),
        within_half=float(((diff <= 0.5).sum() + neither.sum()) / n) if n else float("nan"),
        mean_abs_diff=float(diff.mean()) if len(diff) else float("nan"),
        relevance_agree=float((rel1 == rel2).mean()) if n else float("nan"),
    )


# -- report ---------------------------------------------------------------------


def _fmt(x: float, pct: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "\u2013"
    return f"{100 * x:.0f}%" if pct else f"{x:.2f}"


def _confusion_md(table: pd.DataFrame) -> str:
    cols = [str(c) for c in table.columns]
    lines = [
        "| human \\ model | " + " | ".join(f"{c:>2}" for c in cols) + " |",
        "| ---: | " + " | ".join("---:" for _ in cols) + " |",
    ]
    for label, row in table.iterrows():
        name = f"{label:+d}" if label else "0"
        lines.append(f"| {name} | " + " | ".join(str(int(v)) for v in row) + " |")
    return "\n".join(lines)


def _metrics(
    labels: pd.DataFrame, predictions: pd.DataFrame, *, model: str, input_mode: str
) -> tuple[pd.DataFrame, dict[str, StanceMetrics], dict[str, RelevanceMetrics]]:
    df = labels.merge(predictions, on="item", how="left")
    scorers = {
        "Baseline (word lists)": (df["baseline_stance"], df["baseline_relevant"]),
        f"LLM ({model}, {input_mode})": (
            df["llm_stance"],
            df["llm_relevance"] >= LLM_RELEVANCE_THRESHOLD,
        ),
    }
    stance = {name: stance_metrics(df["human_stance"], s) for name, (s, _) in scorers.items()}
    relevance = {
        name: relevance_metrics(df["human_relevant"], r) for name, (_, r) in scorers.items()
    }
    return df, stance, relevance


def _num(x: float) -> float | None:
    return None if x is None or math.isnan(x) else round(float(x), 4)


def build_json(
    labels: pd.DataFrame,
    predictions: pd.DataFrame,
    consistency: Consistency | None,
    *,
    model: str,
    input_mode: str,
) -> dict[str, Any]:
    """The same results as ``build_report``, as the ``evaluation.json`` the website reads.

    Schema in ``docs/data-contract.md``; NaN becomes ``null``.
    """
    df, stance, relevance = _metrics(labels, predictions, model=model, input_mode=input_mode)
    scorers = []
    for (name, m), r in zip(stance.items(), relevance.values(), strict=True):
        conf = m.confusion
        scorers.append(
            {
                "name": name,
                "kind": "baseline" if name.startswith("Baseline") else "llm",
                "stance": {
                    "n_scored": m.n_scored,
                    "n_compared": m.n_compared,
                    "spearman": _num(m.spearman),
                    "exact": _num(m.exact),
                    "within_one": _num(m.within_one),
                    "confusion": {
                        "labels": SCALE,
                        "rows": conf[SCALE].astype(int).values.tolist(),
                        "no_stance": conf["no stance"].astype(int).tolist(),
                    },
                },
                "relevance": {
                    "n": r.n,
                    "precision": _num(r.precision),
                    "recall": _num(r.recall),
                    "accuracy": _num(r.accuracy),
                },
            }
        )
    out: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": model,
        "input_mode": input_mode,
        "n_labelled": len(df),
        "n_relevant": int(df["human_relevant"].sum()),
        "scorers": scorers,
        "consistency": None,
    }
    if consistency is not None:
        c = consistency
        out["consistency"] = {
            "n": c.n,
            "exact": _num(c.exact),
            "within_half": _num(c.within_half),
            "mean_abs_diff": _num(c.mean_abs_diff),
            "relevance_agree": _num(c.relevance_agree),
        }
    return out


def build_report(
    labels: pd.DataFrame,
    predictions: pd.DataFrame,
    consistency: Consistency | None,
    *,
    model: str,
    input_mode: str,
) -> str:
    """Markdown report. ``predictions`` has one row per item with columns
    ``item, baseline_stance, baseline_relevant, llm_stance, llm_relevance``."""
    df, stance, relevance = _metrics(labels, predictions, model=model, input_mode=input_mode)

    out = [
        "# Scorer evaluation against hand labels",
        "",
        f"{len(df)} labelled items; {int(df['human_relevant'].sum())} scored by hand as about "
        f"monetary policy, {int((~df['human_relevant']).sum())} marked not about it.",
        "",
        "## Stance",
        "",
        "Items the human scored. The scorer's stance is rounded to the nearest whole point "
        "(halves away from zero) for exact accuracy and the confusion matrix; Spearman uses "
        "the unrounded value.",
        "",
        "| scorer | compared | Spearman | exact | within 1 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, m in stance.items():
        out.append(
            f"| {name} | {m.n_compared} of {m.n_scored} | {_fmt(m.spearman)} | "
            f"{_fmt(m.exact, True)} | {_fmt(m.within_one, True)} |"
        )
    for name, m in stance.items():
        out += ["", f"### Confusion matrix: {name}", "", _confusion_md(m.confusion)]
    out += [
        "",
        "## Relevance",
        "",
        "Positive class: about monetary policy. LLM: relevance >= "
        f"{LLM_RELEVANCE_THRESHOLD}. Baseline: policy terms per 100 words >= "
        f"{baseline.RELEVANCE_DENSITY_THRESHOLD}.",
        "",
        "| scorer | items | precision | recall | accuracy |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, r in relevance.items():
        out.append(
            f"| {name} | {r.n} | {_fmt(r.precision, True)} | {_fmt(r.recall, True)} | "
            f"{_fmt(r.accuracy, True)} |"
        )
    if consistency is not None:
        c = consistency
        out += [
            "",
            "## LLM self-consistency",
            "",
            "Every labelled item scored a second time with the same model, prompt and input.",
            "",
            "| items | identical stance | within 0.5 | mean abs. difference "
            "| same relevance call |",
            "| ---: | ---: | ---: | ---: | ---: |",
            f"| {c.n} | {_fmt(c.exact, True)} | {_fmt(c.within_half, True)} | "
            f"{_fmt(c.mean_abs_diff)} | {_fmt(c.relevance_agree, True)} |",
        ]
    return "\n".join(out) + "\n"


# -- CLI ------------------------------------------------------------------------


def predict(
    items: pd.DataFrame, scorer: LLMScorer, replicate: int = 0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Baseline and LLM predictions for each item (``items`` has ``item, kind, text``)."""
    rows, llm_rows = [], []
    for row in items.to_dict("records"):
        b = baseline.score_text(row["text"])
        rec = scorer.score(row["kind"], row["text"], replicate=replicate)
        rows.append(
            {
                "item": row["item"],
                "baseline_stance": b.stance,
                "baseline_relevant": b.is_relevant,
                "llm_stance": rec["stance"],
                "llm_relevance": rec["relevance"],
            }
        )
        llm_rows.append(
            {"item": row["item"], "stance": rec["stance"], "relevance": rec["relevance"]}
        )
    preds = pd.DataFrame(rows)
    preds["llm_stance"] = pd.to_numeric(preds["llm_stance"])
    llm = pd.DataFrame(llm_rows)
    llm["stance"] = pd.to_numeric(llm["stance"])
    return preds, llm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--labelling-set", type=Path, default=OUT_DIR / SET_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--input-mode", choices=["passages", "full"], default=DEFAULT_INPUT_MODE)
    parser.add_argument("--no-consistency", action="store_true", help="skip the second run")
    parser.add_argument("--out", type=Path, default=Path("docs/evaluation.md"))
    parser.add_argument(
        "--json-out", type=Path, default=Path("data/analysis/evaluation.json"), help="for the site"
    )
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

    scorer = LLMScorer(args.model, input_mode=args.input_mode)
    preds, first = predict(items, scorer, replicate=0)
    consistency = None
    if not args.no_consistency:
        _, second = predict(items, scorer, replicate=1)
        consistency = self_consistency(first, second)
    report = build_report(labels, preds, consistency, model=args.model, input_mode=args.input_mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    results = build_json(labels, preds, consistency, model=args.model, input_mode=args.input_mode)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(results, indent=2) + "\n")
    log.info("wrote %s (OpenRouter spend this run: $%.4f)", args.out, scorer.tracker.session_usd)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
