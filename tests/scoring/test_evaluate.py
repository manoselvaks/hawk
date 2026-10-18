from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hawk.scoring.evaluate import (
    build_report,
    read_labels,
    relevance_metrics,
    round_half_away,
    self_consistency,
    spearman,
    stance_metrics,
)

LABELS_CSV = """item,doc_id,kind,score,not_monetary_policy,note,labelled_at
1,d1,speech,2,0,,2026-10-20T10:00:00Z
2,d2,speech,1,0,"close call, maybe 0",2026-10-20T10:01:00Z
3,d3,speech,0,0,,2026-10-20T10:02:00Z
4,d4,speech,-1,0,,2026-10-20T10:03:00Z
5,d5,minutes,-2,0,,2026-10-20T10:04:00Z
6,d6,speech,,1,payments speech,2026-10-20T10:05:00Z
7,d7,speech,,,,
"""


@pytest.fixture
def labels(tmp_path: Path) -> pd.DataFrame:
    path = tmp_path / "labels.csv"
    path.write_text(LABELS_CSV)
    return read_labels(path)


def test_read_labels_drops_unlabelled(labels: pd.DataFrame) -> None:
    assert list(labels["item"]) == [1, 2, 3, 4, 5, 6]
    assert list(labels["human_relevant"]) == [True] * 5 + [False]
    assert pd.isna(labels.loc[5, "human_stance"])


def test_round_half_away() -> None:
    assert [round_half_away(x) for x in (-1.5, -0.5, 0.4, 0.5, 1.5)] == [-2, -1, 0, 1, 2]


def test_spearman() -> None:
    a = pd.Series([1.0, 2, 3, 4])
    assert spearman(a, a * 10) == pytest.approx(1.0)
    assert spearman(a, -a) == pytest.approx(-1.0)
    assert pd.isna(spearman(a, pd.Series([1.0, 1, 1, 1])))


def test_stance_metrics() -> None:
    human = pd.Series([2.0, 1, 0, -1, -2, None])
    model = pd.Series([1.5, 1, 0.5, None, -1, 0])
    m = stance_metrics(human, model)
    assert (m.n_scored, m.n_compared) == (5, 4)
    assert m.exact == pytest.approx(2 / 4)  # 1.5->2 and 1->1 exact; 0.5->1, -1 miss
    assert m.within_one == pytest.approx(1.0)
    assert m.confusion.loc[2, 2] == 1 and m.confusion.loc[-1, "no stance"] == 1


def test_relevance_metrics() -> None:
    r = relevance_metrics(
        pd.Series([True, True, False, False]), pd.Series([True, False, True, False])
    )
    assert (r.precision, r.recall, r.accuracy) == (0.5, 0.5, 0.5)


def test_self_consistency() -> None:
    a = pd.DataFrame({"stance": [1.0, 0.5, None, -1.0], "relevance": [0.9, 0.9, 0.1, 0.8]})
    b = pd.DataFrame({"stance": [1.0, 0.0, None, None], "relevance": [0.9, 0.9, 0.1, 0.2]})
    c = self_consistency(a, b)
    assert c.exact == pytest.approx(2 / 4)
    assert c.within_half == pytest.approx(3 / 4)
    assert c.mean_abs_diff == pytest.approx(0.25)
    assert c.relevance_agree == pytest.approx(3 / 4)


def test_report_from_synthetic_labels(labels: pd.DataFrame) -> None:
    preds = pd.DataFrame(
        {
            "item": [1, 2, 3, 4, 5, 6],
            "baseline_stance": [1.2, 0.4, 0.0, -0.6, -1.8, 0.3],
            "baseline_relevant": [True, True, True, True, True, True],
            "llm_stance": [2.0, 1.0, 0.0, -1.0, -1.5, None],
            "llm_relevance": [1.0, 0.9, 0.8, 0.9, 1.0, 0.1],
        }
    )
    consistency = self_consistency(
        pd.DataFrame({"stance": preds["llm_stance"], "relevance": preds["llm_relevance"]}),
        pd.DataFrame({"stance": preds["llm_stance"], "relevance": preds["llm_relevance"]}),
    )
    report = build_report(labels, preds, consistency, model="test/model", input_mode="full")
    assert "# Scorer evaluation" in report
    assert "| LLM (test/model, full) | 5 of 5 | 1.00 | 100% | 100% |" in report
    assert "| Baseline (word lists) | 6 | 83% | 100% | 83% |" in report
    assert "## LLM self-consistency" in report
