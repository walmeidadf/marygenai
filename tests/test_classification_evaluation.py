from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.confidence import compute_retrieval_confidence
from marygenai.classification.evaluation import (
    evaluate_classification_run,
    structured_source_contradiction,
    study_design_disagreement_status,
    token_ngram_grounding_score,
)
from marygenai.storage import LocalStorage


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_evaluate_classification_run_separates_metrics_and_builds_rerun_input(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    run_dir = data_dir / "normalized/classification_runs"
    run_id = "20260618T105357Z"
    source_path = data_dir / "processed/source.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "A survey assessed memory and executive function in cannabis users.",
        encoding="utf-8",
    )
    sample_row = {
        "sample_id": "sample:1",
        "sample_run_id": "sample-run",
        "sample_reason": "test",
        "strata": {},
        "corpus_record": {
            "document_id": "publication:pmid:1",
            "legacy_study_id": "1",
            "primary_title": "Cannabis cognition survey",
            "publication_year": 2024,
            "pmid": "1",
            "pmcid": None,
            "doi": None,
            "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/1",
            "legacy_study_type": "Metanálise",
            "legacy_result": "Positivo",
            "medical_condition_labels": ["Cognitive Dysfunction"],
            "organ_system_labels": ["Nervous system"],
            "cannabinoid_labels": ["Cannabis"],
            "source_strategy": "test",
            "source_url": "https://example.org",
            "source_text_path": str(source_path),
            "raw_payload_path": None,
            "extracted_text_chars": 64,
            "scientific_section_hit_count": 1,
            "cannabinoid_term_hit_count": 1,
            "source_ready": True,
            "classification_ready": True,
            "classification_dataset_split": "strict_classification_ready",
            "trust_level": "source_text_available",
            "provenance": {},
        },
        "provenance": {},
    }
    input_path = run_dir / "sample.jsonl"
    write_jsonl(input_path, [sample_row])
    record = {
        "classification_id": "classification:run:1",
        "document_id": "publication:pmid:1",
        "classification_run_id": run_id,
        "schema_version": "candidate_study_classification.v2",
        "extractor_name": "test",
        "extractor_version": "1",
        "model_provider": "openai",
        "model_name": "test-model",
        "prompt_version": "candidate_study_classification_prompt.v2",
        "source_text_path": str(source_path),
        "source_text_sha256": "a" * 64,
        "created_at": "2026-06-18T00:00:00Z",
        "study_design_category": "clinical_trial",
        "evidence_context": "human_observational",
        "medical_conditions": [{"free_text_label": "Cognitive Dysfunction"}],
        "cannabinoids_or_exposures": [{"free_text_label": "Cannabis"}],
        "intervention_or_exposure_role": "cannabis_use_or_dependence",
        "population_or_model": {"category": "adult_humans"},
        "outcome_domains": ["cognition"],
        "overall_direction": "mixed",
        "classification_confidence": "medium",
        "evidence_spans": [
            {
                "section": "Abstract",
                "text": "memory and executive function",
                "source_text_path": str(source_path),
            }
        ],
        "supporting_sections": ["Abstract"],
        "missing_or_uncertain_fields": ["overall_direction exact effect is unclear"],
        "warnings": [],
        "provenance": {"does_not_mutate_sqlite": True},
    }
    records_path = run_dir / f"{run_id}_candidate_classification_records.jsonl"
    errors_path = run_dir / f"{run_id}_candidate_classification_errors.jsonl"
    raw_path = run_dir / f"{run_id}_candidate_classification_raw_responses.jsonl"
    summary_path = run_dir / f"{run_id}_candidate_classification_summary.json"
    write_jsonl(records_path, [record])
    write_jsonl(errors_path, [])
    write_jsonl(
        raw_path,
        [
            {
                "document_id": "publication:pmid:1",
                "status_code": 200,
                "attempts": [{"attempt": 1, "status_code": 200}],
                "response_json": {
                    "choices": [{"message": {"content": json.dumps(record)}}]
                },
            }
        ],
    )
    write_json(
        summary_path,
        {
            "input_path": str(input_path),
            "usage": {"total_tokens": 100},
            "latency_seconds": {"total": 1.0},
        },
    )
    legacy_path = (
        data_dir
        / "normalized/legacy_english_context/20260618T000000Z_legacy_english_context_records.jsonl"
    )
    write_jsonl(
        legacy_path,
        [
            {
                "context_id": "legacy:1",
                "document_matches": [{"document_id": "publication:pmid:1"}],
                "pmid": "1",
                "type_of_study": "Meta-analysis",
                "study_result": "Positive",
            }
        ],
    )

    result = evaluate_classification_run(
        storage=LocalStorage(data_dir),
        records_path=records_path,
        legacy_context_path=legacy_path,
        evaluation_run_id="20260618T120000Z",
        estimated_cost_usd=0.01,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    targeted_rows = [
        json.loads(line)
        for line in Path(result["targeted_rerun_input_path"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert report["technical_validity"]["http_200_responses"] == 1
    assert report["retrieval_utility"]["records_with_evidence_spans"] == 1
    assert report["retrieval_utility"]["evidence_spans_exactly_grounded_in_source_text"] == 1
    assert (
        report["retrieval_utility"]["evidence_spans_grounded_with_extraction_tolerance"]
        == 1
    )
    assert report["retrieval_utility"]["machine_readable_uncertainty_records"] == 0
    assert report["inference_quality"]["study_design_disagreements"] == 1
    assert report["inference_quality"]["study_design_disagreement_status_counts"] == {
        "unresolved_disagreement": 1
    }
    assert report["retrieval_confidence"]["records"] == 1
    assert report["retrieval_confidence"]["band_counts"] == {"low": 1}
    assert report["rerun_document_count"] == 1
    assert targeted_rows == [sample_row]


def test_token_ngram_grounding_tolerates_extraction_artifacts() -> None:
    source_text = (
        "The study assessed three months of treatment UNIVERSITY OF EXAMPLE "
        "on executive function and memory."
    )
    evidence_text = (
        "The study assessed three months of treatment on executive function and memory."
    )

    assert token_ngram_grounding_score(source_text, evidence_text) >= 0.8


def test_study_design_disagreement_status_distinguishes_resolved_conflicts() -> None:
    survey_status = study_design_disagreement_status(
        expected_design="meta_analysis",
        predicted_design="other",
        predicted_subtype="survey",
        title="A national survey of clinician perceptions",
        evidence_spans=[],
    )
    refinement_status = study_design_disagreement_status(
        expected_design="meta_analysis",
        predicted_design="clinical_meta_analysis",
        predicted_subtype="systematic_review",
        title="Systematic review and meta-analysis of clinical trials",
        evidence_spans=[],
    )

    assert survey_status == "source_supported_override"
    assert refinement_status == "compatible_refinement"


def test_structured_contradiction_uses_document_title_not_included_studies() -> None:
    assert (
        structured_source_contradiction(
            predicted_subtype=None,
            title="A scoping review of medical cannabis",
        )
        is False
    )
    assert (
        structured_source_contradiction(
            predicted_subtype="systematic_review",
            title="A systematic review and meta-analysis of observational studies",
        )
        is False
    )
    assert (
        structured_source_contradiction(
            predicted_subtype="systematic_review",
            title="A scoping review of medical cannabis",
        )
        is True
    )


def test_retrieval_confidence_ranks_grounded_consistent_record_higher() -> None:
    base_record = {
        "document_id": "publication:pmid:1",
        "schema_version": "candidate_study_classification.v3",
        "model_provider": "openai",
        "model_name": "test-model",
        "prompt_version": "test-prompt",
        "source_text_path": "data/source.txt",
        "source_text_sha256": "a" * 64,
        "provenance": {"method": "test"},
        "study_design_category": "meta_analysis",
        "study_design_subtype": "systematic_review",
        "evidence_context": "review_or_synthesis",
        "medical_conditions": [{"free_text_label": "Pain"}],
        "cannabinoids_or_exposures": [{"free_text_label": "CBD"}],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {"category": "adult_humans"},
        "outcome_domains": ["efficacy"],
        "overall_direction": "beneficial",
        "classification_confidence": "medium",
        "missing_or_uncertain_fields": [],
    }
    source_record = {
        "classification_ready": True,
        "source_ready": True,
        "scientific_section_hit_count": 5,
        "extracted_text_chars": 12_000,
    }
    raw_response = {
        "status_code": 200,
        "attempts": [{"attempt": 1, "status_code": 200}],
    }
    strong = compute_retrieval_confidence(
        record=base_record,
        source_record=source_record,
        raw_response=raw_response,
        exact_grounded=3,
        tolerant_grounded=3,
        total_spans=3,
        disagreement_status="exact_match",
        structured_contradiction=False,
        uncertainty_is_machine_readable=True,
    )
    weak_record = {
        **base_record,
        "document_id": "publication:pmid:2",
        "cannabinoids_or_exposures": [],
        "outcome_domains": [],
        "missing_or_uncertain_fields": [
            "cannabinoids_or_exposures",
            "outcome_domains",
        ],
    }
    weak = compute_retrieval_confidence(
        record=weak_record,
        source_record={
            "classification_ready": False,
            "source_ready": True,
            "scientific_section_hit_count": 1,
            "extracted_text_chars": 1_000,
        },
        raw_response={
            "status_code": 200,
            "attempts": [
                {"attempt": 1, "error": "timeout"},
                {"attempt": 2, "status_code": 200},
            ],
        },
        exact_grounded=0,
        tolerant_grounded=1,
        total_spans=3,
        disagreement_status="unresolved_disagreement",
        structured_contradiction=True,
        uncertainty_is_machine_readable=True,
    )

    assert strong["score"] > weak["score"]
    assert strong["high_precision_score"] > weak["high_precision_score"]
    assert weak["broad_recall_score"] > weak["high_precision_score"]
    assert "structured_source_contradiction" in weak["reasons"]


def test_retrieval_confidence_is_sensitive_to_source_readiness() -> None:
    record = {
        "document_id": "publication:pmid:1",
        "schema_version": "candidate_study_classification.v3",
        "model_provider": "openai",
        "model_name": "test-model",
        "prompt_version": "test-prompt",
        "source_text_path": "data/source.txt",
        "source_text_sha256": "a" * 64,
        "provenance": {"method": "test"},
        "study_design_category": "meta_analysis",
        "study_design_subtype": "systematic_review",
        "evidence_context": "review_or_synthesis",
        "medical_conditions": [{"free_text_label": "Pain"}],
        "cannabinoids_or_exposures": [{"free_text_label": "CBD"}],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {"category": "adult_humans"},
        "outcome_domains": ["efficacy"],
        "overall_direction": "beneficial",
        "classification_confidence": "medium",
        "missing_or_uncertain_fields": [],
    }
    common = {
        "record": record,
        "raw_response": {
            "status_code": 200,
            "attempts": [{"attempt": 1, "status_code": 200}],
        },
        "exact_grounded": 2,
        "tolerant_grounded": 2,
        "total_spans": 2,
        "disagreement_status": "exact_match",
        "structured_contradiction": False,
        "uncertainty_is_machine_readable": True,
    }
    strict = compute_retrieval_confidence(
        **common,
        source_record={
            "classification_ready": True,
            "source_ready": True,
            "scientific_section_hit_count": 4,
            "extracted_text_chars": 8_000,
        },
    )
    broad_only = compute_retrieval_confidence(
        **common,
        source_record={
            "classification_ready": False,
            "source_ready": True,
            "scientific_section_hit_count": 1,
            "extracted_text_chars": 2_000,
        },
    )

    assert strict["score"] > broad_only["score"]
    assert "source_not_strict_classification_ready" in broad_only["reasons"]


def test_model_declared_confidence_does_not_change_computed_score() -> None:
    record = {
        "document_id": "publication:pmid:1",
        "schema_version": "candidate_study_classification.v3",
        "model_provider": "openai",
        "model_name": "test-model",
        "prompt_version": "test-prompt",
        "source_text_path": "data/source.txt",
        "source_text_sha256": "a" * 64,
        "provenance": {"method": "test"},
        "study_design_category": "meta_analysis",
        "study_design_subtype": "systematic_review",
        "evidence_context": "review_or_synthesis",
        "medical_conditions": [{"free_text_label": "Pain"}],
        "cannabinoids_or_exposures": [{"free_text_label": "CBD"}],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {"category": "adult_humans"},
        "outcome_domains": ["efficacy"],
        "overall_direction": "beneficial",
        "missing_or_uncertain_fields": [],
    }
    common = {
        "source_record": {
            "classification_ready": True,
            "source_ready": True,
            "scientific_section_hit_count": 4,
            "extracted_text_chars": 8_000,
        },
        "raw_response": {
            "status_code": 200,
            "attempts": [{"attempt": 1, "status_code": 200}],
        },
        "exact_grounded": 2,
        "tolerant_grounded": 2,
        "total_spans": 2,
        "disagreement_status": "exact_match",
        "structured_contradiction": False,
        "uncertainty_is_machine_readable": True,
    }
    low = compute_retrieval_confidence(
        record={**record, "classification_confidence": "low"},
        **common,
    )
    high = compute_retrieval_confidence(
        record={**record, "classification_confidence": "high"},
        **common,
    )

    assert low["score"] == high["score"]
    assert low["model_declared_classification_confidence"] == "low"
    assert high["model_declared_classification_confidence"] == "high"
