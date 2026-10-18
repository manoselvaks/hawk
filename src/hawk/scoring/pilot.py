"""Pilot: score a small sample with several candidate models and compare them.

Usage::

    python -m hawk.scoring.pilot [--models M1 M2 ...] [--modes passages full] [--n-per-era 5]

The sample is about 20 documents, the same for every model: per era, three speeches by
MPC members, one by other Bank staff (to test the relevance call) and one set of
minutes, drawn with a fixed seed. Documents in the hand-labelling set are left out,
so choosing a model here does not tune it to the evaluation set.

Every (model, input mode) pair scores each document twice (``replicate`` 0 and 1) to
measure self-consistency. Results go to ``data/pilot/pilot_scores.csv`` and a summary
to ``docs/pilot.md``. Calls are cached, so a re-run costs nothing.

There are no hand labels yet, so the pilot cannot say which model is *right*. It
reports what can be measured without them: valid-reply rate, cost, self-consistency,
agreement with the other models and with the baseline, and the reasons themselves,
which are worth reading.
"""

from __future__ import annotations

import argparse
import itertools
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from hawk.scoring import baseline, context
from hawk.scoring.corpus import load_documents
from hawk.scoring.evaluate import LLM_RELEVANCE_THRESHOLD, spearman
from hawk.scoring.llm import LLMScorer
from hawk.scoring.make_labelling_set import OUT_DIR, SET_FILE
from hawk.scoring.spend import SpendTracker

log = logging.getLogger("hawk.scoring.pilot")

CANDIDATES = [
    "deepseek/deepseek-v4.1-flash",
    "openai/gpt-6-luna",
    "anthropic/claude-haiku-5.5",
]
PILOT_SEED = 7
SCORES_PATH = Path("data/pilot/pilot_scores.csv")
REPORT_PATH = Path("docs/pilot.md")


def pilot_sample(
    docs: pd.DataFrame, exclude: set[str], n_per_era: int = 5, seed: int = PILOT_SEED
) -> pd.DataFrame:
    """Per era: MPC-member speeches, one other speech and one set of minutes."""
    rng = np.random.default_rng(seed)
    pool = docs[~docs["doc_id"].isin(exclude)]
    picks = []
    for era in context.ERA_NAMES:
        in_era = pool[pool["era"] == era]
        member = in_era["is_mpc_member"].fillna(False)
        groups = [
            in_era[(in_era["kind"] == "speech") & member],
            in_era[(in_era["kind"] == "speech") & ~member],
            in_era[in_era["kind"] == "minutes"],
        ]
        sizes = [n_per_era - 2, 1, 1] if n_per_era >= 3 else [n_per_era, 0, 0]
        for group, size in zip(groups, sizes, strict=True):
            take = min(size, len(group))
            picks.append(group.iloc[rng.choice(len(group), size=take, replace=False)])
    return pd.concat(picks).sort_values("date").reset_index(drop=True)


def run(
    sample: pd.DataFrame,
    models: list[str],
    modes: list[str],
    tracker: SpendTracker,
    workers: int = 6,
) -> pd.DataFrame:
    """Score every document with every (model, mode, replicate); one row per call."""
    scorers = {
        (m, mode): LLMScorer(m, input_mode=mode, tracker=tracker)  # type: ignore[arg-type]
        for m in models
        for mode in modes
    }
    jobs = list(itertools.product(scorers, range(len(sample)), (0, 1)))

    def one(job: tuple[tuple[str, str], int, int]) -> dict[str, Any]:
        (model, mode), idx, rep = job
        doc = sample.iloc[idx]
        try:
            rec = scorers[(model, mode)].score(doc["kind"], doc["text"], replicate=rep)
        except RuntimeError as exc:  # failed after retries: record it, keep going
            log.error("%s %s %s: %s", model, mode, doc["doc_id"], exc)
            rec = {"stance": None, "relevance": None, "confidence": None, "reason": None}
            rec["error"] = str(exc)
        return {
            "doc_id": doc["doc_id"],
            "model": model,
            "input_mode": mode,
            "replicate": rep,
            **rec,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, jobs))
    return pd.DataFrame(rows)


def summarise(scores: pd.DataFrame, sample: pd.DataFrame, corpus_size: int) -> pd.DataFrame:
    """One row per (model, mode) with the comparison metrics."""
    base = pd.Series(
        [baseline.score_text(t).stance for t in sample["text"]], index=sample["doc_id"]
    )
    first = scores[scores["replicate"] == 0].copy()
    first["stance"] = pd.to_numeric(first["stance"])
    wide = first.pivot_table(
        index="doc_id", columns=["model", "input_mode"], values="stance", dropna=False
    )
    rows = []
    for (model, mode), grp in scores.groupby(["model", "input_mode"]):
        r0 = grp[grp["replicate"] == 0].set_index("doc_id")
        r1 = grp[grp["replicate"] == 1].set_index("doc_id").reindex(r0.index)
        s0, s1 = pd.to_numeric(r0["stance"]), pd.to_numeric(r1["stance"])
        both = s0.notna() & s1.notna()
        same = ((s0 == s1) & both) | (s0.isna() & s1.isna())
        rel0 = pd.to_numeric(r0["relevance"])
        others = [c for c in wide.columns if c[1] == mode and c[0] != model]
        mine = wide[(model, mode)]
        agreement = [spearman(*_paired(mine, wide[c])) for c in others]
        paid = grp[~grp.get("cached", pd.Series(False, index=grp.index)).astype(bool)]
        cost_per_doc = pd.to_numeric(grp["cost_usd"]).mean()
        rows.append(
            {
                "model": model,
                "input": mode,
                "valid": f"{int(rel0.notna().sum())}/{len(r0)}",
                "relevant (>= 0.5)": int((rel0 >= LLM_RELEVANCE_THRESHOLD).sum()),
                "stance given": int(s0.notna().sum()),
                "same stance on re-run": float(same.mean()),
                "rho vs other models": float(np.nanmean(agreement)) if agreement else np.nan,
                "rho vs baseline": spearman(*_paired(s0, base.reindex(s0.index))),
                "prompt tokens": float(pd.to_numeric(grp["prompt_tokens"]).mean()),
                "cost per doc ($)": float(cost_per_doc),
                "full corpus ($)": float(cost_per_doc * corpus_size),
                "calls paid this run": len(paid),
            }
        )
    return pd.DataFrame(rows)


def _paired(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    keep = a.notna() & b.notna()
    return a[keep], b[keep]


def write_report(
    summary: pd.DataFrame,
    scores: pd.DataFrame,
    sample: pd.DataFrame,
    path: Path,
    spend_total: float,
) -> None:
    fmt = summary.copy()
    fmt["same stance on re-run"] = fmt["same stance on re-run"].map(lambda x: f"{100 * x:.0f}%")
    for col in ("rho vs other models", "rho vs baseline"):
        fmt[col] = fmt[col].map(lambda x: "\u2013" if pd.isna(x) else f"{x:.2f}")
    fmt["prompt tokens"] = fmt["prompt tokens"].map(lambda x: f"{x:,.0f}")
    fmt["cost per doc ($)"] = fmt["cost per doc ($)"].map(lambda x: f"{x:.5f}")
    fmt["full corpus ($)"] = fmt["full corpus ($)"].map(lambda x: f"{x:.2f}")
    fmt = fmt.drop(columns="calls paid this run")

    first = scores[scores["replicate"] == 0].merge(
        sample[["doc_id", "title", "date", "kind"]], on="doc_id"
    )
    lines = [
        "# Scoring pilot",
        "",
        f"{len(sample)} documents (none from the labelling set), scored by each model and "
        "input mode twice. Built by `python -m hawk.scoring.pilot`; raw results in "
        "`data/pilot/pilot_scores.csv`.",
        "",
        "`rho` is Spearman rank correlation of stance on documents where both sides gave "
        "one. *Same stance on re-run* counts a null stance on both runs as agreement. "
        "*Full corpus* is cost per document times the number of scorable documents, for "
        "one pass.",
        "",
        _table_md(fmt),
        "",
        f"Cumulative OpenRouter spend recorded in `data/llm_spend.jsonl`: ${spend_total:.4f}.",
        "",
        "## Documents",
        "",
        "| date | kind | title |",
        "| --- | --- | --- |",
    ]
    for row in sample.to_dict("records"):
        lines.append(f"| {row['date'].date()} | {row['kind']} | {row['title']} |")
    lines += ["", "## Every score (first run)", ""]
    for (model, mode), grp in first.groupby(["model", "input_mode"]):
        lines += [f"### {model} · {mode}", "", "| date | title | rel. | stance | reason |"]
        lines.append("| --- | --- | ---: | ---: | --- |")
        for r in grp.sort_values("date").to_dict("records"):
            stance = "\u2013" if pd.isna(r["stance"]) else f"{float(r['stance']):+.1f}"
            rel = "\u2013" if pd.isna(r["relevance"]) else f"{float(r['relevance']):.2f}"
            reason = str(r["reason"]).replace("|", "/")
            day, title = r["date"].date(), r["title"][:60]
            lines.append(f"| {day} | {title} | {rel} | {stance} | {reason} |")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _table_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    out += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", default=CANDIDATES)
    parser.add_argument(
        "--modes", nargs="+", choices=["passages", "full"], default=["passages", "full"]
    )
    parser.add_argument("--n-per-era", type=int, default=5)
    parser.add_argument("--spend-cap", type=float, default=None, help="USD; default $4 or env")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    decisions = pd.read_parquet("data/market/mpc_decisions.parquet")
    docs = context.add_context(load_documents(), decisions)
    labelling = OUT_DIR / SET_FILE
    exclude = set(pd.read_csv(labelling)["doc_id"]) if labelling.exists() else set()
    sample = pilot_sample(docs, exclude, args.n_per_era)

    tracker = SpendTracker(cap_usd=args.spend_cap)
    start = tracker.spent_usd
    scores = run(sample, args.models, args.modes, tracker)
    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    scores.to_csv(SCORES_PATH, index=False)

    summary = summarise(scores, sample, corpus_size=len(docs))
    write_report(summary, scores, sample, REPORT_PATH, tracker.spent_usd)
    log.info("spent $%.4f this run, $%.4f in total", tracker.spent_usd - start, tracker.spent_usd)
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(summary.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
