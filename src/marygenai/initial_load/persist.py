from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from marygenai.initial_load.files import stable_hash
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.schemas import (
    CanonicalPublicationCandidate,
    DocumentOntologyLink,
    LegacySourceRecord,
    OntologyEntity,
    RunManifest,
)
from marygenai.storage import LocalStorage


def persist_initial_load(
    *,
    storage: LocalStorage,
    database_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, int | str]:
    manifest_path = find_initial_load_manifest(storage=storage, run_id=run_id)
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    resolved_database_path = database_path or sqlite_database_path(storage.root)

    with connect_sqlite(resolved_database_path) as connection:
        initialize_schema(connection)
        persist_manifest(connection, manifest=manifest, manifest_path=manifest_path)
        source_records = list(
            read_jsonl(resolve_output_path(storage, manifest, "source_records"), LegacySourceRecord)
        )
        publications = list(
            read_jsonl(
                resolve_output_path(storage, manifest, "publication_candidates"),
                CanonicalPublicationCandidate,
            )
        )
        ontology_entities = list(
            read_jsonl(resolve_output_path(storage, manifest, "ontology_entities"), OntologyEntity)
        )
        document_ontology_links = list(
            read_jsonl(
                resolve_output_path(storage, manifest, "document_ontology_links"),
                DocumentOntologyLink,
            )
        )

        persist_source_records(connection, source_records)
        persist_publications(connection, publications, manifest.run_id)
        persist_ontology_entities(connection, ontology_entities, manifest.run_id)
        persist_document_ontology_links(connection, document_ontology_links, manifest.run_id)
        review_items = persist_legacy_identity_review_queue(
            connection,
            publications=publications,
            run_id=manifest.run_id,
        )

    return {
        "database": str(resolved_database_path),
        "run_id": manifest.run_id,
        "source_records": len(source_records),
        "publication_candidates": len(publications),
        "ontology_entities": len(ontology_entities),
        "document_ontology_links": len(document_ontology_links),
        "review_items": review_items,
    }


def find_initial_load_manifest(*, storage: LocalStorage, run_id: str | None = None) -> Path:
    manifest_dir = storage.path("manifests/runs")
    if run_id:
        manifest_path = manifest_dir / f"{run_id}_initial_load_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing Initial Load manifest for run id {run_id}")
        return manifest_path

    candidates = sorted(manifest_dir.glob("*_initial_load_manifest.json"))
    if not candidates:
        raise FileNotFoundError(f"No Initial Load manifests found under {manifest_dir}")
    return candidates[-1]


def resolve_output_path(storage: LocalStorage, manifest: RunManifest, artifact_name: str) -> Path:
    artifact = next(
        (
            output
            for output in manifest.output_artifacts
            if artifact_name_from_path(Path(output.path)) == artifact_name
        ),
        None,
    )
    if artifact is None:
        raise ValueError(f"Manifest {manifest.run_id} does not include {artifact_name}")

    path = Path(artifact.path)
    if path.exists():
        return path
    if path.is_absolute():
        return path
    return storage.path(path)


def artifact_name_from_path(path: Path) -> str:
    name = path.name
    if name.endswith("_legacy_source_records.jsonl"):
        return "source_records"
    if name.endswith("_publication_candidates.jsonl"):
        return "publication_candidates"
    if name.endswith("_ontology_entities.jsonl"):
        return "ontology_entities"
    if name.endswith("_document_ontology_links.jsonl"):
        return "document_ontology_links"
    return name


def read_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> list[ModelT]:
    records: list[ModelT] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(model.model_validate_json(line))
    return records


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def model_json(model: BaseModel) -> str:
    return dump_json(model.model_dump(mode="json"))


def persist_manifest(
    connection: sqlite3.Connection,
    *,
    manifest: RunManifest,
    manifest_path: Path,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        INSERT INTO run_manifest (
            run_id, job_type, source, started_at, completed_at, status, software_version,
            input_artifacts_json, output_artifacts_json, counts_json, errors_json, notes_json,
            manifest_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            job_type = excluded.job_type,
            source = excluded.source,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            status = excluded.status,
            software_version = excluded.software_version,
            input_artifacts_json = excluded.input_artifacts_json,
            output_artifacts_json = excluded.output_artifacts_json,
            counts_json = excluded.counts_json,
            errors_json = excluded.errors_json,
            notes_json = excluded.notes_json,
            manifest_path = excluded.manifest_path,
            imported_at = excluded.imported_at
        """,
        (
            manifest.run_id,
            manifest.job_type,
            manifest.source,
            manifest.started_at.isoformat(),
            manifest.completed_at.isoformat(),
            manifest.status,
            manifest.software_version,
            dump_json([artifact.model_dump(mode="json") for artifact in manifest.input_artifacts]),
            dump_json([artifact.model_dump(mode="json") for artifact in manifest.output_artifacts]),
            dump_json(manifest.counts),
            dump_json(manifest.errors),
            dump_json(manifest.notes),
            str(manifest_path),
            now,
        ),
    )


def persist_source_records(
    connection: sqlite3.Connection,
    source_records: list[LegacySourceRecord],
) -> None:
    connection.executemany(
        """
        INSERT INTO source_record (
            source_record_id, source, source_table, legacy_id, row_number, payload_hash,
            raw_payload_json, provenance_json, run_id, error_status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_record_id) DO UPDATE SET
            source = excluded.source,
            source_table = excluded.source_table,
            legacy_id = excluded.legacy_id,
            row_number = excluded.row_number,
            payload_hash = excluded.payload_hash,
            raw_payload_json = excluded.raw_payload_json,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id,
            error_status = excluded.error_status
        """,
        [
            (
                record.source_record_id,
                record.source,
                record.source_table,
                record.legacy_id,
                record.row_number,
                record.payload_hash,
                dump_json(record.raw_payload),
                model_json(record.provenance),
                record.provenance.run_id,
                None,
            )
            for record in source_records
        ],
    )


def persist_publications(
    connection: sqlite3.Connection,
    publications: list[CanonicalPublicationCandidate],
    run_id: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO document (
            document_id, document_type, primary_title, publication_year, canonical_url,
            pmid, pmcid, doi, lifecycle_state, review_state, provenance_json, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            document_type = excluded.document_type,
            primary_title = excluded.primary_title,
            publication_year = excluded.publication_year,
            canonical_url = excluded.canonical_url,
            pmid = excluded.pmid,
            pmcid = excluded.pmcid,
            doi = excluded.doi,
            lifecycle_state = excluded.lifecycle_state,
            review_state = excluded.review_state,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id
        """,
        [
            (
                publication.document_id,
                publication.document_type,
                publication.primary_title,
                publication.publication_year,
                publication.canonical_url,
                publication.pmid,
                publication.pmcid,
                publication.doi,
                "active",
                publication.review_state,
                model_json(publication.provenance),
                run_id,
            )
            for publication in publications
        ],
    )
    connection.executemany(
        """
        INSERT INTO publication (
            document_id, title_pt, title_en, normalized_title, legacy_study_id,
            legacy_study_type, legacy_result, legacy_reference_values_json,
            journal, authors_json, publication_types_json, language, abstract
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            title_pt = excluded.title_pt,
            title_en = excluded.title_en,
            normalized_title = excluded.normalized_title,
            legacy_study_id = excluded.legacy_study_id,
            legacy_study_type = excluded.legacy_study_type,
            legacy_result = excluded.legacy_result,
            legacy_reference_values_json = excluded.legacy_reference_values_json
        """,
        [
            (
                publication.document_id,
                publication.title_pt,
                publication.title_en,
                publication.normalized_title,
                publication.legacy_study_id,
                publication.legacy_study_type,
                publication.legacy_result,
                dump_json(publication.legacy_reference_values),
                None,
                None,
                None,
                None,
                None,
            )
            for publication in publications
        ],
    )
    identity_rows = []
    for publication in publications:
        for identity in publication.identities:
            identity_rows.append(
                (
                    document_identity_id(
                        publication.document_id,
                        identity.identifier_type,
                        identity.identifier_value,
                    ),
                    publication.document_id,
                    identity.identifier_type,
                    identity.identifier_value,
                    identity.source,
                    identity.confidence,
                    identity.association_state,
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
        identity_rows,
    )


def document_identity_id(document_id: str, identifier_type: str, identifier_value: str) -> str:
    digest = stable_hash(
        {
            "document_id": document_id,
            "identifier_type": identifier_type,
            "identifier_value": identifier_value,
        }
    )
    return f"document_identity:{digest[:24]}"


def persist_ontology_entities(
    connection: sqlite3.Connection,
    entities: list[OntologyEntity],
    run_id: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO ontology_entity (
            entity_id, entity_type, canonical_label, canonical_label_en, slug,
            aliases_json, descriptions_json, legacy_fields_json, lifecycle_state,
            review_state, provenance_json, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_id) DO UPDATE SET
            entity_type = excluded.entity_type,
            canonical_label = excluded.canonical_label,
            canonical_label_en = excluded.canonical_label_en,
            slug = excluded.slug,
            aliases_json = excluded.aliases_json,
            descriptions_json = excluded.descriptions_json,
            legacy_fields_json = excluded.legacy_fields_json,
            lifecycle_state = excluded.lifecycle_state,
            review_state = excluded.review_state,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id
        """,
        [
            (
                entity.entity_id,
                entity.entity_type,
                entity.canonical_label,
                entity.canonical_label_en,
                entity.slug,
                dump_json(entity.aliases),
                dump_json(entity.descriptions),
                dump_json(entity.legacy_fields),
                "active",
                entity.review_state,
                model_json(entity.provenance),
                run_id,
            )
            for entity in entities
        ],
    )


def persist_document_ontology_links(
    connection: sqlite3.Connection,
    links: list[DocumentOntologyLink],
    run_id: str,
) -> None:
    connection.executemany(
        """
        INSERT INTO document_ontology_link (
            link_id, document_id, legacy_study_id, entity_id, entity_type, link_type,
            source, confidence, evidence_text, review_state, provenance_json, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id, entity_id, link_type, legacy_study_id) DO UPDATE SET
            entity_type = excluded.entity_type,
            source = excluded.source,
            confidence = excluded.confidence,
            evidence_text = excluded.evidence_text,
            review_state = excluded.review_state,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id
        """,
        [
            (
                link.link_id,
                link.document_id,
                link.legacy_study_id,
                link.entity_id,
                link.entity_type,
                link.link_type,
                link.source,
                link.confidence,
                link.evidence_text,
                link.review_state,
                model_json(link.provenance),
                run_id,
            )
            for link in links
        ],
    )


def persist_legacy_identity_review_queue(
    connection: sqlite3.Connection,
    *,
    publications: list[CanonicalPublicationCandidate],
    run_id: str,
) -> int:
    now = datetime.now(UTC).isoformat()
    rows = []
    for publication in publications:
        if publication.pmid or publication.pmcid or publication.doi:
            continue
        priority_tier, priority_score = identity_review_priority(publication)
        metadata = {
            "reason": "missing_pmid_pmcid_doi",
            "legacy_study_id": publication.legacy_study_id,
            "canonical_url": publication.canonical_url,
            "normalized_title": publication.normalized_title,
            "source": "initial_load",
        }
        rows.append(
            (
                review_item_id("legacy_identity_review", publication.document_id),
                "legacy_identity_review",
                publication.document_id,
                priority_tier,
                priority_score,
                None,
                "open",
                run_id,
                dump_json(metadata),
                now,
                now,
            )
        )

    connection.executemany(
        """
        INSERT INTO review_item (
            review_item_id, queue_type, document_id, priority_tier, priority_score,
            assignee, status, batch_run_id, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(queue_type, document_id) DO UPDATE SET
            priority_tier = excluded.priority_tier,
            priority_score = excluded.priority_score,
            batch_run_id = excluded.batch_run_id,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        rows,
    )
    return len(rows)


def identity_review_priority(publication: CanonicalPublicationCandidate) -> tuple[str, float]:
    if publication.canonical_url and publication.normalized_title:
        return "canonical_url_and_title", 80.0
    if publication.canonical_url:
        return "canonical_url_only", 70.0
    if publication.normalized_title:
        return "title_only", 60.0
    return "weak_identity", 50.0


def review_item_id(queue_type: str, document_id: str) -> str:
    digest = stable_hash({"queue_type": queue_type, "document_id": document_id})
    return f"review_item:{digest[:24]}"
