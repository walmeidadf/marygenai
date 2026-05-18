from __future__ import annotations

from datetime import date

from marygenai.pubmed_discovery.backfill import (
    build_pubmed_discovery_command,
    iter_month_windows,
    parse_cli_date,
)


def test_iter_month_windows_splits_partial_months() -> None:
    windows = list(iter_month_windows(date(2024, 6, 15), date(2024, 8, 3)))

    assert [(window.mindate, window.maxdate) for window in windows] == [
        ("2024/06/15", "2024/06/30"),
        ("2024/07/01", "2024/07/31"),
        ("2024/08/01", "2024/08/03"),
    ]


def test_parse_cli_date_accepts_pubmed_or_iso_style() -> None:
    assert parse_cli_date("2024/01/31") == date(2024, 1, 31)
    assert parse_cli_date("2024-01-31") == date(2024, 1, 31)


def test_build_pubmed_discovery_command_includes_window_and_retmax() -> None:
    command = build_pubmed_discovery_command(
        next(iter_month_windows(date(2024, 1, 1), date(2024, 1, 31))),
        retmax=200,
        datetype="pdat",
        extra_args=["--no-persist"],
    )

    assert command[1:5] == ["-m", "marygenai.cli", "pubmed-discovery", "run"]
    assert command[command.index("--mindate") + 1] == "2024/01/01"
    assert command[command.index("--maxdate") + 1] == "2024/01/31"
    assert command[command.index("--retmax") + 1] == "200"
    assert command[-1] == "--no-persist"
