from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MonthWindow:
    start_date: date
    end_date: date

    @property
    def mindate(self) -> str:
        return format_pubmed_date(self.start_date)

    @property
    def maxdate(self) -> str:
        return format_pubmed_date(self.end_date)


def parse_cli_date(value: str) -> date:
    normalized = value.replace("/", "-")
    return date.fromisoformat(normalized)


def format_pubmed_date(value: date) -> str:
    return value.strftime("%Y/%m/%d")


def iter_month_windows(start_date: date, end_date: date) -> Iterator[MonthWindow]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date.")

    current = start_date
    while current <= end_date:
        next_month = first_day_of_next_month(current)
        window_end = min(next_month - timedelta(days=1), end_date)
        yield MonthWindow(start_date=current, end_date=window_end)
        current = next_month


def first_day_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def build_pubmed_discovery_command(
    window: MonthWindow,
    *,
    retmax: int,
    datetype: str,
    extra_args: Sequence[str] = (),
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "marygenai.cli",
        "pubmed-discovery",
        "run",
        "--datetype",
        datetype,
        "--mindate",
        window.mindate,
        "--maxdate",
        window.maxdate,
        "--retmax",
        str(retmax),
        *extra_args,
    ]


def run_monthly_backfill(
    *,
    start_date: date,
    end_date: date,
    retmax: int = 200,
    datetype: str = "pdat",
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
    extra_args: Sequence[str] = (),
) -> int:
    windows = list(iter_month_windows(start_date, end_date))
    for index, window in enumerate(windows, start=1):
        command = build_pubmed_discovery_command(
            window,
            retmax=retmax,
            datetype=datetype,
            extra_args=extra_args,
        )
        printable_command = " ".join(command)
        print(
            f"[{index}/{len(windows)}] PubMed discovery {window.mindate} to "
            f"{window.maxdate}"
        )
        print(printable_command)
        if dry_run:
            continue
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
        if sleep_seconds > 0 and index < len(windows):
            time.sleep(sleep_seconds)
    return 0
