from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pymupdf
from lxml import etree, html

from marygenai.classification_corpus.models import (
    ClassificationCorpusRecord,
    ClassificationSampleRecord,
)
from marygenai.storage import LocalStorage

MIN_CLASSIFICATION_TEXT_CHARS = 4_000
SCIENTIFIC_SECTION_TERMS = {
    "abstract",
    "introduction",
    "background",
    "methods",
    "materials",
    "participants",
    "patients",
    "intervention",
    "results",
    "discussion",
    "conclusion",
    "adverse",
    "safety",
}
CANNABINOID_TERMS = {
    "cannabinoid",
    "cannabis",
    "cannabidiol",
    "cbd",
    "thc",
    "tetrahydrocannabinol",
    "endocannabinoid",
}

SOURCE_STRATEGY_PRIORITY = {
    "pmc_oai": 10,
    "pmc_html": 15,
    "pmc_nxml": 20,
    "unpaywall_pdf": 30,
    "augmented_links": 40,
}

CONDITION_STRATA = {
    "pain": ("pain", "dor", "analgesia"),
    "addiction_cannabis": ("addiction", "dependence", "cannabis use", "dependência"),
    "epilepsy": ("epilepsy", "seizure", "epilepsia", "convulsion"),
    "anxiety": ("anxiety", "ansiedade"),
    "depression": ("depression", "depressão"),
    "psychosis": ("psychosis", "schizophrenia", "psicose", "esquizofrenia"),
    "cancer": ("cancer", "câncer", "tumor", "neoplasm"),
    "inflammation": ("inflammation", "inflamação", "inflammatory"),
}

STUDY_TYPE_STRATA = {
    "meta_analysis": ("meta", "metanálise", "meta-analysis"),
    "animal_study": ("animal", "in vivo", "pré-clínico", "preclinical"),
    "laboratory_study": ("laboratory", "in vitro", "laboratório", "cell"),
    "clinical_trial": ("clinical trial", "ensaio clínico"),
    "double_blind_clinical_trial": ("double-blind", "duplo-cego"),
    "clinical_meta_analysis": ("clinical meta", "metanálise clínica"),
}


@dataclass(frozen=True)
class SourceCandidate:
    document_id: str
    source_strategy: str
    source_url: str | None
    source_text_path: str | None
    raw_payload_path: str | None
    extracted_text_chars: int
    scientific_section_hit_count: int
    cannabinoid_term_hit_count: int
    provenance: dict[str, Any]
    force_source_ready: bool = False
    force_classification_ready: bool = False

    @property
    def source_ready(self) -> bool:
        return self.force_source_ready or (
            self.extracted_text_chars >= MIN_CLASSIFICATION_TEXT_CHARS
            and self.scientific_section_hit_count >= 2
        )

    @property
    def classification_ready(self) -> bool:
        return self.force_classification_ready or (
            self.source_ready and self.cannabinoid_term_hit_count >= 1
        )


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def latest_path(data_dir: Path, pattern: str) -> Path:
    paths = sorted(data_dir.glob(pattern))
    if not paths:
        msg = f"No files matched {data_dir / pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def count_term_hits(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_payload_text(path: Path) -> str:
    suffix = path.suffix.lower()
    body = path.read_bytes()
    if suffix == ".pdf" or body[:10].lstrip().startswith(b"%PDF"):
        try:
            document = pymupdf.open(stream=body, filetype="pdf")
        except Exception:  # noqa: BLE001
            return ""
        try:
            return normalize_text("\n".join(page.get_text("text", sort=True) for page in document))
        finally:
            document.close()
    if suffix in {".html", ".htm"} or b"<html" in body[:1000].lower():
        try:
            document = html.fromstring(body)
        except (etree.ParserError, ValueError):
            return ""
        etree.strip_elements(document, "script", "style", "noscript", with_tail=False)
        return normalize_text(document.text_content())
    if suffix in {".xml", ".nxml"} or body[:200].lstrip().startswith(b"<?xml"):
        parser = etree.XMLParser(recover=True, resolve_entities=False)
        try:
            document = etree.fromstring(body, parser=parser)
        except (etree.ParserError, ValueError):
            return ""
        return normalize_text(" ".join(document.itertext()))
    return normalize_text(body.decode("utf-8", errors="ignore"))


def resolve_data_path(data_dir: Path, stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    path = Path(stored_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == data_dir.name:
        return data_dir.parent / path
    return data_dir / path


def load_publications(
    data_dir: Path,
    publications_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    path = publications_path or latest_path(
        data_dir,
        "normalized/publications/*_publication_candidates.jsonl",
    )
    publications: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        document_id = str(row["document_id"])
        if document_id not in publications:
            publications[document_id] = row
    overlay_strong_legacy_identities(data_dir, publications)
    return publications


def overlay_strong_legacy_identities(
    data_dir: Path,
    publications: dict[str, dict[str, Any]],
) -> None:
    try:
        path = latest_path(
            data_dir,
            "normalized/identity_identifier_resolution/*_strong_legacy_identity_records.jsonl",
        )
    except FileNotFoundError:
        return

    publications_by_legacy_id = {
        value_or_none(row.get("legacy_study_id")): row for row in publications.values()
    }
    for row in read_jsonl(path):
        document_id = str(row["document_id"])
        legacy_study_id = value_or_none(row.get("legacy_study_id"))
        existing = publications.get(document_id) or publications_by_legacy_id.get(legacy_study_id)
        merged = dict(existing or {})
        merged.update(
            {
                "document_id": document_id,
                "legacy_study_id": legacy_study_id,
                "primary_title": value_or_none(row.get("title"))
                or value_or_none(merged.get("primary_title")),
                "publication_year": row.get("publication_year") or merged.get("publication_year"),
                "pmid": value_or_none(row.get("pmid")) or value_or_none(merged.get("pmid")),
                "pmcid": value_or_none(row.get("pmcid")) or value_or_none(merged.get("pmcid")),
                "doi": value_or_none(row.get("doi")) or value_or_none(merged.get("doi")),
                "canonical_url": value_or_none(row.get("canonical_url"))
                or value_or_none(merged.get("canonical_url")),
                "legacy_study_type": value_or_none(row.get("legacy_study_type"))
                or value_or_none(merged.get("legacy_study_type")),
                "provenance": {
                    "method": "classification_corpus_publication_identity_overlay",
                    "source_artifact_path": str(path),
                    "source_provenance": row.get("provenance"),
                    "base_publication_provenance": merged.get("provenance"),
                    "does_not_mutate_sqlite": True,
                },
            }
        )
        publications[document_id] = merged


def load_ontology_labels(
    data_dir: Path,
    *,
    entities_path: Path | None = None,
    links_path: Path | None = None,
) -> dict[str, dict[str, list[str]]]:
    resolved_entities_path = entities_path or latest_path(
        data_dir, "normalized/ontology/ontology_mappings/*_ontology_entities.jsonl"
    )
    resolved_links_path = links_path or latest_path(
        data_dir, "normalized/ontology/ontology_mappings/*_document_ontology_links.jsonl"
    )
    entities = {row["entity_id"]: row for row in read_jsonl(resolved_entities_path)}
    labels: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {
            "medical_condition_labels": set(),
            "organ_system_labels": set(),
            "cannabinoid_labels": set(),
        }
    )
    for link in read_jsonl(resolved_links_path):
        entity = entities.get(link.get("entity_id"))
        if not entity:
            continue
        label = value_or_none(entity.get("canonical_label_en")) or value_or_none(
            entity.get("canonical_label")
        )
        if not label:
            continue
        entity_type = link.get("entity_type")
        document_labels = labels[str(link["document_id"])]
        if entity_type == "medical_condition":
            document_labels["medical_condition_labels"].add(label)
        elif entity_type == "organ_system":
            document_labels["organ_system_labels"].add(label)
        elif entity_type == "cannabinoid":
            document_labels["cannabinoid_labels"].add(label)
    return {
        document_id: {key: sorted(values) for key, values in values_by_type.items()}
        for document_id, values_by_type in labels.items()
    }


def load_access_quality_sources(data_dir: Path) -> list[SourceCandidate]:
    try:
        path = latest_path(
            data_dir,
            "normalized/publication_enrichments/access_artifact_quality/"
            "*_access_artifact_quality_records.jsonl",
        )
    except FileNotFoundError:
        return []

    candidates: list[SourceCandidate] = []
    for row in read_jsonl(path):
        if not row.get("is_usable_for_full_text"):
            continue
        payload_path = resolve_data_path(data_dir, value_or_none(row.get("payload_path")))
        text = extract_payload_text(payload_path) if payload_path and payload_path.exists() else ""
        candidates.append(
            SourceCandidate(
                document_id=str(row["document_id"]),
                source_strategy=str(
                    row.get("artifact_type") or row.get("source") or "access_artifact"
                ),
                source_url=value_or_none(row.get("url")),
                source_text_path=str(payload_path) if payload_path else None,
                raw_payload_path=str(payload_path) if payload_path else None,
                extracted_text_chars=len(text),
                scientific_section_hit_count=count_term_hits(text, SCIENTIFIC_SECTION_TERMS),
                cannabinoid_term_hit_count=count_term_hits(text, CANNABINOID_TERMS),
                force_source_ready=True,
                force_classification_ready=True,
                provenance={
                    "method": "classification_corpus_access_quality_source",
                    "source_artifact_path": str(path),
                    "source_run_id": row.get("source_run_id"),
                    "artifact_id": row.get("artifact_id"),
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "classification_corpus_rollup_not_reviewed_knowledge",
                },
            )
        )
    return candidates


def load_official_acquisition_sources(data_dir: Path) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    pattern = (
        "normalized/official_source_fetch_router/"
        "*_official_source_fetch_*_acquire_records.jsonl"
    )
    for path in sorted(data_dir.glob(pattern)):
        for row in read_jsonl(path):
            text_path = resolve_data_path(data_dir, value_or_none(row.get("text_path")))
            raw_path = resolve_data_path(data_dir, value_or_none(row.get("raw_xml_path")))
            candidates.append(
                SourceCandidate(
                    document_id=str(row["document_id"]),
                    source_strategy=str(row.get("strategy") or "official_source_fetch"),
                    source_url=value_or_none(row.get("final_url")) or value_or_none(row.get("url")),
                    source_text_path=str(text_path) if text_path else None,
                    raw_payload_path=str(raw_path) if raw_path else None,
                    extracted_text_chars=int(row.get("extracted_text_chars") or 0),
                    scientific_section_hit_count=int(row.get("scientific_section_hit_count") or 0),
                    cannabinoid_term_hit_count=int(row.get("cannabinoid_term_hit_count") or 0),
                    provenance={
                        "method": "classification_corpus_official_source_fetch_source",
                        "source_artifact_path": str(path),
                        "source_fetch_run_id": (row.get("provenance") or {}).get("run_id"),
                        "failure_reason": row.get("failure_reason"),
                        "does_not_mutate_sqlite": True,
                        "review_boundary": "classification_corpus_rollup_not_reviewed_knowledge",
                    },
                )
            )
    return candidates


def source_sort_key(candidate: SourceCandidate) -> tuple[int, int, int, int]:
    strategy_priority = SOURCE_STRATEGY_PRIORITY.get(candidate.source_strategy, 100)
    return (
        int(candidate.classification_ready),
        int(candidate.source_ready),
        -strategy_priority,
        candidate.extracted_text_chars,
    )


def best_sources_by_document(candidates: list[SourceCandidate]) -> dict[str, SourceCandidate]:
    best: dict[str, SourceCandidate] = {}
    for candidate in candidates:
        existing = best.get(candidate.document_id)
        if existing is None or source_sort_key(candidate) > source_sort_key(existing):
            best[candidate.document_id] = candidate
    return best


def classification_dataset_split(source: SourceCandidate | None) -> str:
    if source is None or not source.source_ready:
        return "not_source_ready"
    if source.classification_ready:
        return "strict_classification_ready"
    return "broader_source_ready"


def build_corpus_records(
    *,
    data_dir: Path,
    run_id: str,
    publications_path: Path | None = None,
    entities_path: Path | None = None,
    links_path: Path | None = None,
) -> list[ClassificationCorpusRecord]:
    publications = load_publications(data_dir, publications_path)
    ontology_labels = load_ontology_labels(
        data_dir,
        entities_path=entities_path,
        links_path=links_path,
    )
    source_candidates = [
        *load_access_quality_sources(data_dir),
        *load_official_acquisition_sources(data_dir),
    ]
    best_sources = best_sources_by_document(source_candidates)

    records: list[ClassificationCorpusRecord] = []
    for document_id, publication in sorted(publications.items()):
        if not (
            value_or_none(publication.get("pmid"))
            or value_or_none(publication.get("pmcid"))
            or value_or_none(publication.get("doi"))
        ):
            continue
        source = best_sources.get(document_id)
        labels = ontology_labels.get(document_id, {})
        split = classification_dataset_split(source)
        source_ready = bool(source and source.source_ready)
        classification_ready = bool(source and source.classification_ready)
        records.append(
            ClassificationCorpusRecord(
                document_id=document_id,
                legacy_study_id=value_or_none(publication.get("legacy_study_id")),
                primary_title=value_or_none(publication.get("primary_title")),
                publication_year=publication.get("publication_year"),
                pmid=value_or_none(publication.get("pmid")),
                pmcid=value_or_none(publication.get("pmcid")),
                doi=value_or_none(publication.get("doi")),
                canonical_url=value_or_none(publication.get("canonical_url")),
                legacy_study_type=value_or_none(publication.get("legacy_study_type")),
                legacy_result=value_or_none(publication.get("legacy_result")),
                medical_condition_labels=labels.get("medical_condition_labels", []),
                organ_system_labels=labels.get("organ_system_labels", []),
                cannabinoid_labels=labels.get("cannabinoid_labels", []),
                source_strategy=source.source_strategy if source else None,
                source_url=source.source_url if source else None,
                source_text_path=source.source_text_path if source else None,
                raw_payload_path=source.raw_payload_path if source else None,
                extracted_text_chars=source.extracted_text_chars if source else 0,
                scientific_section_hit_count=(
                    source.scientific_section_hit_count if source else 0
                ),
                cannabinoid_term_hit_count=source.cannabinoid_term_hit_count if source else 0,
                source_ready=source_ready,
                classification_ready=classification_ready,
                classification_dataset_split=split,  # type: ignore[arg-type]
                trust_level="source_text_available" if source_ready else "metadata_enriched",
                provenance={
                    "run_id": run_id,
                    "method": "classification_corpus_rollup",
                    "publication_provenance": publication.get("provenance"),
                    "source_provenance": source.provenance if source else None,
                    "does_not_fetch_network": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "candidate_source_intelligence_not_reviewed_knowledge",
                },
            )
        )
    return records


def summarize_records(
    *,
    records: list[ClassificationCorpusRecord],
    run_id: str,
    records_path: Path,
    sample_paths: dict[str, Path] | None,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "records_path": str(records_path),
        "sample_paths": {key: str(value) for key, value in (sample_paths or {}).items()},
        "counts": {
            "records": len(records),
            "source_ready": sum(record.source_ready for record in records),
            "classification_ready": sum(record.classification_ready for record in records),
            "not_source_ready": sum(not record.source_ready for record in records),
        },
        "split_counts": dict(Counter(record.classification_dataset_split for record in records)),
        "source_strategy_counts": dict(
            Counter(record.source_strategy or "none" for record in records)
        ),
        "legacy_study_type_counts": dict(
            Counter(record.legacy_study_type or "unknown" for record in records)
        ),
        "trust_level_counts": dict(Counter(record.trust_level for record in records)),
        "notes": [
            "This rollup reads ignored local data artifacts only.",
            "This rollup does not mutate SQLite, review queues, review decisions, "
            "or reviewed knowledge.",
            "classification_ready is a source-text quality gate, not AI classification.",
        ],
    }


def write_corpus_rollup(
    *,
    storage: LocalStorage,
    run_id: str | None = None,
    sample_size: int = 30,
    write_sample: bool = True,
) -> dict[str, Any]:
    storage.ensure_layout()
    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    records = build_corpus_records(data_dir=storage.root, run_id=resolved_run_id)
    records_path = storage.write_jsonl(
        Path("normalized/classification_corpus")
        / f"{resolved_run_id}_classification_corpus_records.jsonl",
        records,
    )
    sample_paths: dict[str, Path] = {}
    if write_sample:
        sample_paths = write_classification_sample(
            storage=storage,
            corpus_records=records,
            run_id=resolved_run_id,
            sample_size=sample_size,
        )
    completed_at = datetime.now(UTC)
    summary = summarize_records(
        records=records,
        run_id=resolved_run_id,
        records_path=records_path,
        sample_paths=sample_paths,
        started_at=started_at,
        completed_at=completed_at,
    )
    summary_path = storage.write_json(
        Path("normalized/classification_corpus")
        / f"{resolved_run_id}_classification_corpus_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "records_path": str(records_path),
        "summary_path": str(summary_path),
        "sample_paths": {key: str(value) for key, value in sample_paths.items()},
        "counts": summary["counts"],
        "split_counts": summary["split_counts"],
    }


def labels_match(labels: list[str], terms: tuple[str, ...]) -> bool:
    text = " | ".join(labels).lower()
    return any(term in text for term in terms)


def study_type_matches(value: str | None, terms: tuple[str, ...]) -> bool:
    lowered = (value or "").lower()
    return any(term in lowered for term in terms)


def source_strategy_group(value: str | None) -> str:
    if value == "pmc_oai" or value in {"pmc_html", "pmc_nxml"}:
        return "pmc_oai_or_pmc"
    if value == "unpaywall_pdf":
        return "unpaywall_pdf"
    if value == "augmented_links":
        return "augmented_links"
    return value or "unknown"


def record_strata(record: ClassificationCorpusRecord) -> dict[str, list[str] | str | bool]:
    condition_matches = [
        name
        for name, terms in CONDITION_STRATA.items()
        if labels_match(record.medical_condition_labels, terms)
        or labels_match([record.primary_title or ""], terms)
    ]
    study_matches = [
        name
        for name, terms in STUDY_TYPE_STRATA.items()
        if study_type_matches(record.legacy_study_type, terms)
        or labels_match([record.primary_title or ""], terms)
    ]
    return {
        "condition_strata": condition_matches or ["other_condition"],
        "study_type_strata": study_matches or ["other_study_type"],
        "source_strategy_group": source_strategy_group(record.source_strategy),
        "classification_dataset_split": record.classification_dataset_split,
        "classification_ready": record.classification_ready,
    }


def select_first_matching(
    records: list[ClassificationCorpusRecord],
    selected: set[str],
    predicate: Any,
) -> ClassificationCorpusRecord | None:
    for record in records:
        if record.document_id not in selected and predicate(record):
            return record
    return None


def stratified_sample_records(
    records: list[ClassificationCorpusRecord],
    *,
    run_id: str,
    sample_size: int,
) -> list[ClassificationSampleRecord]:
    eligible = sorted(
        [record for record in records if record.source_ready],
        key=lambda record: (
            not record.classification_ready,
            record.source_strategy or "",
            -(record.extracted_text_chars or 0),
            record.document_id,
        ),
    )
    selected: set[str] = set()
    sample: list[ClassificationSampleRecord] = []

    def add(record: ClassificationCorpusRecord, reason: str) -> None:
        if len(sample) >= sample_size or record.document_id in selected:
            return
        selected.add(record.document_id)
        sample.append(
            ClassificationSampleRecord(
                sample_id=f"{run_id}:sample:{len(sample) + 1:03d}",
                sample_run_id=run_id,
                sample_reason=reason,
                strata=record_strata(record),
                corpus_record=record,
                provenance={
                    "method": "classification_corpus_stratified_smoke_sample",
                    "does_not_call_llm": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "sample_packet_not_reviewed_knowledge",
                },
            )
        )

    for name, terms in CONDITION_STRATA.items():
        match = select_first_matching(
            eligible,
            selected,
            lambda record, terms=terms: labels_match(record.medical_condition_labels, terms)
            or labels_match([record.primary_title or ""], terms),
        )
        if match:
            add(match, f"condition:{name}")

    for name, terms in STUDY_TYPE_STRATA.items():
        match = select_first_matching(
            eligible,
            selected,
            lambda record, terms=terms: study_type_matches(record.legacy_study_type, terms)
            or labels_match([record.primary_title or ""], terms),
        )
        if match:
            add(match, f"study_type:{name}")

    for strategy_group in ("pmc_oai_or_pmc", "unpaywall_pdf", "augmented_links"):
        match = select_first_matching(
            eligible,
            selected,
            lambda record, strategy_group=strategy_group: source_strategy_group(
                record.source_strategy
            )
            == strategy_group,
        )
        if match:
            add(match, f"source_strategy:{strategy_group}")

    for split in ("strict_classification_ready", "broader_source_ready"):
        match = select_first_matching(
            eligible,
            selected,
            lambda record, split=split: record.classification_dataset_split == split,
        )
        if match:
            add(match, f"quality_split:{split}")

    for record in eligible:
        if len(sample) >= sample_size:
            break
        add(record, "deterministic_fill")

    return sample


def sample_summary(
    *,
    sample: list[ClassificationSampleRecord],
    run_id: str,
    sample_path: Path,
    errors_path: Path,
) -> dict[str, Any]:
    condition_counts: Counter[str] = Counter()
    study_type_counts: Counter[str] = Counter()
    for item in sample:
        condition_counts.update(item.strata["condition_strata"])  # type: ignore[arg-type]
        study_type_counts.update(item.strata["study_type_strata"])  # type: ignore[arg-type]
    corpus_records = [item.corpus_record for item in sample]
    return {
        "run_id": run_id,
        "sample_size": len(sample),
        "records_path": str(sample_path),
        "errors_path": str(errors_path),
        "condition_strata_counts": dict(condition_counts),
        "study_type_strata_counts": dict(study_type_counts),
        "source_strategy_group_counts": dict(
            Counter(source_strategy_group(record.source_strategy) for record in corpus_records)
        ),
        "classification_dataset_split_counts": dict(
            Counter(record.classification_dataset_split for record in corpus_records)
        ),
        "notes": [
            "This is a smoke-test sample packet for future classification.",
            "No LLM was called and no candidate classification was produced.",
        ],
    }


def write_classification_sample(
    *,
    storage: LocalStorage,
    corpus_records: list[ClassificationCorpusRecord],
    run_id: str,
    sample_size: int,
) -> dict[str, Path]:
    sample = stratified_sample_records(
        corpus_records,
        run_id=run_id,
        sample_size=sample_size,
    )
    sample_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{run_id}_classification_sample_records.jsonl",
        sample,
    )
    errors_path = storage.write_jsonl(
        Path("normalized/classification_runs") / f"{run_id}_classification_errors.jsonl",
        [],
    )
    summary = sample_summary(
        sample=sample,
        run_id=run_id,
        sample_path=sample_path,
        errors_path=errors_path,
    )
    summary_path = storage.write_json(
        Path("normalized/classification_runs")
        / f"{run_id}_classification_sample_summary.json",
        summary,
    )
    return {
        "records": sample_path,
        "summary": summary_path,
        "errors": errors_path,
    }
