"""Meeting-level dataset: the tone known before each MPC decision.

The one rule that matters here is **no look-ahead**. For the decision announced on
day ``D``, the tone features use only documents whose ``published_date`` is strictly
before ``D``, and never the minutes of that same meeting (which, since August 2015,
are published at the same moment as the decision). ``window_documents`` enforces
both; the tests in ``tests/analysis/test_dataset.py`` check it.

Which documents count:

* **MPC-relevant**: ``llm_relevance >= RELEVANCE_THRESHOLD`` (0.5) and a stance. At
  0.5 the LLM's "about monetary policy" call had 97% precision and 94% recall against
  the hand labels (``docs/evaluation.md``), and it is the threshold the website uses.
  Below 0.3 the model gives no stance at all, so the choice only matters for the
  0.3-0.5 band (``findings.md`` reports a check at 0.3 and 0.8).
* **All**: speeches by anyone at the Bank plus minutes.
* **MPC only**: minutes plus speeches by sitting MPC members (the committee's own
  voice).

Features for decision ``i`` (window = since the previous decision):

* ``tone``: mean stance of relevant documents published in ``[D[i-1], D[i])``;
* ``tone_change``: ``tone`` minus the same quantity for the previous window;
* ``tone_mpc``, ``tone_mpc_change``: the same using MPC-only documents;
* ``tone_w``, ``tone_w_change``: mean weighted by ``relevance x confidence``.

An empty window (no relevant document between two meetings, which happens in the
early years) carries the last known value forward, so it still uses only the past.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

RELEVANCE_THRESHOLD = 0.5
SCORES_PATH = Path("data/scores.parquet")
DECISIONS_PATH = Path("data/market/mpc_decisions.parquet")
YIELDS_PATH = Path("data/market/gilt_yields.parquet")

DECISION_CODE = {"cut": -1, "hold": 0, "hike": 1}
# Minutes record a meeting whose decision was announced 0-2 days after the final day
# of the meeting (since 2015 the MPC finishes on Wednesday and announces on Thursday).
MINUTES_LAG_DAYS = 3


@dataclass(frozen=True)
class Inputs:
    scores: pd.DataFrame
    decisions: pd.DataFrame
    yields: pd.DataFrame


def load(
    scores_path: Path = SCORES_PATH,
    decisions_path: Path = DECISIONS_PATH,
    yields_path: Path = YIELDS_PATH,
    scores: pd.DataFrame | None = None,
) -> Inputs:
    """Scores (from ``scores_path`` unless a frame is given), decisions and yields,
    with every date column as ``datetime64[ns]``."""
    scores = pd.read_parquet(scores_path) if scores is None else scores.copy()
    decisions = pd.read_parquet(decisions_path).sort_values("date").reset_index(drop=True)
    yields = pd.read_parquet(yields_path).sort_values("date").reset_index(drop=True)
    for frame, cols in (
        (scores, ["published_date", "meeting_date"]),
        (decisions, ["date"]),
        (yields, ["date"]),
    ):
        for col in cols:
            frame[col] = pd.to_datetime(frame[col]).astype("datetime64[ns]")
    return Inputs(scores, decisions, yields)


def relevant(scores: pd.DataFrame, threshold: float = RELEVANCE_THRESHOLD) -> pd.DataFrame:
    """Documents about monetary policy that have a stance, with helper columns."""
    keep = (scores["llm_relevance"] >= threshold) & scores["llm_stance"].notna()
    out = scores.loc[keep].copy()
    out["is_mpc"] = (out["kind"] == "minutes") | out["is_mpc_member"].fillna(False).astype(bool)
    out["weight"] = (out["llm_relevance"] * out["llm_confidence"]).clip(lower=1e-6)
    return out.reset_index(drop=True)


def minutes_decision_dates(minutes: pd.DataFrame, decision_dates: pd.Series) -> pd.Series:
    """Announcement date of the decision each set of minutes records (NaT if none).

    Uses the first announcement 0-2 days after ``meeting_date``; without a meeting
    date (the 19 March 2020 special meeting), the latest announcement on or before
    publication.
    """
    dates = np.sort(pd.to_datetime(decision_dates).to_numpy())
    out = []
    for meeting, published in zip(minutes["meeting_date"], minutes["published_date"], strict=True):
        if pd.notna(meeting):
            m = np.datetime64(meeting)
            i = np.searchsorted(dates, m, side="left")
            ok = i < len(dates) and dates[i] - m < np.timedelta64(MINUTES_LAG_DAYS, "D")
            out.append(pd.Timestamp(dates[i]) if ok else pd.NaT)
        else:
            j = int(np.searchsorted(dates, np.datetime64(published), side="right")) - 1
            out.append(pd.Timestamp(dates[j]) if j >= 0 else pd.NaT)
    return pd.Series(out, index=minutes.index, dtype="datetime64[ns]")


def add_own_decision(docs: pd.DataFrame, decisions: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``docs`` with ``own_decision``: for minutes, the date of the decision they
    record; NaT for speeches."""
    out = docs.copy()
    out["own_decision"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    is_min = out["kind"] == "minutes"
    if is_min.any():
        out.loc[is_min, "own_decision"] = minutes_decision_dates(out.loc[is_min], decisions["date"])
    return out


def window_documents(
    docs: pd.DataFrame, start: pd.Timestamp | None, decision_date: pd.Timestamp
) -> pd.DataFrame:
    """Documents usable for the decision on ``decision_date``: published in
    ``[start, decision_date)`` and not the minutes of that decision's own meeting.

    ``docs`` must have ``own_decision`` (see ``add_own_decision``).
    """
    mask = docs["published_date"] < decision_date
    if start is not None:
        mask &= docs["published_date"] >= start
    mask &= docs["own_decision"].isna() | (docs["own_decision"] != decision_date)
    return docs.loc[mask]


def _mean(frame: pd.DataFrame, weighted: bool = False) -> float:
    if frame.empty:
        return float("nan")
    if weighted:
        return float(np.average(frame["llm_stance"], weights=frame["weight"]))
    return float(frame["llm_stance"].mean())


def meeting_features(
    scores: pd.DataFrame,
    decisions: pd.DataFrame,
    threshold: float = RELEVANCE_THRESHOLD,
) -> pd.DataFrame:
    """One row per MPC decision with the tone features described in the module doc.

    Also carries the outcome (``decision``, ``y`` = -1/0/+1), the previous decision
    and document counts. The first decision has no previous window, so its features
    use everything published before it.
    """
    docs = add_own_decision(relevant(scores, threshold), decisions)
    dec = decisions.sort_values("date").reset_index(drop=True)
    rows = []
    prev_date: pd.Timestamp | None = None
    for d in dec.to_dict("records"):
        date = pd.Timestamp(d["date"])
        win = window_documents(docs, prev_date, date)
        mpc = win[win["is_mpc"]]
        rows.append(
            {
                "date": date,
                "decision": d["decision"],
                "y": DECISION_CODE[str(d["decision"])],
                "change_bp": int(d["change_bp"]),
                "scheduled": bool(d["scheduled"]),
                "rate_pct": float(d["rate_pct"]),
                "prev_rate_pct": float(d["prev_rate_pct"]),
                "n_docs": len(win),
                "n_docs_mpc": len(mpc),
                "last_doc_date": win["published_date"].max() if len(win) else pd.NaT,
                "tone_raw": _mean(win),
                "tone_mpc_raw": _mean(mpc),
                "tone_w_raw": _mean(win, weighted=True),
            }
        )
        prev_date = date
    out = pd.DataFrame(rows)
    out["prev_y"] = out["y"].shift(1)
    out["prev_decision"] = out["decision"].shift(1)
    for name in ("tone", "tone_mpc", "tone_w"):
        raw = out[f"{name}_raw"]
        out[f"{name}_empty"] = raw.isna()
        out[name] = raw.ffill()
        out[f"{name}_change"] = out[name] - out[name].shift(1)
    return out


def add_market_features(meetings: pd.DataFrame, yields: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``meetings`` with the market's view the day before each decision.

    * ``spread_2y``: 2-year gilt yield minus Bank Rate in force, percentage points, at
      the last close strictly before the announcement day;
    * ``d2y_since_last``: change in the 2-year yield between the closes before the
      previous and the current announcement, percentage points.

    Both are known before the announcement. They are the market benchmark the tone
    has to beat in the prediction test.
    """
    y = yields.dropna(subset=["gilt_2y"]).sort_values("date")
    dates, vals = y["date"].to_numpy(), y["gilt_2y"].to_numpy()
    idx = np.searchsorted(dates, meetings["date"].to_numpy(), side="left") - 1
    before = np.where(idx >= 0, vals[np.clip(idx, 0, None)], np.nan)
    out = meetings.copy()
    out["gilt_2y_before"] = before
    out["spread_2y"] = before - out["prev_rate_pct"]
    out["d2y_since_last"] = out["gilt_2y_before"] - out["gilt_2y_before"].shift(1)
    return out


BASELINE_MODEL = "baseline (word lists)"


def baseline_as_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy of a scores-shaped ``frame`` whose ``llm_*`` columns hold the word-list
    baseline instead, so every analysis can run on either scorer.

    Relevance becomes 1 when the baseline counts the document as about policy (policy
    terms per 100 words >= 1.5) and 0 otherwise; stance is the baseline stance for
    relevant documents; confidence is 1 (the baseline has none).
    """
    from hawk.scoring.baseline import RELEVANCE_DENSITY_THRESHOLD

    out = frame.copy()
    rel = out["baseline_relevance"] >= RELEVANCE_DENSITY_THRESHOLD
    out["llm_relevance"] = rel.astype(float)
    out["llm_stance"] = out["baseline_stance"].where(rel).astype("float64")
    out["llm_confidence"] = 1.0
    out["llm_reason"] = None
    out["model"] = BASELINE_MODEL
    out["input_mode"] = "baseline"
    return out


def baseline_scores() -> pd.DataFrame:
    """The whole corpus scored by the baseline only, shaped like ``scores.parquet``
    (no API calls). Used when the LLM scores do not exist yet."""
    from hawk.scoring import baseline
    from hawk.scoring.corpus import load_documents
    from hawk.scoring.llm import PROMPT_VERSION
    from hawk.scoring.score_all import scores_table

    docs = load_documents()
    rows = []
    for doc_id, text in zip(docs["doc_id"], docs["text"], strict=True):
        b = baseline.score_text(text)
        rows.append(
            {
                "doc_id": doc_id,
                "llm_relevance": float("nan"),
                "llm_stance": None,
                "llm_confidence": float("nan"),
                "llm_reason": None,
                "baseline_stance": b.stance,
                "baseline_hawkish": b.hawkish,
                "baseline_dovish": b.dovish,
                "baseline_relevance": b.relevance,
            }
        )
    table = scores_table(
        docs, rows, model=BASELINE_MODEL, input_mode="baseline", prompt_version=PROMPT_VERSION
    )
    return baseline_as_scores(table)
