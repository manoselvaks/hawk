from __future__ import annotations

from pathlib import Path

import pandas as pd

from hawk.scoring.speakers import Tenure, is_mpc_member, load_tenures, normalise_speaker


def test_aliases_merge_variants() -> None:
    assert normalise_speaker("Andy Haldane") == "Andrew Haldane"
    assert normalise_speaker("Andrew Haldane") == "Andrew Haldane"
    assert normalise_speaker("Catherine L. Mann") == "Catherine L Mann"
    assert normalise_speaker("Mervyn King\nDeputy Governor") == "Mervyn King"
    assert normalise_speaker("MERVYN KING\nGOVERNOR OF") == "Mervyn King"


def test_incomplete_name_falls_back_to_title() -> None:
    title = "Speech at the St Paul's Cathedral Lecture - Edward George"
    assert normalise_speaker("The Rt Hon Sir", title) == "Eddie George"
    assert normalise_speaker("Catherine", "On inflation - speech by Catherine L Mann") == (
        "Catherine L Mann"
    )
    assert normalise_speaker("David", "Untitled") == "David"
    assert normalise_speaker(None, None) is None


def test_url_override_wins() -> None:
    url = (
        "https://www.bankofengland.co.uk/speech/2026/october/financial-innovation-dollar-"
        "dominance-and-their-uk-monetary-policy-implications"
    )
    assert normalise_speaker("Liao", "anything", url) == "Catherine L Mann"


def test_membership_window(tenures: list[Tenure]) -> None:
    assert is_mpc_member("Andrew Haldane", pd.Timestamp("2016-01-01"), tenures)
    assert not is_mpc_member("Andrew Haldane", pd.Timestamp("2013-01-01"), tenures)
    assert is_mpc_member("Huw Pill", pd.Timestamp("2030-01-01"), tenures)  # still serving
    assert not is_mpc_member("Sam Woods", pd.Timestamp("2016-01-01"), tenures)
    assert not is_mpc_member(None, pd.Timestamp("2016-01-01"), tenures)


def test_load_tenures_spans_meetings(tmp_path: Path) -> None:
    members = tmp_path / "members.csv"
    members.write_text(
        "member,first_vote,last_vote,n_votes\n"
        "Old Member,2020-02-01,2020-03-01,2\n"
        "New Member,2020-03-01,2020-04-01,2\n"
    )
    decisions = pd.DataFrame(
        {"date": pd.to_datetime(["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"])}
    )
    old, new = load_tenures(members, decisions)
    assert old.start == pd.Timestamp("2020-01-02")
    assert old.end == pd.Timestamp("2020-03-31")
    assert new.start == pd.Timestamp("2020-02-02")
    assert new.end is None  # voted at the latest meeting
