from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from hawk.scoring.make_labelling_set import render_html, select, stratified_sample, tool_items


def fake_docs(n: int = 400) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    eras = ["pre-2008", "2008-2015", "2016-2021", "2022+"]
    return pd.DataFrame(
        {
            "doc_id": [f"d{i}" for i in range(n)],
            "kind": rng.choice(["speech", "minutes"], n, p=[0.8, 0.2]),
            "url": [f"https://example.org/{i}" for i in range(n)],
            "title": [f"Title {i}" for i in range(n)],
            "speaker": "Some One",
            "role": None,
            "is_mpc_member": pd.Series(rng.choice([True, False], n), dtype="boolean"),
            "date": pd.Timestamp("2010-05-04"),
            "era": rng.choice(eras, n),
            "policy_context": rng.choice(["hike", "cut", "hold"], n, p=[0.1, 0.1, 0.8]),
            "text": "Bank Rate and inflation.\nPayments.",
        }
    )


def test_stratified_sample_spreads_over_cells() -> None:
    docs = fake_docs()
    pool = docs[docs["kind"] == "speech"]
    picked = stratified_sample(pool, 12, np.random.default_rng(1))
    assert len(picked) == 12
    # 12 draws over 4 eras x 3 contexts: one per cell.
    assert picked.groupby(["era", "policy_context"]).size().max() == 1


def test_stratified_sample_skips_empty_cells() -> None:
    docs = fake_docs()
    pool = docs[
        (docs["kind"] == "speech")
        & ~((docs["era"] == "2008-2015") & (docs["policy_context"] == "hike"))
    ]
    picked = stratified_sample(pool, 30, np.random.default_rng(1))
    assert len(picked) == 30
    assert not ((picked["era"] == "2008-2015") & (picked["policy_context"] == "hike")).any()


def test_select_is_reproducible_and_mpc_only() -> None:
    docs = fake_docs()
    a = select(docs, 10, 3, seed=5)
    b = select(docs, 10, 3, seed=5)
    assert list(a["doc_id"]) == list(b["doc_id"])
    assert list(a["item"]) == list(range(1, 14))
    speeches = a[a["kind"] == "speech"]
    assert len(speeches) == 10 and speeches["is_mpc_member"].all()
    assert (a["kind"] == "minutes").sum() == 3


def test_tool_is_blind_and_embeds_items() -> None:
    items = tool_items(select(fake_docs(), 4, 1))
    assert all("policy_context" not in i and "era" not in i for i in items)
    html = render_html(items)
    payload = re.search(r"const ITEMS = (\[.*?\]);\n", html, re.S)
    assert payload is not None
    embedded = json.loads(payload.group(1).replace("<\\/", "</"))
    assert len(embedded) == 5
    lowered = html.lower()
    for leak in ("baseline", "llm", 'stance":', "policy_context"):
        assert leak not in lowered
