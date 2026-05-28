from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from marygenai.persistence.sqlite import connect_sqlite
from marygenai.pubmed_discovery.legacy import load_legacy_index_from_sqlite
from marygenai.pubmed_discovery.models import default_pubmed_window
from marygenai.pubmed_discovery.pipeline import (
    candidate_from_pubmed_record,
    persist_pubmed_candidates,
    write_discovery_outputs,
)
from marygenai.pubmed_discovery.pubmed import PubMedRecord
from marygenai.review.repository import (
    get_publication_candidate_provenance,
    list_open_review_items,
    list_publication_candidate_discoveries,
)
from marygenai.review_api import create_app
from marygenai.schemas import RunManifest
from marygenai.storage import LocalStorage
from tests.test_review_repository import create_review_database


def make_pubmed_record(
    *,
    pmid: str,
    title: str = "Cannabidiol for chronic pain: a randomized placebo-controlled trial.",
    doi: str | None = "10.1000/example",
    publication_date: str = "2026-02-01",
    publication_types: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    chemicals: list[str] | None = None,
) -> PubMedRecord:
    return PubMedRecord(
        pmid=pmid,
        doi=doi,
        pmcid=None,
        title=title,
        abstract="Humans received cannabidiol in a double-blind placebo study.",
        journal="Example Journal",
        publication_date=publication_date,
        publication_status="ppublish",
        publication_types=publication_types or ["Randomized Controlled Trial"],
        mesh_terms=mesh_terms or ["Humans", "Pain"],
        authors=["Jane Smith"],
        languages=["eng"],
        chemicals=chemicals if chemicals is not None else ["Cannabidiol"],
        keywords=[],
        article_ids={"pubmed": pmid},
        provenance={"source": "pubmed"},
    )


def test_default_pubmed_window_overlaps_legacy_boundary() -> None:
    window = default_pubmed_window(
        legacy_max_publication_year=2024,
        today=date(2026, 5, 18),
        overlap_years=1,
    )

    assert window.mindate == "2023/01/01"
    assert window.maxdate == "2026/05/18"
    assert window.legacy_max_publication_year == 2024


def test_candidate_classification_against_sqlite_legacy_index(tmp_path: Path) -> None:
    database_path = create_review_database(tmp_path)
    with connect_sqlite(database_path) as connection:
        connection.row_factory = None
    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        index = load_legacy_index_from_sqlite(connection)

    window = default_pubmed_window(
        legacy_max_publication_year=index.max_publication_year,
        today=date(2026, 5, 18),
    )
    exact = candidate_from_pubmed_record(
        make_pubmed_record(pmid="35319936", title="Cannabis Study", publication_date="2024-01-01"),
        index=index,
        query_names=["strong_evidence_all"],
        run_id="20260518T120000Z",
        fetched_at="2026-05-18T12:00:00+00:00",
        window=window,
    )
    new = candidate_from_pubmed_record(
        make_pubmed_record(pmid="99999999"),
        index=index,
        query_names=["strong_evidence_all"],
        run_id="20260518T120000Z",
        fetched_at="2026-05-18T12:00:00+00:00",
        window=window,
    )

    assert exact.identity_status == "in_legacy_exact"
    assert exact.legacy_document_ids == ["publication:pmid:35319936"]
    assert new.identity_status == "new_candidate"
    assert new.cannabinoid_focus == "direct_title_or_indexed"
    assert new.priority_tier == "direct_title_or_indexed"


def test_persist_pubmed_candidates_creates_review_queue_and_provenance(
    tmp_path: Path,
) -> None:
    database_path = create_review_database(tmp_path)
    data_dir = database_path.parent.parent
    storage = LocalStorage(data_dir)
    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        index = load_legacy_index_from_sqlite(connection)

    run_id = "20260518T120000Z"
    fetched_at = "2026-05-18T12:00:00+00:00"
    window = default_pubmed_window(
        legacy_max_publication_year=index.max_publication_year,
        today=date(2026, 5, 18),
    )
    candidates = [
        candidate_from_pubmed_record(
            make_pubmed_record(
                pmid="35319936",
                title="Cannabis Study",
                publication_date="2024-01-01",
            ),
            index=index,
            query_names=["strong_evidence_all"],
            run_id=run_id,
            fetched_at=fetched_at,
            window=window,
        ),
        candidate_from_pubmed_record(
            make_pubmed_record(pmid="99999999"),
            index=index,
            query_names=["strong_evidence_all"],
            run_id=run_id,
            fetched_at=fetched_at,
            window=window,
        ),
    ]
    paths = write_discovery_outputs(
        storage=storage,
        run_id=run_id,
        source_records=[],
        candidates=candidates,
        review_items=[],
        window=window,
        fetched_at=fetched_at,
        query_count=1,
    )
    manifest = RunManifest(
        run_id=run_id,
        job_type="pubmed_discovery",
        source="pubmed",
        started_at=datetime(2026, 5, 18, 12, tzinfo=UTC),
        completed_at=datetime(2026, 5, 18, 12, 1, tzinfo=UTC),
        status="succeeded",
        software_version="0.1.0",
        input_artifacts=[],
        output_artifacts=[
            {
                "path": str(paths["publication_candidates"]),
                "record_count": len(candidates),
                "sha256": "test",
            }
        ],
        counts={"publication_candidates": len(candidates)},
    )
    storage.write_json(
        Path("manifests/runs") / f"{run_id}_pubmed_discovery_manifest.json",
        manifest,
    )

    result = persist_pubmed_candidates(
        storage=storage,
        database_path=database_path,
        run_id=run_id,
    )

    assert result["publication_candidates"] == 1
    assert result["review_items"] == 1
    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        queue_items = list_open_review_items(
            connection,
            queue_type="publication_candidate_review",
        )
        discoveries = list_publication_candidate_discoveries(connection)
        provenance = get_publication_candidate_provenance(
            connection,
            document_id="publication:pubmed:99999999",
        )
        filtered_items = list_open_review_items(
            connection,
            queue_type="publication_candidate_review",
            identity_status="new_candidate",
            priority_tier="direct_title_or_indexed",
        )
        connection.execute(
            """
            UPDATE review_item
            SET status = 'in_review'
            WHERE review_item_id = ?
            """,
            (queue_items[0].review_item_id,),
        )

    assert len(queue_items) == 1
    assert queue_items[0].publication.review_state == "needs_review"
    assert queue_items[0].metadata["identity_status"] == "new_candidate"
    assert queue_items[0].metadata["cannabinoid_focus"] == "direct_title_or_indexed"
    assert discoveries[0].document_id == "publication:pubmed:99999999"
    assert provenance.identity_status == "new_candidate"
    assert provenance.provenance["method"] == "legacy_anchored_pubmed_discovery"

    client = TestClient(create_app(database_path))
    response = client.get(
        "/review/queues/publication_candidate_review/items"
        "?status=in_review&identity_status=new_candidate&priority_tier=direct_title_or_indexed"
    )

    assert [item.review_item_id for item in filtered_items] == [queue_items[0].review_item_id]
    assert response.status_code == 200
    assert response.json()[0]["metadata"]["identity_status"] == "new_candidate"
    assert response.json()[0]["status"] == "in_review"
