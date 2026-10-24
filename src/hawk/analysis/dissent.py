"""Extra test: does a member's speech tone predict their own dissent at the next meeting?

For each MPC decision and each member who gave at least one MPC-relevant speech in
the window since the previous decision (published strictly before the
announcement), the member's tone is the mean stance of those speeches. The outcome
is how the member voted relative to the agreed rate: ``+1`` for a vote for a higher
rate, ``-1`` lower, ``0`` with the majority (from the Bank's voting record).

Model: linear regression of the outcome on tone, with standard errors clustered by
member (a few members dissent often, so votes by one person are not independent).
Also reported: the mean tone before each kind of vote, and, as a robustness check,
the same regression controlling for the member's own vote at the previous decision
(dissenters tend to dissent again, and their speeches may simply reflect that).
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from hawk.analysis.dataset import RELEVANCE_THRESHOLD, relevant

_MOVE = re.compile(
    r"\s*(?P<name>[^;(]+?)\s*\((?P<move>hike|cut|hold|higher|lower)(?:\s+(?P<bp>\d+)bp)?[^)]*\)"
)


def parse_votes(text: str | None) -> dict[str, int | str]:
    """Dissenters -> preferred change from the previous rate in bp, or ``"higher"`` /
    ``"lower"`` (relative to the agreed rate) when the size was not recorded."""
    if text is None or (isinstance(text, float) and np.isnan(text)) or not str(text).strip():
        return {}
    out: dict[str, int | str] = {}
    for m in _MOVE.finditer(str(text)):
        move = m["move"]
        if move in ("higher", "lower"):
            out[m["name"].strip()] = move
        else:
            bp = int(m["bp"] or 0)
            out[m["name"].strip()] = {"hike": bp, "cut": -bp, "hold": 0}[move]
    return out


def vote_direction(pref: int | str, agreed_bp: int) -> int:
    if pref == "higher":
        return 1
    if pref == "lower":
        return -1
    return int(np.sign(int(pref) - agreed_bp))


def member_meetings(
    scores: pd.DataFrame,
    decisions: pd.DataFrame,
    members: pd.DataFrame,
    threshold: float = RELEVANCE_THRESHOLD,
) -> pd.DataFrame:
    """One row per (decision, voting member with a relevant speech in the window)."""
    docs = relevant(scores, threshold)
    sp = docs[(docs["kind"] == "speech") & docs["is_mpc_member"].fillna(False).astype(bool)]
    first = pd.to_datetime(members["first_vote"])
    last = pd.to_datetime(members["last_vote"])
    dec = decisions.sort_values("date").reset_index(drop=True)
    rows = []
    prev: pd.Timestamp | None = None
    prev_votes: dict[str, int] = {}
    for d in dec.to_dict("records"):
        date = pd.Timestamp(d["date"])
        win = sp[(sp["published_date"] < date)]
        if prev is not None:
            win = win[win["published_date"] >= prev]
        votes = parse_votes(d["dissenters"])
        sitting = set(members.loc[(first <= date) & (last >= date), "member"])
        this_votes = {
            str(m): (
                0
                if votes.get(str(m)) is None
                else vote_direction(votes[str(m)], int(d["change_bp"]))
            )
            for m in sitting
        }
        for name, g in win.groupby("speaker"):
            if name not in sitting:
                continue
            rows.append(
                {
                    "date": date,
                    "member": name,
                    "tone": float(g["llm_stance"].mean()),
                    "n_speeches": len(g),
                    "vote": this_votes[str(name)],
                    "prev_vote": prev_votes.get(str(name), np.nan),
                }
            )
        prev = date
        prev_votes = this_votes
    return pd.DataFrame(rows)


def dissent_test(
    scores: pd.DataFrame, decisions: pd.DataFrame, members: pd.DataFrame
) -> dict[str, Any]:
    mm = member_meetings(scores, decisions, members)
    if mm.empty or mm["member"].nunique() < 3:
        return {"n": len(mm)}
    slope = _tone_slope(mm, ["tone"])
    with_prev = mm.dropna(subset=["prev_vote"])
    by_vote = []
    for v, label in [
        (1, "Voted for a higher rate"),
        (0, "Voted with the majority"),
        (-1, "Voted for a lower rate"),
    ]:
        t = mm.loc[mm["vote"] == v, "tone"]
        by_vote.append(
            {"label": label, "n": len(t), "mean_tone": float(t.mean()) if len(t) else None}
        )
    return {
        "n": len(mm),
        "n_members": int(mm["member"].nunique()),
        "n_dissents": int((mm["vote"] != 0).sum()),
        "by_vote": by_vote,
        "slope": slope,
        "slope_controlling_prev_vote": {
            **_tone_slope(with_prev, ["tone", "prev_vote"]),
            "n": len(with_prev),
        },
    }


def _tone_slope(mm: pd.DataFrame, cols: list[str]) -> dict[str, Any]:
    """OLS of the vote on ``cols``, clustered by member; the coefficient on tone."""
    X = sm.add_constant(mm[cols].astype(float))
    res = sm.OLS(mm["vote"].astype(float), X).fit(
        cov_type="cluster", cov_kwds={"groups": pd.factorize(mm["member"])[0]}
    )
    ci = res.conf_int().loc["tone"]
    return {
        "term": "tone",
        "label": "Member's own speech tone",
        "estimate": float(res.params["tone"]),
        "std_error": float(res.bse["tone"]),
        "p_value": float(res.pvalues["tone"]),
        "ci_low": float(ci.iloc[0]),
        "ci_high": float(ci.iloc[1]),
    }
