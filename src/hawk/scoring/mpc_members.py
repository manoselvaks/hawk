"""Build ``data/market/mpc_members.csv``: every MPC member's first and last Bank Rate vote.

``mpc_decisions.parquet`` keeps only dissenters, so membership needs the full voting
record. This reads the same workbook as the market collector (reusing its parser and
download cache) and writes one row per member.

Usage::

    python -m hawk.scoring.mpc_members [--out data/market/mpc_members.csv]
"""

from __future__ import annotations

import argparse
import io
import logging
from pathlib import Path

import pandas as pd

from hawk.market import mpc, sources
from hawk.market.http import PoliteDownloader
from hawk.scoring.speakers import MEMBERS_PATH

log = logging.getLogger("hawk.scoring.mpc_members")


def members_table(votes: pd.DataFrame) -> pd.DataFrame:
    """One row per member: ``member, first_vote, last_vote, n_votes``, by first vote."""
    table = (
        votes.groupby("member")["date"]
        .agg(first_vote="min", last_vote="max", n_votes="count")
        .reset_index()
        .sort_values(["first_vote", "member"])
    )
    for col in ("first_vote", "last_vote"):
        table[col] = pd.to_datetime(table[col]).dt.date
    return table.reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=MEMBERS_PATH)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/market/.cache"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    downloader = PoliteDownloader(args.cache_dir)
    votes = mpc.parse_mpc_voting(io.BytesIO(downloader.get(sources.MPC_VOTING_URL)))
    table = members_table(votes)
    table.to_csv(args.out, index=False)
    log.info("wrote %d members to %s", len(table), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
