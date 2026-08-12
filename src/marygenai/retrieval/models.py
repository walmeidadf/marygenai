from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RETRIEVAL_INDEX_SCHEMA_VERSION = "candidate_retrieval_index.v2"
RETRIEVAL_API_VERSION = "candidate_retrieval_api.v2"
RETRIEVAL_CONFIDENCE_SEMANTICS = (
    "Deterministic heuristic retrieval-ranking signal; not a calibrated probability "
    "and not clinical evidence strength."
)
TRUST_NOTICE = (
    "Candidate retrieval metadata, not reviewed clinical truth, medical advice, "
    "or a treatment recommendation."
)
INDEX_LIMITATIONS = (
    "The index contains AI-classified candidate evidence, not reviewed knowledge.",
    "The indexed candidate corpus is bounded and may not be representative.",
    "The v3 schema does not structure dose, route, comparator, duration, or specific outcomes.",
    "Classification confidence is categorical and is not a calibrated probability.",
    "Retrieval confidence is a deterministic heuristic ranking signal, not evidence strength.",
)
ZERO_RESULT_NOTICE = (
    "No candidate records were retrieved from the current MaryGenAI index for the "
    "effective query. This does not establish absence from the scientific literature."
)


class FilterGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[str] = Field(
        min_length=1,
        max_length=50,
        description=(
            "English retrieval labels or enum values. Translate non-English clinical "
            "concepts before constructing filters."
        ),
    )
    match: Literal["any", "all"] = "any"

    @field_validator("values")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("Filter values must not be empty.")
            if stripped not in normalized:
                normalized.append(stripped)
        return normalized


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    medical_conditions: FilterGroup | None = None
    cannabinoids_or_exposures: FilterGroup | None = None
    study_design_categories: FilterGroup | None = None
    study_design_subtypes: FilterGroup | None = None
    evidence_contexts: FilterGroup | None = None
    population_categories: FilterGroup | None = None
    intervention_or_exposure_roles: FilterGroup | None = None
    outcome_domains: FilterGroup | None = None
    overall_directions: FilterGroup | None = None
    classification_confidences: FilterGroup | None = None
    review_states: FilterGroup | None = None
    publication_year_from: int | None = Field(default=None, ge=1800, le=2200)
    publication_year_to: int | None = Field(default=None, ge=1800, le=2200)
    has_uncertainty: bool | None = None

    @model_validator(mode="after")
    def validate_year_range(self) -> SearchFilters:
        if (
            self.publication_year_from is not None
            and self.publication_year_to is not None
            and self.publication_year_from > self.publication_year_to
        ):
            raise ValueError("publication_year_from must not exceed publication_year_to.")
        return self


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Concise English retrieval terms. Translate a non-English user question before "
            "calling search; the indexed source and candidate metadata are primarily English."
        ),
    )
    question_type: (
        Literal[
            "background",
            "therapy",
            "harm_or_etiology",
            "diagnosis",
            "prognosis",
            "prevention",
            "prevalence",
            "mechanism",
            "patient_experience",
        ]
        | None
    ) = None
    filters: SearchFilters = Field(
        default_factory=SearchFilters,
        description=(
            "Structured retrieval filters using English labels or documented enum values."
        ),
    )
    unsupported_dimensions: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)
    cursor: str | None = None

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("unsupported_dimensions")
    @classmethod
    def normalize_dimensions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized


class TrustBoundary(BaseModel):
    trust_level: Literal["ai_classified_candidate"] = "ai_classified_candidate"
    review_state: Literal["needs_review"] = "needs_review"
    requires_human_review: Literal[True] = True
    medical_advice: Literal[False] = False
    notice: str = TRUST_NOTICE


class SearchPresentationContract(BaseModel):
    """Machine-readable host rules for presenting candidate retrieval results."""

    result_label: Literal["AI-classified candidate matches"] = (
        "AI-classified candidate matches"
    )
    zero_result_message: str = ZERO_RESULT_NOTICE
    literature_absence_inference_allowed: Literal[False] = False
    preferred_access_url_required_for_cited_results: Literal[True] = True
    preferred_access_url_path: Literal["projected_identity.preferred_access_url"] = (
        "projected_identity.preferred_access_url"
    )
    study_detail_required_for_detailed_evidence_claims: Literal[True] = True
    study_detail_tool: Literal["get_study"] = "get_study"
    distinguish_direct_from_tangential_matches: Literal[True] = True


class SourceIdentity(BaseModel):
    document_id: str
    title: str | None = None
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    canonical_url: str | None = None
    source_url: str | None = None
    publication_year: int | None = None


class IdentifierProvenance(BaseModel):
    source_kind: str
    source_artifact_path: str
    extraction_method: str
    raw_value: str
    normalization_rule: str | None = None


class IdentifierCandidateValue(BaseModel):
    value: str
    provenance: list[IdentifierProvenance]


class ProjectedIdentifier(BaseModel):
    identifier_type: Literal["pmid", "pmcid", "doi"]
    value: str | None = None
    status: Literal["accepted", "conflict", "unavailable"]
    candidate_values: list[IdentifierCandidateValue]


class IdentifierConflict(BaseModel):
    identifier_type: Literal["pmid", "pmcid", "doi"]
    candidate_values: list[IdentifierCandidateValue]


class IdentityUrl(BaseModel):
    label: str
    url: str
    url_kind: Literal["pubmed", "pmc_full_text", "doi", "canonical", "source"]
    physician_facing: bool
    derived_from: dict[str, str] | None = None
    selection_rule: str | None = None


class ProjectedIdentity(BaseModel):
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    status: Literal["consistent", "conflict"]
    identifiers: list[ProjectedIdentifier]
    conflicts: list[IdentifierConflict]
    identity_urls: list[IdentityUrl]
    preferred_access_url: IdentityUrl | None = None


class RetrievalConfidence(BaseModel):
    score: float | None = None
    band: str | None = None
    version: str | None = None
    semantics: str = RETRIEVAL_CONFIDENCE_SEMANTICS


class MatchExplanation(BaseModel):
    matched: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)
    not_represented: list[str] = Field(default_factory=list)


class StudySearchResult(BaseModel):
    document_id: str
    classification_id: str
    source_identity: SourceIdentity
    original_corpus_identity: SourceIdentity
    projected_identity: ProjectedIdentity
    retrieval_metadata: dict[str, Any]
    classification_confidence: str
    retrieval_confidence: RetrievalConfidence
    has_uncertainty: bool
    review_state: str
    trust_boundary: TrustBoundary
    match: MatchExplanation
    detail_uri: str


class SearchTrace(BaseModel):
    question_type: str | None = None
    question_type_applied_as_filter: Literal[False] = False
    query: str | None = None
    query_terms: list[str] = Field(default_factory=list)
    requested_filters: dict[str, Any] = Field(default_factory=dict)
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    unsupported_dimensions: list[str] = Field(default_factory=list)
    relaxations: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    api_version: str = RETRIEVAL_API_VERSION
    total: int
    returned: int
    next_cursor: str | None = None
    search_trace: SearchTrace
    results: list[StudySearchResult]
    presentation_contract: SearchPresentationContract = Field(
        default_factory=SearchPresentationContract,
        description=(
            "Rules the MCP host must follow when describing candidate matches, empty "
            "results, access links, and detailed evidence claims."
        ),
    )
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)


class FacetValue(BaseModel):
    value: str
    match_key: str
    count: int


class FacetsResponse(BaseModel):
    api_version: str = RETRIEVAL_API_VERSION
    total: int
    facets: dict[str, list[FacetValue]]
    search_trace: SearchTrace
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)


class StudyDetailResponse(BaseModel):
    api_version: str = RETRIEVAL_API_VERSION
    document_id: str
    source_identity: SourceIdentity
    original_corpus_identity: SourceIdentity
    projected_identity: ProjectedIdentity
    source_text_path: str
    source_text_sha256: str
    source_trust_level: str | None = None
    candidate_classification: dict[str, Any]
    retrieval_confidence: dict[str, Any] | None = None
    grounding_review: dict[str, Any]
    provenance: dict[str, Any]
    review_state: str
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)


class IndexManifest(BaseModel):
    index_schema_version: str = RETRIEVAL_INDEX_SCHEMA_VERSION
    build_id: str
    built_at: str
    index_path: str
    document_count: int
    classification_run_ids: list[str]
    input_files: list[dict[str, str]]
    source_corpus_path: str
    evaluation_report_paths: list[str]
    inclusion_criteria: list[str] = Field(default_factory=list)
    excluded_document_count: int = 0
    exclusions_path: str | None = None
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)
    limitations: list[str]


class PublicIndexManifest(BaseModel):
    """Path-free manifest contract shared by local and hosted MCP runtimes."""

    index_schema_version: str = RETRIEVAL_INDEX_SCHEMA_VERSION
    build_id: str
    built_at: str
    document_count: int
    classification_run_ids: list[str]
    inclusion_criteria: list[str] = Field(default_factory=list)
    excluded_document_count: int = 0
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)
    limitations: list[str] = Field(default_factory=lambda: list(INDEX_LIMITATIONS))


class SearchCapabilities(BaseModel):
    api_version: str = RETRIEVAL_API_VERSION
    index_schema_version: str
    document_count: int
    classification_run_ids: list[str]
    language_contract: dict[str, Any]
    filter_fields: dict[str, dict[str, Any]]
    question_types: list[str]
    unsupported_v3_dimensions: list[str]
    pagination: dict[str, Any]
    ranking: dict[str, Any]
    presentation_contract: SearchPresentationContract = Field(
        default_factory=SearchPresentationContract
    )
    trust_boundary: TrustBoundary = Field(default_factory=TrustBoundary)
