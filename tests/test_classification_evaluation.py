from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.evaluation import (
    evaluate_classification_run,
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
