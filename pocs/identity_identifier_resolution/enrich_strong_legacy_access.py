"""Run access enrichment for strong audited legacy identity records.

This command starts with the safest legacy cohort: records whose identity was
resolved by audited ScienceDirect PII evidence and that already have PMCID/PMID
or DOI. It writes candidate access evidence only; it does not change document
review state and does not classify medical evidence.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from marygenai import __version__
from marygenai.access_enrichment.models import AccessEnrichmentCandidate, AccessEnrichmentRecord
from marygenai.access_enrichment.pipeline import (
    DefaultAccessClientBundle,
    enrich_candidate,
    persist_access_artifacts,
    persist_access_manifest,
)
from marygenai.initial_load.files import file_sha256
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.schemas import InputArtifact, OutputArtifact, RunManifest
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

DEFAULT_INPUT_GLOB = "*_strong_legacy_identity_records.jsonl"
DEFAULT_ACCESS_PRIORITY = "pmc_full_text_candidate"

console = Console()
app = typer.Typer(help="Enrich strong legacy identity records with access evidence.")


@app.callback()
def main() -> None:
    """Run strong legacy access enrichment commands."""


@app.command()
def run(
    records_path: Annotated[
        Path | None,
        typer.Option("--records-path", help="Strong legacy identity JSONL input."),
    ] = None,
    access_priority: Annotated[
        list[str] | None,
        typer.Option("--access-priority", help="Access priority values to select."),
    ] = None,
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=200, help="Maximum legacy records to enrich."),
    ] = 10,
    fetch_pmc_html: Annotated[
        bool,
        typer.Option("--fetch-pmc-html", help="Also retrieve PMC HTML when PMCID exists."),
    ] = False,
    fetch_pdf: Annotated[
        bool,
        typer.Option("--fetch-pdf", help="Reserved PDF flag; PDFs are not downloaded."),
    ] = False,
    skip_enriched: Annotated[
        bool,
        typer.Option(
            "--skip-enriched/--no-skip-enriched",
            help="Skip records that already have access enrichment artifacts.",
        ),
    ] = True,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", help="Delay between enriched records."),
    ] = 0.25,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Enrich strong legacy records with candidate access/full-text evidence."""
    load_dotenv()
    settings = get_settings()
    storage = LocalStorage(settings.data_dir)
    storage.ensure_layout()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_records_path = records_path or latest_strong_legacy_records_path(settings.data_dir)
    priorities = access_priority or [DEFAULT_ACCESS_PRIORITY]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_strong_legacy_access")
    started_at = datetime.now(UTC)
    fetched_at = started_at.isoformat()

    input_records = load_jsonl(resolved_records_path)
    with connect_sqlite(resolved_database_path) as connection:
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
        candidates = select_candidates(
            connection,
            records=input_records,
            priorities=priorities,
            limit=limit,
            skip_enriched=skip_enriched,
        )

    client_bundle = DefaultAccessClientBundle(unpaywall_email=os.getenv("UNPAYWALL_EMAIL"))
    records: list[AccessEnrichmentRecord] = []
    try:
        for candidate in candidates:
            record = enrich_candidate(
                candidate,
                storage=storage,
                run_id=run_id,
                fetched_at=fetched_at,
                clients=client_bundle,
                fetch_pmc_html=fetch_pmc_html,
                fetch_pdf=fetch_pdf,
            )
            records.append(with_legacy_provenance(record, resolved_records_path))
            time.sleep(sleep_seconds)
    finally:
        client_bundle.close()

    output_paths = write_outputs(
        storage=storage,
        run_id=run_id,
        records=records,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        fetched_at=fetched_at,
        input_records_path=resolved_records_path,
    )
    with connect_sqlite(resolved_database_path) as connection:
        initialize_schema(connection)
        manifest = RunManifest.model_validate_json(
            output_paths["manifest"].read_text(encoding="utf-8")
        )
        persist_access_manifest(
            connection,
            manifest=manifest,
            manifest_path=output_paths["manifest"],
        )
        artifact_count = persist_access_artifacts(connection, records=records, run_id=run_id)

    print_summary(
        records=records,
        selected_count=len(candidates),
        artifact_count=artifact_count,
        output_paths=output_paths,
    )


def latest_strong_legacy_records_path(data_dir: Path) -> Path:
    candidates = sorted(
        (data_dir / "normalized" / "identity_identifier_resolution").glob(DEFAULT_INPUT_GLOB)
    )
    if not candidates:
        raise typer.BadParameter("No strong legacy identity records file was found.")
    return candidates[-1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def select_candidates(
    connection: sqlite3.Connection,
    *,
    records: list[dict[str, Any]],
    priorities: list[str],
    limit: int,
    skip_enriched: bool,
) -> list[AccessEnrichmentCandidate]:
    already_enriched = enriched_document_ids(connection) if skip_enriched else set()
    selected = [
        record
        for record in records
        if record.get("access_enrichment_priority") in priorities
        and record["document_id"] not in already_enriched
    ][:limit]
    return [candidate_from_record(record) for record in selected]


def enriched_document_ids(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT DISTINCT document_id FROM access_enrichment_artifact"
    ).fetchall()
    return {str(row["document_id"]) for row in rows}


def candidate_from_record(record: dict[str, Any]) -> AccessEnrichmentCandidate:
    return AccessEnrichmentCandidate(
        document_id=str(record["document_id"]),
        title=record.get("title"),
        pmid=record.get("pmid"),
        pmcid=record.get("pmcid"),
        doi=record.get("doi"),
        identity_status=str(record["identity_classification"]),
        cannabinoid_focus="legacy_identity_resolved",
        study_design=None,
        priority_score=legacy_access_priority_score(record),
        full_text_review_priority=str(record["access_enrichment_priority"]),
    )


def legacy_access_priority_score(record: dict[str, Any]) -> float:
    score = 1000.0
    if record.get("identity_classification") == "gold_identity_seed":
        score += 100.0
    if record.get("pmcid"):
        score += 50.0
    if record.get("pmid"):
        score += 25.0
    if record.get("doi"):
        score += 10.0
    return score


def with_legacy_provenance(
    record: AccessEnrichmentRecord,
    input_records_path: Path,
) -> AccessEnrichmentRecord:
    provenance = dict(record.provenance)
    provenance.update(
        {
            "source": "strong_legacy_access_enrichment",
            "method": "strong_legacy_identity_access_enrichment",
            "input_records_path": str(input_records_path),
            "review_boundary": "candidate_evidence_not_reviewed_knowledge",
        }
    )
    return record.model_copy(update={"provenance": provenance})


def write_outputs(
    *,
    storage: LocalStorage,
    run_id: str,
    records: list[AccessEnrichmentRecord],
    started_at: datetime,
    completed_at: datetime,
    fetched_at: str,
    input_records_path: Path,
) -> dict[str, Path]:
    records_path = storage.write_jsonl(
        Path("normalized/publication_enrichments/strong_legacy_access")
        / f"{run_id}_strong_legacy_access_records.jsonl",
        records,
    )
    summary = {
        "run_id": run_id,
        "source": "strong_legacy_access_enrichment",
        "method": "strong_legacy_identity_access_enrichment",
        "input_records_path": str(input_records_path),
        "fetched_at": fetched_at,
        "total_records": len(records),
        "resolved_access_class_counts": dict(
            Counter(record.resolved_access_class for record in records).most_common()
        ),
        "records_with_errors": sum(bool(record.errors) for record in records),
        "artifact_count": sum(len(record.artifacts) for record in records),
    }
    summary_path = storage.write_json(
        Path("normalized/publication_enrichments/strong_legacy_access")
        / f"{run_id}_strong_legacy_access_summary.json",
        summary,
    )
    manifest = RunManifest(
        run_id=run_id,
        job_type="strong_legacy_access_enrichment",
        source="strong_legacy_access_enrichment",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        software_version=__version__,
        input_artifacts=[
            InputArtifact(
                path=str(input_records_path),
                sha256=file_sha256(input_records_path),
                size_bytes=input_records_path.stat().st_size,
            )
        ],
        output_artifacts=[
            OutputArtifact(
                path=str(records_path),
                record_count=len(records),
                sha256=file_sha256(records_path),
            ),
            OutputArtifact(
                path=str(summary_path),
                record_count=1,
                sha256=file_sha256(summary_path),
            ),
        ],
        counts={
            "enriched_records": len(records),
            "access_artifacts": sum(len(record.artifacts) for record in records),
        },
        notes=[
            "Strong legacy access enrichment outputs are candidate evidence.",
            "This command does not change document.review_state or classify medical evidence.",
        ],
    )
    manifest_path = storage.write_json(
        Path("manifests/runs") / f"{run_id}_strong_legacy_access_manifest.json",
        manifest,
    )
    return {"records": records_path, "summary": summary_path, "manifest": manifest_path}


def print_summary(
    *,
    records: list[AccessEnrichmentRecord],
    selected_count: int,
    artifact_count: int,
    output_paths: dict[str, Path],
) -> None:
    table = Table(title="Strong legacy access enrichment")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("selected", str(selected_count))
    table.add_row("enriched", str(len(records)))
    table.add_row("artifacts", str(artifact_count))
    table.add_row("records_with_errors", str(sum(bool(record.errors) for record in records)))
    for access_class, count in Counter(record.resolved_access_class for record in records).items():
        table.add_row(access_class, str(count))
    console.print(table)
    console.print({name: str(path) for name, path in output_paths.items()})


if __name__ == "__main__":
    app()
