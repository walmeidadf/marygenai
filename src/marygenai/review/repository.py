from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from marygenai.persistence.sqlite import connect_sqlite
from marygenai.review.models import (
    LegacyReference,
    OntologyLinkSummary,
    PublicationDetail,
    PublicationIdentitySummary,
    PublicationSummary,
    ReviewItemStatus,
    ReviewItemStatusResult,
    ReviewItemStatusUpdate,
    ReviewQueueItem,
    ReviewQueueSummary,
)

REVIEW_SCHEMA_TABLES = {
    "document",
    "document_identity",
    "document_ontology_link",
    "ontology_entity",
    "publication",
    "review_item",
}

STATUS_ADAPTER = TypeAdapter(ReviewItemStatus)


class ReviewDatabaseNotInitializedError(RuntimeError):
    """Raised when review commands are pointed at a missing or uninitialized DB."""


class ReviewItemNotFoundError(LookupError):
    """Raised when a review item id does not exist."""


class PublicationNotFoundError(LookupError):
    """Raised when a document id does not exist."""


@contextmanager
def connect_initialized_review_database(database_path: Path):
    if not database_path.exists():
        raise ReviewDatabaseNotInitializedError(
            f"SQLite database is not initialized at {database_path}. Run `marygenai db init` first."
        )
    with connect_sqlite(database_path) as connection:
        connection.row_factory = sqlite3.Row
        require_review_schema(connection)
        yield connection


def require_review_schema(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    table_names = {row[0] for row in rows}
    missing_tables = REVIEW_SCHEMA_TABLES - table_names
    if missing_tables:
        missing = ", ".join(sorted(missing_tables))
        raise ReviewDatabaseNotInitializedError(
            f"SQLite review schema is not initialized. Missing tables: {missing}."
        )


def list_review_queues(connection: sqlite3.Connection) -> list[ReviewQueueSummary]:
    require_review_schema(connection)
    rows = connection.execute(
        """
        SELECT queue_type, status, COUNT(*) AS item_count
        FROM review_item
        GROUP BY queue_type, status
        ORDER BY queue_type, status
        """
    ).fetchall()
    summaries: dict[str, ReviewQueueSummary] = {}
    for row in rows:
        queue_type = row["queue_type"]
        summary = summaries.setdefault(
            queue_type,
            ReviewQueueSummary(queue_type=queue_type, total_items=0),
        )
        item_count = int(row["item_count"])
        summary.total_items += item_count
        if row["status"] == "open":
            summary.open_items = item_count
        elif row["status"] == "in_review":
            summary.in_review_items = item_count
        elif row["status"] == "resolved":
            summary.resolved_items = item_count
        elif row["status"] == "dismissed":
            summary.dismissed_items = item_count
    return list(summaries.values())


def list_open_review_items(
    connection: sqlite3.Connection,
    *,
    queue_type: str = "legacy_identity_review",
    limit: int = 20,
) -> list[ReviewQueueItem]:
    require_review_schema(connection)
    rows = connection.execute(
        """
        SELECT
            ri.review_item_id,
            ri.queue_type,
            ri.status,
            ri.priority_tier,
            ri.priority_score,
            ri.assignee,
            ri.created_at,
            ri.updated_at,
            ri.metadata_json,
            d.document_id,
            d.document_type,
            d.primary_title,
            d.publication_year,
            d.canonical_url,
            d.pmid,
            d.pmcid,
            d.doi,
            d.review_state,
            p.legacy_study_id,
            p.legacy_study_type
        FROM review_item AS ri
        JOIN document AS d ON d.document_id = ri.document_id
        JOIN publication AS p ON p.document_id = d.document_id
        WHERE ri.queue_type = ? AND ri.status = 'open'
        ORDER BY ri.priority_score DESC, ri.created_at ASC, ri.review_item_id ASC
        LIMIT ?
        """,
        (queue_type, limit),
    ).fetchall()
    return [_queue_item_from_row(row) for row in rows]


def get_publication_detail(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> PublicationDetail:
    require_review_schema(connection)
    row = connection.execute(
        """
        SELECT
            d.document_id,
            d.document_type,
            d.primary_title,
            d.publication_year,
            d.canonical_url,
            d.pmid,
            d.pmcid,
            d.doi,
            d.review_state,
            p.legacy_study_id,
            p.legacy_study_type,
            p.title_pt,
            p.title_en,
            p.normalized_title,
            p.legacy_result,
            p.legacy_reference_values_json
        FROM document AS d
        JOIN publication AS p ON p.document_id = d.document_id
        WHERE d.document_id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise PublicationNotFoundError(f"Publication document not found: {document_id}")

    publication = _publication_summary_from_row(row)
    legacy_reference = LegacyReference(
        legacy_study_id=row["legacy_study_id"],
        title_pt=row["title_pt"],
        title_en=row["title_en"],
        normalized_title=row["normalized_title"],
        legacy_result=row["legacy_result"],
        reference_values=_load_json_object(row["legacy_reference_values_json"]),
    )
    return PublicationDetail(
        publication=publication,
        identities=list_publication_identities(connection, document_id=document_id),
        ontology_links=list_publication_ontology_links(connection, document_id=document_id),
        legacy_reference=legacy_reference,
        review_items=list_publication_review_items(connection, document_id=document_id),
    )


def get_publication_detail_for_review_item(
    connection: sqlite3.Connection,
    *,
    review_item_id: str,
) -> PublicationDetail:
    document_id = connection.execute(
        "SELECT document_id FROM review_item WHERE review_item_id = ?",
        (review_item_id,),
    ).fetchone()
    if document_id is None:
        raise ReviewItemNotFoundError(f"Review item not found: {review_item_id}")
    return get_publication_detail(connection, document_id=document_id["document_id"])


def list_publication_identities(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> list[PublicationIdentitySummary]:
    rows = connection.execute(
        """
        SELECT document_identity_id, identifier_type, identifier_value, source,
            confidence, association_state
        FROM document_identity
        WHERE document_id = ?
        ORDER BY identifier_type, identifier_value
        """,
        (document_id,),
    ).fetchall()
    return [
        PublicationIdentitySummary(
            document_identity_id=row["document_identity_id"],
            identifier_type=row["identifier_type"],
            identifier_value=row["identifier_value"],
            source=row["source"],
            confidence=row["confidence"],
            association_state=row["association_state"],
        )
        for row in rows
    ]


def list_publication_ontology_links(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> list[OntologyLinkSummary]:
    rows = connection.execute(
        """
        SELECT
            link.link_id,
            link.entity_id,
            link.entity_type,
            entity.canonical_label,
            entity.canonical_label_en,
            link.link_type,
            link.source,
            link.confidence,
            link.evidence_text,
            link.review_state
        FROM document_ontology_link AS link
        JOIN ontology_entity AS entity ON entity.entity_id = link.entity_id
        WHERE link.document_id = ?
        ORDER BY link.entity_type, entity.canonical_label, link.link_id
        """,
        (document_id,),
    ).fetchall()
    return [
        OntologyLinkSummary(
            link_id=row["link_id"],
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            canonical_label=row["canonical_label"],
            canonical_label_en=row["canonical_label_en"],
            link_type=row["link_type"],
            source=row["source"],
            confidence=row["confidence"],
            evidence_text=row["evidence_text"],
            review_state=row["review_state"],
        )
        for row in rows
    ]


def list_publication_review_items(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> list[ReviewQueueItem]:
    rows = connection.execute(
        """
        SELECT
            ri.review_item_id,
            ri.queue_type,
            ri.status,
            ri.priority_tier,
            ri.priority_score,
            ri.assignee,
            ri.created_at,
            ri.updated_at,
            ri.metadata_json,
            d.document_id,
            d.document_type,
            d.primary_title,
            d.publication_year,
            d.canonical_url,
            d.pmid,
            d.pmcid,
            d.doi,
            d.review_state,
            p.legacy_study_id,
            p.legacy_study_type
        FROM review_item AS ri
        JOIN document AS d ON d.document_id = ri.document_id
        JOIN publication AS p ON p.document_id = d.document_id
        WHERE ri.document_id = ?
        ORDER BY ri.queue_type, ri.created_at
        """,
        (document_id,),
    ).fetchall()
    return [_queue_item_from_row(row) for row in rows]


def update_review_item_status(
    connection: sqlite3.Connection,
    *,
    update: ReviewItemStatusUpdate,
) -> ReviewItemStatusResult:
    require_review_schema(connection)
    status = STATUS_ADAPTER.validate_python(update.status)
    row = connection.execute(
        "SELECT status, metadata_json FROM review_item WHERE review_item_id = ?",
        (update.review_item_id,),
    ).fetchone()
    if row is None:
        raise ReviewItemNotFoundError(f"Review item not found: {update.review_item_id}")

    now = datetime.now(UTC).isoformat()
    previous_status = STATUS_ADAPTER.validate_python(row["status"])
    metadata = _load_json_object(row["metadata_json"])
    status_history = _status_history(metadata)
    status_history.append(
        {
            "from_status": previous_status,
            "to_status": status,
            "note": update.note,
            "updated_at": now,
        }
    )
    metadata["status_history"] = status_history
    metadata["last_status_note"] = update.note
    metadata["last_status_updated_at"] = now

    connection.execute(
        """
        UPDATE review_item
        SET status = ?, metadata_json = ?, updated_at = ?
        WHERE review_item_id = ?
        """,
        (status, _dump_json(metadata), now, update.review_item_id),
    )
    return ReviewItemStatusResult(
        review_item_id=update.review_item_id,
        previous_status=previous_status,
        status=status,
        note=update.note,
        updated_at=now,
        metadata=metadata,
    )


def _queue_item_from_row(row: sqlite3.Row) -> ReviewQueueItem:
    return ReviewQueueItem(
        review_item_id=row["review_item_id"],
        queue_type=row["queue_type"],
        status=STATUS_ADAPTER.validate_python(row["status"]),
        priority_tier=row["priority_tier"],
        priority_score=row["priority_score"],
        assignee=row["assignee"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=_load_json_object(row["metadata_json"]),
        publication=_publication_summary_from_row(row),
    )


def _publication_summary_from_row(row: sqlite3.Row) -> PublicationSummary:
    return PublicationSummary(
        document_id=row["document_id"],
        document_type=row["document_type"],
        primary_title=row["primary_title"],
        publication_year=row["publication_year"],
        canonical_url=row["canonical_url"],
        pmid=row["pmid"],
        pmcid=row["pmcid"],
        doi=row["doi"],
        legacy_study_id=row["legacy_study_id"],
        legacy_study_type=row["legacy_study_type"],
        review_state=row["review_state"],
    )


def _load_json_object(raw_json: str | None) -> dict[str, Any]:
    if not raw_json:
        return {}
    value = json.loads(raw_json)
    if isinstance(value, dict):
        return value
    return {"value": value}


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _status_history(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    history = metadata.get("status_history")
    if not isinstance(history, Iterable) or isinstance(history, (str, bytes, dict)):
        return []
    return [entry for entry in history if isinstance(entry, dict)]
