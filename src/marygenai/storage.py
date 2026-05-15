from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

LOCAL_DATA_DIRECTORIES = (
    "raw/legacy/studies",
    "raw/legacy/ontology",
    "raw/pubmed/esearch",
    "raw/pubmed/efetch",
    "raw/pmc/html",
    "raw/pmc/xml",
    "raw/europe_pmc/metadata",
    "raw/europe_pmc/full_text_xml",
    "raw/unpaywall/doi",
    "raw/clinical_trials/studies",
    "raw/icite/pmid_batches",
    "raw/semantic_scholar/papers",
    "raw/drug_interactions/source_payloads",
    "raw/pdf/samples",
    "staging/source_records/legacy",
    "staging/identity_resolution",
    "staging/access_resolution",
    "staging/extraction_candidates",
    "normalized/ontology/cannabinoids",
    "normalized/ontology/medical_conditions",
    "normalized/ontology/pathologies",
    "normalized/ontology/organ_systems",
    "normalized/ontology/terpenes",
    "normalized/ontology/glossary_terms",
    "normalized/ontology/ontology_mappings",
    "normalized/publications",
    "normalized/clinical_trial_records",
    "normalized/drug_interaction_documents",
    "normalized/publication_enrichments",
    "normalized/review_items",
    "reviewed/snapshots",
    "reviewed/reviewed_fields",
    "reviewed/knowledge_exports",
    "manifests/runs",
    "manifests/source_windows",
    "manifests/file_hashes",
    "db",
)


class JsonSerializable(Protocol):
    def model_dump(self, *, mode: str = "python") -> dict[str, Any]: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def ensure_layout(self) -> list[Path]:
        created_paths: list[Path] = []
        for directory in LOCAL_DATA_DIRECTORIES:
            path = self.root / directory
            path.mkdir(parents=True, exist_ok=True)
            created_paths.append(path)
        return created_paths

    def path(self, relative_path: Path | str) -> Path:
        return self.root / relative_path

    def write_jsonl(self, relative_path: Path | str, records: Iterable[JsonSerializable]) -> Path:
        output_path = self.path(relative_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as file:
            for record in records:
                serialized = json.dumps(
                    record.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                )
                file.write(serialized)
                file.write("\n")
        return output_path

    def write_json(self, relative_path: Path | str, payload: BaseModel | dict[str, Any]) -> Path:
        output_path = self.path(relative_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, BaseModel):
            value = payload.model_dump(mode="json")
        else:
            value = payload
        output_path.write_text(
            json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path
