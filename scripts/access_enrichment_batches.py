#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Sequence

DEFAULT_BATCHES = 20
DEFAULT_LIMIT = 50
DEFAULT_SLEEP_SECONDS = 30.0
SELECTED_CANDIDATES_RE = re.compile(r"['\"]selected_candidates['\"]\s*:\s*(\d+)")


def build_access_enrichment_command(limit: int, extra_args: Sequence[str] = ()) -> list[str]:
    return [
        sys.executable,
        "-m",
        "marygenai.cli",
        "access-enrichment",
        "run",
        "--limit",
        str(limit),
        *extra_args,
    ]


def selected_candidate_count(output: str) -> int | None:
    match = SELECTED_CANDIDATES_RE.search(output)
    if not match:
        return None
    return int(match.group(1))


def run_access_enrichment_batches(
    *,
    batches: int = DEFAULT_BATCHES,
    limit: int = DEFAULT_LIMIT,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    dry_run: bool = False,
    stop_when_empty: bool = True,
    extra_args: Sequence[str] = (),
) -> int:
    for index in range(1, batches + 1):
        command = build_access_enrichment_command(limit, extra_args=extra_args)
        printable_command = " ".join(command)
        print(f"[{index}/{batches}] Access enrichment batch")
        print(printable_command)
        if dry_run:
            continue

        completed = subprocess.run(
            command,
            check=False,
            stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE,
            text=True,
        )
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.returncode != 0:
            return completed.returncode

        selected_count = selected_candidate_count(completed.stdout)
        if stop_when_empty and selected_count == 0:
            print("No candidates selected; stopping early.")
            return 0

        if sleep_seconds > 0 and index < batches:
            time.sleep(sleep_seconds)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run MaryGenAI access enrichment in incremental batches.",
    )
    parser.add_argument(
        "--batches",
        type=int,
        default=DEFAULT_BATCHES,
        help=f"Number of access enrichment batches to run. Defaults to {DEFAULT_BATCHES}.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum candidates per batch. Defaults to {DEFAULT_LIMIT}.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help=f"Delay between batches. Defaults to {DEFAULT_SLEEP_SECONDS:g} seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without running access enrichment.",
    )
    parser.add_argument(
        "--no-stop-when-empty",
        action="store_true",
        help="Keep running even when a batch selects zero candidates.",
    )
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed to marygenai access-enrichment run after --.",
    )
    args = parser.parse_args()
    extra_args = args.extra_args
    if extra_args and extra_args[0] == "--":
        extra_args = extra_args[1:]
    return run_access_enrichment_batches(
        batches=args.batches,
        limit=args.limit,
        sleep_seconds=args.sleep_seconds,
        dry_run=args.dry_run,
        stop_when_empty=not args.no_stop_when_empty,
        extra_args=extra_args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
