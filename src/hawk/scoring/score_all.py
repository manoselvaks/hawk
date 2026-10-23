"""Score the whole corpus with the LLM and the baseline.

Usage::

    python -m hawk.scoring.score_all                 # print the cost estimate and stop
    python -m hawk.scoring.score_all --confirm       # actually score (spends money)

Without ``--confirm`` this only prints how many documents would be scored, how many
are already cached, and the estimated cost, taken from the mean cost per document of
the same model and input mode in ``data/pilot/pilot_scores.csv``. With ``--confirm``
it scores every document (cached ones cost nothing), stopping if the spend cap is
reached, and writes ``data/scores.parquet`` (schema in ``docs/data-contract.md``).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from hawk.scoring import baseline
from hawk.scoring.corpus import load_documents
from hawk.scoring.llm import DEFAULT_INPUT_MODE, DEFAULT_MODEL, PROMPT_VERSION, LLMScorer
from hawk.scoring.pilot import SCORES_PATH as PILOT_SCORES
from hawk.scoring.spend import BudgetExceededError, SpendTracker

log = logging.getLogger("hawk.scoring.score_all")

OUT_PATH = Path("data/scores.parquet")

# Column order of data/scores.parquet; docs/data-contract.md describes each one.
SCORES_COLUMNS = [
    "doc_id",
    "kind",
    "url",
    "title",
    "speaker",
    "role",
    "is_mpc_member",
    "published_date",
    "speech_date",
    "meeting_date",
    "n_chars",
    "policy_density",
    "llm_relevance",
    "llm_stance",
    "llm_confidence",
    "llm_reason",
    "baseline_stance",
    "baseline_hawkish",
    "baseline_dovish",
    "baseline_relevance",
    "model",
    "input_mode",
    "prompt_version",
]


def estimate_cost(
    n_uncached: int, model: str, input_mode: str, pilot_path: Path = PILOT_SCORES
) -> float | None:
    """Mean pilot cost per document for this model and mode, times ``n_uncached``."""
    if not pilot_path.exists():
        return None
    pilot = pd.read_csv(pilot_path)
    match = pilot[(pilot["model"] == model) & (pilot["input_mode"] == input_mode)]
    if match.empty:
        return None
    return float(match["cost_usd"].mean()) * n_uncached


def scores_table(
    docs: pd.DataFrame,
    rows: list[dict[str, Any]],
    *,
    model: str,
    input_mode: str,
    prompt_version: str = PROMPT_VERSION,
) -> pd.DataFrame:
    """Join document metadata with per-document score rows into the contract table.

    ``docs`` is ``load_documents()`` output; ``rows`` hold ``doc_id`` and the ``llm_*``
    and ``baseline_*`` fields. Documents without a row (e.g. after the spend cap
    stopped the run) are left out. ``date`` is renamed ``published_date``.
    """
    meta = docs.drop(columns="text").rename(columns={"date": "published_date"})
    scores = meta.merge(pd.DataFrame(rows), on="doc_id")
    scores["llm_stance"] = pd.to_numeric(scores["llm_stance"]).astype("float64")
    scores["model"], scores["input_mode"] = model, input_mode
    scores["prompt_version"] = prompt_version
    return scores[SCORES_COLUMNS]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--input-mode", choices=["passages", "full"], default=DEFAULT_INPUT_MODE)
    parser.add_argument("--confirm", action="store_true", help="really call the API")
    parser.add_argument("--spend-cap", type=float, default=None, help="USD; default $4 or env")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument(
        "--max-retries", type=int, default=3, help="attempts per document (OpenRouter 402s)"
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=2_000,
        help="reply cap; a lower cap makes OpenRouter reserve less credit per request",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    docs = load_documents()
    tracker = SpendTracker(cap_usd=args.spend_cap)
    scorer = LLMScorer(
        args.model,
        input_mode=args.input_mode,
        tracker=tracker,
        max_retries=args.max_retries,
        max_tokens=args.max_tokens,
    )
    uncached = sum(
        scorer.cached(k, t) is None for k, t in zip(docs["kind"], docs["text"], strict=True)
    )
    estimate = estimate_cost(uncached, args.model, args.input_mode)
    est_text = "unknown (no pilot run for this model and mode)"
    if estimate is not None:
        est_text = f"about ${estimate:.2f}"
    print(
        f"{len(docs)} documents; {len(docs) - uncached} already cached, {uncached} to score "
        f"with {args.model} ({args.input_mode}).\n"
        f"Estimated cost: {est_text}. Spent so far: ${tracker.spent_usd:.4f} "
        f"of a ${tracker.cap_usd:.2f} cap."
    )
    if not args.confirm:
        print("Nothing scored. Re-run with --confirm to score the corpus.")
        return 2

    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    try:
        for i, doc in enumerate(docs.to_dict("records"), start=1):
            try:
                rec = scorer.score(doc["kind"], doc["text"])
            except (RuntimeError, requests.RequestException) as exc:
                log.error("skipped %s: %s", doc["doc_id"], exc)
                failed.append(doc["doc_id"])
                continue
            b = baseline.score_text(doc["text"])
            rows.append(
                {
                    "doc_id": doc["doc_id"],
                    "llm_relevance": rec["relevance"],
                    "llm_stance": rec["stance"],
                    "llm_confidence": rec["confidence"],
                    "llm_reason": rec["reason"],
                    "baseline_stance": b.stance,
                    "baseline_hawkish": b.hawkish,
                    "baseline_dovish": b.dovish,
                    "baseline_relevance": b.relevance,
                }
            )
            if i % 100 == 0:
                log.info("%d/%d scored, $%.4f spent", i, len(docs), tracker.session_usd)
    except BudgetExceededError as exc:
        log.error("stopped early: %s", exc)

    scores = scores_table(
        docs, rows, model=args.model, input_mode=args.input_mode, prompt_version=PROMPT_VERSION
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(args.out, index=False)
    log.info("wrote %d rows to %s; spent $%.4f", len(scores), args.out, tracker.session_usd)
    if failed:
        log.error("%d documents failed and are missing; re-run to fill them", len(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
