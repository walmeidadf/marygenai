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
