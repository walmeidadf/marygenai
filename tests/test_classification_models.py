from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from marygenai.classification.models import (
    CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION,
    CandidateClassificationLabel,
    CandidateStudyClassification,
    EvidenceSpan,
    PopulationOrModel,
)


def valid_classification_payload() -> dict:
    return {
        "classification_id": "classification:run:publication:pmid:1",
        "document_id": "publication:pmid:1",
        "classification_run_id": "classification_run:test",
        "extractor_name": "marygenai_candidate_classifier",
        "extractor_version": "0.1.0",
        "model_provider": "openai",
        "model_name": "gpt-test",
        "prompt_version": "candidate_study_classification_prompt.v3",
        "source_text_path": "data/processed/source.txt",
        "source_text_sha256": "a" * 64,
        "created_at": datetime(2026, 6, 15, tzinfo=UTC),
        "study_design_category": "double_blind_clinical_trial",
        "study_design_subtype": "pilot_study",
        "evidence_context": "human_clinical",
        "medical_conditions": [
            {
                "normalized_label": "Pain",
                "free_text_label": "chronic pain",
                "ontology_entity_id": "ontology:medical_condition:pain",
                "confidence": "medium",
                "evidence_text": "Participants had chronic pain.",
            }
        ],
        "cannabinoids_or_exposures": [
            {
                "normalized_label": "Cannabidiol (CBD)",
                "free_text_label": "CBD",
                "confidence": "high",
            }
        ],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {
            "category": "adult_humans",
            "description": "Adult human participants",
        },
        "outcome_domains": ["efficacy", "safety"],
        "overall_direction": "mixed",
        "classification_confidence": "medium",
        "evidence_spans": [
            {
                "section": "Methods",
                "text": "Participants were randomized to CBD or placebo.",
                "char_start": 10,
                "char_end": 56,
                "source_text_path": "data/processed/source.txt",
            }
        ],
        "supporting_sections": ["Methods", "Results"],
        "missing_or_uncertain_fields": [],
        "warnings": [],
        "provenance": {
            "does_not_mutate_sqlite": True,
            "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
        },
    }


def test_candidate_study_classification_accepts_valid_payload() -> None:
    record = CandidateStudyClassification.model_validate(valid_classification_payload())

    assert record.schema_version == CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION
    assert record.requires_human_review is True
    assert record.review_state == "needs_review"
    assert record.medical_conditions[0].normalized_label == "Pain"
    assert record.evidence_spans[0].section == "Methods"


def test_candidate_study_classification_rejects_extra_fields_and_bad_enums() -> None:
    payload = valid_classification_payload()
    payload["study_design_category"] = "definitely_a_trial"
    payload["human_reviewed"] = True

    with pytest.raises(ValidationError) as exc_info:
        CandidateStudyClassification.model_validate(payload)

    errors = exc_info.value.errors()
    assert any(error["type"] == "literal_error" for error in errors)
    assert any(error["type"] == "extra_forbidden" for error in errors)


def test_candidate_study_classification_requires_candidate_review_state() -> None:
    payload = valid_classification_payload()
    payload["requires_human_review"] = False
    payload["review_state"] = "human_reviewed"

    with pytest.raises(ValidationError):
        CandidateStudyClassification.model_validate(payload)


def test_candidate_study_classification_validates_source_text_hash() -> None:
    payload = valid_classification_payload()
    payload["source_text_sha256"] = "not-a-sha"

    with pytest.raises(ValidationError):
        CandidateStudyClassification.model_validate(payload)


def test_evidence_span_rejects_reversed_offsets() -> None:
    with pytest.raises(ValidationError):
        EvidenceSpan(text="Evidence text", char_start=20, char_end=10)


def test_cannot_determine_outputs_must_explain_uncertainty() -> None:
    payload = valid_classification_payload()
    payload["study_design_category"] = "cannot_determine"

    with pytest.raises(ValidationError, match="missing_or_uncertain_fields"):
        CandidateStudyClassification.model_validate(payload)

    payload["missing_or_uncertain_fields"] = ["study_design_category"]
    record = CandidateStudyClassification.model_validate(payload)

    assert record.study_design_category == "cannot_determine"


def test_uncertainty_fields_are_strictly_field_scoped() -> None:
    payload = valid_classification_payload()
    payload["missing_or_uncertain_fields"] = [
        "overall_direction exact effect size is unclear"
    ]

    with pytest.raises(ValidationError, match="literal"):
        CandidateStudyClassification.model_validate(payload)


def test_empty_list_fields_require_machine_readable_uncertainty() -> None:
    payload = valid_classification_payload()
    payload["outcome_domains"] = []

    with pytest.raises(ValidationError, match="outcome_domains"):
        CandidateStudyClassification.model_validate(payload)

    payload["missing_or_uncertain_fields"] = ["outcome_domains"]
    record = CandidateStudyClassification.model_validate(payload)

    assert record.outcome_domains == []


def test_cognition_is_an_official_outcome_domain() -> None:
    payload = valid_classification_payload()
    payload["outcome_domains"] = ["cognition"]

    record = CandidateStudyClassification.model_validate(payload)

    assert record.outcome_domains == ["cognition"]


def test_cannot_determine_is_rejected_inside_outcome_domains() -> None:
    payload = valid_classification_payload()
    payload["outcome_domains"] = ["cannot_determine"]

    with pytest.raises(ValidationError):
        CandidateStudyClassification.model_validate(payload)


def test_nested_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CandidateClassificationLabel(free_text_label="CBD", confidence="high", extra="nope")

    with pytest.raises(ValidationError):
        PopulationOrModel(category="adult_humans", extra="nope")
