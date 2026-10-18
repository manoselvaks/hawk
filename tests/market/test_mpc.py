from __future__ import annotations

import pandas as pd
import pytest


def test_parse_mpc_voting_converts_fractions_and_dates(votes: pd.DataFrame) -> None:
    assert votes["date"].nunique() == 5
    # The 11 Mar 2020 row is stored as an Excel serial number.
    assert pd.Timestamp("2020-03-11") in set(votes["date"])
    first = votes[votes["date"] == pd.Timestamp("1997-06-06")]
    assert first["rate_pct"].iat[0] == pytest.approx(6.5)
    # Member E was not on the committee in 1997, and the
    # "Past members" label is not mistaken for a member.
    assert sorted(first["member"]) == ["Member A", "Member B", "Member C", "Member D"]
    assert "Past members" not in set(votes["member"])


def test_build_mpc_decisions(decisions: pd.DataFrame) -> None:
    by_date = decisions.set_index(decisions["date"].dt.strftime("%Y-%m-%d"))
    june_1997 = by_date.loc["1997-06-06"]
    assert june_1997["decision"] == "hike"
    assert june_1997["change_bp"] == 25
    assert june_1997["prev_rate_pct"] == pytest.approx(6.25)
    assert june_1997["vote_split"] == "3-1"
    assert june_1997["votes_hike"] == 3 and june_1997["votes_hold"] == 1
    assert june_1997["dissent_lower"] == 1
    assert june_1997["dissenters"] == "Member D (hold)"

    assert by_date.loc["2020-03-11", "change_bp"] == -50
    assert not by_date.loc["2020-03-11", "scheduled"]
    assert by_date.loc["2020-03-26", "scheduled"]


def test_hold_with_dissent_in_both_directions(decisions: pd.DataFrame) -> None:
    hold = decisions[decisions["date"] == pd.Timestamp("2020-03-26")].iloc[0]
    assert hold["decision"] == "hold"
    assert hold["vote_split"] == "3-2"
    assert (hold["votes_hike"], hold["votes_hold"], hold["votes_cut"]) == (1, 3, 1)
    assert (hold["dissent_higher"], hold["dissent_lower"]) == (1, 1)
    assert hold["dissenters"] == "Member D (hike 15bp); Member E (cut 5bp)"
