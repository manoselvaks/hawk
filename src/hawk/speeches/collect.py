"""Build ``data/speeches.parquet`` and ``data/minutes.parquet`` from the BoE website.

Usage::

    python -m hawk.speeches.collect                       # full rebuild
    python -m hawk.speeches.collect --limit-speeches 20   # quick smoke run

Raw downloads are cached under ``data/raw/``; re-running after an interruption
re-uses everything already downloaded, so the collector is resumable.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import Path
from typing import Any, cast

import pandas as pd
from pypdf.errors import PyPdfError

from hawk.speeches.discover import discover
from hawk.speeches.fetch import FetchError, PoliteFetcher
from hawk.speeches.parse import (
    parse_meeting_date,
    parse_minutes_html,
    parse_speech_html,
    pdf_text,
    speaker_and_role_from_text,
)

log = logging.getLogger("hawk.speeches.collect")

# An HTML page with less text than this is treated as a stub that links to a PDF.
MIN_HTML_CHARS = 1500


@dataclass(frozen=True)
class SpeechRecord:
    url: str
    title: str | None
    speaker: str | None
    role: str | None
    speech_date: date | None
    published_date: date | None
    source: str  # "html" or "pdf"
    pdf_url: str | None
    text: str


@dataclass(frozen=True)
class MinutesRecord:
    url: str
    title: str | None
    meeting_date: date | None
    published_date: date | None
    source: str
    pdf_url: str | None
    text: str


def is_pdf(body: bytes) -> bool:
    return body.lstrip()[:5] == b"%PDF-"


def pdf_fallback(fetcher: PoliteFetcher, pdf_url: str) -> str | None:
    """Text of the PDF a stub page links to, or ``None`` if it cannot be read."""
    try:
        return pdf_text(fetcher.get(pdf_url))
    except (FetchError, PyPdfError, ValueError) as exc:
        log.warning("keeping HTML text; PDF %s unreadable: %s", pdf_url, exc)
        return None


def collect_speech(fetcher: PoliteFetcher, url: str) -> SpeechRecord:
    body = fetcher.get(url)
    if is_pdf(body):
        text = pdf_text(body)
        speaker, role = speaker_and_role_from_text(text)
        return SpeechRecord(url, None, speaker, role, None, None, "pdf", url, text)

    page = parse_speech_html(body, url)
    text, source = page.text, "html"
    speaker, role = page.speaker, page.role
    if len(text) < MIN_HTML_CHARS and page.pdf_url:
        pdf = pdf_fallback(fetcher, page.pdf_url)
        if pdf:
            text, source = pdf, "pdf"
            pdf_speaker, pdf_role = speaker_and_role_from_text(pdf)
            speaker, role = speaker or pdf_speaker, role or pdf_role
    return SpeechRecord(
        url=url,
        title=page.title,
        speaker=speaker,
        role=role,
        speech_date=page.speech_date,
        published_date=page.published_date,
        source=source,
        pdf_url=page.pdf_url,
        text=text,
    )


def collect_minutes(fetcher: PoliteFetcher, url: str) -> MinutesRecord:
    page = parse_minutes_html(fetcher.get(url), url)
    text, source, meeting_date = page.text, "html", page.meeting_date
    if len(text) < MIN_HTML_CHARS and page.pdf_url:
        pdf = pdf_fallback(fetcher, page.pdf_url)
        if pdf:
            text, source = pdf, "pdf"
            meeting_date = meeting_date or parse_meeting_date(pdf)
    return MinutesRecord(
        url=url,
        title=page.title,
        meeting_date=meeting_date,
        published_date=page.published_date,
        source=source,
        pdf_url=page.pdf_url,
        text=text,
    )


def collect_all(
    fetcher: PoliteFetcher,
    urls: Iterable[str],
    collect_one: Callable[[PoliteFetcher, str], Any],
) -> tuple[list[Any], list[tuple[str, str]]]:
    """Collect every URL, returning (records, failures) instead of stopping on errors."""
    records: list[Any] = []
    failures: list[tuple[str, str]] = []
    urls = list(urls)
    for i, url in enumerate(urls, start=1):
        try:
            records.append(collect_one(fetcher, url))
        except (FetchError, PyPdfError, ValueError) as exc:
            log.warning("failed %s: %s", url, exc)
            failures.append((url, str(exc)))
        if i % 50 == 0 or i == len(urls):
            log.info("%d/%d done (%d network requests)", i, len(urls), fetcher.network_requests)
    return records, failures


def to_frame(
    records: list[Any], record_type: type[Any], date_columns: tuple[str, ...]
) -> pd.DataFrame:
    """One row per record, with real datetime columns, sorted by the first date column."""
    columns = [f.name for f in fields(record_type)]
    frame = pd.DataFrame([asdict(record) for record in records], columns=columns)
    for column in date_columns:
        frame[column] = pd.to_datetime(frame[column])
    sort_key = date_columns[0]
    return frame.sort_values([sort_key, "url"], na_position="last").reset_index(drop=True)


def counts_by_year(frame: pd.DataFrame, date_column: str) -> pd.Series:
    """Number of records per calendar year (``NaN`` dates are counted as "unknown")."""
    years = frame[date_column].dt.year.astype("Int64").astype(str).replace("<NA>", "unknown")
    return cast(pd.Series, years.value_counts().sort_index())


@dataclass(frozen=True)
class Job:
    name: str
    urls: list[str]
    collect_one: Callable[[PoliteFetcher, str], Any]
    record_type: type[Any]
    date_columns: tuple[str, ...]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--out-dir", type=Path, default=Path("data"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--min-interval", type=float, default=1.0, help="seconds between requests")
    parser.add_argument("--limit-speeches", type=int, default=None)
    parser.add_argument("--limit-minutes", type=int, default=None)
    parser.add_argument("--skip-speeches", action="store_true")
    parser.add_argument("--skip-minutes", action="store_true")
    parser.add_argument(
        "--sitemap",
        action="append",
        default=None,
        help="sitemap URL to start from (repeatable); defaults to those in robots.txt",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    fetcher = PoliteFetcher(args.cache_dir, min_interval=args.min_interval)
    found = discover(fetcher, args.sitemap)
    if not found.speeches and not found.minutes:
        log.error("no speech or minutes URLs found; is the site reachable?")
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[Job] = []
    if not args.skip_speeches:
        jobs.append(
            Job(
                "speeches",
                found.speeches[: args.limit_speeches],
                collect_speech,
                SpeechRecord,
                ("published_date", "speech_date"),
            )
        )
    if not args.skip_minutes:
        jobs.append(
            Job(
                "minutes",
                found.minutes[: args.limit_minutes],
                collect_minutes,
                MinutesRecord,
                ("meeting_date", "published_date"),
            )
        )

    all_failures: list[tuple[str, str]] = []
    for job in jobs:
        name, date_columns = job.name, job.date_columns
        records, failures = collect_all(fetcher, job.urls, job.collect_one)
        all_failures += failures
        frame = to_frame(records, job.record_type, date_columns)
        path = args.out_dir / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        print(f"\n{name}: {len(frame)} records -> {path} ({len(failures)} failed)")
        if not frame.empty:
            print(counts_by_year(frame, date_columns[0]).to_string())

    if all_failures:
        failures_path = args.out_dir / "collect_failures.csv"
        pd.DataFrame(all_failures, columns=["url", "error"]).to_csv(failures_path, index=False)
        print(f"\n{len(all_failures)} failures written to {failures_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
