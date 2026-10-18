from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from hawk.market import collect, sources

FIXTURES = Path(__file__).parent / "fixtures"


class FakeDownloader:
    """Serves fixture files in place of the Bank of England."""

    def __init__(self, cache_dir: Path, **_: object) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.urls.append(url)
        files = {
            sources.BANK_RATE_URL: "bank_rate.html",
            sources.MPC_VOTING_URL: "mpcvoting_sample.xlsx",
            sources.YIELD_ARCHIVE_URL: "glc_archive_sample.zip",
            sources.YIELD_LATEST_URL: "glc_latest_sample.zip",
        }
        return (FIXTURES / files[url]).read_bytes()


def test_collect_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect, "PoliteDownloader", FakeDownloader)
    assert collect.main(["--out-dir", str(tmp_path)]) == 0

    bank_rate = pd.read_parquet(tmp_path / "bank_rate.parquet")
    decisions = pd.read_parquet(tmp_path / "mpc_decisions.parquet")
    gilts = pd.read_parquet(tmp_path / "gilt_yields.parquet")
    assert len(bank_rate) == 14 and len(decisions) == 16 and len(gilts) == 8
    assert list(gilts.columns) == ["date", "gilt_2y", "gilt_10y"]
    assert pd.api.types.is_datetime64_any_dtype(decisions["date"])

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["bank_rate"] == {
        "rows": 14,
        "first_date": "1997-05-06",
        "last_date": "2023-08-03",
    }
