from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from marygenai.initial_load.persist import persist_initial_load, review_item_id
from marygenai.initial_load.pipeline import run_initial_load
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.review.models import IdentityReviewDecisionCreate, ReviewItemStatusUpdate
from marygenai.review.repository import (
    IdentityDecisionNotApplicableError,
    IdentityDecisionNotFoundError,
    ReviewDatabaseNotInitializedError,
    apply_latest_identity_review_decision,
    connect_initialized_review_database,
    create_identity_review_decision,
    get_publication_detail,
    list_identity_review_decisions_for_item,
    list_identity_review_decisions_for_publication,
    list_open_review_items,
    list_review_items,
    list_review_queues,
    update_review_item_status,
)
from marygenai.storage import LocalStorage
from tests.test_sqlite_persistence import create_identity_review_legacy_csvs


def create_review_database(tmp_path: Path) -> Path:
    legacy_dir = tmp_path / "legacy"
    data_dir = tmp_path / "data"
    create_identity_review_legacy_csvs(legacy_dir)
    run_initial_load(
        legacy_dir=legacy_dir,
        storage=LocalStorage(data_dir),
        run_id="20260515T120000Z",
    )
    persist_initial_load(storage=LocalStorage(data_dir))
    return sqlite_database_path(data_dir)


def test_list_open_review_items_orders_by_priority(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    lower_priority_item_id = review_item_id(
        "legacy_identity_review",
        "publication:pmid:35319936",
    )
    with connect_sqlite(database_path) as connection:
        connection.execute(
            """
            INSERT INTO review_item (
                review_item_id, queue_type, document_id, priority_tier, priority_score,
                assignee, status, batch_run_id, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lower_priority_item_id,
                "legacy_identity_review",
                "publication:pmid:35319936",
                "manual_test_low_priority",
                10.0,
                None,
                "open",
                "20260515T120000Z",
                "{}",
                "2026-05-15T12:00:00+00:00",
                "2026-05-15T12:00:00+00:00",
            ),
        )

        items = list_open_review_items(connection, queue_type="legacy_identity_review")

    assert [item.priority_score for item in items] == [5080.0, 10.0]
    assert items[0].publication.primary_title == "Cannabinoid Trial Without Stable Identifier"
    assert items[1].publication.document_id == "publication:pmid:35319936"


def test_list_review_items_filters_by_workflow_status(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    lower_priority_item_id = review_item_id(
        "legacy_identity_review",
        "publication:pmid:35319936",
    )
    with connect_sqlite(database_path) as connection:
        open_item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        connection.execute(
            """
            INSERT INTO review_item (
                review_item_id, queue_type, document_id, priority_tier, priority_score,
                assignee, status, batch_run_id, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lower_priority_item_id,
                "legacy_identity_review",
                "publication:pmid:35319936",
                "manual_test_low_priority",
                10.0,
                None,
                "resolved",
                "20260515T120000Z",
                "{}",
                "2026-05-15T12:00:00+00:00",
                "2026-05-15T12:00:00+00:00",
            ),
        )

        open_items = list_review_items(
            connection,
            queue_type="legacy_identity_review",
            status="open",
        )
        resolved_items = list_review_items(
            connection,
            queue_type="legacy_identity_review",
            status="resolved",
        )
        all_items = list_review_items(
            connection,
            queue_type="legacy_identity_review",
            status="all",
        )

    assert [item.review_item_id for item in open_items] == [open_item.review_item_id]
    assert [item.review_item_id for item in resolved_items] == [lower_priority_item_id]
    assert [item.status for item in all_items] == ["open", "resolved"]


def test_get_publication_detail_includes_identities_and_ontology_links(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        detail = get_publication_detail(connection, document_id="publication:pmid:35319936")

    assert detail.publication.primary_title == "Cannabis Study"
    assert {identity.identifier_type for identity in detail.identities} >= {
        "legacy_id",
        "pmid",
        "canonical_url",
        "normalized_title",
    }
    assert {link.entity_type for link in detail.ontology_links} == {
        "cannabinoid",
        "medical_condition",
        "organ_system",
        "terpene",
    }
    assert detail.legacy_reference.reference_values["Tipo de Estudo"] == "Metanálise"


def test_update_review_item_status_records_note_in_metadata(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        result = update_review_item_status(
            connection,
            update=ReviewItemStatusUpdate(
                review_item_id=item.review_item_id,
                status="in_review",
                note="Checking legacy identity before resolution.",
            ),
        )
        updated = connection.execute(
            "SELECT status, metadata_json FROM review_item WHERE review_item_id = ?",
            (item.review_item_id,),
        ).fetchone()

    assert result.previous_status == "open"
    assert result.status == "in_review"
    assert result.note == "Checking legacy identity before resolution."
    assert updated is not None
    assert updated[0] == "in_review"
    assert result.metadata["last_status_note"] == "Checking legacy identity before resolution."
    assert result.metadata["status_history"][0]["from_status"] == "open"


def test_update_review_item_status_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ReviewItemStatusUpdate(
            review_item_id="review_item:missing",
            status="closed",
        )


def test_create_and_list_identity_review_decision(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        result = create_identity_review_decision(
            connection,
            decision=IdentityReviewDecisionCreate(
                review_item_id=item.review_item_id,
                document_id=item.publication.document_id,
                reviewer="reviewer@example.org",
                decision="corrected_identity",
                reviewed_pmid="12345678",
                reviewed_pmcid="PMC123456",
                reviewed_doi="10.1000/example",
                reviewed_canonical_url="https://example.org/corrected",
                rationale="Matched by title and external source.",
                original_identity_signals={
                    "publication": item.publication.model_dump(mode="json"),
                },
                provenance={"source": "test"},
            ),
        )
        item_decisions = list_identity_review_decisions_for_item(
            connection,
            review_item_id=item.review_item_id,
        )
        publication_decisions = list_identity_review_decisions_for_publication(
            connection,
            document_id=item.publication.document_id,
        )

    assert result.review_decision_id.startswith("review_decision:")
    assert result.decision_type == "legacy_identity"
    assert result.decision == "corrected_identity"
    assert result.reviewed_pmid == "12345678"
    assert result.provenance["source"] == "test"
    assert result.provenance["decision_schema_version"] == "identity_review_decision.v1"
    assert item_decisions == [result]
    assert publication_decisions == [result]


def test_apply_latest_confirmed_identity_decision_resolves_review_item(
    tmp_path: Path,
) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        decision = create_identity_review_decision(
            connection,
            decision=IdentityReviewDecisionCreate(
                review_item_id=item.review_item_id,
                document_id=item.publication.document_id,
                reviewer="reviewer@example.org",
                decision="confirmed_identity",
                reviewed_canonical_url=item.publication.canonical_url,
                rationale="Legacy title and URL identify this publication.",
                provenance={"source": "test"},
            ),
        )
        result = apply_latest_identity_review_decision(
            connection,
            review_item_id=item.review_item_id,
            source="test",
        )
        updated = connection.execute(
            "SELECT status, metadata_json FROM review_item WHERE review_item_id = ?",
            (item.review_item_id,),
        ).fetchone()

    assert result.review_decision_id == decision.review_decision_id
    assert result.previous_status == "open"
    assert result.status == "resolved"
    assert updated is not None
    assert updated[0] == "resolved"
    application = result.metadata["last_identity_decision_application"]
    assert application["review_decision_id"] == decision.review_decision_id
    assert application["decision"] == "confirmed_identity"
    assert application["applied_status"] == "resolved"
    assert result.metadata["status_history"][0]["application"]["source"] == "test"


def test_apply_latest_not_same_publication_decision_dismisses_review_item(
    tmp_path: Path,
) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        create_identity_review_decision(
            connection,
            decision=IdentityReviewDecisionCreate(
                review_item_id=item.review_item_id,
                document_id=item.publication.document_id,
                reviewer="reviewer@example.org",
                decision="not_same_publication",
                rationale="The legacy URL points to a different publication.",
            ),
        )
        result = apply_latest_identity_review_decision(
            connection,
            review_item_id=item.review_item_id,
        )

    assert result.status == "dismissed"


def test_apply_latest_unresolved_identity_decision_does_not_close_item(
    tmp_path: Path,
) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        create_identity_review_decision(
            connection,
            decision=IdentityReviewDecisionCreate(
                review_item_id=item.review_item_id,
                document_id=item.publication.document_id,
                reviewer="reviewer@example.org",
                decision="unresolved",
                rationale="More source work is required.",
            ),
        )
        with pytest.raises(IdentityDecisionNotApplicableError):
            apply_latest_identity_review_decision(
                connection,
                review_item_id=item.review_item_id,
            )


def test_apply_latest_identity_decision_requires_saved_decision(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
        with pytest.raises(IdentityDecisionNotFoundError):
            apply_latest_identity_review_decision(
                connection,
                review_item_id=item.review_item_id,
            )


def test_empty_initialized_database_returns_empty_review_results(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)

    with connect_sqlite(database_path) as connection:
        initialize_schema(connection)
        assert list_review_queues(connection) == []
        assert list_open_review_items(connection, queue_type="legacy_identity_review") == []


def test_missing_database_reports_not_initialized(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)

    with pytest.raises(ReviewDatabaseNotInitializedError):
        with connect_initialized_review_database(database_path):
            pass


def test_initialized_connection_can_opt_into_cross_thread_use(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)

    with connect_initialized_review_database(
        database_path,
        check_same_thread=False,
    ) as connection:
        with ThreadPoolExecutor(max_workers=1) as executor:
            summaries = executor.submit(list_review_queues, connection).result()

    assert summaries[0].queue_type == "legacy_identity_review"
