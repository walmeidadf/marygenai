from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TrustLevel = Literal[
    "source_discovered",
    "metadata_enriched",
    "source_text_available",
    "ai_classified_candidate",
    "human_reviewed",
]


class ClassificationCorpusRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    legacy_study_id: str | None = None
    primary_title: str | None = None
    publication_year: int | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    legacy_study_type: str | None = None
    legacy_result: str | None = None
    medical_condition_labels: list[str] = Field(default_factory=list)
    organ_system_labels: list[str] = Field(default_factory=list)
    cannabinoid_labels: list[str] = Field(default_factory=list)
    source_strategy: str | None = None
    source_url: str | None = None
    source_text_path: str | None = None
    raw_payload_path: str | None = None
    extracted_text_chars: int = 0
    scientific_section_hit_count: int = 0
    cannabinoid_term_hit_count: int = 0
    source_ready: bool = False
    classification_ready: bool = False
    classification_dataset_split: Literal[
        "strict_classification_ready",
        "broader_source_ready",
        "not_source_ready",
    ] = "not_source_ready"
    trust_level: TrustLevel = "source_discovered"
    provenance: dict[str, Any] = Field(default_factory=dict)


class ClassificationSampleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_id: str
    sample_run_id: str
    sample_reason: str
    strata: dict[str, list[str] | str | bool]
    corpus_record: ClassificationCorpusRecord
    provenance: dict[str, Any] = Field(default_factory=dict)


class PubMedArtifactQualityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    source: str
    artifact_type: str
    source_url: str | None = None
    payload_path: str | None = None
    stored_sha256: str | None = None
    computed_sha256: str | None = None
    hash_matches: bool = False
    detected_format: Literal["html", "xml", "unknown"] = "unknown"
    declared_format_matches: bool = False
    artifact_title: str | None = None
    artifact_pmid: str | None = None
    artifact_doi: str | None = None
    title_matches: bool = False
    identifier_matches: bool = False
    identity_verified: bool = False
    extracted_text_chars: int = 0
    scientific_section_hit_count: int = 0
    cannabinoid_term_hit_count: int = 0
    quality_pass: bool = False
    failure_reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class PubMedSourceQualityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    primary_title: str | None = None
    publication_year: int | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    identity_status: str
    cannabinoid_focus: str
    study_design: str | None = None
    study_design_rank: int = 0
    priority_score: float = 0.0
    review_state: str
    artifact_count: int = 0
    artifact_assessments: list[PubMedArtifactQualityAssessment] = Field(default_factory=list)
    selected_artifact_id: str | None = None
    source_quality_gate_pass: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class PubMedCanaryIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_title: str
    publication_year: int
    pmid: str
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str


class PubMedCanaryOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    artifact_id: str
    artifact_type: str
    detected_format: Literal["html", "xml"]
    source_url: str | None = None
    raw_artifact_path: str
    raw_artifact_sha256: str
    extracted_text_path: str
    extracted_text_sha256: str
    extracted_text_chars: int
    extracted_text_bytes: int
    scientific_section_hit_count: int
    cannabinoid_term_hit_count: int


class PubMedCanaryManifestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corpus_version: str
    selection_rank: int
    document_id: str
    identity: PubMedCanaryIdentity
    origin: PubMedCanaryOrigin
    selection_criteria: list[str]
    current_trust_level: Literal["source_text_available"] = "source_text_available"
    classification_output_trust_level: Literal["ai_classified_candidate"] = (
        "ai_classified_candidate"
    )
    review_state: Literal["needs_review"] = "needs_review"
    requires_human_review: Literal[True] = True
    provenance: dict[str, Any] = Field(default_factory=dict)


class PubMedIdentitySet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_title: str | None = None
    publication_year: int | None = None
    pmid: str
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str | None = None


class PubMedIdentityRepairRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["pubmed_source_identity_repair.v1"] = (
        "pubmed_source_identity_repair.v1"
    )
    repair_run_id: str
    selection_rank: int
    document_id: str
    current_identity: PubMedIdentitySet
    resolved_identity: PubMedIdentitySet | None = None
    resolution_status: Literal["resolved", "pubmed_record_missing", "fetch_error"]
    changed_fields: list[str] = Field(default_factory=list)
    source_quality_failure_reasons: list[str] = Field(default_factory=list)
    recommended_action: Literal[
        "reenrich_from_resolved_pmcid",
        "refetch_existing_pmc_route",
        "try_europe_pmc_or_unpaywall",
        "manual_identity_investigation",
    ]
    apply_status: Literal["not_applied"] = "not_applied"
    review_state: Literal["needs_review"] = "needs_review"
    requires_human_review: Literal[True] = True
    provenance: dict[str, Any] = Field(default_factory=dict)
