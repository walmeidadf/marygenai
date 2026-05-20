from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marygenai.access_enrichment.pipeline import (
    run_access_enrichment,
    select_access_enrichment_candidates,
)
from marygenai.persistence.sqlite import connect_sqlite
from marygenai.pubmed_discovery.legacy import load_legacy_index_from_sqlite
from marygenai.pubmed_discovery.models import default_pubmed_window
from marygenai.pubmed_discovery.pipeline import (
    candidate_from_pubmed_record,
    persist_pubmed_candidates,
    write_discovery_outputs,
)
from marygenai.schemas import RunManifest
from marygenai.storage import LocalStorage
from tests.test_pubmed_candidate_enrichment import make_pubmed_record
from tests.test_review_repository import create_review_database


class FakePmcClient:
    def fetch_nxml(self, pmcid: str) -> bytes:
        return f"<article><article-id>{pmcid}</article-id></article>".encode()

    def fetch_html(self, pmcid: str) -> bytes:
        return f"<html><body>{pmcid}</body></html>".encode()


class FakeEuropePmcClient:
    def search_by_pmid_or_doi(self, *, pmid: str | None, doi: str | None) -> dict[str, Any]:
        return {
            "resultList": {
                "result": [
                    {
                        "id": pmid or "10.1000/example",
                        "source": "MED",
                        "pmid": pmid,
                        "doi": doi,
                        "hasFullText": "Y",
                        "isOpenAccess": "Y",
                        "license": "cc-by",
                        "fullTextUrlList": {
                            "fullTextUrl": [
                                {
                                    "url": "https://example.org/article.xml",
                                    "availabilityCode": "OA",
                                    "documentStyle": "html",
                                },
                                {
                                    "url": "https://example.org/article.pdf",
                                    "availabilityCode": "OA",
                                    "documentStyle": "pdf",
                                },
                            ]
                        },
                    }
                ]
            }
        }

    def fetch_full_text_xml(self, *, source: str, identifier: str) -> bytes:
        return f"<full-text source='{source}' id='{identifier}' />".encode()


class FakeUnpaywallClient:
    def get_by_doi(self, doi: str) -> dict[str, Any]:
        return {
            "doi": doi,
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_landing_page": "https://example.org/landing",
                "url_for_pdf": "https://example.org/unpaywall.pdf",
                "license": "cc-by",
            },
        }


class FakeAccessClients:
    def __init__(self) -> None:
        self.pmc = FakePmcClient()
        self.europe_pmc = FakeEuropePmcClient()
        self.unpaywall = FakeUnpaywallClient()


def create_pubmed_candidate_database(tmp_path: Path) -> Path:
    database_path = create_review_database(tmp_path)
    data_dir = database_path.parent.parent
    storage = LocalStorage(data_dir)
    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        index = load_legacy_index_from_sqlite(connection)

    run_id = "20260520T120000Z"
    fetched_at = "2026-05-20T12:00:00+00:00"
    window = default_pubmed_window(
        legacy_max_publication_year=index.max_publication_year,
        today=datetime(2026, 5, 20, tzinfo=UTC).date(),
    )
    records = [
        replace(
            make_pubmed_record(
                pmid="99999991",
                doi="10.1000/one",
                publication_types=["Randomized Controlled Trial"],
            ),
            pmcid="PMC99999991",
        ),
        make_pubmed_record(
            pmid="99999992",
            title="Fuzzy Cannabis Study",
            doi="10.1000/two",
            publication_types=["Randomized Controlled Trial"],
        ),
    ]
    candidates = [
        candidate_from_pubmed_record(
            record,
            index=index,
            query_names=["strong_evidence_all"],
            run_id=run_id,
            fetched_at=fetched_at,
            window=window,
        )
        for record in records
    ]
    candidates[1] = candidates[1].model_copy(
        update={"identity_status": "needs_manual_identity_review"}
    )
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
        started_at=datetime(2026, 5, 20, 12, tzinfo=UTC),
        completed_at=datetime(2026, 5, 20, 12, 1, tzinfo=UTC),
        status="succeeded",
        software_version="0.1.0",
        input_artifacts=[],
        output_artifacts=[
            {"path": str(paths["publication_candidates"]), "record_count": 2, "sha256": "test"}
        ],
        counts={"publication_candidates": 2},
    )
    storage.write_json(
        Path("manifests/runs") / f"{run_id}_pubmed_discovery_manifest.json",
        manifest,
    )
    persist_pubmed_candidates(storage=storage, database_path=database_path, run_id=run_id)
    return database_path


def test_select_access_enrichment_candidates_skips_manual_identity_review(tmp_path: Path) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        selected = select_access_enrichment_candidates(connection, limit=10)
        selected_with_manual = select_access_enrichment_candidates(
            connection,
            limit=10,
            include_manual_identity_review=True,
            identity_statuses=["needs_manual_identity_review"],
        )

    assert [candidate.document_id for candidate in selected] == ["publication:pubmed:99999991"]
    assert [candidate.identity_status for candidate in selected_with_manual] == [
        "needs_manual_identity_review"
    ]


def test_run_access_enrichment_writes_snapshots_and_persists_artifacts(tmp_path: Path) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)
    data_dir = database_path.parent.parent

    result = run_access_enrichment(
        storage=LocalStorage(data_dir),
        database_path=database_path,
        run_id="20260520T130000Z",
        limit=10,
        clients=FakeAccessClients(),
        sleep_seconds=0,
    )

    records_path = Path(result.output_paths["records"])
    manifest_path = Path(result.manifest_path)
    assert result.counts["selected_candidates"] == 1
    assert result.counts["access_artifacts"] == 4
    assert records_path.exists()
    assert manifest_path.exists()
    record_text = records_path.read_text(encoding="utf-8")
    assert '"review_state": "needs_review"' in record_text
    assert "candidate_evidence_not_reviewed_knowledge" in record_text

    with connect_sqlite(database_path) as connection:
        artifact_count = connection.execute(
            "SELECT COUNT(*) FROM access_enrichment_artifact"
        ).fetchone()[0]
        reviewed_count = connection.execute(
            "SELECT COUNT(*) FROM document WHERE review_state != 'needs_review'"
        ).fetchone()[0]

    assert artifact_count == 4
    assert reviewed_count == 2
