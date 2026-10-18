"""Choose the documents to hand-label and build the labelling tool.

Usage::

    python -m hawk.scoring.make_labelling_set [--speeches 30] [--minutes 6] [--seed 2026]

Writes ``labelling/labelling_set.csv`` (the chosen documents, with their era and
policy context, for the evaluation) and ``labelling/label.html`` (the self-contained
labelling tool, with the documents embedded).

Selection, all with one seeded random generator so it can be reproduced:

* speeches by sitting MPC members only (``is_mpc_member``), since those carry the
  policy signal the project is about; minutes are drawn separately;
* each pool is split into cells of era x policy context (hike / cut / hold, see
  ``hawk.scoring.context``);
* documents are drawn one at a time, visiting the cells in rounds: in each round every
  era is visited once and the context rotates (``(round + era index) mod 3``), so the
  sample spreads over eras and contexts instead of mirroring the corpus, where holds
  outnumber moves seven to one. Empty or used-up cells (there were no hikes from
  2008 to 2015) are skipped;
* within a cell the document is drawn at random.

The tool shows each document's policy passages, never any model or baseline score,
and the items are shown in shuffled order so era does not run in sequence.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from hawk.scoring import context
from hawk.scoring.corpus import load_documents
from hawk.scoring.textprep import policy_passages

log = logging.getLogger("hawk.scoring.make_labelling_set")

OUT_DIR = Path("labelling")
SET_FILE = "labelling_set.csv"
HTML_FILE = "label.html"
TEMPLATE = Path(__file__).parent / "templates" / "label_template.html"
DEFAULT_SEED = 2026
SET_COLUMNS = [
    "item",
    "doc_id",
    "kind",
    "url",
    "title",
    "speaker",
    "date",
    "era",
    "policy_context",
]


def stratified_sample(pool: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Draw ``n`` rows spread over era x policy context, as described in the module doc."""
    remaining = {
        (e, c): list(pool.index[(pool["era"] == e) & (pool["policy_context"] == c)])
        for e in context.ERA_NAMES
        for c in context.CONTEXTS
    }
    chosen: list[int] = []
    round_no = 0
    while len(chosen) < n and any(remaining.values()):
        for e_idx, e in enumerate(context.ERA_NAMES):
            if len(chosen) == n:
                break
            cell = remaining[(e, context.CONTEXTS[(round_no + e_idx) % len(context.CONTEXTS)])]
            if cell:
                chosen.append(cell.pop(int(rng.integers(len(cell)))))
        round_no += 1
    if len(chosen) < n:
        log.warning("only %d documents available, wanted %d", len(chosen), n)
    return pool.loc[chosen]


def select(
    docs: pd.DataFrame, n_speeches: int, n_minutes: int, seed: int = DEFAULT_SEED
) -> pd.DataFrame:
    """The labelling set, in shuffled display order, with ``item`` numbered from 1."""
    rng = np.random.default_rng(seed)
    speeches = docs[(docs["kind"] == "speech") & docs["is_mpc_member"].fillna(False)]
    minutes = docs[docs["kind"] == "minutes"]
    picked = pd.concat(
        [stratified_sample(speeches, n_speeches, rng), stratified_sample(minutes, n_minutes, rng)]
    )
    picked = picked.iloc[rng.permutation(len(picked))].reset_index(drop=True)
    picked.insert(0, "item", range(1, len(picked) + 1))
    return picked


def tool_items(selection: pd.DataFrame) -> list[dict[str, object]]:
    """What the labelling page shows for each item: no scores, no policy context."""
    items = []
    for row in selection.to_dict("records"):
        speech = row["kind"] == "speech"
        items.append(
            {
                "item": int(row["item"]),
                "doc_id": row["doc_id"],
                "kind": row["kind"],
                "title": row["title"] or "(untitled)",
                "speaker": row["speaker"] if speech else "Monetary Policy Committee",
                "role": row["role"] if isinstance(row["role"], str) else "",
                "date": f"{row['date'].day} {row['date']:%B %Y}",
                "url": row["url"],
                "passages": policy_passages(row["text"]),
                "full_text": row["text"],
            }
        )
    return items


def render_html(items: list[dict[str, object]], template: Path = TEMPLATE) -> str:
    """The template with the items embedded as JSON (``</`` escaped for safety)."""
    payload = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    html = template.read_text()
    if "/*__ITEMS__*/[]" not in html:
        raise ValueError("template has no /*__ITEMS__*/[] placeholder")
    return html.replace("/*__ITEMS__*/[]", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--speeches", type=int, default=30)
    parser.add_argument("--minutes", type=int, default=6)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    decisions = pd.read_parquet("data/market/mpc_decisions.parquet")
    docs = context.add_context(load_documents(), decisions)
    selection = select(docs, args.speeches, args.minutes, args.seed)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    table = selection[SET_COLUMNS].assign(date=selection["date"].dt.date)
    table.to_csv(args.out_dir / SET_FILE, index=False)
    (args.out_dir / HTML_FILE).write_text(render_html(tool_items(selection)))
    counts = selection.groupby(["kind", "era", "policy_context"]).size()
    log.info("selected %d items:\n%s", len(selection), counts.to_string())
    log.info("wrote %s and %s", args.out_dir / SET_FILE, args.out_dir / HTML_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
