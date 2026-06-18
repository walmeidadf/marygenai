from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION = "candidate_study_classification.v3"

StudyDesignCategory = Literal[
    "meta_analysis",
    "clinical_meta_analysis",
    "clinical_trial",
    "double_blind_clinical_trial",
    "animal_study",
    "laboratory_study",
    "other",
    "cannot_determine",
]
StudyDesignSubtype = Literal[
    "systematic_review",
    "scoping_review",
    "narrative_review",
    "mechanistic_review",
    "survey",
    "case_report_or_series",
    "observational_study",
    "pilot_study",
    "other",
    "cannot_determine",
]
EvidenceContext = Literal[
    "human_clinical",
    "human_observational",
    "animal_preclinical",
    "in_vitro_or_cellular",
    "review_or_synthesis",
    "mixed",
    "cannot_determine",
]
InterventionOrExposureRole = Literal[
    "therapeutic_intervention",
    "recreational_or_nonmedical_exposure",
    "endocannabinoid_system_mechanism",
    "synthetic_or_pharmaceutical_cannabinoid",
    "cannabis_use_or_dependence",
    "cannot_determine",
]
PopulationCategory = Literal[
    "adult_humans",
    "pediatric_humans",
    "animals",
    "cells",
    "mixed",
    "cannot_determine",
]
OutcomeDomain = Literal[
    "efficacy",
    "safety",
    "adverse_events",
    "biomarker",
    "cognition",
    "mechanism",
    "pharmacokinetics",
    "public_health",
    "use_pattern",
]
OverallDirection = Literal[
    "beneficial",
    "harmful",
    "mixed",
    "null",
    "not_applicable",
    "cannot_determine",
]
ClassificationConfidence = Literal["high", "medium", "low"]
CandidateReviewState = Literal["needs_review"]
UncertainFieldName = Literal[
    "study_design_category",
    "study_design_subtype",
    "evidence_context",
    "medical_conditions",
    "cannabinoids_or_exposures",
    "intervention_or_exposure_role",
    "population_or_model",
    "outcome_domains",
    "overall_direction",
    "classification_confidence",
]


class CandidateClassificationLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_label: str | None = None
    free_text_label: str
    ontology_entity_id: str | None = None
    confidence: ClassificationConfidence = "low"
    evidence_text: str | None = None


class PopulationOrModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: PopulationCategory
    description: str | None = None


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str | None = None
    text: str = Field(min_length=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    source_text_path: str | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> EvidenceSpan:
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            msg = "char_end must be greater than or equal to char_start."
            raise ValueError(msg)
        return self


class CandidateStudyClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification_id: str
    document_id: str
    classification_run_id: str
    schema_version: Literal["candidate_study_classification.v3"] = (
        CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION
    )
    extractor_name: str
    extractor_version: str
    model_provider: str
    model_name: str
    prompt_version: str
    source_text_path: str
    source_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime

    study_design_category: StudyDesignCategory
    study_design_subtype: StudyDesignSubtype
    evidence_context: EvidenceContext
    medical_conditions: list[CandidateClassificationLabel] = Field(default_factory=list)
    cannabinoids_or_exposures: list[CandidateClassificationLabel] = Field(default_factory=list)
    intervention_or_exposure_role: InterventionOrExposureRole
    population_or_model: PopulationOrModel
    outcome_domains: list[OutcomeDomain] = Field(default_factory=list)
    overall_direction: OverallDirection
    classification_confidence: ClassificationConfidence
    requires_human_review: Literal[True] = True
    review_state: CandidateReviewState = "needs_review"

    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    supporting_sections: list[str] = Field(default_factory=list)
    missing_or_uncertain_fields: list[UncertainFieldName] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_uncertainty_notes_for_low_information_records(self) -> CandidateStudyClassification:
        required_uncertainty_fields = {
            field_name
            for field_name, cannot_determine in (
                ("study_design_category", self.study_design_category == "cannot_determine"),
                ("study_design_subtype", self.study_design_subtype == "cannot_determine"),
                ("evidence_context", self.evidence_context == "cannot_determine"),
                (
                    "intervention_or_exposure_role",
                    self.intervention_or_exposure_role == "cannot_determine",
                ),
                ("population_or_model", self.population_or_model.category == "cannot_determine"),
                ("overall_direction", self.overall_direction == "cannot_determine"),
                ("medical_conditions", not self.medical_conditions),
                ("cannabinoids_or_exposures", not self.cannabinoids_or_exposures),
                ("outcome_domains", not self.outcome_domains),
            )
            if cannot_determine
        }
        uncertainty_fields = set(self.missing_or_uncertain_fields)
        missing_fields = sorted(required_uncertainty_fields - uncertainty_fields)
        if missing_fields:
            msg = (
                "missing_or_uncertain_fields must include each field with cannot_determine "
                f"or an empty retrieval list: {', '.join(missing_fields)}."
            )
            raise ValueError(msg)
        if len(uncertainty_fields) != len(self.missing_or_uncertain_fields):
            msg = "missing_or_uncertain_fields must not contain duplicate field names."
            raise ValueError(msg)
        return self


class ClassificationRunError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    classification_run_id: str
    document_id: str | None = None
    source_record_id: str | None = None
    error_type: str
    message: str
    provenance: dict[str, Any] = Field(default_factory=dict)


class CandidateClassificationPromptPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    prompt_packet_run_id: str
    document_id: str
    schema_version: Literal["candidate_study_classification.v3"] = (
        CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION
    )
    prompt_version: str
    target_model_provider: str | None = None
    target_model_name: str | None = None
    source_text_path: str
    source_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_text_excerpt: str = Field(min_length=1)
    source_text_excerpt_chars: int
    system_prompt: str = Field(min_length=1)
    user_prompt: str = Field(min_length=1)
    response_json_schema: dict[str, Any]
    corpus_metadata: dict[str, Any]
    created_at: datetime
    provenance: dict[str, Any] = Field(default_factory=dict)
