from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import duckdb
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session

from marygenai.mcp_server import create_mcp_server
from marygenai.retrieval.identity import (
    build_identity_urls,
    choose_preferred_access_url,
    normalize_identifier,
    project_bibliographic_identities,
)
from marygenai.retrieval.index import build_retrieval_index, normalize_match_key
from marygenai.retrieval.models import FilterGroup, SearchFilters, SearchRequest
from marygenai.retrieval.service import RetrievalService


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
    assert response.trust_boundary.medical_advice is False

    page_one = service.search(SearchRequest(limit=2))
    assert page_one.total == 3
    assert page_one.next_cursor
    page_two = service.search(SearchRequest(limit=2, cursor=page_one.next_cursor))
    assert page_two.returned == 1
    assert {item.document_id for item in page_one.results}.isdisjoint(
        {item.document_id for item in page_two.results}
    )


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
    assert result.structuredContent["trust_boundary"]["medical_advice"] is False
