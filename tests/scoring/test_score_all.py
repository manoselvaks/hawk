from __future__ import annotations

from pathlib import Path

import pytest

from hawk.scoring.score_all import estimate_cost


def test_estimate_cost_from_pilot(tmp_path: Path) -> None:
    pilot = tmp_path / "pilot.csv"
    pilot.write_text("model,input_mode,cost_usd\nm,full,0.001\nm,full,0.003\nm,passages,0.5\n")
    assert estimate_cost(100, "m", "full", pilot) == pytest.approx(0.2)
    assert estimate_cost(100, "other", "full", pilot) is None
    assert estimate_cost(100, "m", "full", tmp_path / "missing.csv") is None
