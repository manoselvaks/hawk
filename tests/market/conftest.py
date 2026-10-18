from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hawk.market import bank_rate, mpc

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def rate_history() -> pd.Series:
    return bank_rate.parse_bank_rate_table((FIXTURES / "bank_rate.html").read_bytes())


@pytest.fixture
def votes() -> pd.DataFrame:
    return mpc.parse_mpc_voting(FIXTURES / "mpcvoting_sample.xlsx")


@pytest.fixture
def decisions(votes: pd.DataFrame, rate_history: pd.Series) -> pd.DataFrame:
    return mpc.build_mpc_decisions(votes, rate_history)


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES
