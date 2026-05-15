from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["publication", "clinical_trial_record", "drug_interaction_document", "pdf"]
ReviewState = Literal["trusted_legacy_reference", "needs_review"]
OntologyEntityType = Literal[
    "cannabinoid",
    "medical_condition",
    "organ_system",
    "terpene",
    "glossary_term",
]


class Provenance(BaseModel):
    source: str
    source_file: str
    source_row_number: int
    method: str
    run_id: str


class LegacySourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_record_id: str
    source: str = "legacy_cannadocs"
    source_table: str
    legacy_id: str | None = None
    row_number: int
    payload_hash: str
    raw_payload: dict[str, Any]
    provenance: Provenance


class PublicationIdentity(BaseModel):
    identifier_type: Literal[
        "pmid",
        "pmcid",
        "doi",
        "canonical_url",
        "normalized_title",
        "legacy_id",
    ]
    identifier_value: str
    source: str = "legacy_cannadocs"
    confidence: float
    association_state: Literal["trusted_legacy_reference", "needs_manual_identity_review"]


class CanonicalPublicationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_type: DocumentType = "publication"
    primary_title: str | None = None
    title_pt: str | None = None
    title_en: str | None = None
    normalized_title: str | None = None
    publication_year: int | None = None
    canonical_url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    legacy_study_id: str
    legacy_study_type: str | None = None
    legacy_result: str | None = None
    legacy_reference_values: dict[str, Any]
    identities: list[PublicationIdentity]
    review_state: ReviewState = "trusted_legacy_reference"
    provenance: Provenance


class OntologyEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    entity_type: OntologyEntityType
    canonical_label: str
    canonical_label_en: str | None = None
    slug: str | None = None
    aliases: list[str] = Field(default_factory=list)
    descriptions: dict[str, str] = Field(default_factory=dict)
    legacy_fields: dict[str, Any]
    review_state: ReviewState = "trusted_legacy_reference"
    provenance: Provenance


class DocumentOntologyLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link_id: str
    document_id: str
    legacy_study_id: str
    entity_id: str
    entity_type: OntologyEntityType
    link_type: Literal["legacy_study_reference"] = "legacy_study_reference"
    source: str = "legacy_cannadocs"
    confidence: float = 1.0
    evidence_text: str | None = None
    review_state: ReviewState = "trusted_legacy_reference"
    provenance: Provenance


class OutputArtifact(BaseModel):
    path: str
    record_count: int
    sha256: str


class InputArtifact(BaseModel):
    path: str
    sha256: str
    size_bytes: int


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    job_type: str = "initial_load"
    source: str = "legacy_cannadocs"
    started_at: datetime
    completed_at: datetime
    status: Literal["succeeded", "failed"]
    software_version: str
    input_artifacts: list[InputArtifact]
    output_artifacts: list[OutputArtifact]
    counts: dict[str, int]
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class InitialLoadResult(BaseModel):
    run_id: str
    manifest_path: Path
    output_paths: dict[str, Path]
    counts: dict[str, int]
