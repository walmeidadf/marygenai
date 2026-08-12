from __future__ import annotations

import csv
import hashlib
import json
import stat
from collections.abc import AsyncGenerator
from pathlib import Path

import duckdb
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.testclient import TestClient
from typer.testing import CliRunner

from marygenai.mcp_server import create_mcp_server, lambda_runtime
from marygenai.mcp_server.cli import app as mcp_cli_app
from marygenai.mcp_server.http import create_http_app, hash_access_token
from marygenai.mcp_server.lambda_runtime import IndexArtifactConfig, materialize_index
from marygenai.retrieval.identity import (
    build_identity_urls,
    choose_preferred_access_url,
    normalize_identifier,
    project_bibliographic_identities,
)
from marygenai.retrieval.identity_review import export_identity_conflicts
from marygenai.retrieval.index import build_retrieval_index, normalize_match_key
from marygenai.retrieval.models import FilterGroup, SearchFilters, SearchRequest
from marygenai.retrieval.service import RetrievalService
from marygenai.viewer.app import create_app as create_viewer_app


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def candidate(
    document_id: str,
    *,
    condition: str,
    exposure: str,
    population: str,
    run_id: str = "20260710T000000Z",
) -> dict:
    return {
        "classification_id": f"classification:{run_id}:{document_id}",
        "document_id": document_id,
        "classification_run_id": run_id,
        "schema_version": "candidate_study_classification.v3",
        "extractor_name": "marygenai_candidate_classifier",
        "extractor_version": "0.1.0",
        "model_provider": "openai",
        "model_name": "test-model",
        "prompt_version": "candidate_study_classification_prompt.v5",
        "source_text_path": f"data/processed/{document_id}.txt",
        "source_text_sha256": "a" * 64,
        "created_at": "2026-07-10T00:00:00Z",
        "study_design_category": "double_blind_clinical_trial",
        "study_design_subtype": "pilot_study",
        "evidence_context": "human_clinical",
        "medical_conditions": [
            {
                "normalized_label": condition,
                "free_text_label": condition,
                "ontology_entity_id": None,
                "confidence": "high",
                "evidence_text": f"Participants with {condition}",
            }
        ],
        "cannabinoids_or_exposures": [
            {
                "normalized_label": exposure,
                "free_text_label": exposure,
                "ontology_entity_id": None,
                "confidence": "high",
                "evidence_text": f"Intervention was {exposure}",
            }
        ],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {"category": population, "description": population},
        "outcome_domains": ["efficacy", "safety"],
        "overall_direction": "mixed",
        "classification_confidence": "medium",
        "requires_human_review": True,
        "review_state": "needs_review",
        "evidence_spans": [
            {
                "section": "Abstract",
                "text": f"A study of {exposure} in {condition}.",
                "char_start": None,
                "char_end": None,
                "source_text_path": f"data/processed/{document_id}.txt",
            }
        ],
        "supporting_sections": ["Abstract"],
        "missing_or_uncertain_fields": ["overall_direction"],
        "warnings": ["Candidate classification for retrieval only."],
        "provenance": {
            "method": "test",
            "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
            "does_not_mutate_sqlite": True,
        },
    }


@pytest.fixture
def retrieval_index(tmp_path: Path) -> Path:
    records_path = tmp_path / "records.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    confidence_path = tmp_path / "confidence.jsonl"
    grounding_path = tmp_path / "grounding.jsonl"
    report_path = tmp_path / "report.json"
    output_path = tmp_path / "retrieval.duckdb"
    records = [
        candidate(
            "publication:test:1",
            condition="Dravet syndrome",
            exposure="Cannabidiol (CBD)",
            population="pediatric_humans",
        ),
        candidate(
            "publication:test:2",
            condition="Epilepsy",
            exposure="Cannabidiol",
            population="adult_humans",
        ),
        candidate(
            "publication:test:3",
            condition="Obesity",
            exposure="Tetrahydrocannabinol (THC)",
            population="adult_humans",
        ),
    ]
    write_jsonl(records_path, records)
    write_jsonl(
        corpus_path,
        [
            {
                "document_id": record["document_id"],
                "primary_title": f"Title for {record['document_id']}",
                "doi": f"10.1000/{index}",
                "pmid": str(10000 + index),
                "pmcid": None,
                "canonical_url": f"https://doi.org/10.1000/{index}",
                "source_url": f"https://example.test/{index}",
                "publication_year": 2020 + index,
                "source_text_path": record["source_text_path"],
                "trust_level": "source_text_available",
            }
            for index, record in enumerate(records, start=1)
        ],
    )
    write_jsonl(
        confidence_path,
        [
            {
                "document_id": record["document_id"],
                "score": 1.0 - (index * 0.1),
                "band": "high" if index == 1 else "medium",
                "version": "retrieval_confidence.v1",
                "semantics": "Heuristic only.",
            }
            for index, record in enumerate(records)
        ],
    )
    write_jsonl(
        grounding_path,
        [
            {
                "document_id": "publication:test:1",
                "section": "Abstract",
                "text": "A study of CBD in Dravet syndrome.",
                "source_text_path": "data/processed/publication:test:1.txt",
                "evidence_token_count": 7,
                "token_bigram_grounding_score": 0.7,
            }
        ],
    )
    report_path.write_text(
        json.dumps(
            {
                "classification_run_id": "20260710T000000Z",
                "outputs": {
                    "retrieval_confidence_records_path": str(confidence_path),
                    "evidence_spans_requiring_grounding_review_path": str(grounding_path),
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = build_retrieval_index(
        data_dir=tmp_path,
        output_path=output_path,
        records_paths=[records_path],
        corpus_path=corpus_path,
        evaluation_report_paths=[report_path],
    )
    assert manifest.document_count == 3
    assert "The indexed candidate corpus is bounded and may not be representative." in (
        manifest.limitations
    )
    assert all("500-document" not in limitation for limitation in manifest.limitations)
    return output_path


def test_normalize_match_key_consolidates_case_and_trailing_abbreviations() -> None:
    assert normalize_match_key("Cannabidiol (CBD)") == "cannabidiol"
    assert normalize_match_key("cannabidiol") == "cannabidiol"
    assert normalize_match_key("Cannabinoid (unspecified)") == "cannabinoid unspecified"


def test_identity_normalization_and_physician_facing_link_selection() -> None:
    assert normalize_identifier("doi", "10.3389/fneur.2022.818522/full") == (
        "10.3389/fneur.2022.818522",
        "frontiers_full_route_suffix.v1",
    )
    assert normalize_identifier("doi", "10.1000/example/full") == (
        "10.1000/example/full",
        "lowercase_and_trim_punctuation.v1",
    )
    urls = build_identity_urls(
        {
            "canonical_url": "https://publisher.test/article",
            "source_url": "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=GetRecord",
        },
        {"pmid": "12345678", "pmcid": "PMC123456", "doi": "10.1000/example"},
    )
    preferred = choose_preferred_access_url(urls)
    assert preferred is not None
    assert preferred["url_kind"] == "pmc_full_text"
    assert next(row for row in urls if row["url_kind"] == "source")["physician_facing"] is False


def test_identity_projection_preserves_original_conflicts_explicitly(tmp_path: Path) -> None:
    source = tmp_path / "article.nxml"
    source.write_text(
        '<article-meta><article-id pub-id-type="doi">10.1000/source</article-id>'
        "</article-meta>",
        encoding="utf-8",
    )
    document_id = "publication:test:conflict"
    projection = project_bibliographic_identities(
        data_dir=tmp_path,
        corpus={
            document_id: {
                "document_id": document_id,
                "doi": "10.1000/corpus",
                "pmid": None,
                "pmcid": None,
                "canonical_url": "https://publisher.test/article",
                "source_url": None,
            }
        },
        candidates=[{"document_id": document_id, "source_text_path": str(source)}],
    )[document_id]
    assert projection["status"] == "conflict"
    assert projection["doi"] is None
    assert {row["value"] for row in projection["conflicts"][0]["candidate_values"]} == {
        "10.1000/corpus",
        "10.1000/source",
    }
    assert all(row["url_kind"] != "doi" for row in projection["identity_urls"])


def test_export_identity_conflicts_writes_adjudication_csv(tmp_path: Path) -> None:
    index_path = tmp_path / "retrieval.duckdb"
    output_path = tmp_path / "identity_conflicts.csv"
    projected = {
        "pmid": "123",
        "pmcid": None,
        "doi": None,
        "status": "conflict",
        "conflicts": [
            {
                "identifier_type": "doi",
                "candidate_values": [
                    {
                        "value": "10.1000/corpus",
                        "provenance": [
                            {
                                "extraction_method": "corpus_doi",
                                "source_artifact_path": "classification_corpus",
                            }
                        ],
                    },
                    {
                        "value": "10.1000/source",
                        "provenance": [
                            {
                                "extraction_method": "pmc_oai_nxml_article_id",
                                "source_artifact_path": "data/raw/article.xml",
                            }
                        ],
                    },
                ],
            }
        ],
    }
    connection = duckdb.connect(str(index_path))
    try:
        connection.execute("CREATE TABLE index_metadata (key VARCHAR, value VARCHAR)")
        connection.execute("INSERT INTO index_metadata VALUES ('build_id', 'build-test')")
        connection.execute(
            """
            CREATE TABLE documents (
                document_id VARCHAR,
                classification_run_id VARCHAR,
                title VARCHAR,
                publication_year INTEGER,
                source_text_path VARCHAR,
                source_text_sha256 VARCHAR,
                canonical_url VARCHAR,
                source_url VARCHAR,
                corpus_json VARCHAR,
                original_corpus_identity_json VARCHAR,
                projected_identity_json VARCHAR,
                identity_conflict_count INTEGER
            )
            """
        )
        connection.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "publication:test:conflict",
                "run-conflict",
                "Conflicting identity",
                2026,
                "data/processed/article.txt",
                "a" * 64,
                "https://publisher.test/article",
                "https://source.test/article",
                json.dumps(
                    {
                        "source_strategy": "pmc_oai",
                        "raw_payload_path": "data/raw/article.xml",
                    }
                ),
                json.dumps(
                    {
                        "pmid": "123",
                        "pmcid": None,
                        "doi": "10.1000/corpus",
                    }
                ),
                json.dumps(projected),
                1,
            ],
        )
    finally:
        connection.close()

    result = export_identity_conflicts(
        index_path=index_path,
        output_path=output_path,
        classification_run_id="run-conflict",
    )

    with output_path.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert result["document_count"] == 1
    assert result["identifier_conflict_count"] == 1
    assert rows[0]["identifier_type"] == "doi"
    assert rows[0]["candidate_values"] == "10.1000/corpus | 10.1000/source"
    assert rows[0]["decision_status"] == ""
    assert rows[0]["selected_value"] == ""
    assert output_path.with_suffix(".summary.json").exists()


def test_search_supports_aliases_all_filters_pagination_and_trace(
    retrieval_index: Path,
) -> None:
    service = RetrievalService(retrieval_index)
    request = SearchRequest(
        query="Dravet CBD",
        question_type="therapy",
        filters=SearchFilters(
            medical_conditions=FilterGroup(values=["dravet syndrome"], match="all"),
            cannabinoids_or_exposures=FilterGroup(values=["cannabidiol"], match="all"),
            population_categories=FilterGroup(values=["pediatric_humans"]),
            outcome_domains=FilterGroup(values=["efficacy", "safety"], match="all"),
        ),
        unsupported_dimensions=["dose", "comparator"],
        limit=1,
    )
    response = service.search(request)
    assert response.total == 1
    assert response.returned == 1
    assert response.next_cursor is None
    assert response.results[0].document_id == "publication:test:1"
    assert response.results[0].match.not_represented == ["dose", "comparator"]
    assert response.results[0].original_corpus_identity.pmid == "10001"
    assert response.results[0].projected_identity.pmid == "10001"
    assert response.results[0].projected_identity.preferred_access_url is not None
    assert response.search_trace.relaxations == []
    assert response.presentation_contract.result_label == (
        "AI-classified candidate matches"
    )
    assert response.presentation_contract.preferred_access_url_required_for_cited_results
    assert response.presentation_contract.study_detail_tool == "get_study"
    assert response.trust_boundary.medical_advice is False

    page_one = service.search(SearchRequest(limit=2))
    assert page_one.total == 3
    assert page_one.next_cursor
    page_two = service.search(SearchRequest(limit=2, cursor=page_one.next_cursor))
    assert page_two.returned == 1
    assert {item.document_id for item in page_one.results}.isdisjoint(
        {item.document_id for item in page_two.results}
    )


def test_zero_result_contract_does_not_claim_literature_absence(
    retrieval_index: Path,
) -> None:
    response = RetrievalService(retrieval_index).search(
        SearchRequest(query="hypothyroidism")
    )

    assert response.total == 0
    assert response.returned == 0
    assert response.results == []
    assert "current MaryGenAI index" in (
        response.presentation_contract.zero_result_message
    )
    assert "does not establish absence" in (
        response.presentation_contract.zero_result_message
    )
    assert response.presentation_contract.literature_absence_inference_allowed is False


def test_facets_consolidate_aliases_and_detail_preserves_candidate_provenance(
    retrieval_index: Path,
) -> None:
    service = RetrievalService(retrieval_index)
    facets = service.facets(SearchRequest(), top=20)
    cannabidiol = [
        value
        for value in facets.facets["cannabinoids_or_exposures"]
        if value.match_key == "cannabidiol"
    ]
    assert len(cannabidiol) == 1
    assert cannabidiol[0].count == 2

    detail = service.get_study("publication:test:1")
    assert detail.source_text_sha256 == "a" * 64
    assert detail.review_state == "needs_review"
    assert detail.grounding_review["status"] == "requires_review"
    assert detail.grounding_review["flagged_span_count"] == 1
    assert detail.candidate_classification["evidence_spans"]
    assert detail.provenance["prompt_version"] == "candidate_study_classification_prompt.v5"
    assert detail.original_corpus_identity.doi == "10.1000/1"
    assert detail.projected_identity.doi == "10.1000/1"
    assert service.identity_coverage()["identifier_conflicts"] == 0


def test_retrieval_runtime_connection_rejects_writes(retrieval_index: Path) -> None:
    connection = duckdb.connect(str(retrieval_index), read_only=True)
    try:
        with pytest.raises(duckdb.Error):
            connection.execute("CREATE TABLE forbidden_write(value INTEGER)")
    finally:
        connection.close()


def test_streamable_http_requires_header_token_and_rejects_query_tokens(
    retrieval_index: Path,
) -> None:
    token = "mary_test_token_with_sufficient_entropy"
    app = create_http_app(
        retrieval_index,
        bearer_token_sha256=hash_access_token(token),
    )
    with TestClient(app, base_url="http://localhost:8000") as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["trust_level"] == "ai_classified_candidate"

        missing = client.post("/mcp", json={})
        assert missing.status_code == 401
        assert missing.headers["www-authenticate"] == "Bearer"

        query_token = client.post(f"/mcp?key={token}", json={})
        assert query_token.status_code == 400

        initialized = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["serverInfo"]["name"] == (
            "MaryGenAI Candidate Evidence Retrieval"
        )


def test_streamable_http_can_explicitly_allow_pilot_query_key(
    retrieval_index: Path,
) -> None:
    token = "mary_test_token_with_sufficient_entropy"
    app = create_http_app(
        retrieval_index,
        bearer_token_sha256=hash_access_token(token),
        allow_query_token=True,
    )
    with TestClient(app, base_url="http://localhost:8000") as client:
        initialized = client.post(
            f"/mcp?key={token}",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert initialized.status_code == 200

        ambiguous = client.post(
            f"/mcp?key={token}",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert ambiguous.status_code == 400

        alternate_query_field = client.post(f"/mcp?api_key={token}", json={})
        assert alternate_query_field.status_code == 400


def test_generate_access_token_writes_private_file_without_echoing_token(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "pilot-token.json"

    result = CliRunner().invoke(
        mcp_cli_app,
        ["generate-access-token", "--output-path", str(output_path)],
    )

    assert result.exit_code == 0
    record = json.loads(output_path.read_text(encoding="utf-8"))
    command_output = json.loads(result.stdout)
    assert record["token"].startswith("mary_")
    assert record["token"] not in result.stdout
    assert command_output["sha256"] == record["sha256"]
    assert record["sha256"] == hashlib.sha256(record["token"].encode()).hexdigest()
    assert stat.S_IMODE(output_path.stat().st_mode) == 0o600


def test_generate_access_token_refuses_to_overwrite_existing_file(tmp_path: Path) -> None:
    output_path = tmp_path / "pilot-token.json"
    output_path.write_text("preserve", encoding="utf-8")

    result = CliRunner().invoke(
        mcp_cli_app,
        ["generate-access-token", "--output-path", str(output_path)],
    )

    assert result.exit_code != 0
    assert output_path.read_text(encoding="utf-8") == "preserve"


class FakeS3Client:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.downloads = 0

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        assert bucket == "private-index-bucket"
        assert key == "retrieval-indexes/test.duckdb"
        Path(filename).write_bytes(self.content)
        self.downloads += 1


def test_lambda_index_materialization_verifies_hash_and_reuses_warm_copy(
    tmp_path: Path,
) -> None:
    content = b"immutable duckdb snapshot"
    client = FakeS3Client(content)
    config = IndexArtifactConfig(
        bucket="private-index-bucket",
        key="retrieval-indexes/test.duckdb",
        sha256=hashlib.sha256(content).hexdigest(),
        local_path=tmp_path / "retrieval.duckdb",
    )

    assert materialize_index(config, s3_client=client) == config.local_path
    assert materialize_index(config, s3_client=client) == config.local_path
    assert config.local_path.read_bytes() == content
    assert client.downloads == 1


def test_lambda_index_materialization_rejects_hash_mismatch(tmp_path: Path) -> None:
    client = FakeS3Client(b"unexpected content")
    config = IndexArtifactConfig(
        bucket="private-index-bucket",
        key="retrieval-indexes/test.duckdb",
        sha256="a" * 64,
        local_path=tmp_path / "retrieval.duckdb",
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        materialize_index(config, s3_client=client)
    assert not config.local_path.exists()
    assert not config.local_path.with_suffix(".download").exists()


def test_lambda_handler_uses_fresh_adapter_for_each_stateless_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds: list[int] = []

    class FakeAdapter:
        def __init__(self, build_number: int) -> None:
            self.build_number = build_number

        def __call__(self, event: dict, context: object) -> dict:
            assert context is None
            return {"event": event, "build_number": self.build_number}

    def build_adapter() -> FakeAdapter:
        builds.append(len(builds) + 1)
        return FakeAdapter(builds[-1])

    monkeypatch.setattr(lambda_runtime, "create_lambda_adapter", build_adapter)

    assert lambda_runtime.handler({"request": 1}, None)["build_number"] == 1
    assert lambda_runtime.handler({"request": 2}, None)["build_number"] == 2
    assert builds == [1, 2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def mcp_client(retrieval_index: Path) -> AsyncGenerator[ClientSession]:
    server = create_mcp_server(retrieval_index)
    async with create_connected_server_and_client_session(
        server,
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.mark.anyio
async def test_mcp_exposes_only_read_only_candidate_retrieval_tools(
    mcp_client: ClientSession,
) -> None:
    tools = await mcp_client.list_tools()
    assert [tool.name for tool in tools.tools] == [
        "search_studies",
        "get_study",
        "get_facets",
        "get_search_capabilities",
    ]
    for tool in tools.tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False
    assert "Translate non-English scientific concepts" in tools.tools[0].description
    assert "zero matches do not establish absence" in tools.tools[0].description
    assert "projected_identity.preferred_access_url" in tools.tools[0].description
    assert "call get_study" in tools.tools[0].description

    result = await mcp_client.call_tool(
        "search_studies",
        {
            "request": {
                "filters": {
                    "medical_conditions": {
                        "values": ["Dravet syndrome"],
                        "match": "any",
                    }
                },
                "limit": 5,
            }
        },
    )
    assert result.isError is False
    assert result.structuredContent["total"] == 1
    projected = result.structuredContent["results"][0]["projected_identity"]
    assert projected["preferred_access_url"]["url_kind"] == "pubmed"
    presentation = result.structuredContent["presentation_contract"]
    assert presentation["result_label"] == "AI-classified candidate matches"
    assert presentation["distinguish_direct_from_tangential_matches"] is True
    assert presentation["study_detail_required_for_detailed_evidence_claims"] is True
    assert result.structuredContent["trust_boundary"]["medical_advice"] is False

    capabilities = await mcp_client.call_tool("get_search_capabilities", {})
    assert capabilities.isError is False
    language = capabilities.structuredContent["language_contract"]
    assert language["corpus_primary_language"] == "English"
    assert language["query_and_filter_language"] == "English"
    assert language["host_translation_required_for_non_english_questions"] is True
    assert language["answer_in_user_language"] is True
    capabilities_presentation = capabilities.structuredContent["presentation_contract"]
    assert capabilities_presentation["literature_absence_inference_allowed"] is False
    assert capabilities_presentation["preferred_access_url_path"] == (
        "projected_identity.preferred_access_url"
    )


def test_viewer_api_projects_search_and_detail_without_private_paths(
    retrieval_index: Path,
) -> None:
    client = TestClient(create_viewer_app(retrieval_index))

    meta_response = client.get("/api/viewer/meta")
    assert meta_response.status_code == 200
    meta = meta_response.json()
    assert meta["mode"] == "index"
    assert meta["documentCount"] == 3
    assert meta["facets"]["conditions"]
    assert meta["sortOptions"] == [
        {"value": "confidence", "label": "Retrieval confidence"}
    ]

    search_response = client.get(
        "/api/viewer/studies",
        params={"query": "Dravet syndrome", "condition": "Dravet syndrome"},
    )
    assert search_response.status_code == 200
    search = search_response.json()
    assert search["total"] == 1
    assert search["results"][0]["matchKind"] == "direct"
    assert search["results"][0]["reviewState"] == "needs_review"
    assert "does not establish absence" in search["zeroResultMessage"]
    document_id = search["results"][0]["documentId"]

    second_page = client.get(
        "/api/viewer/studies",
        params={"page": 2, "pageSize": 1},
    ).json()
    assert second_page["page"] == 2
    assert len(second_page["results"]) == 1
    assert second_page["results"][0]["documentId"] != document_id

    detail_response = client.get(f"/api/viewer/studies/{document_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["evidence"]
    assert detail["preferredAccessUrl"].startswith("https://pubmed.ncbi.nlm.nih.gov/")
    assert detail["provenance"]["sourceHash"] == "a" * 64
    assert "source_text_path" not in detail_response.text
    assert "data/processed" not in detail_response.text


def test_viewer_api_rejects_unsupported_sort_and_reversed_years(
    retrieval_index: Path,
) -> None:
    client = TestClient(create_viewer_app(retrieval_index))

    assert client.get("/api/viewer/studies", params={"sort": "title"}).status_code == 422
    assert client.get(
        "/api/viewer/studies",
        params={"yearFrom": 2024, "yearTo": 2020},
    ).status_code == 422
