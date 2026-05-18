from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SQLITE_FILENAME = "marygenai.sqlite"
SCHEMA_VERSION = 3


def sqlite_database_path(data_dir: Path) -> Path:
    return data_dir / "db" / DEFAULT_SQLITE_FILENAME


@contextmanager
def connect_sqlite(
    database_path: Path,
    *,
    check_same_thread: bool = True,
) -> Iterator[sqlite3.Connection]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, check_same_thread=check_same_thread)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]


MIGRATIONS = (
    Migration(
        version=1,
        name="initial_review_schema",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS run_manifest (
                run_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                source TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                status TEXT NOT NULL,
                software_version TEXT NOT NULL,
                input_artifacts_json TEXT NOT NULL,
                output_artifacts_json TEXT NOT NULL,
                counts_json TEXT NOT NULL,
                errors_json TEXT NOT NULL,
                notes_json TEXT NOT NULL,
                manifest_path TEXT,
                imported_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_record (
                source_record_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_table TEXT NOT NULL,
                legacy_id TEXT,
                row_number INTEGER NOT NULL,
                payload_hash TEXT NOT NULL,
                raw_payload_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                error_status TEXT,
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS document (
                document_id TEXT PRIMARY KEY,
                document_type TEXT NOT NULL,
                primary_title TEXT,
                publication_year INTEGER,
                canonical_url TEXT,
                pmid TEXT,
                pmcid TEXT,
                doi TEXT,
                lifecycle_state TEXT NOT NULL DEFAULT 'active',
                review_state TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS document_identity (
                document_identity_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                identifier_type TEXT NOT NULL,
                identifier_value TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                association_state TEXT NOT NULL,
                run_id TEXT NOT NULL,
                UNIQUE (document_id, identifier_type, identifier_value),
                FOREIGN KEY (document_id) REFERENCES document(document_id),
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS publication (
                document_id TEXT PRIMARY KEY,
                title_pt TEXT,
                title_en TEXT,
                normalized_title TEXT,
                legacy_study_id TEXT NOT NULL,
                legacy_study_type TEXT,
                legacy_result TEXT,
                legacy_reference_values_json TEXT NOT NULL,
                journal TEXT,
                authors_json TEXT,
                publication_types_json TEXT,
                language TEXT,
                abstract TEXT,
                FOREIGN KEY (document_id) REFERENCES document(document_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ontology_entity (
                entity_id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                canonical_label TEXT NOT NULL,
                canonical_label_en TEXT,
                slug TEXT,
                aliases_json TEXT NOT NULL,
                descriptions_json TEXT NOT NULL,
                legacy_fields_json TEXT NOT NULL,
                lifecycle_state TEXT NOT NULL DEFAULT 'active',
                review_state TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS document_ontology_link (
                link_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                legacy_study_id TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                link_type TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence_text TEXT,
                review_state TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                UNIQUE (document_id, entity_id, link_type, legacy_study_id),
                FOREIGN KEY (document_id) REFERENCES document(document_id),
                FOREIGN KEY (entity_id) REFERENCES ontology_entity(entity_id),
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS review_item (
                review_item_id TEXT PRIMARY KEY,
                queue_type TEXT NOT NULL,
                document_id TEXT NOT NULL,
                priority_tier TEXT NOT NULL,
                priority_score REAL NOT NULL,
                assignee TEXT,
                status TEXT NOT NULL,
                batch_run_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (queue_type, document_id),
                FOREIGN KEY (document_id) REFERENCES document(document_id),
                FOREIGN KEY (batch_run_id) REFERENCES run_manifest(run_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_source_record_run_id ON source_record(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_document_pmid ON document(pmid)",
            "CREATE INDEX IF NOT EXISTS idx_document_pmcid ON document(pmcid)",
            "CREATE INDEX IF NOT EXISTS idx_document_doi ON document(doi)",
            """
            CREATE INDEX IF NOT EXISTS idx_document_identity_lookup
            ON document_identity(identifier_type, identifier_value)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ontology_entity_type_label
            ON ontology_entity(entity_type, canonical_label)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_document_ontology_link_document
            ON document_ontology_link(document_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_document_ontology_link_entity
            ON document_ontology_link(entity_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_review_item_queue_status
            ON review_item(queue_type, status, priority_score DESC)
            """,
        ),
    ),
    Migration(
        version=2,
        name="structured_review_decisions",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS review_decision (
                review_decision_id TEXT PRIMARY KEY,
                review_item_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                decision TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                reviewed_pmid TEXT,
                reviewed_pmcid TEXT,
                reviewed_doi TEXT,
                reviewed_canonical_url TEXT,
                rationale TEXT,
                original_identity_signals_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (review_item_id) REFERENCES review_item(review_item_id),
                FOREIGN KEY (document_id) REFERENCES document(document_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_review_decision_review_item
            ON review_decision(review_item_id, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_review_decision_document
            ON review_decision(document_id, created_at DESC)
            """,
        ),
    ),
    Migration(
        version=3,
        name="pubmed_candidate_discovery",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS publication_candidate_discovery (
                document_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_candidate_id TEXT NOT NULL,
                identity_status TEXT NOT NULL,
                legacy_match_type TEXT,
                legacy_match_confidence REAL NOT NULL,
                legacy_document_ids_json TEXT NOT NULL,
                legacy_study_ids_json TEXT NOT NULL,
                cannabinoid_focus TEXT NOT NULL,
                study_design TEXT,
                study_design_rank INTEGER NOT NULL,
                priority_tier TEXT NOT NULL,
                priority_score REAL NOT NULL,
                full_text_review_priority TEXT NOT NULL,
                query_names_json TEXT NOT NULL,
                score_reasons_json TEXT NOT NULL,
                review_reasons_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES document(document_id),
                FOREIGN KEY (run_id) REFERENCES run_manifest(run_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_pubmed_candidate_identity_status
            ON publication_candidate_discovery(identity_status, priority_score DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_pubmed_candidate_focus
            ON publication_candidate_discovery(cannabinoid_focus, priority_score DESC)
            """,
        ),
    ),
)


def initialize_schema(connection: sqlite3.Connection) -> int:
    """Create or upgrade the local SQLite schema idempotently."""
    current_version = connection.execute("PRAGMA user_version").fetchone()[0]
    for migration in MIGRATIONS:
        if migration.version <= current_version:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(f"PRAGMA user_version = {migration.version}")
        current_version = migration.version
    return current_version
