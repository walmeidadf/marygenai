"""Classify and apply audited identity-resolution POC outputs.

This command consumes JSONL records produced by resolve_review_identifiers.py.
It is intentionally conservative: dry-run is the default, and apply mode only
closes review items whose ScienceDirect PII evidence passes explicit confidence
rules.
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

from marygenai import __version__
from marygenai.initial_load.persist import document_identity_id, dump_json
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.models import IdentityReviewDecisionCreate
from marygenai.review.repository import (
    apply_latest_identity_review_decision,
    connect_initialized_review_database,
    create_identity_review_decision,
)
from marygenai.settings import get_settings

console = Console()
app = typer.Typer(help="Apply audited legacy identity identifier resolutions.")
DEFAULT_OUTPUT_SUBDIR = Path("normalized/identity_identifier_resolution")

AUTO_CLASSIFICATION = "auto_identity_resolved"
GOLD_CLASSIFICATION = "gold_identity_seed"
AMBIGUOUS_CLASSIFICATION = "ambiguous_identity"
MANUAL_CLASSIFICATION = "needs_manual_identity_review"


@dataclass(frozen=True)
class ResolutionClassification:
    review_item_id: str
    document_id: str
    classification: str
    apply_decision: bool
    resolved: dict[str, str | None]
    title_similarity: float | None
    year_delta: int | None
    matched_candidate_source: str | None
    reasons: list[str]


@app.callback()
def main() -> None:
    """Run audited identity-resolution application commands."""


def load_resolution_records(records_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with records_path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def classify_resolution_record(
    record: dict[str, Any],
    *,
    min_auto_title_similarity: float = 0.92,
    min_gold_title_similarity: float = 0.97,
    max_auto_year_delta: int = 1,
) -> ResolutionClassification:
    resolved = _resolved_identifiers(record)
    pii = _clean(record.get("extracted_pii"))
    candidate = _best_pii_crossref_candidate(record, pii=pii)
    title_similarity = _candidate_title_similarity(candidate)
    year_delta = _candidate_year_delta(record, candidate)
    reasons: list[str] = []

    if not pii:
        reasons.append("missing_sciencedirect_pii")
    if not resolved["doi"]:
        reasons.append("missing_resolved_doi")
    if candidate is None:
        reasons.append("missing_crossref_pii_alternative_id_match")
    if title_similarity is None:
        reasons.append("missing_title_similarity")
    elif title_similarity < min_auto_title_similarity:
        reasons.append("title_similarity_below_auto_threshold")
    if year_delta is None:
        reasons.append("missing_year_comparison")
    elif year_delta > max_auto_year_delta:
        reasons.append("year_delta_above_auto_threshold")

    auto_pass = (
        bool(pii)
        and bool(resolved["doi"])
        and candidate is not None
        and title_similarity is not None
        and title_similarity >= min_auto_title_similarity
        and year_delta is not None
        and year_delta <= max_auto_year_delta
    )
    gold_pass = (
        auto_pass
        and title_similarity is not None
        and title_similarity >= min_gold_title_similarity
        and year_delta == 0
        and bool(resolved["pmid"])
    )

    if gold_pass:
        classification = GOLD_CLASSIFICATION
        reasons.append("pii_doi_title_year_and_pubmed_match")
    elif auto_pass:
        classification = AUTO_CLASSIFICATION
        reasons.append("pii_doi_title_and_year_match")
    elif resolved["doi"]:
        classification = AMBIGUOUS_CLASSIFICATION
    else:
        classification = MANUAL_CLASSIFICATION

    return ResolutionClassification(
        review_item_id=str(record["review_item_id"]),
        document_id=str(record["document_id"]),
        classification=classification,
        apply_decision=classification in {GOLD_CLASSIFICATION, AUTO_CLASSIFICATION},
        resolved=resolved,
        title_similarity=title_similarity,
        year_delta=year_delta,
        matched_candidate_source=candidate.get("source") if candidate else None,
        reasons=reasons,
    )


def apply_classification(
    connection: sqlite3.Connection,
    *,
    record: dict[str, Any],
    classification: ResolutionClassification,
    reviewer: str,
    records_path: Path,
    run_id: str,
) -> None:
    if not classification.apply_decision:
        return

    now = datetime.now(UTC).isoformat()
    original_identity_signals = {
        "known": record.get("known") or {},
        "canonical_url": record.get("canonical_url"),
        "extracted_pii": record.get("extracted_pii"),
    }
    provenance = {
        "source": "identity_identifier_resolution_apply",
        "method": "sciencedirect_pii_crossref_pubmed_identity_application",
        "records_path": str(records_path),
        "run_id": run_id,
        "classification": asdict(classification),
        "resolution_record_provenance": record.get("provenance") or {},
        "software_version": __version__,
        "applied_at": now,
    }
    create_identity_review_decision(
        connection,
        decision=IdentityReviewDecisionCreate(
            review_item_id=classification.review_item_id,
            document_id=classification.document_id,
            reviewer=reviewer,
            decision="corrected_identity",
            reviewed_pmid=classification.resolved["pmid"],
            reviewed_pmcid=classification.resolved["pmcid"],
            reviewed_doi=classification.resolved["doi"],
            reviewed_canonical_url=_canonical_url(record, classification.resolved["doi"]),
            rationale=_rationale(classification),
            original_identity_signals=original_identity_signals,
            provenance=provenance,
        ),
    )
    _upsert_recovered_identities(
        connection,
        document_id=classification.document_id,
        pii=_clean(record.get("extracted_pii")),
        resolved=classification.resolved,
        run_id=run_id,
        association_state=classification.classification,
    )
    _fill_empty_document_identifiers(
        connection,
        document_id=classification.document_id,
        resolved=classification.resolved,
    )
    apply_latest_identity_review_decision(
        connection,
        review_item_id=classification.review_item_id,
        source="identity_identifier_resolution_apply",
    )


def _resolved_identifiers(record: dict[str, Any]) -> dict[str, str | None]:
    resolved = record.get("resolved") or {}
    return {
        "doi": _clean(resolved.get("doi")),
        "pmid": _clean(resolved.get("pmid")),
        "pmcid": _clean(resolved.get("pmcid")),
    }


def _best_pii_crossref_candidate(
    record: dict[str, Any],
    *,
    pii: str | None,
) -> dict[str, Any] | None:
    if not pii:
        return None
    candidates = [
        candidate
        for candidate in record.get("candidates", [])
        if candidate.get("source") == "crossref"
        and pii in (candidate.get("evidence") or {}).get("alternative_ids", [])
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: float(candidate.get("score") or 0.0))


def _candidate_title_similarity(candidate: dict[str, Any] | None) -> float | None:
    if not candidate:
        return None
    value = (candidate.get("evidence") or {}).get("title_similarity")
    return float(value) if value is not None else None


def _candidate_year_delta(
    record: dict[str, Any],
    candidate: dict[str, Any] | None,
) -> int | None:
    if not candidate:
        return None
    record_year = record.get("publication_year")
    candidate_year = candidate.get("publication_year")
    if record_year is None or candidate_year is None:
        return None
    return abs(int(record_year) - int(candidate_year))


def _canonical_url(record: dict[str, Any], doi: str | None) -> str | None:
    if doi:
        return f"https://doi.org/{doi}"
    return _clean(record.get("canonical_url"))


def _rationale(classification: ResolutionClassification) -> str:
    return (
        "Identity resolved from ScienceDirect PII. Crossref matched the PII as an "
        "alternative-id and returned a compatible DOI/title/year candidate; PubMed "
        "identifier evidence was included when available. Classification: "
        f"{classification.classification}."
    )


def _upsert_recovered_identities(
    connection: sqlite3.Connection,
    *,
    document_id: str,
    pii: str | None,
    resolved: dict[str, str | None],
    run_id: str,
    association_state: str,
) -> None:
    rows = []
    for identifier_type, identifier_value in (
        ("pii", pii),
        ("doi", resolved["doi"]),
        ("pmid", resolved["pmid"]),
        ("pmcid", resolved["pmcid"]),
    ):
        if not identifier_value:
            continue
        rows.append(
            (
                document_identity_id(document_id, identifier_type, identifier_value),
                document_id,
                identifier_type,
                identifier_value,
                "identity_identifier_resolution",
                0.99 if identifier_type in {"doi", "pmid", "pmcid"} else 0.95,
                association_state,
                run_id,
            )
        )
    connection.executemany(
        """
        INSERT INTO document_identity (
            document_identity_id, document_id, identifier_type, identifier_value, source,
            confidence, association_state, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id, identifier_type, identifier_value) DO UPDATE SET
            source = excluded.source,
            confidence = excluded.confidence,
            association_state = excluded.association_state,
            run_id = excluded.run_id
        """,
        rows,
    )


def _fill_empty_document_identifiers(
    connection: sqlite3.Connection,
    *,
    document_id: str,
    resolved: dict[str, str | None],
) -> None:
    connection.execute(
        """
        UPDATE document
        SET
            doi = CASE WHEN doi IS NULL OR doi = '' THEN ? ELSE doi END,
            pmid = CASE WHEN pmid IS NULL OR pmid = '' THEN ? ELSE pmid END,
            pmcid = CASE WHEN pmcid IS NULL OR pmcid = '' THEN ? ELSE pmcid END
        WHERE document_id = ?
        """,
        (resolved["doi"], resolved["pmid"], resolved["pmcid"], document_id),
    )


def _insert_run_manifest(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    started_at: str,
    completed_at: str,
    records_path: Path,
    dry_run: bool,
    counts: dict[str, int],
) -> None:
    connection.execute(
        """
        INSERT INTO run_manifest (
            run_id, job_type, source, started_at, completed_at, status, software_version,
            input_artifacts_json, output_artifacts_json, counts_json, errors_json,
            notes_json, manifest_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            completed_at = excluded.completed_at,
            status = excluded.status,
            counts_json = excluded.counts_json,
            notes_json = excluded.notes_json,
            imported_at = excluded.imported_at
        """,
        (
            run_id,
            "identity_identifier_resolution_apply",
            "identity_identifier_resolution",
            started_at,
            completed_at,
            "dry_run" if dry_run else "succeeded",
            __version__,
            dump_json({"records_path": str(records_path)}),
            dump_json({}),
            dump_json(counts),
            dump_json([]),
            dump_json(
                {
                    "dry_run": dry_run,
                    "note": "Applies only strong ScienceDirect PII identity classifications.",
                }
            ),
            None,
            completed_at,
        ),
    )


def write_classification_outputs(
    *,
    output_dir: Path,
    run_id: str,
    records_path: Path,
    classifications: list[ResolutionClassification],
    applied_count: int,
    dry_run: bool,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    classification_path = output_dir / f"{run_id}_identity_resolution_application_records.jsonl"
    summary_path = output_dir / f"{run_id}_identity_resolution_application_summary.json"
    with classification_path.open("w", encoding="utf-8") as file:
        for classification in classifications:
            file.write(json.dumps(asdict(classification), ensure_ascii=False, sort_keys=True))
            file.write("\n")
    summary = {
        "source": "identity_identifier_resolution_apply",
        "method": "sciencedirect_pii_crossref_pubmed_identity_application",
        "records_path": str(records_path),
        "classification_path": str(classification_path),
        "dry_run": dry_run,
        "total_records": len(classifications),
        "applied_records": 0 if dry_run else applied_count,
        "would_apply_records": applied_count,
        "classification_counts": dict(
            Counter(item.classification for item in classifications).most_common()
        ),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return classification_path, summary_path


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def print_summary(
    *,
    classifications: list[ResolutionClassification],
    applied_count: int,
    dry_run: bool,
    classification_path: Path,
    summary_path: Path,
) -> None:
    class_counts = Counter(item.classification for item in classifications)
    table = Table(title="Identity resolution application")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("total", str(len(classifications)))
    table.add_row("would_apply" if dry_run else "applied", str(applied_count))
    for classification, count in class_counts.most_common():
        table.add_row(classification, str(count))
    console.print(table)
    console.print({"summary": str(summary_path), "records": str(classification_path)})


@app.command()
def run(
    records_path: Annotated[
        Path,
        typer.Option("--records-path", help="POC JSONL records to classify/apply."),
    ],
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite review database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for application audit outputs."),
    ] = None,
    reviewer: Annotated[
        str,
        typer.Option("--reviewer", help="Reviewer/provenance label for decisions."),
    ] = "marygenai_identity_identifier_resolution_poc",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--apply", help="Preview by default; use --apply to write SQLite."),
    ] = True,
    min_auto_title_similarity: Annotated[
        float,
        typer.Option("--min-auto-title-similarity", help="Minimum title match for auto apply."),
    ] = 0.92,
    min_gold_title_similarity: Annotated[
        float,
        typer.Option("--min-gold-title-similarity", help="Minimum title match for gold seed."),
    ] = 0.97,
    max_auto_year_delta: Annotated[
        int,
        typer.Option(
            "--max-auto-year-delta",
            help="Maximum publication-year delta for auto apply.",
        ),
    ] = 1,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Limit records for a trial run."),
    ] = None,
) -> None:
    """Classify POC records and optionally apply strong identity resolutions."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ_identity_resolution_apply")
    records = load_resolution_records(records_path)
    if limit is not None:
        records = records[:limit]

    classifications = [
        classify_resolution_record(
            record,
            min_auto_title_similarity=min_auto_title_similarity,
            min_gold_title_similarity=min_gold_title_similarity,
            max_auto_year_delta=max_auto_year_delta,
        )
        for record in records
    ]
    applied_count = sum(item.apply_decision for item in classifications)
    classification_path, summary_path = write_classification_outputs(
        output_dir=resolved_output_dir,
        run_id=run_id,
        records_path=records_path,
        classifications=classifications,
        applied_count=applied_count,
        dry_run=dry_run,
    )

    if not dry_run:
        started_at = datetime.now(UTC).isoformat()
        counts = dict(Counter(item.classification for item in classifications))
        counts["applied"] = applied_count
        with connect_initialized_review_database(resolved_database_path) as connection:
            _insert_run_manifest(
                connection,
                run_id=run_id,
                started_at=started_at,
                completed_at=datetime.now(UTC).isoformat(),
                records_path=records_path,
                dry_run=dry_run,
                counts=counts,
            )
            by_item = {record["review_item_id"]: record for record in records}
            for classification in classifications:
                apply_classification(
                    connection,
                    record=by_item[classification.review_item_id],
                    classification=classification,
                    reviewer=reviewer,
                    records_path=records_path,
                    run_id=run_id,
                )

    print_summary(
        classifications=classifications,
        applied_count=applied_count,
        dry_run=dry_run,
        classification_path=classification_path,
        summary_path=summary_path,
    )


if __name__ == "__main__":
    app()
