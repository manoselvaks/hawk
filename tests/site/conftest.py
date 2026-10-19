from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

HAWKISH = (
    "Inflation has risen sharply and wage growth remains strong. The labour market is tight "
    "and there is little spare capacity. Upside risks to inflation mean further tightening "
    "may be required to bring inflation back to target. "
)
DOVISH = (
    "Demand is weak and unemployment has risen. Spare capacity has opened up and inflation "
    "is expected to fall below target, so a rate cut may be appropriate soon. "
)


def _speech(url: str, title: str, speaker: str, date: str, text: str) -> dict[str, object]:
    return {
        "url": f"https://www.bankofengland.co.uk/speech/{url}",
        "title": title,
        "speaker": speaker,
        "role": "External MPC member",
        "speech_date": pd.Timestamp(date) - pd.Timedelta(days=1),
        "published_date": pd.Timestamp(date),
        "source": "html",
        "pdf_url": None,
        "text": text * 8,
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny repository layout with every input the site build reads."""
    (tmp_path / "data" / "market").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    speeches = pd.DataFrame(
        [
            _speech(
                "2022/a", "Hawkish speech - speech by Huw Pill", "Huw Pill", "2022-03-01", HAWKISH
            ),
            _speech(
                "2022/b", "Another view - speech by Huw Pill", "Huw Pill", "2022-05-10", HAWKISH
            ),
            _speech("2023/c", "Payments", "Victoria Cleland", "2023-02-01", "Payments. " * 200),
            _speech(
                "2024/d",
                "Slack ahead - speech by Swati Dhingra",
                "Swati Dhingra",
                "2023-01-15",
                DOVISH,
            ),
        ]
    )
    minutes = pd.DataFrame(
        {
            "url": [
                "https://www.bankofengland.co.uk/minutes/2022/feb",
                "https://www.bankofengland.co.uk/minutes/2022/may",
            ],
            "title": ["Minutes February 2022", "Minutes May 2022"],
            "meeting_date": pd.to_datetime(["2022-02-02", "2022-05-04"]),
            "published_date": pd.to_datetime(["2022-02-03", "2022-05-05"]),
            "source": "html",
            "pdf_url": None,
            "text": [HAWKISH * 8, DOVISH * 8],
        }
    )
    speeches.to_parquet(tmp_path / "data" / "speeches.parquet")
    minutes.to_parquet(tmp_path / "data" / "minutes.parquet")
    decisions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-11-04", "2022-02-03", "2022-05-05", "2023-02-02"]),
            "decision": ["hold", "hike", "hike", "hike"],
            "change_bp": pd.array([0, 25, 25, 50], dtype="Int64"),
            "rate_pct": [0.1, 0.5, 1.0, 4.0],
            "prev_rate_pct": [0.1, 0.25, 0.75, 3.5],
            "scheduled": True,
            "vote_split": ["7-2", "5-4", "6-3", "7-2"],
            "votes_hike": [2, 9, 9, 7],
            "votes_hold": [7, 0, 0, 2],
            "votes_cut": [0, 0, 0, 0],
            "dissent_higher": [2, 4, 3, 0],
            "dissent_lower": [0, 0, 0, 2],
            "dissenters": [
                "Huw Pill (hike 15bp); Michael Saunders (hike 15bp)",
                "Huw Pill (hike 50bp)",
                "Huw Pill (hike 75bp)",
                "Swati Dhingra (hold); Silvana Tenreyro (hold)",
            ],
        }
    )
    decisions.to_parquet(tmp_path / "data" / "market" / "mpc_decisions.parquet")
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2021-12-16", "2022-02-03", "2022-05-05", "2023-02-02"]),
            "rate_pct": [0.25, 0.5, 1.0, 4.0],
            "prev_rate_pct": [0.1, 0.25, 0.75, 3.5],
            "change_bp": [15, 25, 25, 50],
            "mpc_match": "scheduled",
        }
    ).to_parquet(tmp_path / "data" / "market" / "bank_rate.parquet")
    (tmp_path / "data" / "market" / "mpc_members.csv").write_text(
        "member,first_vote,last_vote,n_votes\n"
        "Huw Pill,2021-11-04,2023-02-02,4\n"
        "Swati Dhingra,2022-11-03,2023-02-02,2\n"
    )
    (tmp_path / "docs" / "methodology.md").write_text(
        "# Scoring methodology\n\nIntro.\n\n## The scale\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
        "See [the pilot](pilot.md).\n"
    )
    return tmp_path
