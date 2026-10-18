from __future__ import annotations

import pandas as pd
import pytest


def _decision(decisions: pd.DataFrame, day: str) -> pd.Series:
    return decisions[decisions["date"] == pd.Timestamp(day)].iloc[0]


def test_parse_mpc_voting_reads_real_layout(votes: pd.DataFrame) -> None:
    first = votes[votes["date"] == pd.Timestamp("1997-06-06")]
    assert first["rate_pct"].iat[0] == pytest.approx(6.5)  # stored as 0.065
    assert len(first) == 6  # the committee was not yet at full strength
    assert "Eddie George" in set(first["member"])
    # Labels and summary rows are not members; names lose their line breaks.
    members = set(votes["member"])
    assert not members & {"Past members", "Current members", "Voted to increase"}
    assert "Andrew Haldane" in members
    # The pre-MPC opening rate (no date) is not a decision.
    assert votes["date"].min() == pd.Timestamp("1997-06-06")


def test_direction_only_votes_are_kept(votes: pd.DataFrame) -> None:
    jan_1998 = votes[votes["date"] == pd.Timestamp("1998-01-08")].set_index("member")
    assert jan_1998.loc["Alan Budd", "vote_dir"] == 1
    assert pd.isna(jan_1998.loc["Alan Budd", "vote_pct"])
    assert jan_1998.loc["Eddie George", "vote_dir"] == 0


def test_build_mpc_decisions(decisions: pd.DataFrame) -> None:
    june_1997 = _decision(decisions, "1997-06-06")
    assert june_1997["decision"] == "hike"
    assert june_1997["change_bp"] == 25
    assert june_1997["prev_rate_pct"] == pytest.approx(6.25)
    assert june_1997["vote_split"] == "6-0"

    covid = _decision(decisions, "2020-03-19")
    assert (covid["decision"], covid["change_bp"], covid["rate_pct"]) == ("cut", -15, 0.1)
    assert not covid["scheduled"]
    assert _decision(decisions, "2020-03-26")["scheduled"]


def test_split_votes_and_dissenters(decisions: pd.DataFrame) -> None:
    peak = _decision(decisions, "2023-08-03")
    assert (peak["decision"], peak["vote_split"]) == ("hike", "6-3")
    assert (peak["votes_hike"], peak["votes_hold"], peak["votes_cut"]) == (8, 1, 0)
    assert (peak["dissent_higher"], peak["dissent_lower"]) == (2, 1)
    assert peak["dissenters"] == (
        "Catherine L Mann (hike 50bp); Jonathan Haskel (hike 50bp); Swati Dhingra (hold)"
    )

    hold = _decision(decisions, "2023-09-21")
    assert (hold["decision"], hold["vote_split"]) == ("hold", "5-4")
    assert (hold["votes_hike"], hold["votes_hold"]) == (4, 5)


def test_direction_only_dissents_count_without_a_size(decisions: pd.DataFrame) -> None:
    jan_1998 = _decision(decisions, "1998-01-08")
    assert (jan_1998["decision"], jan_1998["vote_split"]) == ("hold", "5-3")
    assert (jan_1998["votes_hike"], jan_1998["votes_hold"]) == (3, 5)
    assert jan_1998["dissenters"].startswith("Alan Budd (higher, size not recorded)")

    # "Decrease" against a hike could be a hold or a smaller hike: counted as a
    # dissent, but not as a hike, hold or cut.
    june_1998 = _decision(decisions, "1998-06-04")
    assert (june_1998["vote_split"], june_1998["dissent_lower"]) == ("8-1", 1)
    assert june_1998["votes_hike"] + june_1998["votes_hold"] + june_1998["votes_cut"] == 8
