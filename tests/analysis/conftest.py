from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest


def doc(
    doc_id: str,
    published: str,
    stance: float | None,
    *,
    kind: str = "speech",
    relevance: float = 0.9,
    member: bool | None = True,
    speaker: str | None = "A Member",
    meeting: str | None = None,
    confidence: float = 0.8,
) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "kind": kind,
        "speaker": None if kind == "minutes" else speaker,
        "is_mpc_member": None if kind == "minutes" else member,
        "published_date": pd.Timestamp(published),
        "meeting_date": pd.Timestamp(meeting) if meeting else pd.NaT,
        "llm_relevance": relevance,
        "llm_stance": stance,
        "llm_confidence": confidence,
        "model": "test/model",
        "prompt_version": "stance_v1",
    }


def scores_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    out = pd.DataFrame(rows)
    out["llm_stance"] = pd.to_numeric(out["llm_stance"]).astype("float64")
    out["meeting_date"] = pd.to_datetime(out["meeting_date"]).astype("datetime64[ns]")
    out["published_date"] = pd.to_datetime(out["published_date"]).astype("datetime64[ns]")
    return out


@pytest.fixture
def decisions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-02-03", "2022-03-17", "2022-05-05"]).astype(
                "datetime64[ns]"
            ),
            "decision": ["hike", "hold", "cut"],
            "change_bp": [25, 0, -25],
            "scheduled": [True, True, True],
            "rate_pct": [0.5, 0.5, 0.25],
            "prev_rate_pct": [0.25, 0.5, 0.5],
            "dissenters": ["B Hawk (hike 50bp)", "", "B Hawk (hold); C Dove (cut 50bp)"],
        }
    )


@pytest.fixture
def yields() -> pd.DataFrame:
    dates = pd.bdate_range("2021-12-01", "2022-06-30")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {"date": dates.astype("datetime64[ns]"), "gilt_2y": 1 + rng.normal(0, 0.03, len(dates))}
    )
