from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hawk.market import bank_rate, mpc
from hawk.market.sources import BANK_RATE_SERIES

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def daily_rate() -> pd.Series:
    text = (FIXTURES / "iadb_bank_rate.csv").read_text()
    return bank_rate.parse_iadb_csv(text, BANK_RATE_SERIES)


@pytest.fixture
def votes() -> pd.DataFrame:
    return mpc.parse_mpc_voting(FIXTURES / "mpcvoting_sample.xlsx")


@pytest.fixture
def decisions(votes: pd.DataFrame, daily_rate: pd.Series) -> pd.DataFrame:
    return mpc.build_mpc_decisions(votes, daily_rate)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
