"""Export legacy publications with strong audited identity evidence.

This is a bridge artifact for later access/full-text enrichment. It does not
download full text and does not change review state.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.repository import connect_initialized_review_database
from marygenai.settings import get_settings

DEFAULT_OUTPUT_SUBDIR = Path("normalized/identity_identifier_resolution")
STRONG_STATES = ("gold_identity_seed", "auto_identity_resolved")

console = Console()
app = typer.Typer(help="Export legacy records with strong audited identity evidence.")


@dataclass(frozen=True)
class StrongLegacyIdentityRecord:
    document_id: str
    review_item_id: str
    review_item_status: str
    identity_classification: str
    title: str | None
    publication_year: int | None
    canonical_url: str | None
    doi: str | None
    pmid: str | None
    pmcid: str | None
    legacy_study_id: str
    legacy_study_type: str | None
    review_decision_id: str | None
    decision_created_at: str | None
    access_enrichment_priority: str
    provenance: dict[str, Any]


@app.callback()
def main() -> None:
    """Run strong legacy identity export commands."""


@app.command()
def run(
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite review database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for export outputs."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Limit exported records."),
    ] = None,
) -> None:
    """Export strong legacy identity records for later access enrichment."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    records_path = resolved_output_dir / f"{run_id}_strong_legacy_identity_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_strong_legacy_identity_summary.json"

    with connect_initialized_review_database(resolved_database_path) as connection:
        records = select_strong_legacy_identity_records(connection, limit=limit)

    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        database_path=resolved_database_path,
        records_path=records_path,
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


def select_strong_legacy_identity_records(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[StrongLegacyIdentityRecord]:
    params: list[Any] = [*STRONG_STATES]
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(limit)
    rows = connection.execute(
        f"""
        WITH strong_identity AS (
            SELECT
                document_id,
                MAX(
                    CASE association_state
                        WHEN 'gold_identity_seed' THEN 2
                        WHEN 'auto_identity_resolved' THEN 1
                        ELSE 0
                    END
                ) AS classification_rank
            FROM document_identity
            WHERE source = 'identity_identifier_resolution'
            AND association_state IN (?, ?)
            GROUP BY document_id
        ),
        latest_decision AS (
            SELECT rd.*
            FROM review_decision AS rd
            JOIN (
                SELECT review_item_id, MAX(created_at) AS created_at
                FROM review_decision
                WHERE reviewer = 'marygenai_identity_identifier_resolution_poc'
                GROUP BY review_item_id
            ) AS latest
                ON latest.review_item_id = rd.review_item_id
                AND latest.created_at = rd.created_at
        )
        SELECT
            d.document_id,
            ri.review_item_id,
            ri.status AS review_item_status,
            CASE strong_identity.classification_rank
                WHEN 2 THEN 'gold_identity_seed'
                ELSE 'auto_identity_resolved'
            END AS identity_classification,
            d.primary_title,
            d.publication_year,
            d.canonical_url,
            d.doi,
            d.pmid,
            d.pmcid,
            p.legacy_study_id,
            p.legacy_study_type,
            latest_decision.review_decision_id,
            latest_decision.created_at AS decision_created_at,
            latest_decision.provenance_json AS decision_provenance_json
        FROM strong_identity
        JOIN document AS d ON d.document_id = strong_identity.document_id
        JOIN publication AS p ON p.document_id = d.document_id
        JOIN review_item AS ri
            ON ri.document_id = d.document_id
            AND ri.queue_type = 'legacy_identity_review'
        LEFT JOIN latest_decision ON latest_decision.review_item_id = ri.review_item_id
        ORDER BY
            strong_identity.classification_rank DESC,
            d.pmid IS NULL,
            d.pmcid IS NULL,
            d.publication_year DESC,
            d.document_id ASC
        {limit_clause}
        """,
        params,
    ).fetchall()
    return [_record_from_row(row) for row in rows]


def _record_from_row(row: sqlite3.Row) -> StrongLegacyIdentityRecord:
    return StrongLegacyIdentityRecord(
        document_id=row["document_id"],
        review_item_id=row["review_item_id"],
        review_item_status=row["review_item_status"],
        identity_classification=row["identity_classification"],
        title=row["primary_title"],
        publication_year=row["publication_year"],
        canonical_url=row["canonical_url"],
        doi=row["doi"],
        pmid=row["pmid"],
        pmcid=row["pmcid"],
        legacy_study_id=row["legacy_study_id"],
        legacy_study_type=row["legacy_study_type"],
        review_decision_id=row["review_decision_id"],
        decision_created_at=row["decision_created_at"],
        access_enrichment_priority=access_enrichment_priority(row),
        provenance={
            "source": "strong_legacy_identity_export",
            "method": "identity_identifier_resolution_audited_legacy_selection",
            "decision_provenance": _load_json_object(row["decision_provenance_json"]),
        },
    )


def access_enrichment_priority(row: sqlite3.Row) -> str:
    if row["pmcid"]:
        return "pmc_full_text_candidate"
    if row["pmid"] and row["doi"]:
        return "pubmed_doi_access_candidate"
    if row["doi"]:
        return "doi_access_candidate"
    return "identity_only_defer_access"


def build_summary(
    records: list[StrongLegacyIdentityRecord],
    *,
    database_path: Path,
    records_path: Path,
) -> dict[str, Any]:
    return {
        "source": "strong_legacy_identity_export",
        "method": "identity_identifier_resolution_audited_legacy_selection",
        "database_path": str(database_path),
        "records_path": str(records_path),
        "total_records": len(records),
        "classification_counts": dict(
            Counter(record.identity_classification for record in records).most_common()
        ),
        "access_enrichment_priority_counts": dict(
            Counter(record.access_enrichment_priority for record in records).most_common()
        ),
        "records_with_doi": sum(record.doi is not None for record in records),
        "records_with_pmid": sum(record.pmid is not None for record in records),
        "records_with_pmcid": sum(record.pmcid is not None for record in records),
    }


def write_jsonl(path: Path, records: list[StrongLegacyIdentityRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Strong legacy identity export")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("total", str(summary["total_records"]))
    table.add_row("with_doi", str(summary["records_with_doi"]))
    table.add_row("with_pmid", str(summary["records_with_pmid"]))
    table.add_row("with_pmcid", str(summary["records_with_pmcid"]))
    for classification, count in summary["classification_counts"].items():
        table.add_row(classification, str(count))
    for priority, count in summary["access_enrichment_priority_counts"].items():
        table.add_row(priority, str(count))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


def _load_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


if __name__ == "__main__":
    app()
