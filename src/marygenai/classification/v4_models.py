from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BROAD_V4_SCHEMA_VERSION = "broad_v4_candidate_record.v1"
CLINICAL_TOPIC_SCHEMA_VERSION = "clinical_topic_anatomy_organ_system.v1"
CANNABINOID_ROLE_SCHEMA_VERSION = "cannabinoid_identity_scientific_role.v1"
POPULATION_STRUCTURE_SCHEMA_VERSION = "population_sample_geography_study_structure.v1"
OUTCOMES_DIRECTION_SCHEMA_VERSION = "outcomes_overall_direction.v1"
V4_PROMPT_PACKET_SCHEMA_VERSION = "classification_v4_prompt_packet.v2"
MINIMAL_SEMANTIC_RESPONSE_SCHEMA_VERSION = "minimal_semantic_field_response.v1"

FieldConfidence = Literal["high", "medium", "low"]
SemanticFamily = Literal[
    "broad_v4",
    "clinical_topic",
    "cannabinoid_role",
    "population_structure",
    "outcomes_direction",
]
ExtractionMethod = Literal["metadata", "parser", "ontology", "llm", "derived"]
UncertaintyReason = Literal[
    "insufficient_source_evidence",
    "ambiguous_candidates",
    "not_applicable",
    "relation_uncertain",
    "source_conflict",
]


class V4EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    field_name: str
    text: str = Field(min_length=1)
    source_text_path: str
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    extraction_method: str


class V4CandidateValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_value: str | int | None = None
    normalized_label: str
    ontology_entity_id: str | None = None
    scientific_role: str | None = None
    field_confidence: FieldConfidence
    evidence_ids: list[str] = Field(min_length=1)
    extraction_method: ExtractionMethod = "llm"


class V4Uncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    reason: UncertaintyReason
    detail: str


class MinimalSemanticFieldDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    values: list[str | int | bool] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    field_confidence: FieldConfidence
    uncertainty_reason: UncertaintyReason | None = None

    @model_validator(mode="after")
    def validate_evidence_or_uncertainty(self) -> MinimalSemanticFieldDecision:
        if self.values and not self.evidence_ids:
            raise ValueError("Populated semantic values require evidence_ids.")
        if not self.values and self.uncertainty_reason is None:
            raise ValueError("Empty semantic values require uncertainty_reason.")
        return self


class MinimalSemanticFieldResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["minimal_semantic_field_response.v1"] = (
        MINIMAL_SEMANTIC_RESPONSE_SCHEMA_VERSION
    )
    decisions: list[MinimalSemanticFieldDecision]


class ClinicalTopicAnatomyOrganSystem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["clinical_topic_anatomy_organ_system.v1"] = (
        CLINICAL_TOPIC_SCHEMA_VERSION
    )
    medical_conditions: list[V4CandidateValue] = Field(default_factory=list)
    pathologies_or_disease_families: list[V4CandidateValue] = Field(default_factory=list)
    symptoms_or_indications: list[V4CandidateValue] = Field(default_factory=list)
    anatomical_entities: list[V4CandidateValue] = Field(default_factory=list)
    organ_systems: list[V4CandidateValue] = Field(default_factory=list)
    comorbidities: list[V4CandidateValue] = Field(default_factory=list)
    uncertainties: list[V4Uncertainty] = Field(default_factory=list)


class CannabinoidIdentityAndScientificRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cannabinoid_identity_scientific_role.v1"] = (
        CANNABINOID_ROLE_SCHEMA_VERSION
    )
    cannabinoids_or_exposures: list[V4CandidateValue] = Field(default_factory=list)
    principal_role: Literal[
        "intervention",
        "exposure",
        "biomarker",
        "mechanism",
        "comparator",
        "background_mention",
        "not_cannabinoid_focused",
        "cannot_determine",
    ]
    products_or_formulations: list[V4CandidateValue] = Field(default_factory=list)
    routes_of_administration: list[V4CandidateValue] = Field(default_factory=list)
    comparators: list[V4CandidateValue] = Field(default_factory=list)
    uncertainties: list[V4Uncertainty] = Field(default_factory=list)


class PopulationSampleGeographyStudyStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["population_sample_geography_study_structure.v1"] = (
        POPULATION_STRUCTURE_SCHEMA_VERSION
    )
    population_category: Literal[
        "adult_humans",
        "pediatric_humans",
        "animals",
        "cells",
        "mixed",
        "cannot_determine",
    ]
    population_description: str | None = None
    age_groups: list[V4CandidateValue] = Field(default_factory=list)
    sex_or_gender: list[V4CandidateValue] = Field(default_factory=list)
    species: list[V4CandidateValue] = Field(default_factory=list)
    sample_size: int | None = Field(default=None, ge=1)
    sample_size_scope: Literal[
        "enrolled",
        "analyzed",
        "cases",
        "controls",
        "included_studies",
        "animals",
        "cells_or_samples",
        "records_or_charts",
        "other",
        "cannot_determine",
    ]
    sample_size_evidence_ids: list[str] = Field(default_factory=list)
    study_countries: list[V4CandidateValue] = Field(default_factory=list)
    publication_type: Literal[
        "primary_research",
        "review",
        "trial_report",
        "case_report",
        "protocol",
        "other",
        "cannot_determine",
    ]
    study_design_category: Literal[
        "meta_analysis",
        "clinical_meta_analysis",
        "clinical_trial",
        "double_blind_clinical_trial",
        "animal_study",
        "laboratory_study",
        "other",
        "cannot_determine",
    ]
    study_design_subtype: Literal[
        "systematic_review",
        "scoping_review",
        "narrative_review",
        "mechanistic_review",
        "survey",
        "case_report_or_series",
        "observational_study",
        "pilot_study",
        "randomized_trial",
        "in_silico_study",
        "other",
        "cannot_determine",
    ]
    evidence_context: Literal[
        "human_clinical",
        "human_observational",
        "animal_preclinical",
        "in_vitro_or_cellular",
        "in_silico",
        "review_or_synthesis",
        "mixed",
        "cannot_determine",
    ]
    randomization: Literal["yes", "no", "uncertain"]
    blinding: Literal["open_label", "single_blind", "double_blind", "masked", "uncertain"]
    uncertainties: list[V4Uncertainty] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_sample_evidence(self) -> PopulationSampleGeographyStudyStructure:
        if self.sample_size is not None and not self.sample_size_evidence_ids:
            raise ValueError("sample_size_evidence_ids is required when sample_size is populated.")
        return self


class OutcomesAndOverallDirection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["outcomes_overall_direction.v1"] = OUTCOMES_DIRECTION_SCHEMA_VERSION
    outcome_domains: list[
        Literal[
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
    ] = Field(default_factory=list)
    outcome_entities: list[V4CandidateValue] = Field(default_factory=list)
    adverse_events: list[V4CandidateValue] = Field(default_factory=list)
    overall_direction: Literal[
        "beneficial",
        "harmful",
        "mixed",
        "null",
        "not_applicable",
        "cannot_determine",
    ]
    direction_question: str | None = None
    key_findings: list[V4CandidateValue] = Field(default_factory=list)
    uncertainties: list[V4Uncertainty] = Field(default_factory=list)


class BroadV4CandidateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    document_id: str
    classification_run_id: str
    schema_version: Literal["broad_v4_candidate_record.v1"] = BROAD_V4_SCHEMA_VERSION
    source_text_path: str
    source_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_identity: dict[str, Any]
    extractor_name: str
    extractor_version: str
    model_provider: str
    model_name: str
    prompt_version: str
    created_at: datetime
    clinical_topic: ClinicalTopicAnatomyOrganSystem
    cannabinoid_role: CannabinoidIdentityAndScientificRole
    population_structure: PopulationSampleGeographyStudyStructure
    outcomes_direction: OutcomesAndOverallDirection
    evidence: list[V4EvidenceReference]
    warnings: list[str] = Field(default_factory=list)
    requires_human_review: Literal[True] = True
    review_state: Literal["needs_review"] = "needs_review"
    provenance: dict[str, Any]


class V4PromptPacket(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packet_id: str
    packet_run_id: str
    packet_schema_version: Literal["classification_v4_prompt_packet.v2"] = (
        V4_PROMPT_PACKET_SCHEMA_VERSION
    )
    strategy: Literal["broad", "selective"]
    semantic_family: SemanticFamily
    document_id: str
    response_schema_version: str
    prompt_version: str
    target_model_provider: str
    target_model_name: str
    max_completion_tokens: int = Field(ge=1)
    requested_fields: list[str] = Field(min_length=1)
    field_routes: list[dict[str, Any]]
    deterministic_fields: dict[str, Any]
    metadata_candidates: dict[str, Any]
    evidence_candidates: list[V4EvidenceReference]
    source_text_path: str
    source_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    system_prompt: str
    user_prompt: str
    response_json_schema: dict[str, Any]
    estimated_input_tokens: int = Field(ge=1)
    estimated_max_output_tokens: int = Field(ge=1)
    created_at: datetime
    provenance: dict[str, Any]
