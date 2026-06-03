from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marygenai.access_enrichment.pipeline import (
    audit_access_artifacts,
    invalid_full_text_payload_error,
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


class FakeHtmlFromXmlPmcClient(FakePmcClient):
    def fetch_nxml(self, pmcid: str) -> bytes:
        return f"<!doctype html><html><body>{pmcid}</body></html>".encode()


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


class FakeHtmlFromXmlAccessClients(FakeAccessClients):
    def __init__(self) -> None:
        self.pmc = FakeHtmlFromXmlPmcClient()
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


def insert_access_enrichment_artifact(
    connection: Any, *, document_id: str, run_id: str = "20260520T120000Z"
) -> None:
    connection.execute(
        """
        INSERT INTO access_enrichment_artifact (
            artifact_id, document_id, source, artifact_type, access_class, url, license,
            payload_path, payload_sha256, payload_size_bytes, raw_payload_json, errors_json,
            provenance_json, run_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"test-artifact:{document_id}",
            document_id,
            "europe_pmc",
            "europe_pmc_metadata",
            "open",
            "https://example.org/full-text",
            "cc-by",
            None,
            None,
            None,
            "{}",
            "[]",
            "{}",
            run_id,
            "2026-05-20T13:00:00+00:00",
        ),
    )


def insert_full_text_artifact(
    connection: Any,
    *,
    document_id: str,
    artifact_type: str,
    payload_path: Path,
    errors_json: str = "[]",
) -> None:
    connection.execute(
        """
        INSERT INTO access_enrichment_artifact (
            artifact_id, document_id, source, artifact_type, access_class, url, license,
            payload_path, payload_sha256, payload_size_bytes, raw_payload_json, errors_json,
            provenance_json, run_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"test-artifact:{document_id}:{artifact_type}",
            document_id,
            "pmc",
            artifact_type,
            "open_access_xml",
            "https://example.org/full-text",
            "cc-by",
            str(payload_path),
            "sha",
            payload_path.stat().st_size,
            "{}",
            errors_json,
            "{}",
            "20260520T120000Z",
            "2026-05-20T13:00:00+00:00",
        ),
    )


def test_invalid_full_text_payload_detects_recaptcha_and_html_xml() -> None:
    assert (
        invalid_full_text_payload_error(
            b"<!doctype html><base href='https://www.google.com/recaptcha/challengepage/'>"
            b"<script>window['ppConfig'] = {productName: 'RecaptchaChallengePageUi'}</script>",
            artifact_type="pmc_nxml",
        )
        == "pmc_nxml:blocked_recaptcha_or_javascript_payload"
    )
    assert (
        invalid_full_text_payload_error(
            b"<!doctype html><html><body>Not XML</body></html>",
            artifact_type="pmc_nxml",
        )
        == "pmc_nxml:expected_xml_received_html"
    )
    assert (
        invalid_full_text_payload_error(
            b"<article><body><p>Valid article XML.</p></body></article>",
            artifact_type="pmc_nxml",
        )
        is None
    )


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


def test_select_access_enrichment_candidates_skips_enriched_by_default(
    tmp_path: Path,
) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        insert_access_enrichment_artifact(
            connection, document_id="publication:pubmed:99999991"
        )
        selected = select_access_enrichment_candidates(connection, limit=10)

    assert selected == []


def test_select_access_enrichment_candidates_can_refresh_existing(tmp_path: Path) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        insert_access_enrichment_artifact(
            connection, document_id="publication:pubmed:99999991"
        )
        selected = select_access_enrichment_candidates(
            connection, limit=10, skip_enriched=False
        )

    assert [candidate.document_id for candidate in selected] == ["publication:pubmed:99999991"]


def test_select_access_enrichment_candidates_composes_filters_with_incremental_skip(
    tmp_path: Path,
) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)

    with connect_sqlite(database_path) as connection:
        connection.row_factory = __import__("sqlite3").Row
        baseline = select_access_enrichment_candidates(connection, limit=10)
        assert len(baseline) == 1
        candidate = baseline[0]
        insert_access_enrichment_artifact(connection, document_id=candidate.document_id)

        selected = select_access_enrichment_candidates(
            connection,
            limit=10,
            identity_statuses=[candidate.identity_status],
            cannabinoid_focuses=[candidate.cannabinoid_focus],
            full_text_priorities=[candidate.full_text_review_priority],
            study_designs=[candidate.study_design or ""],
        )
        selected_with_refresh = select_access_enrichment_candidates(
            connection,
            limit=10,
            identity_statuses=[candidate.identity_status],
            cannabinoid_focuses=[candidate.cannabinoid_focus],
            full_text_priorities=[candidate.full_text_review_priority],
            study_designs=[candidate.study_design or ""],
            skip_enriched=False,
        )

    assert selected == []
    assert [candidate.document_id for candidate in selected_with_refresh] == [
        "publication:pubmed:99999991"
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


def test_run_access_enrichment_reclassifies_xml_endpoint_html_as_pmc_html(
    tmp_path: Path,
) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)
    data_dir = database_path.parent.parent

    result = run_access_enrichment(
        storage=LocalStorage(data_dir),
        database_path=database_path,
        run_id="20260520T140000Z",
        limit=10,
        clients=FakeHtmlFromXmlAccessClients(),
        sleep_seconds=0,
    )

    records_path = Path(result.output_paths["records"])
    record_text = records_path.read_text(encoding="utf-8")
    assert '"artifact_type": "pmc_html"' in record_text
    assert '"artifact_type": "pmc_nxml"' not in record_text


def test_audit_access_artifacts_writes_artifact_and_document_quality(
    tmp_path: Path,
) -> None:
    database_path = create_pubmed_candidate_database(tmp_path)
    data_dir = database_path.parent.parent
    invalid_payload_path = data_dir / "raw" / "pmc" / "xml" / "recaptcha.nxml"
    invalid_payload_path.parent.mkdir(parents=True, exist_ok=True)
    invalid_payload_path.write_bytes(
        b"<!doctype html><base href='https://www.google.com/recaptcha/challengepage/'>"
        b"<script>window['ppConfig'] = {productName: 'RecaptchaChallengePageUi'}</script>"
    )
    with connect_sqlite(database_path) as connection:
        insert_full_text_artifact(
            connection,
            document_id="publication:pubmed:99999991",
            artifact_type="pmc_nxml",
            payload_path=invalid_payload_path,
        )
        before_reviewed_count = connection.execute(
            "SELECT COUNT(*) FROM document WHERE review_state != 'needs_review'"
        ).fetchone()[0]

    summary = audit_access_artifacts(
        storage=LocalStorage(data_dir),
        database_path=database_path,
        run_id="20260603T120000Z",
    )

    artifact_records_path = Path(summary["artifact_records_path"])
    document_records_path = Path(summary["document_records_path"])
    artifact_text = artifact_records_path.read_text(encoding="utf-8")
    document_text = document_records_path.read_text(encoding="utf-8")
    assert summary["artifact_count"] == 1
    assert summary["document_count"] == 1
    assert summary["payload_quality_status_counts"] == {"invalid_payload": 1}
    assert summary["document_enrichment_status_counts"] == {"needs_reenrichment": 1}
    assert "blocked_recaptcha_or_javascript_payload" in artifact_text
    assert '"needs_reenrichment": true' in document_text

    with connect_sqlite(database_path) as connection:
        after_reviewed_count = connection.execute(
            "SELECT COUNT(*) FROM document WHERE review_state != 'needs_review'"
        ).fetchone()[0]

    assert after_reviewed_count == before_reviewed_count
