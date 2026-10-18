from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hawk.scoring.score_all import SCORES_COLUMNS, estimate_cost, scores_table


def test_estimate_cost_from_pilot(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot.csv"
    pilot.write_text("model,input_mode,cost_usd\nm,full,0.001\nm,full,0.003\nm,passages,0.5\n")
    assert estimate_cost(100, "m", "full", pilot) == pytest.approx(0.2)
    assert estimate_cost(100, "other", "full", pilot) is None
    assert estimate_cost(100, "m", "full", tmp_path / "missing.csv") is None


def test_scores_table_matches_contract() -> None:
    docs = pd.DataFrame(
        {
            "doc_id": ["speech-a", "minutes-b"],
            "kind": ["speech", "minutes"],
            "url": ["u1", "u2"],
            "title": ["t1", "t2"],
            "speaker": ["Huw Pill", None],
            "role": ["Chief Economist", None],
            "is_mpc_member": pd.array([True, pd.NA], dtype="boolean"),
            "date": pd.to_datetime(["2024-01-02", "2024-02-03"]),
            "speech_date": pd.to_datetime(["2024-01-01", "NaT"]),
            "meeting_date": pd.to_datetime(["NaT", "2024-01-31"]),
            "n_chars": [5000, 9000],
            "policy_density": [3.1, 4.2],
            "text": ["x", "y"],
        }
    )
    rows = [
        {
            "doc_id": d,
            "llm_relevance": 0.9,
            "llm_stance": st,
            "llm_confidence": 0.8,
            "llm_reason": "r",
            "baseline_stance": 0.5,
            "baseline_hawkish": 3,
            "baseline_dovish": 1,
            "baseline_relevance": 2.0,
        }
        for d, st in [("speech-a", 1.0), ("minutes-b", None)]
    ]
    out = scores_table(docs, rows, model="m", input_mode="full", prompt_version="stance_v1")
    assert list(out.columns) == SCORES_COLUMNS
    assert out["llm_stance"].dtype == "float64" and out["llm_stance"].isna().sum() == 1
    assert (out["prompt_version"] == "stance_v1").all()
