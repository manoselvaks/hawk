from datetime import date

import pytest

from hawk.speeches.parse import (
    parse_date,
    parse_meeting_date,
    parse_minutes_html,
    parse_speech_html,
    pdf_text,
    speaker_and_role_from_text,
)
from tests.speeches.conftest import fixture, make_pdf

SPEECH_URL = "https://www.bankofengland.co.uk/speech/2023/march/andrew-bailey-lse"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14 March 2023", date(2023, 3, 14)),
        ("1st Sept. 1998", date(1998, 9, 1)),
        ("3 Jun 2001", date(2001, 6, 3)),
        ("2023-03-14T09:00:00Z", date(2023, 3, 14)),
        ("not a date", None),
    ],
)
def test_parse_date(raw: str, expected: date | None) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("At its meeting ending on 22 March 2023, the MPC voted", date(2023, 3, 22)),
        ("Minutes of the meeting held on 5-6 June 1997.", date(1997, 6, 6)),
        ("the meeting held on 3 and 4 February 1999", date(1999, 2, 4)),
        ("the meeting on 30 June-1 July 1998", date(1998, 7, 1)),
        ("at its meeting on Wednesday 7 May 2025", date(2025, 5, 7)),
        ("no meeting mentioned here", None),
    ],
)
def test_parse_meeting_date(text: str, expected: date | None) -> None:
    assert parse_meeting_date(text) == expected


def test_parse_speech_html() -> None:
    page = parse_speech_html(fixture("speech_html.html"), SPEECH_URL)

    assert page.title == "Inflation and the path of Bank Rate - speech by Andrew Bailey"
    assert page.speaker == "Andrew Bailey"
    assert page.role == "Governor"
    assert page.published_date == date(2023, 3, 14)
    assert page.speech_date == date(2023, 3, 13)
    assert page.pdf_url == (
        "https://www.bankofengland.co.uk/-/media/boe/files/speech/2023/march/"
        "inflation-and-the-path-of-bank-rate.pdf"
    )
    assert "further tightening in monetary policy would be required" in page.text
    # Navigation, footer and scripts are stripped.
    assert "Threadneedle" not in page.text
    assert "analytics" not in page.text


def test_parse_speech_stub_finds_pdf_and_speaker() -> None:
    page = parse_speech_html(fixture("speech_pdf_stub.html"), SPEECH_URL)

    assert page.title == "Monetary policy in an uncertain world"
    assert page.speaker == "Mervyn King"
    assert page.role == "Deputy Governor"
    assert page.published_date == date(1999, 2, 22)
    assert page.speech_date is None
    assert page.pdf_url is not None and page.pdf_url.endswith(".pdf?la=en")
    assert len(page.text) < 500


def test_parse_minutes_html() -> None:
    page = parse_minutes_html(fixture("minutes_html.html"), "https://example.org/")

    assert page.title is not None and page.title.endswith("meeting, March 2023")
    assert page.meeting_date == date(2023, 3, 22)
    assert page.published_date == date(2023, 3, 23)
    assert "increase Bank Rate by 0.25 percentage points" in page.text


def test_parse_old_minutes_stub() -> None:
    page = parse_minutes_html(
        fixture("minutes_1997_stub.html"), "https://www.bankofengland.co.uk/x"
    )

    assert page.meeting_date == date(1997, 6, 6)
    assert page.published_date == date(1997, 7, 9)
    assert (
        page.pdf_url
        == "https://www.bankofengland.co.uk/-/media/boe/files/minutes/1997/mpc-june-1997.pdf"
    )


def test_pdf_text_and_speaker() -> None:
    body = make_pdf("Speech by Mervyn King, Deputy Governor\nInflation expectations matter.")
    text = pdf_text(body)

    assert "Inflation expectations matter." in text
    assert speaker_and_role_from_text(text) == ("Mervyn King", "Deputy Governor")
