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
