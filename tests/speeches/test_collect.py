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
STUB = f"{BOE}/speech/1999/february/monetary-policy-in-an-uncertain-world"
STUB_PDF = f"{BOE}/-/media/boe/files/speech/1999/monetary-policy-in-an-uncertain-world.pdf?la=en"
MINUTES = f"{BOE}/monetary-policy-summary-and-minutes/2023/march-2023"
OLD_MINUTES = f"{BOE}/monetary-policy-summary-and-minutes/1997/june-1997"
OLD_MINUTES_PDF = f"{BOE}/-/media/boe/files/minutes/1997/mpc-june-1997.pdf"


def test_speech_stub_falls_back_to_pdf(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[STUB] = fixture("speech_pdf_stub.html")
    session.pages[STUB_PDF] = make_pdf("The MPC must be forward-looking.\n" * 60)

    record = collect_speech(fetcher, STUB)

    assert record.source == "pdf"
    assert record.speaker == "Mervyn King"
    assert record.published_date == date(1999, 2, 22)
    assert "forward-looking" in record.text


def test_url_that_is_itself_a_pdf(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[STUB] = make_pdf("Speech by Eddie George, Governor\nStability matters.")

    record = collect_speech(fetcher, STUB)

    assert (record.source, record.speaker, record.role) == ("pdf", "Eddie George", "Governor")


def test_minutes_keep_html_when_pdf_is_missing(
    fetcher: PoliteFetcher, session: FakeSession
) -> None:
    session.pages[MINUTES] = fixture("minutes_html.html")  # its linked PDF returns 404

    record = collect_minutes(fetcher, MINUTES)

    assert record.source == "html"
    assert record.meeting_date == date(2023, 3, 22)
    assert record.published_date == date(2023, 3, 23)


def test_collect_all_records_failures(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[OLD_MINUTES] = fixture("minutes_1997_stub.html")
    session.pages[OLD_MINUTES_PDF] = make_pdf("Minutes of the meeting held on 5-6 June 1997")

    records, failures = collect_all(fetcher, [OLD_MINUTES, f"{BOE}/missing"], collect_minutes)

    assert [r.meeting_date for r in records] == [date(1997, 6, 6)]
    assert failures[0][0] == f"{BOE}/missing"


def test_to_frame_and_counts(fetcher: PoliteFetcher, session: FakeSession) -> None:
    session.pages[MINUTES] = fixture("minutes_html.html")
    records, _ = collect_all(fetcher, [MINUTES], collect_minutes)

    frame = to_frame(records, MinutesRecord, ("meeting_date", "published_date"))

    assert pd.api.types.is_datetime64_any_dtype(frame["published_date"])
    assert counts_by_year(frame, "meeting_date").to_dict() == {"2023": 1}


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
