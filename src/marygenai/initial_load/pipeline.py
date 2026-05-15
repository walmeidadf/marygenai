from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from marygenai import __version__
from marygenai.initial_load.files import input_artifact, output_artifact, resolve_legacy_tables
from marygenai.initial_load.legacy_ontology import import_legacy_ontology
from marygenai.initial_load.legacy_studies import import_legacy_studies
from marygenai.schemas import InitialLoadResult, RunManifest
from marygenai.storage import LocalStorage


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_initial_load(
    *,
    legacy_dir: Path,
    storage: LocalStorage,
    run_id: str | None = None,
) -> InitialLoadResult:
    storage.ensure_layout()
    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    table_paths = resolve_legacy_tables(legacy_dir)

    study_source_records, publications, legacy_id_to_document_id = import_legacy_studies(
        studies_path=table_paths["studies"],
        run_id=resolved_run_id,
    )
    ontology_source_records, ontology_entities, document_ontology_links = import_legacy_ontology(
        table_paths=table_paths,
        legacy_id_to_document_id=legacy_id_to_document_id,
        run_id=resolved_run_id,
    )
    source_records = [*study_source_records, *ontology_source_records]

    source_records_path = storage.write_jsonl(
        Path("staging/source_records/legacy") / f"{resolved_run_id}_legacy_source_records.jsonl",
        source_records,
    )
    publications_path = storage.write_jsonl(
        Path("normalized/publications") / f"{resolved_run_id}_publication_candidates.jsonl",
        publications,
    )
    ontology_mapping_dir = Path("normalized/ontology/ontology_mappings")
    ontology_entities_path = storage.write_jsonl(
        ontology_mapping_dir / f"{resolved_run_id}_ontology_entities.jsonl",
        ontology_entities,
    )
    document_ontology_links_path = storage.write_jsonl(
        Path("normalized/ontology/ontology_mappings")
        / f"{resolved_run_id}_document_ontology_links.jsonl",
        document_ontology_links,
    )

    output_paths = {
        "source_records": source_records_path,
        "publication_candidates": publications_path,
        "ontology_entities": ontology_entities_path,
        "document_ontology_links": document_ontology_links_path,
    }
    counts = {
        "source_records": len(source_records),
        "publication_candidates": len(publications),
        "ontology_entities": len(ontology_entities),
        "document_ontology_links": len(document_ontology_links),
    }
    completed_at = datetime.now(UTC)
    output_artifacts = [
        output_artifact(source_records_path, len(source_records)),
        output_artifact(publications_path, len(publications)),
        output_artifact(ontology_entities_path, len(ontology_entities)),
        output_artifact(document_ontology_links_path, len(document_ontology_links)),
    ]
    manifest = RunManifest(
        run_id=resolved_run_id,
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        software_version=__version__,
        input_artifacts=[input_artifact(path) for path in table_paths.values()],
        output_artifacts=output_artifacts,
        counts=counts,
        notes=[
            "Initial MVP load writes JSONL snapshots and a run manifest.",
            "SQLite persistence is prepared as a local data directory but not populated yet.",
        ],
    )
    manifest_path = storage.write_json(
        Path("manifests/runs") / f"{resolved_run_id}_initial_load_manifest.json",
        manifest,
    )
    output_paths["manifest"] = manifest_path

    return InitialLoadResult(
        run_id=resolved_run_id,
        manifest_path=manifest_path,
        output_paths=output_paths,
        counts=counts,
    )
