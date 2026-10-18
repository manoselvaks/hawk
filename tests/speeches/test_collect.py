from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import hawk.speeches.collect as collect_module
from hawk.speeches.collect import (
    MinutesRecord,
    collect_all,
    collect_minutes,
    collect_speech,
    counts_by_year,
    main,
    to_frame,
)
from hawk.speeches.fetch import PoliteFetcher
from tests.speeches.conftest import FakeSession, fixture, make_pdf

BOE = "https://www.bankofengland.co.uk"
STUB = f"{BOE}/speech/1998/alice-in-euroland"
STUB_PDF = f"{BOE}/-/media/boe/files/speech/1998/alice-in-euroland.pdf"
MINUTES = f"{BOE}/monetary-policy-summary-and-minutes/2025/may-2025"
MINUTES_PDF = (
    f"{BOE}/-/media/boe/files/monetary-policy-summary-and-minutes/2025/"
    "monetary-policy-summary-and-minutes-may-2025.pdf"
)
OLD_MINUTES = f"{BOE}/minutes/1997/monetary-policy-committee-june-1997"
OLD_MINUTES_PDF = f"{BOE}/-/media/boe/files/minutes/1900-2000/1997/minutes-june-1997.pdf"
PLACEHOLDER = f"{BOE}/monetary-policy-summary-and-minutes/2026/november-2026"


def test_speech_stub_falls_back_to_pdf(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[STUB] = fixture("speech_pdf_stub.html")
    session.pages[STUB_PDF] = fixture("speech_1998_page1.pdf")

    record = collect_speech(fetcher, STUB)

    assert record.source == "pdf"
    assert record.speaker == "Willem H. Buiter"
    assert record.published_date == date(1998, 12, 15)
    assert record.speech_date == date(1998, 12, 15)  # from the PDF cover
    assert "Economic and Monetary Union has arrived de facto" in record.text


def test_url_that_is_itself_a_pdf(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[STUB] = make_pdf("Speech by Eddie George, Governor\n21 October 1998\nHello.")

    record = collect_speech(fetcher, STUB)

    assert (record.source, record.speaker, record.role) == ("pdf", "Eddie George", "Governor")
    assert record.speech_date == date(1998, 10, 21)


def test_short_minutes_page_falls_back_to_the_longer_pdf(
    fetcher: PoliteFetcher, session: FakeSession
) -> None:
    # The trimmed fixture is summary-length, like the 2015-2021 pages whose minutes
    # are only in the PDF.
    session.pages[MINUTES] = fixture("minutes_html.html")
    session.pages[MINUTES_PDF] = make_pdf("1: The Committee discussed the outlook.\n" * 400)

    record = collect_minutes(fetcher, MINUTES)

    assert record.source == "pdf"
    assert record.meeting_date == date(2025, 5, 7)
    assert record.text.startswith("1: The Committee discussed")


def test_minutes_keep_html_when_pdf_is_missing(
    fetcher: PoliteFetcher, session: FakeSession
) -> None:
    session.pages[MINUTES] = fixture("minutes_html.html")  # its PDF returns 404

    record = collect_minutes(fetcher, MINUTES)

    assert record.source == "html"
    assert record.pdf_url == MINUTES_PDF
    assert "voted by a majority" in record.text


def test_old_minutes_come_from_the_pdf(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[OLD_MINUTES] = fixture("minutes_1997_stub.html")
    session.pages[OLD_MINUTES_PDF] = fixture("minutes_1997_page1.pdf")

    record = collect_minutes(fetcher, OLD_MINUTES)

    assert record.source == "pdf"
    assert (record.meeting_date, record.published_date) == (date(1997, 6, 6), date(1997, 7, 16))
    assert record.text.startswith("Publication date: 16 July 1997")


def test_collect_all_records_failures_and_skips_unpublished(
    fetcher: PoliteFetcher, session: FakeSession
) -> None:
    session.pages[MINUTES] = fixture("minutes_html.html")
    session.pages[PLACEHOLDER] = fixture("minutes_placeholder.html")  # "to be published"

    records, failures = collect_all(
        fetcher, [MINUTES, PLACEHOLDER, f"{BOE}/missing"], collect_minutes, today=date(2026, 10, 18)
    )

    assert [r.url for r in records] == [MINUTES]
    assert [url for url, _ in failures] == [f"{BOE}/missing"]


def test_to_frame_and_counts(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[MINUTES] = fixture("minutes_html.html")
    records, _ = collect_all(fetcher, [MINUTES], collect_minutes)

    frame = to_frame(records, MinutesRecord, ("meeting_date", "published_date"))

    assert pd.api.types.is_datetime64_any_dtype(frame["published_date"])
    assert counts_by_year(frame, "meeting_date").to_dict() == {"2025": 1}


def test_main_writes_parquet(
    tmp_path: Path, session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.pages[f"{BOE}/robots.txt"] = f"Sitemap: {BOE}/sitemap.xml\n".encode()
    session.pages[f"{BOE}/sitemap.xml"] = (
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + f"<url><loc>{MINUTES}</loc></url></urlset>".encode()
    )
    session.pages[MINUTES] = fixture("minutes_html.html")

    def fake_fetcher(cache_dir: Path, **kwargs: float) -> PoliteFetcher:
        return PoliteFetcher(cache_dir, session=session, sleep=lambda _: None)

    monkeypatch.setattr(collect_module, "PoliteFetcher", fake_fetcher)

    assert main(["--out-dir", str(tmp_path), "--cache-dir", str(tmp_path / "raw")]) == 0

    minutes = pd.read_parquet(tmp_path / "minutes.parquet")
    assert minutes["url"].tolist() == [MINUTES]
    speeches = pd.read_parquet(tmp_path / "speeches.parquet")
    assert speeches.empty
    assert "published_date" in speeches.columns


def test_main_fails_when_nothing_is_discovered(
    tmp_path: Path, session: FakeSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_fetcher(cache_dir: Path, **kwargs: float) -> PoliteFetcher:
        return PoliteFetcher(cache_dir, session=session, sleep=lambda _: None)

    monkeypatch.setattr(collect_module, "PoliteFetcher", fake_fetcher)

    assert main(["--out-dir", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()
