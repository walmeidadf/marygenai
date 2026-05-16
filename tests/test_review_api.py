from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from marygenai.initial_load.persist import review_item_id
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.review.repository import list_open_review_items
from marygenai.review_api import create_app
from tests.test_review_repository import create_review_database


def create_review_api_client(database_path: Path) -> TestClient:
    return TestClient(create_app(database_path))


def test_healthcheck_reports_database_state(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    client = create_review_api_client(database_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database_path": str(database_path),
        "database_initialized": True,
    }


def test_review_ui_index_is_served(tmp_path: Path) -> None:
    client = create_review_api_client(create_review_database(tmp_path))

    response = client.get("/ui")

    assert response.status_code == 200
    assert "MaryGenAI Review" in response.text
    assert "/ui/static/app.js" in response.text


def test_review_ui_static_assets_are_served(tmp_path: Path) -> None:
    client = create_review_api_client(create_review_database(tmp_path))

    response = client.get("/ui/static/app.js")

    assert response.status_code == 200
    assert 'const QUEUE_TYPE = "legacy_identity_review";' in response.text
    assert "/review/queues" in response.text
    assert "/identity-decisions" in response.text
    assert "/identity-decisions/apply" in response.text
    assert "Apply decision to workflow" in response.text


def test_list_review_queues(tmp_path: Path) -> None:
    client = create_review_api_client(create_review_database(tmp_path))

    response = client.get("/review/queues")

    assert response.status_code == 200
    assert response.json() == [
        {
            "queue_type": "legacy_identity_review",
            "total_items": 1,
            "open_items": 1,
            "in_review_items": 0,
            "resolved_items": 0,
            "dismissed_items": 0,
        }
    ]


def test_list_open_items_ordered_by_priority(tmp_path: Path) -> None:
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
    client = create_review_api_client(database_path)

    response = client.get("/review/queues/legacy_identity_review/items?status=open&limit=20")

    assert response.status_code == 200
    payload = response.json()
    assert [item["priority_score"] for item in payload] == [80.0, 10.0]
    assert payload[0]["publication"]["primary_title"] == (
        "Cannabinoid Trial Without Stable Identifier"
    )


def test_get_review_item_detail(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
    client = create_review_api_client(database_path)

    response = client.get(f"/review/items/{item.review_item_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["publication"]["document_id"] == item.publication.document_id
    assert payload["legacy_reference"]["legacy_study_id"] == "2"
    assert payload["review_items"][0]["review_item_id"] == item.review_item_id


def test_get_publication_detail_by_document_id(tmp_path: Path) -> None:
    client = create_review_api_client(create_review_database(tmp_path))

    response = client.get("/publications/publication:pmid:35319936")

    assert response.status_code == 200
    payload = response.json()
    assert payload["publication"]["primary_title"] == "Cannabis Study"
    assert {identity["identifier_type"] for identity in payload["identities"]} >= {
        "legacy_id",
        "pmid",
        "canonical_url",
        "normalized_title",
    }


def test_update_review_item_status(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
    client = create_review_api_client(database_path)

    response = client.patch(
        f"/review/items/{item.review_item_id}/status",
        json={"status": "in_review", "note": "Checking identity in the API."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["previous_status"] == "open"
    assert payload["status"] == "in_review"
    assert payload["note"] == "Checking identity in the API."
    assert payload["metadata"]["last_status_note"] == "Checking identity in the API."


def test_create_and_list_identity_review_decision(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
    client = create_review_api_client(database_path)

    response = client.post(
        f"/review/items/{item.review_item_id}/identity-decisions",
        json={
            "review_item_id": item.review_item_id,
            "document_id": item.publication.document_id,
            "reviewer": "reviewer@example.org",
            "decision": "confirmed_identity",
            "reviewed_pmid": None,
            "reviewed_pmcid": None,
            "reviewed_doi": None,
            "reviewed_canonical_url": "https://example.org/cannabinoid-trial",
            "rationale": "Legacy URL and title are sufficient for this item.",
            "original_identity_signals": {
                "publication": item.publication.model_dump(mode="json"),
            },
            "provenance": {"source": "api_test"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "confirmed_identity"
    assert payload["reviewer"] == "reviewer@example.org"
    assert payload["provenance"]["source"] == "api_test"

    item_response = client.get(f"/review/items/{item.review_item_id}/identity-decisions")
    publication_response = client.get(
        f"/publications/{item.publication.document_id}/identity-decisions"
    )

    assert item_response.status_code == 200
    assert publication_response.status_code == 200
    assert item_response.json() == [payload]
    assert publication_response.json() == [payload]


def test_apply_identity_review_decision_updates_workflow_status(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
    client = create_review_api_client(database_path)

    create_response = client.post(
        f"/review/items/{item.review_item_id}/identity-decisions",
        json={
            "review_item_id": item.review_item_id,
            "document_id": item.publication.document_id,
            "reviewer": "reviewer@example.org",
            "decision": "corrected_identity",
            "reviewed_pmid": "12345678",
            "reviewed_pmcid": None,
            "reviewed_doi": None,
            "reviewed_canonical_url": None,
            "rationale": "External lookup corrected the publication identity.",
            "original_identity_signals": {},
            "provenance": {"source": "api_test"},
        },
    )
    apply_response = client.post(
        f"/review/items/{item.review_item_id}/identity-decisions/apply",
    )

    assert create_response.status_code == 200
    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert payload["review_decision_id"] == create_response.json()["review_decision_id"]
    assert payload["decision"] == "corrected_identity"
    assert payload["previous_status"] == "open"
    assert payload["status"] == "resolved"
    assert payload["metadata"]["last_identity_decision_application"]["source"] == (
        "marygenai.review_api"
    )

    queue_response = client.get("/review/queues")
    assert queue_response.json()[0]["open_items"] == 0
    assert queue_response.json()[0]["resolved_items"] == 1


def test_apply_unresolved_identity_review_decision_returns_conflict(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        item = list_open_review_items(connection, queue_type="legacy_identity_review")[0]
    client = create_review_api_client(database_path)

    client.post(
        f"/review/items/{item.review_item_id}/identity-decisions",
        json={
            "review_item_id": item.review_item_id,
            "document_id": item.publication.document_id,
            "reviewer": "reviewer@example.org",
            "decision": "unresolved",
            "reviewed_pmid": None,
            "reviewed_pmcid": None,
            "reviewed_doi": None,
            "reviewed_canonical_url": None,
            "rationale": "Needs more review.",
            "original_identity_signals": {},
            "provenance": {},
        },
    )

    response = client.post(f"/review/items/{item.review_item_id}/identity-decisions/apply")

    assert response.status_code == 409
    assert "unresolved" in response.json()["detail"]


def test_missing_database_returns_clear_error(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)
    client = create_review_api_client(database_path)

    response = client.get("/review/queues")

    assert response.status_code == 503
    assert response.json()["detail"] == (
        f"SQLite database is not initialized at {database_path}. Run `marygenai db init` first."
    )


def test_empty_initialized_database_returns_empty_results(tmp_path: Path) -> None:
    database_path = sqlite_database_path(tmp_path)
    with connect_sqlite(database_path) as connection:
        initialize_schema(connection)
    client = create_review_api_client(database_path)

    queues_response = client.get("/review/queues")
    items_response = client.get("/review/queues/legacy_identity_review/items")

    assert queues_response.status_code == 200
    assert queues_response.json() == []
    assert items_response.status_code == 200
    assert items_response.json() == []
