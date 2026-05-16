from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewItemStatus = Literal["open", "in_review", "resolved", "dismissed"]
IdentityDecision = Literal[
    "confirmed_identity",
    "corrected_identity",
    "not_same_publication",
    "unresolved",
]


class ReviewQueueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue_type: str
    total_items: int
    open_items: int = 0
    in_review_items: int = 0
    resolved_items: int = 0
    dismissed_items: int = 0


class PublicationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: str
    primary_title: str | None = None
    publication_year: int | None = None
    canonical_url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    legacy_study_id: str
    legacy_study_type: str | None = None
    review_state: str


class ReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_item_id: str
    queue_type: str
    status: ReviewItemStatus
    priority_tier: str
    priority_score: float
    assignee: str | None = None
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    publication: PublicationSummary


class PublicationIdentitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_identity_id: str
    identifier_type: str
    identifier_value: str
    source: str
    confidence: float
    association_state: str


class OntologyLinkSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: str
    entity_id: str
    entity_type: str
    canonical_label: str
    canonical_label_en: str | None = None
    link_type: str
    source: str
    confidence: float
    evidence_text: str | None = None
    review_state: str


class LegacyReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legacy_study_id: str
    title_pt: str | None = None
    title_en: str | None = None
    normalized_title: str | None = None
    legacy_result: str | None = None
    reference_values: dict[str, Any] = Field(default_factory=dict)


class PublicationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication: PublicationSummary
    identities: list[PublicationIdentitySummary] = Field(default_factory=list)
    ontology_links: list[OntologyLinkSummary] = Field(default_factory=list)
    legacy_reference: LegacyReference
    review_items: list[ReviewQueueItem] = Field(default_factory=list)


class ReviewItemStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_item_id: str
    status: ReviewItemStatus
    note: str | None = None


class ReviewItemStatusResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_item_id: str
    previous_status: ReviewItemStatus
    status: ReviewItemStatus
    note: str | None = None
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IdentityReviewDecisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_item_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    decision: IdentityDecision
    reviewed_pmid: str | None = None
    reviewed_pmcid: str | None = None
    reviewed_doi: str | None = None
    reviewed_canonical_url: str | None = None
    rationale: str | None = None
    original_identity_signals: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class IdentityReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_decision_id: str
    review_item_id: str
    document_id: str
    decision_type: str = "legacy_identity"
    reviewer: str
    decision: IdentityDecision
    reviewed_pmid: str | None = None
    reviewed_pmcid: str | None = None
    reviewed_doi: str | None = None
    reviewed_canonical_url: str | None = None
    rationale: str | None = None
    original_identity_signals: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    provenance: dict[str, Any] = Field(default_factory=dict)
