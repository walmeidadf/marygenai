from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from marygenai import __version__
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema
from marygenai.review.models import (
    IdentityDecisionApplicationResult,
    IdentityReviewDecision,
    IdentityReviewDecisionCreate,
    LegacyReference,
    OntologyLinkSummary,
    PublicationCandidateDiscoverySummary,
    PublicationCandidateProvenance,
    PublicationDetail,
    PublicationIdentitySummary,
    PublicationSummary,
    ReviewItemStatus,
    ReviewItemStatusFilter,
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
    "publication_candidate_discovery",
    "review_decision",
    "review_item",
}

STATUS_ADAPTER = TypeAdapter(ReviewItemStatus)
STATUS_FILTER_ADAPTER = TypeAdapter(ReviewItemStatusFilter)


class ReviewDatabaseNotInitializedError(RuntimeError):
    """Raised when review commands are pointed at a missing or uninitialized DB."""


class ReviewItemNotFoundError(LookupError):
    """Raised when a review item id does not exist."""


class PublicationNotFoundError(LookupError):
    """Raised when a document id does not exist."""


class IdentityDecisionNotFoundError(LookupError):
    """Raised when a review item has no structured identity decision to apply."""


class IdentityDecisionNotApplicableError(ValueError):
    """Raised when the latest identity decision cannot advance workflow state."""


@contextmanager
def connect_initialized_review_database(
    database_path: Path,
    *,
    check_same_thread: bool = True,
):
    if not database_path.exists():
        raise ReviewDatabaseNotInitializedError(
            f"SQLite database is not initialized at {database_path}. Run `marygenai db init` first."
        )
    with connect_sqlite(database_path, check_same_thread=check_same_thread) as connection:
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
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


def list_review_items(
    connection: sqlite3.Connection,
    *,
    queue_type: str = "legacy_identity_review",
    status: ReviewItemStatusFilter = "open",
    limit: int = 20,
    identity_status: str | None = None,
    priority_tier: str | None = None,
    full_text_review_priority: str | None = None,
) -> list[ReviewQueueItem]:
    require_review_schema(connection)
    status_filter = STATUS_FILTER_ADAPTER.validate_python(status)
    filters = ["ri.queue_type = ?"]
    parameters: list[Any] = [queue_type]
    if status_filter != "all":
        filters.append("ri.status = ?")
        parameters.append(status_filter)
    if identity_status:
        filters.append("discovery.identity_status = ?")
        parameters.append(identity_status)
    if priority_tier:
        filters.append("ri.priority_tier = ?")
        parameters.append(priority_tier)
    if full_text_review_priority:
        filters.append("discovery.full_text_review_priority = ?")
        parameters.append(full_text_review_priority)
    parameters.append(limit)
    where_clause = " AND ".join(filters)
    rows = connection.execute(
        f"""
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
            p.legacy_study_type,
            discovery.identity_status,
            discovery.cannabinoid_focus,
            discovery.full_text_review_priority,
            discovery.legacy_match_type,
            discovery.legacy_match_confidence,
            discovery.review_reasons_json
        FROM review_item AS ri
        JOIN document AS d ON d.document_id = ri.document_id
        JOIN publication AS p ON p.document_id = d.document_id
        LEFT JOIN publication_candidate_discovery AS discovery
            ON discovery.document_id = ri.document_id
        WHERE {where_clause}
        ORDER BY
            CASE ri.status
                WHEN 'open' THEN 0
                WHEN 'in_review' THEN 1
                WHEN 'resolved' THEN 2
                WHEN 'dismissed' THEN 3
                ELSE 4
            END,
            ri.priority_score DESC,
            ri.created_at ASC,
            ri.review_item_id ASC
        LIMIT ?
        """,
        parameters,
    ).fetchall()
    return [_queue_item_from_row(row) for row in rows]


def list_open_review_items(
    connection: sqlite3.Connection,
    *,
    queue_type: str = "legacy_identity_review",
    limit: int = 20,
    identity_status: str | None = None,
    priority_tier: str | None = None,
    full_text_review_priority: str | None = None,
) -> list[ReviewQueueItem]:
    return list_review_items(
        connection,
        queue_type=queue_type,
        status="open",
        limit=limit,
        identity_status=identity_status,
        priority_tier=priority_tier,
        full_text_review_priority=full_text_review_priority,
    )


def list_publication_candidate_discoveries(
    connection: sqlite3.Connection,
    *,
    limit: int = 20,
    identity_status: str | None = None,
) -> list[PublicationCandidateDiscoverySummary]:
    require_review_schema(connection)
    if identity_status:
        rows = connection.execute(
            """
            SELECT
                discovery.document_id,
                discovery.source,
                discovery.source_candidate_id,
                discovery.identity_status,
                discovery.cannabinoid_focus,
                discovery.study_design,
                discovery.priority_tier,
                discovery.priority_score,
                discovery.full_text_review_priority,
                discovery.query_names_json,
                discovery.review_reasons_json,
                d.primary_title,
                d.publication_year,
                d.pmid,
                d.pmcid,
                d.doi
            FROM publication_candidate_discovery AS discovery
            JOIN document AS d ON d.document_id = discovery.document_id
            WHERE discovery.identity_status = ?
            ORDER BY discovery.priority_score DESC, discovery.document_id ASC
            LIMIT ?
            """,
            (identity_status, limit),
        ).fetchall()
    else:
        rows = connection.execute(
            """
            SELECT
                discovery.document_id,
                discovery.source,
                discovery.source_candidate_id,
                discovery.identity_status,
                discovery.cannabinoid_focus,
                discovery.study_design,
                discovery.priority_tier,
                discovery.priority_score,
                discovery.full_text_review_priority,
                discovery.query_names_json,
                discovery.review_reasons_json,
                d.primary_title,
                d.publication_year,
                d.pmid,
                d.pmcid,
                d.doi
            FROM publication_candidate_discovery AS discovery
            JOIN document AS d ON d.document_id = discovery.document_id
            ORDER BY discovery.priority_score DESC, discovery.document_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        PublicationCandidateDiscoverySummary(
            document_id=row["document_id"],
            source=row["source"],
            source_candidate_id=row["source_candidate_id"],
            identity_status=row["identity_status"],
            cannabinoid_focus=row["cannabinoid_focus"],
            study_design=row["study_design"],
            priority_tier=row["priority_tier"],
            priority_score=row["priority_score"],
            full_text_review_priority=row["full_text_review_priority"],
            title=row["primary_title"],
            publication_year=row["publication_year"],
            pmid=row["pmid"],
            pmcid=row["pmcid"],
            doi=row["doi"],
            query_names=_load_json_array(row["query_names_json"]),
            review_reasons=_load_json_array(row["review_reasons_json"]),
        )
        for row in rows
    ]


def get_publication_candidate_provenance(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> PublicationCandidateProvenance:
    require_review_schema(connection)
    row = connection.execute(
        """
        SELECT
            discovery.*,
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
        FROM publication_candidate_discovery AS discovery
        JOIN document AS d ON d.document_id = discovery.document_id
        JOIN publication AS p ON p.document_id = discovery.document_id
        WHERE discovery.document_id = ?
        """,
        (document_id,),
    ).fetchone()
    if row is None:
        raise PublicationNotFoundError(f"Publication candidate not found: {document_id}")
    return PublicationCandidateProvenance(
        document_id=row["document_id"],
        source=row["source"],
        source_candidate_id=row["source_candidate_id"],
        identity_status=row["identity_status"],
        legacy_match_type=row["legacy_match_type"],
        legacy_match_confidence=row["legacy_match_confidence"],
        legacy_document_ids=_load_json_array(row["legacy_document_ids_json"]),
        legacy_study_ids=_load_json_array(row["legacy_study_ids_json"]),
        cannabinoid_focus=row["cannabinoid_focus"],
        study_design=row["study_design"],
        study_design_rank=row["study_design_rank"],
        priority_tier=row["priority_tier"],
        priority_score=row["priority_score"],
        full_text_review_priority=row["full_text_review_priority"],
        query_names=_load_json_array(row["query_names_json"]),
        score_reasons=_load_json_array(row["score_reasons_json"]),
        review_reasons=_load_json_array(row["review_reasons_json"]),
        provenance=_load_json_object(row["provenance_json"]),
        publication=_publication_summary_from_row(row),
    )


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


def create_identity_review_decision(
    connection: sqlite3.Connection,
    *,
    decision: IdentityReviewDecisionCreate,
) -> IdentityReviewDecision:
    require_review_schema(connection)
    review_item = connection.execute(
        "SELECT document_id FROM review_item WHERE review_item_id = ?",
        (decision.review_item_id,),
    ).fetchone()
    if review_item is None:
        raise ReviewItemNotFoundError(f"Review item not found: {decision.review_item_id}")
    if review_item["document_id"] != decision.document_id:
        raise PublicationNotFoundError(
            "Review decision document_id does not match the review item document."
        )

    created_at = datetime.now(UTC).isoformat()
    provenance = _decision_provenance(decision.provenance)
    review_decision_id = f"review_decision:{uuid4()}"
    connection.execute(
        """
        INSERT INTO review_decision (
            review_decision_id,
            review_item_id,
            document_id,
            decision_type,
            decision,
            reviewer,
            reviewed_pmid,
            reviewed_pmcid,
            reviewed_doi,
            reviewed_canonical_url,
            rationale,
            original_identity_signals_json,
            provenance_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            review_decision_id,
            decision.review_item_id,
            decision.document_id,
            "legacy_identity",
            decision.decision,
            decision.reviewer,
            _clean_text(decision.reviewed_pmid),
            _clean_text(decision.reviewed_pmcid),
            _clean_text(decision.reviewed_doi),
            _clean_text(decision.reviewed_canonical_url),
            _clean_text(decision.rationale),
            _dump_json(decision.original_identity_signals),
            _dump_json(provenance),
            created_at,
        ),
    )
    return IdentityReviewDecision(
        review_decision_id=review_decision_id,
        review_item_id=decision.review_item_id,
        document_id=decision.document_id,
        decision_type="legacy_identity",
        reviewer=decision.reviewer,
        decision=decision.decision,
        reviewed_pmid=_clean_text(decision.reviewed_pmid),
        reviewed_pmcid=_clean_text(decision.reviewed_pmcid),
        reviewed_doi=_clean_text(decision.reviewed_doi),
        reviewed_canonical_url=_clean_text(decision.reviewed_canonical_url),
        rationale=_clean_text(decision.rationale),
        original_identity_signals=decision.original_identity_signals,
        created_at=created_at,
        provenance=provenance,
    )


def apply_latest_identity_review_decision(
    connection: sqlite3.Connection,
    *,
    review_item_id: str,
    source: str = "marygenai.review",
) -> IdentityDecisionApplicationResult:
    require_review_schema(connection)
    review_item = connection.execute(
        """
        SELECT review_item_id, document_id, status, metadata_json
        FROM review_item
        WHERE review_item_id = ?
        """,
        (review_item_id,),
    ).fetchone()
    if review_item is None:
        raise ReviewItemNotFoundError(f"Review item not found: {review_item_id}")

    decision_row = connection.execute(
        """
        SELECT *
        FROM review_decision
        WHERE review_item_id = ? AND decision_type = 'legacy_identity'
        ORDER BY created_at DESC, review_decision_id DESC
        LIMIT 1
        """,
        (review_item_id,),
    ).fetchone()
    if decision_row is None:
        raise IdentityDecisionNotFoundError(
            f"No structured identity decision is available for review item: {review_item_id}"
        )

    decision = _identity_decision_from_row(decision_row)
    target_status = _identity_decision_target_status(decision.decision)
    if target_status is None:
        raise IdentityDecisionNotApplicableError(
            "The latest identity decision is unresolved and cannot close the workflow item."
        )

    now = datetime.now(UTC).isoformat()
    previous_status = STATUS_ADAPTER.validate_python(review_item["status"])
    metadata = _load_json_object(review_item["metadata_json"])
    status_history = _status_history(metadata)
    status_history.append(
        {
            "from_status": previous_status,
            "to_status": target_status,
            "note": f"Applied identity decision {decision.review_decision_id}.",
            "updated_at": now,
            "application": {
                "type": "identity_decision_workflow_application",
                "source": source,
                "review_decision_id": decision.review_decision_id,
                "decision": decision.decision,
                "decision_created_at": decision.created_at,
                "decision_reviewer": decision.reviewer,
                "software_version": __version__,
                "application_schema_version": "identity_decision_application.v1",
            },
        }
    )
    metadata["status_history"] = status_history
    metadata["last_status_note"] = f"Applied identity decision {decision.review_decision_id}."
    metadata["last_status_updated_at"] = now
    metadata["last_identity_decision_application"] = {
        "source": source,
        "review_decision_id": decision.review_decision_id,
        "decision": decision.decision,
        "applied_status": target_status,
        "applied_at": now,
        "software_version": __version__,
        "application_schema_version": "identity_decision_application.v1",
    }

    connection.execute(
        """
        UPDATE review_item
        SET status = ?, metadata_json = ?, updated_at = ?
        WHERE review_item_id = ?
        """,
        (target_status, _dump_json(metadata), now, review_item_id),
    )
    return IdentityDecisionApplicationResult(
        review_item_id=review_item_id,
        review_decision_id=decision.review_decision_id,
        decision=decision.decision,
        previous_status=previous_status,
        status=target_status,
        applied_at=now,
        metadata=metadata,
    )


def list_identity_review_decisions_for_item(
    connection: sqlite3.Connection,
    *,
    review_item_id: str,
) -> list[IdentityReviewDecision]:
    require_review_schema(connection)
    item = connection.execute(
        "SELECT 1 FROM review_item WHERE review_item_id = ?",
        (review_item_id,),
    ).fetchone()
    if item is None:
        raise ReviewItemNotFoundError(f"Review item not found: {review_item_id}")
    rows = connection.execute(
        """
        SELECT *
        FROM review_decision
        WHERE review_item_id = ?
        ORDER BY created_at DESC, review_decision_id DESC
        """,
        (review_item_id,),
    ).fetchall()
    return [_identity_decision_from_row(row) for row in rows]


def list_identity_review_decisions_for_publication(
    connection: sqlite3.Connection,
    *,
    document_id: str,
) -> list[IdentityReviewDecision]:
    require_review_schema(connection)
    publication = connection.execute(
        "SELECT 1 FROM document WHERE document_id = ?",
        (document_id,),
    ).fetchone()
    if publication is None:
        raise PublicationNotFoundError(f"Publication document not found: {document_id}")
    rows = connection.execute(
        """
        SELECT *
        FROM review_decision
        WHERE document_id = ?
        ORDER BY created_at DESC, review_decision_id DESC
        """,
        (document_id,),
    ).fetchall()
    return [_identity_decision_from_row(row) for row in rows]


def _queue_item_from_row(row: sqlite3.Row) -> ReviewQueueItem:
    metadata = _load_json_object(row["metadata_json"])
    if row["queue_type"] == "publication_candidate_review" and "identity_status" in row.keys():
        metadata.update(
            {
                "identity_status": row["identity_status"],
                "cannabinoid_focus": row["cannabinoid_focus"],
                "full_text_review_priority": row["full_text_review_priority"],
                "legacy_match_type": row["legacy_match_type"],
                "legacy_match_confidence": row["legacy_match_confidence"],
                "review_reasons": _load_json_array(row["review_reasons_json"]),
            }
        )
    return ReviewQueueItem(
        review_item_id=row["review_item_id"],
        queue_type=row["queue_type"],
        status=STATUS_ADAPTER.validate_python(row["status"]),
        priority_tier=row["priority_tier"],
        priority_score=row["priority_score"],
        assignee=row["assignee"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        metadata=metadata,
        publication=_publication_summary_from_row(row),
    )


def _load_json_array(value: str | None) -> list[Any]:
    if not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return loaded


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


def _identity_decision_from_row(row: sqlite3.Row) -> IdentityReviewDecision:
    return IdentityReviewDecision(
        review_decision_id=row["review_decision_id"],
        review_item_id=row["review_item_id"],
        document_id=row["document_id"],
        decision_type=row["decision_type"],
        reviewer=row["reviewer"],
        decision=row["decision"],
        reviewed_pmid=row["reviewed_pmid"],
        reviewed_pmcid=row["reviewed_pmcid"],
        reviewed_doi=row["reviewed_doi"],
        reviewed_canonical_url=row["reviewed_canonical_url"],
        rationale=row["rationale"],
        original_identity_signals=_load_json_object(row["original_identity_signals_json"]),
        created_at=row["created_at"],
        provenance=_load_json_object(row["provenance_json"]),
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


def _decision_provenance(provenance: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(provenance)
    merged.setdefault("source", "marygenai.review")
    merged.setdefault("software_version", __version__)
    merged.setdefault("decision_schema_version", "identity_review_decision.v1")
    return merged


def _identity_decision_target_status(decision: str) -> ReviewItemStatus | None:
    if decision in {"confirmed_identity", "corrected_identity"}:
        return "resolved"
    if decision == "not_same_publication":
        return "dismissed"
    return None


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
