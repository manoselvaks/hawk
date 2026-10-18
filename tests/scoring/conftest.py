from __future__ import annotations

import pandas as pd
import pytest

from hawk.scoring.speakers import Tenure


@pytest.fixture
def tenures() -> list[Tenure]:
    return [
        Tenure("Andrew Haldane", pd.Timestamp("2014-05-09"), pd.Timestamp("2021-07-28")),
        Tenure("Huw Pill", pd.Timestamp("2021-08-06"), None),
    ]


@pytest.fixture
def decisions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-11-04", "2021-12-16", "2022-02-03", "2022-03-17"]),
            "decision": ["hold", "hike", "hike", "hike"],
        }
    )
