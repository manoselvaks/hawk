from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hawk.analysis import dissent, event_study, market, prediction
from hawk.analysis.run import clean, findings_json
from tests.analysis.conftest import doc, scores_frame


def test_weekly_tone_bins_and_excludes_decision_day(decisions: pd.DataFrame) -> None:
    from hawk.analysis.dataset import relevant

    scores = scores_frame(
        [
            doc("w0", "2022-03-16", 1.0),  # 1 day before -> week 0
            doc("w1", "2022-03-08", -1.0),  # 9 days before -> week -1
            doc("d0", "2022-03-17", 2.0),  # decision day: never used
        ]
    )
    tone = event_study.weekly_tone(relevant(scores), decisions).iloc[1]
    assert tone[0] == pytest.approx(1.0) and tone[-1] == pytest.approx(-1.0)
    assert np.isnan(tone[-2])


def test_event_study_shape(decisions: pd.DataFrame) -> None:
    scores = scores_frame([doc(f"s{i}", f"2022-0{1 + i % 4}-1{i % 9}", 0.5) for i in range(12)])
    es = event_study.event_study(scores, decisions, n_boot=50)
    assert es["offsets_weeks"][0] == -12 and es["offsets_weeks"][-1] == 0
    assert {s["decision"] for s in es["series"]} == {"hike", "hold", "cut"}
    assert all(len(s["mean"]) == 13 for s in es["series"])


def test_scores_and_rules() -> None:
    y = np.array([0, 0, 1, -1])
    perfect = prediction.rule_proba(y)
    s = prediction.scores(perfect, y)
    assert s["accuracy"] == 1.0 and s["brier"] == pytest.approx(0, abs=1e-6)
    uniform = np.full((4, 3), 1 / 3)
    assert prediction.scores(uniform, y)["log_loss"] == pytest.approx(np.log(3))


def test_expanding_window_uses_only_earlier_decisions() -> None:
    rng = np.random.default_rng(1)
    n = 120
    tone = rng.normal(size=n)
    y = np.where(tone > 0.8, 1, np.where(tone < -0.8, -1, 0))
    data = pd.DataFrame(
        {
            "date": pd.date_range("2000-01-01", periods=n, freq="MS"),
            "y": y,
            "prev_y": np.r_[0, y[:-1]],
            "scheduled": True,
            "tone": tone,
            "tone_change": np.r_[0, np.diff(tone)],
        }
    )
    data = prediction.design(data)
    specs = [
        prediction.Spec("Prev", prediction.PREV, False),
        prediction.Spec("Tone", [*prediction.PREV, "tone"], True),
    ]
    oos = prediction.expanding_window(data, specs, start=pd.Timestamp("2004-01-01"))
    assert oos["date"].min() >= pd.Timestamp("2004-01-01")
    # Changing the last outcome cannot change any forecast made before it.
    altered = data.copy()
    altered.loc[altered.index[-1], "y"] = -altered.loc[altered.index[-1], "y"] or 1
    oos2 = prediction.expanding_window(altered, specs, start=pd.Timestamp("2004-01-01"))
    pd.testing.assert_frame_equal(oos.drop(columns="y").iloc[:-1], oos2.drop(columns="y").iloc[:-1])
    rows = {r["name"]: r for r in prediction.evaluate(oos, specs)}
    assert rows["Tone"]["log_loss"] < rows["Prev"]["log_loss"]  # tone is the true driver
    gain = prediction.compare_log_loss(oos, "Prev", "Tone", n_boot=200)
    assert gain["ci_low"] > 0


def test_market_panel_excludes_events_and_maps_weekends(
    decisions: pd.DataFrame, yields: pd.DataFrame
) -> None:
    scores = scores_frame(
        [
            doc("sat", "2022-03-05", 1.0),  # Saturday -> Monday 7 March
            doc("dec", "2022-03-17", -1.0),  # announcement day: excluded
            doc("min", "2022-02-17", 0.0, kind="minutes", meeting="2022-02-02"),
        ]
    )
    p = market.panel(scores, decisions, yields)
    mon = p.set_index("date").loc[pd.Timestamp("2022-03-07")]
    assert bool(mon["speech"]) and mon["stance"] == 1.0
    assert bool(p.set_index("date").loc[pd.Timestamp("2022-03-17"), "event"])
    assert bool(p.set_index("date").loc[pd.Timestamp("2022-02-17"), "event"])


def test_surprise_uses_only_earlier_documents(yields: pd.DataFrame) -> None:
    scores = scores_frame(
        [doc("a", "2022-03-01", 1.0), doc("b", "2022-03-10", -1.0), doc("c", "2022-03-10", 2.0)]
    )
    sd = market.speech_days(scores, market.daily_changes(yields)).set_index("date")
    day = sd.loc[pd.Timestamp("2022-03-10")]
    assert day["stance"] == pytest.approx(0.5) and day["prior_tone"] == pytest.approx(1.0)
    assert day["surprise"] == pytest.approx(-0.5)


def test_placebo_finds_no_effect_in_noise() -> None:
    rng = np.random.default_rng(3)
    n = 2000
    speech = rng.random(n) < 0.2
    data = pd.DataFrame(
        {
            "date": pd.bdate_range("2000-01-03", periods=n),
            "d2y": rng.normal(0, 3, n),
            "speech": speech,
            "stance": np.where(speech, rng.normal(0, 1, n), np.nan),
        }
    )
    pl = market.placebo(data, n=200)
    assert pl["p_value"] > 0.01


def test_parse_votes_and_direction() -> None:
    votes = dissent.parse_votes(
        "Huw Pill (hike 25bp); Swati Dhingra (hold); Alan Budd (higher, size not recorded)"
    )
    assert votes == {"Huw Pill": 25, "Swati Dhingra": 0, "Alan Budd": "higher"}
    assert dissent.vote_direction(0, -25) == 1  # wanted a hold when the MPC cut
    assert dissent.vote_direction(-50, -25) == -1
    assert dissent.vote_direction("lower", 25) == -1
    assert dissent.parse_votes(None) == {}


def test_member_meetings_window(decisions: pd.DataFrame) -> None:
    members = pd.DataFrame(
        {
            "member": ["B Hawk", "C Dove"],
            "first_vote": ["2020-01-01"] * 2,
            "last_vote": ["2030-01-01"] * 2,
        }
    )
    scores = scores_frame(
        [
            doc("h", "2022-04-01", 2.0, speaker="B Hawk"),
            doc("d", "2022-04-02", -2.0, speaker="C Dove"),
            doc("late", "2022-05-05", -2.0, speaker="B Hawk"),  # announcement day
        ]
    )
    mm = dissent.member_meetings(scores, decisions, members).set_index("member")
    assert mm.loc["B Hawk", "tone"] == 2.0 and mm.loc["B Hawk", "vote"] == 1
    assert mm.loc["C Dove", "vote"] == -1
    # both spoke before the May meeting; at the March meeting both voted with the majority
    assert (mm["date"] == pd.Timestamp("2022-05-05")).all()
    assert mm.loc["B Hawk", "prev_vote"] == 0 and mm.loc["C Dove", "prev_vote"] == 0


def test_clean_makes_json_safe() -> None:
    out = clean({"a": float("nan"), "b": np.float64(1.234567), "c": [np.int64(2)]})
    assert out == {"a": None, "b": 1.2346, "c": [2]}


def test_findings_json_leads_with_the_three_primary_results() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "analysis"
    detail = json.loads((root / "findings_detail.json").read_text())
    evaluation = json.loads((root / "evaluation.json").read_text())
    f = clean(findings_json(detail, evaluation))
    assert [h["id"] for h in f["headline"]] == ["event_study", "prediction", "dissent"]
    assert f["headline"][0]["display"] == "+1.00"
    assert f["accuracy"]["display"] == "\u03c1 = 0.37"
    assert f["dissent"]["by_vote"][0]["n"] == detail["dissent"]["by_vote"][0]["n"]
    assert len(f["dissent"]["cautions"]) == 2
    # The rebuilt file is what is committed.
    assert json.loads((root / "findings.json").read_text())["headline"] == f["headline"]
