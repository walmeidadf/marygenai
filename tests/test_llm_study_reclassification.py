import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx

import pocs.llm_study_reclassification.reclassify_studies as reclassify_studies
from pocs.llm_study_reclassification.reclassify_studies import (
    ArtifactReference,
    build_candidates,
    build_evidence_plan,
    build_evidence_summary_packet_record,
    build_merged_semantic_paragraph_indexes,
    build_micro_extraction_packet,
    build_micro_span_grounding_audit,
    build_paragraph_index_audit,
    build_paragraph_windows,
    build_prompt_package,
    build_segmented_unit_pipeline_prompt,
    build_segmented_unit_repair_packet,
    build_source_unit_quality_record,
    build_source_unit_quality_summary,
    build_span_grounding_audit,
    build_task_packet_record,
    build_unit_classification_packet,
    build_unit_grounding_audit,
    build_unit_repair_packet,
    dry_run_summary_comparison_record,
    evidence_summary_output_schema,
    extract_html_paragraphs,
    extract_xml_paragraphs,
    infer_segmented_unit_pipeline,
    load_artifacts_by_document_id,
    load_processed_semantic_window_keys,
    load_processed_unit_classification_keys,
    load_repair_needed_unit_records,
    normalize_label,
    post_provider_with_retries,
    resolve_provider_models,
    result_direction_matches,
    segmented_unit_pipeline_output_schema,
    select_best_full_text_artifact,
    select_evidence_chunks,
    select_micro_extraction_candidates,
    select_stratified_candidates,
    select_task_evidence_spans,
    select_units_for_classification_task,
    select_units_for_segmented_pipeline,
    source_unit_index_record_from_candidate,
    throughput_metrics,
)


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    def post(self, *args, **kwargs) -> httpx.Response:
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("temporary timeout")
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}]},
        )


def make_artifact(
    artifact_type: str,
    *,
    document_id: str = "publication:pmid:1",
    payload_path: str | None = "data/raw/example.xml",
    payload_size_bytes: int = 100,
) -> ArtifactReference:
    return ArtifactReference(
        artifact_id=f"artifact:{artifact_type}",
        document_id=document_id,
        artifact_type=artifact_type,
        source="pmc",
        payload_path=payload_path,
        payload_sha256="sha",
        payload_size_bytes=payload_size_bytes,
        raw_payload={},
        url="https://example.org/article",
        license="cc-by",
        created_at="2026-05-27T00:00:00+00:00",
    )


def test_select_best_full_text_artifact_prefers_pmc_nxml() -> None:
    selected = select_best_full_text_artifact(
        [
            make_artifact("pmc_html", payload_size_bytes=10_000),
            make_artifact("europe_pmc_full_text_xml", payload_size_bytes=20_000),
            make_artifact("pmc_nxml", payload_size_bytes=1_000),
        ]
    )

    assert selected is not None
    assert selected.artifact_type == "pmc_nxml"


def test_legacy_comparison_normalization_handles_case() -> None:
    assert normalize_label("Double Blind Clinical Trial") == "double blind clinical trial"
    assert result_direction_matches("Positive", "positive") is True
    assert result_direction_matches("Negative", "neutral") is False


def test_select_stratified_candidates_skips_processed_and_round_robins() -> None:
    records = [
        {
            "document_id": "publication:pmid:1",
            "context_id": "context:1",
            "title": "Cannabis and cancer",
            "type_of_study": "Meta-analysis",
            "study_result": "Positive",
        },
        {
            "document_id": "publication:pmid:2",
            "context_id": "context:2",
            "title": "Cannabis and pain",
            "type_of_study": "Clinical Trial",
            "study_result": "Positive",
        },
        {
            "document_id": "publication:pmid:3",
            "context_id": "context:3",
            "title": "Cannabis and inflammation",
            "type_of_study": "Meta-analysis",
            "study_result": "Mixed",
        },
    ]
    candidates = build_candidates(
        records,
        artifacts_by_document_id={
            "publication:pmid:1": [make_artifact("pmc_nxml", document_id="publication:pmid:1")],
            "publication:pmid:2": [make_artifact("pmc_nxml", document_id="publication:pmid:2")],
            "publication:pmid:3": [make_artifact("pmc_nxml", document_id="publication:pmid:3")],
        },
        abstracts_by_document_id={},
    )

    selected = select_stratified_candidates(
        candidates,
        processed_document_ids={"publication:pmid:1"},
        limit=2,
    )

    assert [candidate.document_id for candidate in selected] == [
        "publication:pmid:3",
        "publication:pmid:2",
    ]


def test_build_prompt_package_includes_legacy_guardrail_and_safety_boundary(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        "<article><body><p>Randomized trial of cannabidiol for pain in "
        "42 humans.</p></body></article>",
        encoding="utf-8",
    )
    record = {
        "document_id": "publication:pmid:1",
        "context_id": "legacy_english_context:1",
        "title": "Cannabidiol for pain",
        "type_of_study": "Clinical Trial",
        "study_result": "Positive",
        "key_findings": ["Pain improved."],
    }
    candidate = build_candidates(
        [record],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]

    package = build_prompt_package(candidate, max_source_chars=5_000)

    assert package.evidence_source_used == "full_text"
    assert "Do not provide medical advice" in package.prompt
    assert "guardrail and comparison baseline, not absolute truth" in package.prompt
    assert "insufficient_evidence" in package.prompt
    assert "Randomized trial of cannabidiol" in package.prompt
    assert "field_evidence_chunks" in package.prompt
    assert package.context_strategy == "full_text_compact"
    assert package.retrieval_method == "direct_full_text_v0.1"


def test_load_artifacts_by_document_id_reads_raw_payload_json() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE access_enrichment_artifact (
            artifact_id TEXT,
            document_id TEXT,
            source TEXT,
            artifact_type TEXT,
            url TEXT,
            license TEXT,
            payload_path TEXT,
            payload_sha256 TEXT,
            payload_size_bytes INTEGER,
            raw_payload_json TEXT,
            created_at TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO access_enrichment_artifact VALUES (
            'artifact:1',
            'publication:pmid:1',
            'europe_pmc',
            'europe_pmc_metadata',
            'https://example.org',
            'cc-by',
            NULL,
            NULL,
            NULL,
            '{"resultList":{"result":[{"abstractText":"<b>Abstract text</b>"}]}}',
            '2026-05-27T00:00:00+00:00'
        )
        """
    )

    artifacts = load_artifacts_by_document_id(connection, ["publication:pmid:1"])

    assert artifacts["publication:pmid:1"][0].raw_payload["resultList"]["result"][0][
        "abstractText"
    ] == "<b>Abstract text</b>"


def test_select_evidence_chunks_retrieves_relevant_results_beyond_prefix(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "article.nxml"
    long_intro = "Background context without extraction targets. " * 160
    xml_path.write_text(
        f"""
        <article>
          <front>
            <article-meta>
              <abstract><p>Trial abstract about cannabis and pain.</p></abstract>
            </article-meta>
          </front>
          <body>
            <sec><title>Introduction</title><p>{long_intro}</p></sec>
            <sec><title>Methods</title>
              <p>Forty-two human participants were randomized to cannabidiol or placebo.</p>
            </sec>
            <sec><title>Results</title>
              <p>Cannabidiol 25 mg reduced pain scores and adverse events were mild nausea.</p>
            </sec>
          </body>
        </article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol for pain",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]

    chunks = select_evidence_chunks(candidate, max_source_chars=5_000)
    packet = build_prompt_package(candidate, max_source_chars=5_000).prompt

    assert any(chunk.section == "Results" for chunk in chunks)
    assert "Cannabidiol 25 mg reduced pain scores" in packet
    assert "adverse events were mild nausea" in packet


def test_study_design_task_packet_starts_from_legacy(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Methods</title>
            <p>This randomized placebo-controlled trial enrolled 42 participants.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol trial",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )

    packet = build_task_packet_record(
        candidate,
        evidence_plan=evidence_plan,
        task_name="study_design_verification",
        run_id="test-run",
    )

    assert packet.task_order == 1
    assert packet.model_tier_hint == "high_tier_recommended"
    assert "Start from the legacy study type" in packet.prompt
    assert "keep_legacy | change_legacy | insufficient_evidence" in packet.prompt


def test_condition_organ_system_task_requires_explicit_conditions(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Results</title>
            <p>Cannabidiol reduced inflammatory pain behavior in a mouse model.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and inflammatory pain",
                "type_of_study": "Animal Study",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )

    packet = build_task_packet_record(
        candidate,
        evidence_plan=evidence_plan,
        task_name="condition_organ_system_extraction",
        run_id="test-run",
    )

    assert packet.task_order == 3
    assert "Organ systems may be inferred only from a specific extracted condition" in packet.prompt
    assert "pathologies_or_conditions" in packet.prompt
    assert "legacy_condition_alignment" in packet.prompt


def test_summary_spans_are_extractive_and_task_scored(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Methods</title>
            <p>Forty-two participants were randomized to placebo or oral cannabidiol.</p>
          </sec>
          <sec><title>Results</title>
            <p>Cannabidiol 25 mg reduced inflammatory pain scores.</p>
            <p>Unrelated background about botanical taxonomy was discussed.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and inflammatory pain",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )

    spans = select_task_evidence_spans(
        candidate,
        evidence_plan=evidence_plan,
        task_name="intervention_exposure",
        max_spans=4,
    )

    source_text = " ".join(chunk.text for chunk in evidence_plan.source_chunks)

    assert spans
    assert all(span.text in source_text for span in spans)
    assert any("cannabidiol" in span.text.lower() for span in spans)
    assert any(span.chunk_id for span in spans)


def test_summary_packet_requires_span_citations_and_no_unsupported_facts(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Results</title>
            <p>Cannabidiol reduced inflammatory pain behavior in a mouse model.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and inflammatory pain",
                "type_of_study": "Animal Study",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=1_000,
        large_full_text_char_limit=80_000,
    )

    packet = build_evidence_summary_packet_record(
        candidate,
        evidence_plan=evidence_plan,
        task_name="condition_organ_system_extraction",
        run_id="test-run",
        max_spans=4,
    )

    assert packet.selected_span_ids
    assert "Every synthesized claim must cite at least one span_id" in packet.prompt
    assert "Evidence text must be a short verbatim substring" in packet.prompt
    assert "candidate_value must be explicitly named in the cited span" in packet.prompt
    assert "Do not add background knowledge" in packet.prompt
    assert "legacy English context is a guardrail" in packet.prompt
    assert "field_support" in packet.prompt


def test_span_grounding_audit_flags_evidence_text_not_in_cited_span(
    tmp_path: Path,
) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Results</title>
            <p>Cannabidiol reduced inflammatory pain behavior in a mouse model.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and inflammatory pain",
                "type_of_study": "Animal Study",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )
    packet = build_evidence_summary_packet_record(
        candidate,
        evidence_plan=evidence_plan,
        task_name="condition_organ_system_extraction",
        run_id="test-run",
        max_spans=4,
    )
    record = {
        "field_support": {
            "condition": [
                {
                    "candidate_value": "inflammatory pain",
                    "cited_span_ids": [packet.selected_span_ids[0]],
                    "evidence_text": "this text is not present in the span",
                }
            ]
        }
    }

    audit = build_span_grounding_audit(record, packet)

    assert audit["passes_basic_grounding"] is False
    assert audit["unsupported_evidence_texts"][0]["field_name"] == "condition"


def test_intervention_exposure_summary_schema_tracks_cannabinoid_role() -> None:
    schema = evidence_summary_output_schema("intervention_exposure")

    role_schema = schema["intervention_exposure_summary"]

    assert "role_of_cannabinoid" in role_schema
    assert "background_only" in role_schema["role_of_cannabinoid"]
    assert "is_primary_study_target" in role_schema
    assert "support_status" in role_schema
    assert "cited_span_ids" in role_schema


def test_resolve_provider_models_allows_provider_overrides() -> None:
    provider_models = resolve_provider_models(
        "groq,openai",
        model=None,
        model_overrides="openai:gpt-4.1-mini",
    )

    assert provider_models == [
        ("groq", "llama-3.3-70b-versatile"),
        ("openai", "gpt-4.1-mini"),
    ]


def test_resolve_provider_models_includes_cerebras_default() -> None:
    provider_models = resolve_provider_models(
        "cerebras",
        model=None,
        model_overrides=None,
    )

    assert provider_models == [("cerebras", "gpt-oss-120b")]


def test_post_provider_with_retries_retries_transient_timeout(monkeypatch) -> None:
    client = FlakyClient()
    monkeypatch.setattr(reclassify_studies.time, "sleep", lambda seconds: None)

    response, attempts = post_provider_with_retries(
        client,  # type: ignore[arg-type]
        provider="openai",
        request_payload={"model": "gpt-4.1", "messages": []},
        api_key="test-key",
        max_attempts=2,
    )

    assert response.status_code == 200
    assert client.calls == 2
    assert attempts[0]["error_type"] == "ReadTimeout"
    assert attempts[1]["status_code"] == 200


def test_resume_key_loaders_skip_successes_but_retry_errors(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    records_path.write_text(
        "\n".join(
            [
                (
                    '{"document_id":"doc:1","window_id":"doc:1:window:0001",'
                    '"provider":"openai","model":"gpt-4.1",'
                    '"poc_status":"candidate_semantic_paragraph_index"}'
                ),
                (
                    '{"document_id":"doc:2","window_id":"doc:2:window:0001",'
                    '"provider":"openai","model":"gpt-4.1","poc_status":"error"}'
                ),
                (
                    '{"document_id":"doc:1","task_name":"study_classification",'
                    '"provider":"openai","model":"gpt-4.1",'
                    '"poc_status":"candidate_unit_classification"}'
                ),
                (
                    '{"document_id":"doc:2","task_name":"study_classification",'
                    '"provider":"openai","model":"gpt-4.1","poc_status":"error"}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    semantic_keys = load_processed_semantic_window_keys(
        records_path,
        retry_errors=True,
    )
    unit_keys = load_processed_unit_classification_keys(
        records_path,
        retry_errors=True,
    )

    assert semantic_keys == {("doc:1", "doc:1:window:0001", "openai", "gpt-4.1")}
    assert unit_keys == {("doc:1", "study_classification", "openai", "gpt-4.1")}


def test_model_comparison_dry_run_preserves_packet_provenance(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Methods</title>
            <p>Participants received oral cannabidiol or placebo for pain.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and pain",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )
    packet = build_evidence_summary_packet_record(
        candidate,
        evidence_plan=evidence_plan,
        task_name="intervention_exposure",
        run_id="test-run",
        max_spans=4,
    )

    record = dry_run_summary_comparison_record(
        packet,
        provider="openai",
        model="gpt-4.1",
    )

    assert record["poc_status"] == "dry_run_prompt_prepared"
    assert record["provider"] == "openai"
    assert record["model"] == "gpt-4.1"
    assert record["provenance"]["selected_span_ids"] == packet.selected_span_ids
    assert record["provenance"]["legacy_context_id"] == "legacy_english_context:1"
    assert record["span_grounding_audit"]["passes_basic_grounding"] is True


def test_micro_extraction_packet_is_atomic_and_preserves_spans(tmp_path: Path) -> None:
    xml_path = tmp_path / "article.nxml"
    xml_path.write_text(
        """
        <article><body>
          <sec><title>Methods</title>
            <p>Participants received oral cannabidiol or placebo for pain.</p>
          </sec>
        </body></article>
        """,
        encoding="utf-8",
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol and pain",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
            }
        ],
        artifacts_by_document_id={
            "publication:pmid:1": [
                make_artifact(
                    "pmc_nxml",
                    document_id="publication:pmid:1",
                    payload_path=str(xml_path),
                )
            ]
        },
        abstracts_by_document_id={},
    )[0]
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=5_000,
        direct_full_text_char_limit=50,
        large_full_text_char_limit=80_000,
    )

    packet = build_micro_extraction_packet(
        candidate,
        evidence_plan=evidence_plan,
        field_name="cannabinoid_role",
        run_id="test-run",
        max_spans=4,
    )

    assert packet["field_name"] == "cannabinoid_role"
    assert packet["task_name"] == "intervention_exposure"
    assert packet["selected_span_ids"]
    assert "Do not write a narrative synthesis" in packet["prompt"]
    assert "role_of_cannabinoid" in packet["prompt"]
    assert packet["provenance"]["legacy_context_id"] == "legacy_english_context:1"


def test_micro_span_grounding_requires_citations_for_supported_values() -> None:
    packet = {
        "spans": [],
        "field_name": "cannabinoid_role",
    }
    record = {
        "field_name": "cannabinoid_role",
        "candidate": {
            "role_of_cannabinoid": "intervention",
            "support_status": "supported",
            "cited_span_ids": [],
            "evidence_text": "",
        },
    }

    audit = build_micro_span_grounding_audit(record, packet)

    assert audit["passes_basic_grounding"] is False
    assert audit["missing_required_citations"] is True


def test_select_micro_extraction_candidates_uses_fixed_document_ids() -> None:
    candidates = [
        build_candidates(
            [
                {
                    "document_id": "publication:pmid:1",
                    "context_id": "legacy_english_context:1",
                    "title": "One",
                    "type_of_study": "Clinical Trial",
                }
            ],
            artifacts_by_document_id={},
            abstracts_by_document_id={},
        )[0],
        build_candidates(
            [
                {
                    "document_id": "publication:pmid:2",
                    "context_id": "legacy_english_context:2",
                    "title": "Two",
                    "type_of_study": "Clinical Trial",
                }
            ],
            artifacts_by_document_id={},
            abstracts_by_document_id={},
        )[0],
    ]

    selected = select_micro_extraction_candidates(
        candidates,
        document_ids=["publication:pmid:2"],
        limit=None,
    )

    assert [candidate.document_id for candidate in selected] == ["publication:pmid:2"]


def test_extract_xml_paragraphs_preserves_literal_clean_text() -> None:
    raw = b"""
    <article><body>
      <sec><title>Methods</title>
        <p> Participants   received <italic>oral cannabidiol</italic> or placebo. </p>
        <p>Short.</p>
      </sec>
      <sec><title>Results</title>
        <p>Cannabidiol reduced pain scores in the treatment arm.</p>
      </sec>
    </body></article>
    """
    artifact = make_artifact("pmc_nxml")

    paragraphs = extract_xml_paragraphs(raw, artifact=artifact)

    assert [paragraph.section for paragraph in paragraphs] == ["Methods", "Results"]
    assert paragraphs[0].text == "Participants received oral cannabidiol or placebo."
    assert paragraphs[0].paragraph_id == "p0001"
    assert paragraphs[0].unit_type == "paragraph"
    assert paragraphs[1].text == "Cannabidiol reduced pain scores in the treatment arm."


def test_extract_xml_paragraphs_skips_obvious_boilerplate() -> None:
    raw = b"""
    <article><body>
      <sec><title>Body</title>
        <p>An official website of the United States government</p>
        <p>Participants received oral cannabidiol or placebo.</p>
      </sec>
    </body></article>
    """
    artifact = make_artifact("pmc_nxml")

    paragraphs = extract_xml_paragraphs(raw, artifact=artifact)

    assert len(paragraphs) == 1
    assert paragraphs[0].text == "Participants received oral cannabidiol or placebo."


def test_extract_xml_paragraphs_maps_tables_and_figure_captions() -> None:
    raw = b"""
    <article><body>
      <sec><title>Results</title>
        <p>Participants received oral cannabidiol or placebo.</p>
        <table-wrap>
          <caption><title>Table 1</title><p>Cannabidiol dose and pain outcomes.</p></caption>
          <table><tr><td>CBD 25 mg</td><td>Pain improved</td></tr></table>
        </table-wrap>
        <fig>
          <caption><p>Figure 1 shows cannabinoid exposure response.</p></caption>
        </fig>
      </sec>
    </body></article>
    """
    artifact = make_artifact("pmc_nxml")

    paragraphs = extract_xml_paragraphs(raw, artifact=artifact)

    assert [paragraph.unit_type for paragraph in paragraphs] == [
        "paragraph",
        "table",
        "figure_caption",
    ]
    assert paragraphs[1].section == "Results"
    assert "CBD 25 mg" in paragraphs[1].text
    assert paragraphs[2].text == "Figure 1 shows cannabinoid exposure response."


def test_extract_html_paragraphs_maps_tables_without_duplicate_paragraphs() -> None:
    raw = b"""
    <html><body>
      <h2>Results</h2>
      <p>Participants received oral cannabidiol or placebo.</p>
      <table><tr><td>CBD 25 mg oral dose</td><td>Pain improved after treatment</td></tr></table>
      <figure><figcaption>Figure shows cannabinoid exposure response.</figcaption></figure>
    </body></html>
    """
    artifact = make_artifact("pmc_html")

    paragraphs = extract_html_paragraphs(raw, artifact=artifact)

    assert [paragraph.unit_type for paragraph in paragraphs] == [
        "paragraph",
        "table",
        "figure_caption",
    ]
    assert paragraphs[1].text == "CBD 25 mg oral dose Pain improved after treatment"
    assert paragraphs[2].text == "Figure shows cannabinoid exposure response."


def test_select_units_for_classification_task_uses_semantic_labels() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo.</p>
          <p>Major depressive disorder was the target condition.</p>
          <p>Randomized trial procedures enrolled fifty participants.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )

    selected = select_units_for_classification_task(
        paragraphs,
        task_name="cannabinoid_classification",
        labels_by_unit={paragraphs[0].paragraph_id: ["intervention_or_exposure"]},
        max_units=1,
    )

    assert [unit.paragraph_id for unit in selected] == [paragraphs[0].paragraph_id]


def test_infer_segmented_unit_pipeline_uses_legacy_study_type() -> None:
    candidates = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabis review",
                "type_of_study": "Meta-analysis",
            },
            {
                "document_id": "publication:pmid:2",
                "context_id": "legacy_english_context:2",
                "title": "Cannabidiol mouse model",
                "type_of_study": "Animal Study",
            },
            {
                "document_id": "publication:pmid:3",
                "context_id": "legacy_english_context:3",
                "title": "Nabiximols trial",
                "type_of_study": "Double Blind Clinical Trial",
            },
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={},
    )

    assert infer_segmented_unit_pipeline(candidates[0]) == "evidence_synthesis"
    assert infer_segmented_unit_pipeline(candidates[1]) == "preclinical_mechanistic"
    assert infer_segmented_unit_pipeline(candidates[2]) == "clinical_intervention"


def test_select_units_for_segmented_pipeline_uses_segment_keywords() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo.</p>
          <p>CB1 receptor signaling was measured in mouse tissue using an assay.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )

    selected = select_units_for_segmented_pipeline(
        paragraphs,
        pipeline_name="preclinical_mechanistic",
        labels_by_unit={},
        max_units=1,
    )

    assert [unit.paragraph_id for unit in selected] == [paragraphs[1].paragraph_id]


def test_segmented_pipeline_prompt_has_evidence_synthesis_guardrails() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Abstract</title>
          <p>This systematic review included randomized controlled trials of cannabinoids.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabinoid systematic review",
                "type_of_study": "Meta-analysis",
                "condition": "Pain",
            }
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={},
    )[0]

    prompt = build_segmented_unit_pipeline_prompt(
        candidate=candidate,
        pipeline_name="evidence_synthesis",
        schema=segmented_unit_pipeline_output_schema("evidence_synthesis"),
        units=paragraphs,
        labels_by_unit={paragraphs[0].paragraph_id: ["study_design"]},
        legacy_context_text="Legacy English context says meta-analysis for pain.",
    )

    assert "Do not extract single cited studies" in prompt
    assert "legacy English context only as a guardrail" in prompt
    assert "Do not cite the legacy English context as a source unit" in prompt
    assert "one contiguous substring from exactly one cited unit" in prompt
    assert "source_unit_ids" in prompt


def test_segmented_unit_repair_packet_uses_segment_schema() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Results</title>
          <p>CBD reduced CB1 expression in irradiated rats.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol in rats",
                "type_of_study": "Animal Study",
            }
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={},
    )[0]
    source_record = {
        "run_id": "source-run",
        "document_id": candidate.document_id,
        "task_name": "preclinical_mechanistic",
        "pipeline_name": "preclinical_mechanistic",
        "provider": "openai",
        "model": "gpt-4.1",
        "unit_grounding_audit": {
            "grounding_repair_needed": True,
            "evidence_text_policy_violations": [
                {"evidence_text": "CBD reduced CB1 expression in irradiated rats."}
            ],
        },
    }

    packet = build_segmented_unit_repair_packet(
        candidate,
        source_record=source_record,
        units=paragraphs,
        labels_by_unit={},
        run_id="repair-run",
        semantic_index_path=None,
    )

    assert packet["pipeline_name"] == "preclinical_mechanistic"
    assert packet["prompt_version"].endswith("_segmented_repair_preclinical_mechanistic")
    assert "preclinical_mechanistic" in packet["expected_output_schema"]
    assert "Do not cite the legacy English context as a source unit" in packet["prompt"]


def test_unit_classification_prompt_separates_quote_from_note() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo for pain.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol trial",
                "type_of_study": "Clinical Trial",
            }
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={},
    )[0]

    packet = build_unit_classification_packet(
        candidate,
        task_name="cannabinoid_classification",
        units=paragraphs,
        labels_by_unit={},
        run_id="test-run",
        semantic_index_path=None,
    )

    assert "evidence_text is a quote field, not a summary field" in packet["prompt"]
    assert "evidence_note, not evidence_text" in packet["prompt"]
    assert "220 characters or fewer" in packet["prompt"]


def test_unit_grounding_audit_flags_unknown_ids_and_unsupported_text() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    packet = {"units": paragraphs}
    record = {
        "task_name": "cannabinoid_classification",
        "cannabinoid_classification": {
            "support_status": "supported",
            "cited_unit_ids": ["unknown"],
            "evidence_text": "unsupported phrase",
        },
    }

    audit = build_unit_grounding_audit(record, packet)

    assert audit["passes_basic_grounding"] is False
    assert audit["unknown_unit_ids"] == ["unknown"]
    assert audit["unsupported_evidence_texts"][0]["evidence_text"] == "unsupported phrase"
    assert audit["grounding_repair_needed"] is True


def test_unit_grounding_audit_flags_stitched_evidence_text() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo for pain.</p>
          <p>Cannabidiol reduced pain scores after four weeks.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    packet = {"units": paragraphs}
    record = {
        "task_name": "cannabinoid_classification",
        "cannabinoid_classification": {
            "support_status": "supported",
            "cited_unit_ids": [paragraphs[0].paragraph_id, paragraphs[1].paragraph_id],
            "evidence_text": (
                "Participants received oral cannabidiol or placebo for pain. ... "
                "Cannabidiol reduced pain scores after four weeks."
            ),
        },
    }

    audit = build_unit_grounding_audit(record, packet)

    assert audit["passes_basic_grounding"] is False
    assert audit["grounding_repair_needed"] is True
    violations = audit["evidence_text_policy_violations"][0]["violations"]
    assert "evidence_text_contains_ellipsis" in violations
    assert "evidence_text_requires_exactly_one_cited_unit" in violations


def test_unit_repair_packet_scopes_repair_to_failed_record() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo for pain.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol trial",
                "type_of_study": "Clinical Trial",
            }
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={},
    )[0]
    source_record = {
        "run_id": "source-run",
        "document_id": candidate.document_id,
        "task_name": "cannabinoid_classification",
        "provider": "openai",
        "model": "gpt-4.1",
        "unit_grounding_audit": {"grounding_repair_needed": True},
    }

    packet = build_unit_repair_packet(
        candidate,
        source_record=source_record,
        units=paragraphs,
        labels_by_unit={},
        run_id="repair-run",
        semantic_index_path=None,
    )

    assert packet["prompt_version"].endswith("_unit_repair_cannabinoid_classification")
    assert "This is not a new extraction task" in packet["prompt"]
    assert "Original failed record" in packet["prompt"]
    assert packet["provenance"]["source_record_run_id"] == "source-run"


def test_load_repair_needed_unit_records_deduplicates_records(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    repair_audit = '{"grounding_repair_needed": true}'
    records_path.write_text(
        "\n".join(
            [
                (
                    '{"document_id":"doc:1","task_name":"study_classification",'
                    '"provider":"openai","model":"gpt-4.1",'
                    f'"unit_grounding_audit":{repair_audit}}}'
                ),
                (
                    '{"document_id":"doc:1","task_name":"study_classification",'
                    '"provider":"openai","model":"gpt-4.1",'
                    f'"unit_grounding_audit":{repair_audit}}}'
                ),
                (
                    '{"document_id":"doc:2","task_name":"study_classification",'
                    '"provider":"openai","model":"gpt-4.1",'
                    '"unit_grounding_audit":{"grounding_repair_needed": false}}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = load_repair_needed_unit_records([records_path])

    assert len(records) == 1
    assert records[0]["document_id"] == "doc:1"


def test_throughput_metrics_summarizes_prompt_output_and_latency() -> None:
    records = [
        {
            "provenance": {
                "input_prompt_chars": 400,
                "rough_input_token_estimate": 100,
                "output_chars": 80,
                "rough_output_token_estimate": 20,
                "latency_seconds": 1.25,
            }
        },
        {
            "provenance": {
                "input_prompt_chars": 800,
                "rough_input_token_estimate": 200,
                "latency_seconds": 2.75,
            }
        },
    ]

    metrics = throughput_metrics(records)

    assert metrics["record_count"] == 2
    assert metrics["total_prompt_chars"] == 1200
    assert metrics["mean_prompt_chars"] == 600
    assert metrics["total_rough_input_tokens"] == 300
    assert metrics["output_record_count"] == 1
    assert metrics["total_output_chars"] == 80
    assert metrics["total_latency_seconds"] == 4.0
    assert metrics["mean_latency_seconds"] == 2.0


def test_build_paragraph_windows_uses_overlap() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Body</title>
          <p>Paragraph one has enough words for indexing.</p>
          <p>Paragraph two has enough words for indexing.</p>
          <p>Paragraph three has enough words for indexing.</p>
          <p>Paragraph four has enough words for indexing.</p>
          <p>Paragraph five has enough words for indexing.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )

    windows = build_paragraph_windows(
        "publication:pmid:1",
        paragraphs,
        window_paragraphs=3,
        overlap_paragraphs=1,
        max_windows=None,
    )

    assert [window.paragraph_ids for window in windows] == [
        [paragraphs[0].paragraph_id, paragraphs[1].paragraph_id, paragraphs[2].paragraph_id],
        [paragraphs[2].paragraph_id, paragraphs[3].paragraph_id, paragraphs[4].paragraph_id],
    ]


def test_paragraph_index_audit_flags_unknown_ids_and_invalid_labels() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    window = build_paragraph_windows(
        "publication:pmid:1",
        paragraphs,
        window_paragraphs=3,
        overlap_paragraphs=0,
        max_windows=None,
    )[0]
    packet = {"paragraph_ids": window.paragraph_ids, "paragraphs": window.paragraphs}
    record = {
        "paragraph_annotations": [
            {
                "paragraph_id": "unknown",
                "labels": ["bad_label"],
                "evidence_terms": ["not in paragraph"],
            }
        ]
    }

    audit = build_paragraph_index_audit(record, packet)

    assert audit["passes_basic_audit"] is False
    assert audit["unknown_paragraph_ids"] == ["unknown"]
    assert audit["invalid_labels"][0]["label"] == "bad_label"


def test_merge_semantic_paragraph_indexes_deduplicates_votes() -> None:
    artifact = make_artifact("pmc_nxml")
    paragraphs = extract_xml_paragraphs(
        b"""
        <article><body><sec><title>Methods</title>
          <p>Participants received oral cannabidiol or placebo.</p>
        </sec></body></article>
        """,
        artifact=artifact,
    )
    record = {
        "document_id": "publication:pmid:1",
        "provider": "openai",
        "model": "gpt-4.1",
        "paragraph_annotations": [
            {
                "paragraph_id": paragraphs[0].paragraph_id,
                "labels": ["intervention_or_exposure"],
                "question_relevance": {"cannabinoid_role": "high"},
                "evidence_terms": ["oral cannabidiol"],
                "needs_human_review_hint": False,
            }
        ],
        "poc_status": "candidate_semantic_paragraph_index",
    }

    merged = build_merged_semantic_paragraph_indexes(
        [record],
        paragraph_index_inputs={"publication:pmid:1": paragraphs},
    )

    assert merged[0]["annotated_paragraph_count"] == 1
    annotation = merged[0]["merged_annotations"][0]
    assert annotation["labels"] == ["intervention_or_exposure"]
    assert annotation["label_votes"] == {"intervention_or_exposure": 1}
    assert annotation["unit_type"] == "paragraph"


def test_source_unit_quality_detects_recaptcha_js_artifact() -> None:
    source_record = {
        "document_id": "publication:pmcid:PMC8039032",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": [
            {
                "paragraph_id": "p0001",
                "section": "unparsed_full_text",
                "unit_type": "paragraph",
                "labels": ["not_relevant"],
                "text": "window['ppConfig'] = {productName: 'RecaptchaChallengePageUi'};",
            }
        ],
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["quality_bucket"] == "recaptcha_or_js"
    assert record["routing_recommendation"] == "block_before_llm"
    assert record["recaptcha_or_js_detected"] is True
    assert record["needs_source_repair"] is True


def test_source_unit_quality_detects_abstract_plus_boilerplate() -> None:
    source_record = {
        "document_id": "publication:pmcid:PMC2011510",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": [
            {
                "paragraph_id": "p0001",
                "section": "html_full_text",
                "unit_type": "paragraph",
                "labels": ["not_relevant"],
                "text": (
                    "This article is licensed under a Creative Commons Attribution "
                    "4.0 International License."
                ),
            },
            {
                "paragraph_id": "p0002",
                "section": "Abstract",
                "unit_type": "paragraph",
                "labels": [
                    "study_design",
                    "population_model",
                    "intervention_or_exposure",
                    "condition_or_target",
                ],
                "text": (
                    "Nabilone, a synthetic cannabinoid, was compared in a "
                    "double-blind crossover study of 34 patients with cancer pain."
                ),
            },
            {
                "paragraph_id": "p0003",
                "section": "Selected References",
                "unit_type": "paragraph",
                "labels": ["not_relevant"],
                "text": "These references are in PubMed. This may not be the complete list.",
            },
        ],
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["quality_bucket"] == "abstract_plus_boilerplate"
    assert record["routing_recommendation"] == "abstract_triage_or_fetch_better_source"
    assert record["has_abstract"] is True
    assert record["scientific_unit_count"] == 1
    assert record["boilerplate_unit_count"] == 2


def test_source_unit_quality_detects_rich_full_text() -> None:
    annotations = []
    for index in range(12):
        section = "Methods" if index < 4 else "Results"
        annotations.append(
            {
                "paragraph_id": f"p{index + 1:04d}",
                "section": section,
                "unit_type": "paragraph",
                "labels": ["study_design", "intervention_or_exposure", "outcomes_results"],
                "text": (
                    "Patients received cannabidiol treatment in a randomized trial "
                    "and outcomes were measured after dosing."
                ),
            }
        )
    source_record = {
        "document_id": "publication:pmcid:PMC2228252",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": annotations,
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["quality_bucket"] == "full_text_rich"
    assert record["routing_recommendation"] == "use_for_segmented_classification"
    assert record["has_methods"] is True
    assert record["has_results"] is True


def test_source_unit_quality_does_not_treat_scanned_method_as_ocr() -> None:
    annotations = []
    for index in range(12):
        annotations.append(
            {
                "paragraph_id": f"p{index + 1:04d}",
                "section": "Methods" if index < 6 else "Results",
                "unit_type": "paragraph",
                "labels": ["study_design", "outcomes_results"],
                "text": (
                    "Cannabidiol treated cell images were scanned for analysis "
                    "and significant outcomes were measured."
                ),
            }
        )
    source_record = {
        "document_id": "publication:pmid:scan-method",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": annotations,
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["needs_ocr"] is False
    assert record["quality_bucket"] == "full_text_rich"


def test_source_unit_quality_detects_low_cannabinoid_focus() -> None:
    source_record = {
        "document_id": "publication:url:0c4ab371df7dff5b",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": [
            {
                "paragraph_id": "p0001",
                "section": "Methods",
                "unit_type": "paragraph",
                "labels": ["study_design", "population_model"],
                "text": (
                    "Adult patients with major depressive disorder were enrolled in "
                    "a double-blind randomized trial."
                ),
            },
            {
                "paragraph_id": "p0002",
                "section": "Results",
                "unit_type": "paragraph",
                "labels": ["outcomes_results"],
                "text": "The treatment group had improved depression scores compared with placebo.",
            },
        ],
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["quality_bucket"] == "low_cannabinoid_focus"
    assert record["routing_recommendation"] == "source_repair_or_identity_check"
    assert record["cannabinoid_focus_score"] == 0.0


def test_source_unit_quality_detects_biomarker_only_focus() -> None:
    source_record = {
        "document_id": "publication:pmcid:PMC10466388",
        "provider": "openai",
        "model": "gpt-4.1",
        "merged_annotations": [
            {
                "paragraph_id": "p0001",
                "section": "Methods",
                "unit_type": "paragraph",
                "labels": ["study_design", "population_model"],
                "text": "Participants completed Tai Chi exercise for knee osteoarthritis pain.",
            },
            {
                "paragraph_id": "p0002",
                "section": "Results",
                "unit_type": "paragraph",
                "labels": ["outcomes_results"],
                "text": (
                    "Plasma endocannabinoid levels were measured as biomarkers "
                    "before and after the exercise intervention."
                ),
            },
        ],
    }

    record = build_source_unit_quality_record(source_record, run_id="run")

    assert record["quality_bucket"] == "biomarker_only"
    assert record["routing_recommendation"] == "biomarker_or_indirect_focus_review"
    assert record["needs_source_repair"] is False


def test_source_unit_index_record_from_candidate_uses_abstract_not_legacy() -> None:
    candidate = build_candidates(
        [
            {
                "document_id": "publication:pmid:1",
                "context_id": "legacy_english_context:1",
                "title": "Cannabidiol trial",
                "type_of_study": "Clinical Trial",
                "study_result": "Positive",
                "key_findings": "Legacy says cannabidiol was studied.",
            }
        ],
        artifacts_by_document_id={},
        abstracts_by_document_id={
            "publication:pmid:1": (
                "Cannabidiol was evaluated in adults with chronic pain. "
                "The randomized trial measured pain outcomes."
            )
        },
    )[0]

    record = source_unit_index_record_from_candidate(candidate)

    assert record["selected_artifact_type"] is None
    assert record["has_publication_abstract"] is True
    assert record["paragraph_count"] == 2
    assert {
        annotation["source_kind"] for annotation in record["merged_annotations"]
    } == {"abstract_metadata"}
    assert "Legacy says" not in record["merged_annotations"][0]["text"]


def test_source_unit_quality_summary_counts_buckets_and_routes(tmp_path: Path) -> None:
    started_at = datetime(2026, 6, 3, tzinfo=UTC)
    records = [
        {
            "quality_bucket": "full_text_rich",
            "routing_recommendation": "use_for_segmented_classification",
            "selected_artifact_type": "pmc_nxml",
            "legacy_study_type": "Clinical Trial",
            "needs_source_repair": False,
            "recaptcha_or_js_detected": False,
            "needs_ocr": False,
            "unit_count": 12,
            "scientific_unit_count": 12,
            "cannabinoid_focus_score": 0.5,
        },
        {
            "quality_bucket": "recaptcha_or_js",
            "routing_recommendation": "block_before_llm",
            "selected_artifact_type": "pmc_html",
            "legacy_study_type": "Meta-analysis",
            "needs_source_repair": True,
            "recaptcha_or_js_detected": True,
            "needs_ocr": False,
            "unit_count": 3,
            "scientific_unit_count": 0,
            "cannabinoid_focus_score": 0.0,
        },
    ]

    summary = build_source_unit_quality_summary(
        run_id="run",
        input_mode="source-artifacts",
        cohort_path=tmp_path / "cohort.jsonl",
        database_path=tmp_path / "db.sqlite",
        semantic_index_path=None,
        records_path=tmp_path / "records.jsonl",
        selected_records=[{}, {}],
        audit_records=records,
        started_at=started_at,
        completed_at=started_at,
    )

    assert summary["quality_bucket_counts"] == {
        "full_text_rich": 1,
        "recaptcha_or_js": 1,
    }
    assert summary["routing_recommendation_counts"] == {
        "use_for_segmented_classification": 1,
        "block_before_llm": 1,
    }
    assert summary["selected_artifact_type_counts"] == {"pmc_nxml": 1, "pmc_html": 1}
    assert summary["legacy_study_type_counts"] == {
        "Clinical Trial": 1,
        "Meta-analysis": 1,
    }
    assert summary["needs_source_repair_count"] == 1
