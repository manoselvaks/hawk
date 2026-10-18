from datetime import date

import pytest

from hawk.speeches.parse import (
    parse_date,
    parse_meeting_date,
    parse_minutes_html,
    parse_speech_html,
    pdf_text,
    speaker_and_role_from_text,
    speech_date_from_pdf,
)
from tests.speeches.conftest import fixture, make_pdf

BOE = "https://www.bankofengland.co.uk"
SPEECH_URL = f"{BOE}/speech/2025/april/david-bailey-speech-at-a-climate-financial-risk-forum"
STUB_URL = f"{BOE}/speech/1998/alice-in-euroland"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14 March 2023", date(2023, 3, 14)),
        ("09 July 2015", date(2015, 7, 9)),
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
        ("At its meeting ending on 7 May 2025, the MPC voted", date(2025, 5, 7)),
        ("Minutes of the MPC Meeting held on 5 and 6 June 1997", date(1997, 6, 6)),
        ("Special Monetary Policy Committee Meeting held on 8 October 2008", date(2008, 10, 8)),
        ("the meeting on 30 June-1 July 1998", date(1998, 7, 1)),
        ("no meeting mentioned here", None),
    ],
)  # fmt: skip
def test_parse_meeting_date(text: str, expected: date | None) -> None:
    assert parse_meeting_date(text) == expected


def test_parse_speech_html() -> None:
    page = parse_speech_html(fixture("speech_html.html"), SPEECH_URL)

    assert page.title == (
        "Maintaining Momentum: Managing Climate risk in a changing world"
        " \u2212 speech by David Bailey"  # a minus sign, as on the page
    )
    assert page.speaker == "David Bailey"
    # From the "Published on" line, not the <time> tags of the "Other speeches" panel.
    assert page.published_date == date(2025, 4, 30)
    assert page.text.startswith("Speech\nGood morning.")
    assert "Other speeches" not in page.text
    # The body cites a 2015 speech PDF; that is not this speech's own PDF.
    assert page.pdf_url is None


def test_parse_speech_stub_finds_pdf_and_speaker() -> None:
    page = parse_speech_html(fixture("speech_pdf_stub.html"), STUB_URL)

    assert page.title == "Alice in Euroland - speech by Willem H. Buiter"
    assert page.speaker == "Willem H. Buiter"
    assert page.published_date == date(1998, 12, 15)
    assert page.pdf_url == f"{BOE}/-/media/boe/files/speech/1998/alice-in-euroland.pdf"
    assert len(page.text) < 100


def test_parse_minutes_html() -> None:
    page = parse_minutes_html(fixture("minutes_html.html"), BOE)

    assert page.title == "Bank Rate reduced to 4.25% - May 2025"
    assert page.meeting_date == date(2025, 5, 7)
    assert page.published_date == date(2025, 5, 8)
    assert "voted by a majority of 5\u20134 to reduce Bank Rate" in page.text


def test_parse_old_minutes_stub() -> None:
    page = parse_minutes_html(fixture("minutes_1997_stub.html"), BOE)

    assert page.meeting_date == date(1997, 6, 6)  # from the title, the second day
    assert page.published_date == date(1997, 7, 16)
    assert page.pdf_url == f"{BOE}/-/media/boe/files/minutes/1900-2000/1997/minutes-june-1997.pdf"


def test_real_speech_pdf_cover() -> None:
    text = pdf_text(fixture("speech_1998_page1.pdf"))

    assert text.startswith("Alice in Euroland\nSpeech given by\nWillem H. Buiter")
    assert "All speeches are available online" not in text  # repeated page banner removed
    assert speech_date_from_pdf(text) == date(1998, 12, 15)
    assert speaker_and_role_from_text(text) == (
        "Willem H. Buiter",
        "Member, Monetary Policy Committee",
    )


def test_pdf_text_and_speaker() -> None:
    body = make_pdf("Speech by Mervyn King, Deputy Governor\nInflation expectations matter.")
    text = pdf_text(body)

    assert "Inflation expectations matter." in text
    assert speaker_and_role_from_text(text) == ("Mervyn King", "Deputy Governor")
    assert speech_date_from_pdf(text) is None
