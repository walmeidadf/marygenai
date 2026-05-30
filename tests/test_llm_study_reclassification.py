import sqlite3
from pathlib import Path

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
    build_span_grounding_audit,
    build_task_packet_record,
    dry_run_summary_comparison_record,
    evidence_summary_output_schema,
    extract_xml_paragraphs,
    load_artifacts_by_document_id,
    normalize_label,
    resolve_provider_models,
    result_direction_matches,
    select_best_full_text_artifact,
    select_evidence_chunks,
    select_micro_extraction_candidates,
    select_stratified_candidates,
    select_task_evidence_spans,
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
