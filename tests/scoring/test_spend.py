from __future__ import annotations

import json
from pathlib import Path

import pytest

from hawk.scoring.spend import BudgetExceededError, SpendTracker


def test_records_and_persists(tmp_path: Path) -> None:
    log = tmp_path / "spend.jsonl"
    tracker = SpendTracker(log, cap_usd=1.0)
    tracker.record(0.25, model="m", key="k1")
    tracker.record(0.5, model="m", key="k2")
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [line["cumulative_usd"] for line in lines] == [0.25, 0.75]
    assert SpendTracker(log, cap_usd=1.0).spent_usd == pytest.approx(0.75)


def test_refuses_past_cap(tmp_path: Path) -> None:
    tracker = SpendTracker(tmp_path / "spend.jsonl", cap_usd=0.1, reserve_usd=0.01)
    tracker.check()
    tracker.record(0.095, model="m", key="k")
    with pytest.raises(BudgetExceededError):
        tracker.check()


def test_cap_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HAWK_SPEND_CAP_USD", "0.5")
    assert SpendTracker(tmp_path / "s.jsonl").cap_usd == 0.5
