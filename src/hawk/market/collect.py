"""Download, build, validate and save the market data.

Usage::

    python -m hawk.market.collect [--out-dir data/market] [--refresh]
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from hawk.market import bank_rate, mpc, sources, yields
from hawk.market.http import PoliteDownloader
from hawk.market.validate import validate

log = logging.getLogger("hawk.market.collect")

START = pd.Timestamp("1997-01-01")
# Fetch Bank Rate from earlier so the first 1997 change has a previous rate.
BANK_RATE_LOOKBACK_START = date(1996, 1, 1)


def build(downloader: PoliteDownloader, today: date) -> dict[str, pd.DataFrame]:
    """Fetch every source and return the three output tables."""
    rate_url = sources.iadb_csv_url(
        sources.BANK_RATE_SERIES, BANK_RATE_LOOKBACK_START, today
    )
    daily_rate = bank_rate.parse_iadb_csv(
        downloader.get(rate_url).decode(), sources.BANK_RATE_SERIES
    )

    votes = mpc.parse_mpc_voting(io.BytesIO(downloader.get(sources.MPC_VOTING_URL)))
    decisions = mpc.build_mpc_decisions(votes, daily_rate)
    decisions = decisions[decisions["date"] >= START].reset_index(drop=True)

    changes = bank_rate.bank_rate_changes(daily_rate, START)
    changes = bank_rate.classify_changes(changes, decisions)

    workbooks = {}
    for url in (sources.YIELD_ARCHIVE_URL, sources.YIELD_LATEST_URL):
        workbooks.update(yields.glc_workbooks(downloader.get(url)))
    frames = [
        yields.parse_spot_curve(book, sources.GILT_MATURITIES_YEARS)
        for book in workbooks.values()
    ]
    gilts = yields.combine_yields(frames, START)

    return {"bank_rate": changes, "mpc_decisions": decisions, "gilt_yields": gilts}


def write(tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    """Save each table as parquet plus a manifest of row counts and coverage."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    for name, frame in tables.items():
        frame.to_parquet(out_dir / f"{name}.parquet", index=False)
        manifest[name] = {
            "rows": len(frame),
            "first_date": str(frame["date"].min().date()),
            "last_date": str(frame["date"].max().date()),
        }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, default=Path("data/market"))
    parser.add_argument(
        "--cache-dir", type=Path, default=None, help="default: <out-dir>/.cache"
    )
    parser.add_argument(
        "--refresh", action="store_true", help="ignore cached downloads"
    )
    parser.add_argument(
        "--min-interval", type=float, default=2.0, help="seconds between requests"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    downloader = PoliteDownloader(
        args.cache_dir or args.out_dir / ".cache",
        min_interval=args.min_interval,
        ttl=timedelta(hours=24),
        refresh=args.refresh,
    )
    tables = build(downloader, date.today())

    report = validate(
        tables["bank_rate"], tables["mpc_decisions"], tables["gilt_yields"]
    )
    for flag in report.flags:
        log.warning("flag: %s", flag)
    for error in report.errors:
        log.error("validation: %s", error)
    if not report.ok:
        log.error("validation failed; nothing written")
        return 1

    write(tables, args.out_dir)
    for name, frame in tables.items():
        log.info(
            "%s: %d rows, %s to %s",
            name,
            len(frame),
            frame["date"].min().date(),
            frame["date"].max().date(),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
