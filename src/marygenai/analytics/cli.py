from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from marygenai.analytics.base_status import (
    build_base_status_report,
    write_report_json,
)
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.settings import get_settings

app = typer.Typer(help="Generate read-only local analytics reports.")
console = Console()


@app.callback()
def main() -> None:
    """Run analytics commands."""


@app.command("base-status")
def base_status(
    condition: Annotated[
        str | None,
        typer.Option("--condition", help="Filter the medical-condition ranking."),
    ] = None,
    top: Annotated[
        int,
        typer.Option("--top", min=1, help="Number of medical conditions to show."),
    ] = 25,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Output format: rich or json."),
    ] = "rich",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report output path."),
    ] = None,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    legacy_csv_path: Annotated[
        Path | None,
        typer.Option("--legacy-csv-path", help="Optional legacy studies CSV fallback path."),
    ] = None,
    legacy_english_path: Annotated[
        Path | None,
        typer.Option(
            "--legacy-english-path",
            help="Optional normalized English legacy reference JSONL path.",
        ),
    ] = None,
) -> None:
    """Report local base status without changing SQLite or legacy files."""
    settings = get_settings()
    legacy_csv = legacy_csv_path or settings.temp_dir / "legacy/cannadocs/Estudos-Grid view.csv"
    report = build_base_status_report(
        database_path=database_path or sqlite_database_path(settings.data_dir),
        legacy_csv_path=legacy_csv,
        legacy_english_path=legacy_english_path,
        condition=condition,
        top=top,
    )
    if output:
        write_report_json(report, output)

    if output_format == "json":
        console.print_json(json.dumps(report, ensure_ascii=False))
    elif output_format == "rich":
        _print_rich_report(report)
        if output:
            console.print(f"\nJSON report written to {output}")
    else:
        console.print("Unsupported format. Use `rich` or `json`.")
        raise typer.Exit(1)


def _print_rich_report(report: dict) -> None:
    console.print("[bold]MaryGenAI base status[/bold]")
    console.print(f"Generated at: {report['generated_at']}")
    console.print(f"SQLite: {report['database_path']}")
    console.print(f"Legacy study source: {report['legacy_study_source']}")
    console.print(
        "\nBoundary notes: trusted legacy records, PubMed candidates, pending review items, "
        "artifact-confirmed open access, and PMCID/PMC-inferred open access are distinct."
    )

    _print_key_values("Overview", report["overview"])
    _print_metric_group("Bibliographic identity", report["bibliographic_identity"])
    _print_key_values("Canonical URL", report["canonical_url"])
    _print_legacy_english_reference(report["legacy_english_reference"])
    _print_metric_group(
        "Portuguese legacy descriptive evidence",
        report["legacy_descriptive_evidence"]["field_counts"],
    )
    console.print(
        {
            "strong_descriptive_evidence": report["legacy_descriptive_evidence"][
                "strong_descriptive_evidence"
            ]
        }
    )
    _print_study_types(report["study_type"], title="Portuguese legacy study type")
    _print_key_values("Access / download", report["access_open_download"])
    _print_conditions(report["conditions"], title="Portuguese legacy medical conditions")


def _print_key_values(title: str, values: dict) -> None:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for key, value in values.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        table.add_row(key, rendered)
    console.print(table)


def _print_metric_group(title: str, values: dict) -> None:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_column("Percent", justify="right")
    for key, value in values.items():
        if isinstance(value, dict) and "count" in value:
            table.add_row(key, str(value["count"]), f"{value['percent']:.2f}%")
        else:
            table.add_row(key, str(value), "")
    console.print(table)


def _print_study_types(values: dict, *, title: str = "Study type") -> None:
    table = Table(title=title)
    table.add_column("Type")
    table.add_column("Count", justify="right")
    table.add_column("Percent", justify="right")
    for item in values["counts"]:
        table.add_row(item["study_type"], str(item["count"]), f"{item['percent']:.2f}%")
    console.print(table)
    console.print({"study_type_by_result": values["study_type_by_result"]})


def _print_conditions(values: dict, *, title: str = "Medical conditions") -> None:
    table = Table(title=title)
    table.add_column("Condition")
    table.add_column("Studies", justify="right")
    table.add_column("Metanálise", justify="right")
    table.add_column("Metanálise Clínica", justify="right")
    table.add_column("Ensaio Clínico", justify="right")
    table.add_column("Duplo-Cego", justify="right")
    table.add_column("Strong ID", justify="right")
    table.add_column("PMCID", justify="right")
    table.add_column("OA artifact", justify="right")
    for item in values["items"]:
        table.add_row(
            item["condition"],
            str(item["total_studies"]),
            str(item["meta_analysis"]),
            str(item["clinical_meta_analysis"]),
            str(item["clinical_trial"]),
            str(item["double_blind_clinical_trial"]),
            str(item["with_pmid_pmcid_or_doi"]),
            str(item["with_pmcid"]),
            str(item["with_open_access_artifact"]),
        )
    console.print(table)


def _print_legacy_english_reference(values: dict) -> None:
    if not values.get("available"):
        _print_key_values("Legacy English reference", values)
        return
    console.print("\n[bold]Legacy English reference[/bold]")
    _print_key_values(
        "Legacy English overview",
        {
            "path": values["path"],
            "total_records": values["total_records"],
            "condition_filter": values["condition_filter"],
            "identity_confirmation_status_counts": values[
                "identity_confirmation_status_counts"
            ],
            "study_result_counts": values["study_result_counts"],
        },
    )
    _print_metric_group("Legacy English field coverage", values["field_coverage"])
    _print_key_values("Legacy English access progress", values["access_progress"])
    _print_counter_table("Legacy English study types", values["study_type_counts"])
    _print_counter_table("Legacy English study results", values["study_result_counts"])
    _print_ranked_values("Legacy English pathologies", values["top_pathologies"])
    _print_ranked_values("Legacy English organ systems", values["top_organ_systems"])
    _print_ranked_values("Legacy English cannabinoids", values["top_cannabinoids"])
    _print_ranked_values("Legacy English terpenes", values["top_terpenes"])
    _print_ranked_values("Legacy English receptors", values["top_receptors"])
    _print_ranked_values("Legacy English locations", values["top_locations"])


def _print_ranked_values(title: str, items: list[dict]) -> None:
    table = Table(title=title)
    table.add_column("Value")
    table.add_column("Count", justify="right")
    for item in items:
        table.add_row(str(item["value"]), str(item["count"]))
    console.print(table)


def _print_counter_table(title: str, values: dict) -> None:
    table = Table(title=title)
    table.add_column("Value")
    table.add_column("Count", justify="right")
    for value, count in values.items():
        table.add_row(str(value), str(count))
    console.print(table)


__all__ = ["app", "base_status"]
