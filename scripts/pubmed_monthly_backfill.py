#!/usr/bin/env python
from __future__ import annotations

import argparse
from datetime import date

from marygenai.pubmed_discovery.backfill import parse_cli_date, run_monthly_backfill


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run MaryGenAI PubMed discovery month by month.",
    )
    parser.add_argument(
        "--start-date",
        default="2024-06-01",
        help="First publication date to query, YYYY-MM-DD or YYYY/MM/DD. Defaults to 2024-06-01.",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Last publication date to query, YYYY-MM-DD or YYYY/MM/DD. Defaults to today.",
    )
    parser.add_argument(
        "--retmax",
        type=int,
        default=200,
        help="Maximum PubMed records per monthly query.",
    )
    parser.add_argument(
        "--datetype",
        default="pdat",
        help="PubMed date field to query.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.0,
        help="Optional delay between monthly runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print monthly commands without running them.",
    )
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed to marygenai pubmed-discovery run after --.",
    )
    args = parser.parse_args()
    extra_args = args.extra_args
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    return run_monthly_backfill(
        start_date=parse_cli_date(args.start_date),
        end_date=parse_cli_date(args.end_date),
        retmax=args.retmax,
        datetype=args.datetype,
        dry_run=args.dry_run,
        sleep_seconds=args.sleep_seconds,
        extra_args=extra_args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
