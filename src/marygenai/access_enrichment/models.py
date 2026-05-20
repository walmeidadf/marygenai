from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AccessSource = Literal["pmc", "europe_pmc", "unpaywall"]
AccessArtifactType = Literal[
    "pmc_nxml",
    "pmc_html",
    "europe_pmc_metadata",
    "europe_pmc_full_text_xml",
    "unpaywall_metadata",
]


class AccessEnrichmentCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    identity_status: str
    cannabinoid_focus: str
    study_design: str | None = None
    priority_score: float
    full_text_review_priority: str


class AccessArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    document_id: str
    source: AccessSource
    artifact_type: AccessArtifactType
    url: str | None = None
    access_class: str
    license: str | None = None
    payload_path: str | None = None
    payload_sha256: str | None = None
    payload_size_bytes: int | None = None
    raw_payload: dict[str, Any] | None = None
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class AccessEnrichmentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    document_id: str
    title: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    identity_status: str
    cannabinoid_focus: str
    study_design: str | None = None
    full_text_review_priority: str
    resolved_access_class: str
    candidate_full_text_urls: list[str] = Field(default_factory=list)
    candidate_pdf_urls: list[str] = Field(default_factory=list)
    artifacts: list[AccessArtifact] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    review_state: Literal["needs_review"] = "needs_review"
    provenance: dict[str, Any] = Field(default_factory=dict)


class AccessEnrichmentResult(BaseModel):
    run_id: str
    manifest_path: str
    output_paths: dict[str, str]
    counts: dict[str, int]
