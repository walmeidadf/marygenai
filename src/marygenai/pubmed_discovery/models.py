from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PubMedLegacyIdentityStatus = Literal[
    "in_legacy_exact",
    "possible_legacy_match",
    "needs_manual_identity_review",
    "new_candidate",
]


class PubMedDiscoveryWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datetype: str = "pdat"
    mindate: str
    maxdate: str
    overlap_years: int
    legacy_max_publication_year: int | None = None


class PubMedCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    pmid: str
    doi: str | None = None
    pmcid: str | None = None
    canonical_url: str
    title: str | None = None
    normalized_title: str | None = None
    abstract: str | None = None
    journal: str | None = None
    publication_date: str | None = None
    publication_year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    chemicals: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    article_ids: dict[str, str] = Field(default_factory=dict)
    query_names: list[str] = Field(default_factory=list)
    cannabinoid_focus: Literal[
        "direct_title_or_indexed",
        "abstract_only",
        "no_cannabinoid_signal",
    ]
    study_design: str | None = None
    study_design_rank: int = 0
    priority_score: float
    priority_tier: str
    score_reasons: list[str] = Field(default_factory=list)
    full_text_review_priority: str
    identity_status: PubMedLegacyIdentityStatus
    legacy_match_type: str | None = None
    legacy_match_confidence: float = 0.0
    legacy_document_ids: list[str] = Field(default_factory=list)
    legacy_study_ids: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    review_state: Literal["needs_review"] = "needs_review"
    provenance: dict[str, Any] = Field(default_factory=dict)


class PubMedDiscoverySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    source: str = "pubmed"
    method: str = "legacy_anchored_pubmed_discovery"
    fetched_at: str
    window: PubMedDiscoveryWindow
    query_count: int
    records_after_dedupe: int
    identity_status_counts: dict[str, int]
    cannabinoid_focus_counts: dict[str, int]
    output_paths: dict[str, str]


class PubMedLegacyIndexRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    legacy_study_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    normalized_title: str | None = None
    publication_year: int | None = None


def default_pubmed_window(
    *,
    legacy_max_publication_year: int | None,
    today: date,
    overlap_years: int = 1,
) -> PubMedDiscoveryWindow:
    if legacy_max_publication_year is None:
        start_year = today.year - overlap_years
    else:
        start_year = legacy_max_publication_year - overlap_years
    return PubMedDiscoveryWindow(
        datetype="pdat",
        mindate=f"{start_year}/01/01",
        maxdate=today.strftime("%Y/%m/%d"),
        overlap_years=overlap_years,
        legacy_max_publication_year=legacy_max_publication_year,
    )
