from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

IDENTITY_CONFLICT_COLUMNS = (
    "document_id",
    "classification_run_id",
    "title",
    "publication_year",
    "source_strategy",
    "source_text_path",
    "source_text_sha256",
    "raw_payload_path",
    "canonical_url",
    "source_url",
    "original_pmid",
    "original_pmcid",
    "original_doi",
    "projected_pmid",
    "projected_pmcid",
    "projected_doi",
    "identifier_type",
    "original_corpus_value",
    "candidate_values",
    "candidate_extraction_methods",
    "candidate_source_artifact_paths",
    "candidate_provenance_json",
    "decision_status",
    "selected_value",
    "decision_rationale",
    "reviewer",
    "reviewed_at",
)


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def export_identity_conflicts(
    *,
    index_path: Path,
    output_path: Path,
    classification_run_id: str | None = None,
) -> dict[str, Any]:
    """Export projected-identity conflicts for manual adjudication without mutation."""
    resolved_index_path = index_path.resolve()
    resolved_output_path = output_path.resolve()
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(resolved_index_path), read_only=True)
    try:
        build_row = connection.execute(
            "SELECT value FROM index_metadata WHERE key = 'build_id'"
        ).fetchone()
        build_id = str(build_row[0]) if build_row else None
        query = """
            SELECT
                document_id,
                classification_run_id,
                title,
                publication_year,
                source_text_path,
                source_text_sha256,
                canonical_url,
                source_url,
                corpus_json,
                original_corpus_identity_json,
                projected_identity_json
            FROM documents
            WHERE identity_conflict_count > 0
        """
        parameters: list[str] = []
        if classification_run_id:
            query += " AND classification_run_id = ?"
            parameters.append(classification_run_id)
        query += " ORDER BY document_id"
        rows = connection.execute(query, parameters).fetchall()
    finally:
        connection.close()

    exported_rows: list[dict[str, Any]] = []
    document_ids: set[str] = set()
    for (
        document_id,
        run_id,
        title,
        publication_year,
        source_text_path,
        source_text_sha256,
        canonical_url,
        source_url,
        corpus_json,
        original_identity_json,
        projected_identity_json,
    ) in rows:
        corpus = json.loads(corpus_json)
        original = json.loads(original_identity_json)
        projected = json.loads(projected_identity_json)
        for conflict in projected.get("conflicts", []):
            identifier_type = str(conflict["identifier_type"])
            candidates = conflict.get("candidate_values", [])
            methods: list[str] = []
            source_paths: list[str] = []
            for candidate in candidates:
                for provenance in candidate.get("provenance", []):
                    methods.append(str(provenance.get("extraction_method") or ""))
                    source_paths.append(str(provenance.get("source_artifact_path") or ""))
            exported_rows.append(
                {
                    "document_id": document_id,
                    "classification_run_id": run_id,
                    "title": title or "",
                    "publication_year": publication_year or "",
                    "source_strategy": corpus.get("source_strategy") or "",
                    "source_text_path": source_text_path,
                    "source_text_sha256": source_text_sha256,
                    "raw_payload_path": corpus.get("raw_payload_path") or "",
                    "canonical_url": canonical_url or "",
                    "source_url": source_url or "",
                    "original_pmid": original.get("pmid") or "",
                    "original_pmcid": original.get("pmcid") or "",
                    "original_doi": original.get("doi") or "",
                    "projected_pmid": projected.get("pmid") or "",
                    "projected_pmcid": projected.get("pmcid") or "",
                    "projected_doi": projected.get("doi") or "",
                    "identifier_type": identifier_type,
                    "original_corpus_value": original.get(identifier_type) or "",
                    "candidate_values": " | ".join(
                        str(candidate["value"]) for candidate in candidates
                    ),
                    "candidate_extraction_methods": " | ".join(
                        _ordered_unique(methods)
                    ),
                    "candidate_source_artifact_paths": " | ".join(
                        _ordered_unique(source_paths)
                    ),
                    "candidate_provenance_json": json.dumps(
                        candidates,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "decision_status": "",
                    "selected_value": "",
                    "decision_rationale": "",
                    "reviewer": "",
                    "reviewed_at": "",
                }
            )
            document_ids.add(str(document_id))

    with resolved_output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=IDENTITY_CONFLICT_COLUMNS)
        writer.writeheader()
        writer.writerows(exported_rows)

    exported_at = datetime.now(UTC).isoformat()
    summary = {
        "artifact_type": "candidate_identity_conflict_adjudication_export.v1",
        "exported_at": exported_at,
        "index_path": str(resolved_index_path),
        "index_build_id": build_id,
        "classification_run_id": classification_run_id,
        "document_count": len(document_ids),
        "identifier_conflict_count": len(exported_rows),
        "csv_path": str(resolved_output_path),
        "decision_columns": [
            "decision_status",
            "selected_value",
            "decision_rationale",
            "reviewer",
            "reviewed_at",
        ],
        "allowed_decision_statuses": [
            "select_candidate",
            "keep_original",
            "mark_unresolved",
            "exclude_mismatched_source",
        ],
        "does_not_mutate_sqlite": True,
        "does_not_mutate_review_state": True,
        "trust_boundary": (
            "Candidate source-identity adjudication input, not reviewed knowledge "
            "or clinical guidance."
        ),
    }
    summary_path = resolved_output_path.with_suffix(".summary.json")
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
