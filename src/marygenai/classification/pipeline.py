from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

from marygenai.classification.models import (
    CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION,
    CandidateClassificationLabel,
    CandidateClassificationPromptPacket,
    CandidateStudyClassification,
    ClassificationRunError,
    EvidenceSpan,
    PopulationOrModel,
)
from marygenai.classification_corpus.models import (
    ClassificationCorpusRecord,
    ClassificationSampleRecord,
)
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

PROMPT_VERSION = "candidate_study_classification_prompt.v5"
EXTRACTOR_NAME = "marygenai_candidate_classifier"
EXTRACTOR_VERSION = "0.1.0"
DRY_RUN_PROVIDER = "dry_run"
DRY_RUN_MODEL = "deterministic_mock_classifier"
DEFAULT_PROMPT_SOURCE_CHARS = 12_000
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_BASE_URL = "https://api.openai.com/v1"
OPENAI_BATCH_CHAT_COMPLETIONS_ENDPOINT = "/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_MAX_COMPLETION_TOKENS = 3000
DEFAULT_MAX_ESTIMATED_BATCH_ENQUEUED_TOKENS = 1_800_000
CLASSIFICATION_DATASET_SPLITS = {
    "strict_classification_ready",
    "broader_source_ready",
}


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


def resolve_data_path(data_dir: Path, stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    path = Path(stored_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == data_dir.name:
        return data_dir.parent / path
    return data_dir / path


def safe_id_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def load_source_text_excerpt(path: Path, *, limit: int = 700) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"\s+", " ", text).strip()[:limit]


def load_source_text_for_prompt(path: Path, *, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"\s+", " ", text).strip()[:max_chars]


def load_smoke_corpus_records(
    *,
    data_dir: Path,
    input_path: Path | None,
    limit: int,
    dataset_split: str | None = None,
    offset: int = 0,
) -> tuple[list[ClassificationCorpusRecord], Path]:
    if dataset_split is not None and dataset_split not in CLASSIFICATION_DATASET_SPLITS:
        allowed = ", ".join(sorted(CLASSIFICATION_DATASET_SPLITS))
        msg = f"Unsupported dataset split {dataset_split!r}. Expected one of: {allowed}."
        raise ValueError(msg)
    path = input_path or latest_path(
        data_dir,
        "normalized/classification_runs/*_classification_sample_records.jsonl",
    )
    rows = read_jsonl(path)
    records: list[ClassificationCorpusRecord] = []
    skipped = 0
    for row in rows:
        if "corpus_record" in row:
            record = ClassificationSampleRecord.model_validate(row).corpus_record
        else:
            record = ClassificationCorpusRecord.model_validate(row)
        if record.source_ready:
            if dataset_split is not None and record.classification_dataset_split != dataset_split:
                continue
            if skipped < offset:
                skipped += 1
                continue
            records.append(record)
        if len(records) >= limit:
            break
    return records, path


def normalize_lookup_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def clean_doi(value: str | None) -> str:
    return (value or "").lower().removeprefix("https://doi.org/").strip()


def latest_legacy_english_context_path(data_dir: Path) -> Path | None:
    paths = sorted(data_dir.glob("normalized/legacy_english_context/*_records.jsonl"))
    return paths[-1] if paths else None


def load_legacy_english_context_index(data_dir: Path) -> dict[str, dict[str, dict[str, Any]]]:
    path = latest_legacy_english_context_path(data_dir)
    indexes: dict[str, dict[str, dict[str, Any]]] = {
        "document_id": {},
        "pmid": {},
        "pmcid": {},
        "doi": {},
        "title_year": {},
    }
    if path is None or not path.exists():
        return indexes
    for row in read_jsonl(path):
        for match in row.get("document_matches") or []:
            document_id = match.get("document_id")
            if document_id and document_id not in indexes["document_id"]:
                indexes["document_id"][document_id] = row
        if row.get("pmid"):
            indexes["pmid"][str(row["pmid"])] = row
        if row.get("pmcid"):
            indexes["pmcid"][str(row["pmcid"])] = row
        if row.get("doi"):
            indexes["doi"][clean_doi(row["doi"])] = row
        if row.get("normalized_title") and row.get("publication_year"):
            key = f"{row['normalized_title']}|{row['publication_year']}"
            indexes["title_year"][key] = row
    return indexes


def legacy_english_context_for_record(
    record: ClassificationCorpusRecord,
    indexes: dict[str, dict[str, dict[str, Any]]] | None,
) -> dict[str, Any] | None:
    if not indexes:
        return None
    if record.document_id in indexes["document_id"]:
        return indexes["document_id"][record.document_id]
    if record.pmid and record.pmid in indexes["pmid"]:
        return indexes["pmid"][record.pmid]
    if record.pmcid and record.pmcid in indexes["pmcid"]:
        return indexes["pmcid"][record.pmcid]
    doi = clean_doi(record.doi)
    if doi and doi in indexes["doi"]:
        return indexes["doi"][doi]
    title_key = f"{normalize_lookup_text(record.primary_title)}|{record.publication_year}"
    return indexes["title_year"].get(title_key)


def infer_study_design_category(legacy_study_type: str | None) -> str:
    value = (legacy_study_type or "").lower()
    if "double blind clinical trial" in value or "duplo-cego" in value:
        return "double_blind_clinical_trial"
    if "clinical meta-analysis" in value:
        return "clinical_meta_analysis"
    if value.strip() == "meta-analysis" or "metanálise" in value or "meta" in value:
        return "meta_analysis"
    if "clinical trial" in value or "ensaio clínico" in value:
        return "clinical_trial"
    if "animal" in value:
        return "animal_study"
    if "laboratorial" in value or "laboratory" in value:
        return "laboratory_study"
    return "cannot_determine"


def infer_evidence_context(study_design_category: str) -> str:
    if study_design_category in {
        "clinical_trial",
        "double_blind_clinical_trial",
    }:
        return "human_clinical"
    if study_design_category == "animal_study":
        return "animal_preclinical"
    if study_design_category == "laboratory_study":
        return "in_vitro_or_cellular"
    if study_design_category in {"meta_analysis", "clinical_meta_analysis"}:
        return "review_or_synthesis"
    return "cannot_determine"


def infer_study_design_subtype(study_design_category: str) -> str:
    if study_design_category in {"meta_analysis", "clinical_meta_analysis"}:
        return "systematic_review"
    return "cannot_determine"


def infer_population_or_model(study_design_category: str) -> PopulationOrModel:
    if study_design_category in {"clinical_trial", "double_blind_clinical_trial"}:
        return PopulationOrModel(category="adult_humans", description="Dry-run inferred humans.")
    if study_design_category == "animal_study":
        return PopulationOrModel(category="animals", description="Dry-run inferred animal model.")
    if study_design_category == "laboratory_study":
        return PopulationOrModel(category="cells", description="Dry-run inferred cellular model.")
    if study_design_category in {"meta_analysis", "clinical_meta_analysis"}:
        return PopulationOrModel(category="mixed", description="Dry-run inferred synthesis record.")
    return PopulationOrModel(category="cannot_determine", description=None)


def infer_intervention_or_exposure_role(record: ClassificationCorpusRecord) -> str:
    label_text = " ".join(
        [
            record.primary_title or "",
            *record.medical_condition_labels,
            *record.cannabinoid_labels,
        ]
    ).lower()
    if any(term in label_text for term in ("addiction", "dependence", "cannabis use")):
        return "cannabis_use_or_dependence"
    if any(term in label_text for term in ("endocannabinoid", "anandamide", "faah", "magl")):
        return "endocannabinoid_system_mechanism"
    if any(term in label_text for term in ("synthetic", "dronabinol", "nabilone")):
        return "synthetic_or_pharmaceutical_cannabinoid"
    if record.medical_condition_labels:
        return "therapeutic_intervention"
    return "cannot_determine"


def infer_overall_direction(legacy_result: str | None) -> str:
    value = (legacy_result or "").lower()
    if "positivo" in value or "positive" in value:
        return "beneficial"
    if "negativo" in value or "negative" in value:
        return "null"
    if "misto" in value or "mixed" in value:
        return "mixed"
    return "cannot_determine"


def candidate_labels(
    labels: list[str],
    *,
    confidence: str = "low",
) -> list[CandidateClassificationLabel]:
    return [
        CandidateClassificationLabel(
            normalized_label=label,
            free_text_label=label,
            confidence=confidence,  # type: ignore[arg-type]
        )
        for label in labels
    ]


def build_mock_classification(
    *,
    record: ClassificationCorpusRecord,
    run_id: str,
    data_dir: Path,
    created_at: datetime,
) -> CandidateStudyClassification:
    source_text_path = resolve_data_path(data_dir, record.source_text_path)
    if source_text_path is None or not source_text_path.exists():
        msg = f"Missing source text path for {record.document_id}: {record.source_text_path}"
        raise FileNotFoundError(msg)

    study_design_category = infer_study_design_category(record.legacy_study_type)
    study_design_subtype = infer_study_design_subtype(study_design_category)
    evidence_context = infer_evidence_context(study_design_category)
    population_or_model = infer_population_or_model(study_design_category)
    intervention_or_exposure_role = infer_intervention_or_exposure_role(record)
    overall_direction = infer_overall_direction(record.legacy_result)
    missing_or_uncertain_fields = []
    for field_name, value in (
        ("study_design_category", study_design_category),
        ("study_design_subtype", study_design_subtype),
        ("evidence_context", evidence_context),
        ("intervention_or_exposure_role", intervention_or_exposure_role),
        ("population_or_model", population_or_model.category),
        ("overall_direction", overall_direction),
    ):
        if value == "cannot_determine":
            missing_or_uncertain_fields.append(field_name)
    for field_name, values in (
        ("medical_conditions", record.medical_condition_labels),
        ("cannabinoids_or_exposures", record.cannabinoid_labels),
        (
            "outcome_domains",
            ["efficacy"] if overall_direction == "beneficial" else [],
        ),
    ):
        if not values:
            missing_or_uncertain_fields.append(field_name)

    evidence_text = load_source_text_excerpt(source_text_path)
    supporting_sections = ["source_excerpt"] if evidence_text else []
    evidence_spans = [
        EvidenceSpan(
            section="source_excerpt",
            text=evidence_text,
            char_start=0,
            char_end=len(evidence_text),
            source_text_path=str(source_text_path),
        )
    ] if evidence_text else []

    return CandidateStudyClassification(
        classification_id=f"classification:{run_id}:{safe_id_fragment(record.document_id)}",
        document_id=record.document_id,
        classification_run_id=run_id,
        extractor_name=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        model_provider=DRY_RUN_PROVIDER,
        model_name=DRY_RUN_MODEL,
        prompt_version=PROMPT_VERSION,
        source_text_path=str(source_text_path),
        source_text_sha256=file_sha256(source_text_path),
        created_at=created_at,
        study_design_category=study_design_category,  # type: ignore[arg-type]
        study_design_subtype=study_design_subtype,  # type: ignore[arg-type]
        evidence_context=evidence_context,  # type: ignore[arg-type]
        medical_conditions=candidate_labels(record.medical_condition_labels, confidence="medium"),
        cannabinoids_or_exposures=candidate_labels(record.cannabinoid_labels, confidence="medium"),
        intervention_or_exposure_role=intervention_or_exposure_role,  # type: ignore[arg-type]
        population_or_model=population_or_model,
        outcome_domains=["efficacy"] if overall_direction == "beneficial" else [],
        overall_direction=overall_direction,  # type: ignore[arg-type]
        classification_confidence="low",
        evidence_spans=evidence_spans,
        supporting_sections=supporting_sections,
        missing_or_uncertain_fields=missing_or_uncertain_fields,
        warnings=[
            "Dry-run deterministic mock output for schema and pipeline validation only.",
        ],
        provenance={
            "method": "classification_smoke_dry_run_mock",
            "corpus_record_provenance": record.provenance,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
        },
    )


def build_system_prompt() -> str:
    return (
        "You classify scientific source text for cannabinoid medicine source intelligence. "
        "Return only valid JSON matching the provided schema. Do not provide medical advice, "
        "treatment recommendations, or reviewed clinical conclusions. Treat the output as "
        "candidate evidence for human review. Use cannot_determine only for scalar fields "
        "whose enums support it. For unsupported list fields, return an empty list and add "
        "the canonical field name to missing_or_uncertain_fields."
    )


def legacy_english_prompt_metadata(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not context:
        return None
    list_fields = context.get("list_fields") or {}
    return {
        "context_id": context.get("context_id"),
        "type_of_study": context.get("type_of_study"),
        "study_result": context.get("study_result"),
        "key_findings": context.get("key_findings") or [],
        "cannabinoids_studied": list_fields.get("Cannabinoids Studied") or [],
        "study_sample_size": context.get("study_sample_size"),
        "source_row_count": context.get("source_row_count"),
    }


def corpus_metadata_for_prompt(
    record: ClassificationCorpusRecord,
    legacy_english_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "document_id": record.document_id,
        "legacy_study_id": record.legacy_study_id,
        "primary_title": record.primary_title,
        "publication_year": record.publication_year,
        "pmid": record.pmid,
        "pmcid": record.pmcid,
        "doi": record.doi,
        "canonical_url": record.canonical_url,
        "legacy_study_type": record.legacy_study_type,
        "legacy_result": record.legacy_result,
        "medical_condition_labels": record.medical_condition_labels,
        "organ_system_labels": record.organ_system_labels,
        "cannabinoid_labels": record.cannabinoid_labels,
        "source_strategy": record.source_strategy,
        "classification_dataset_split": record.classification_dataset_split,
        "trust_level": record.trust_level,
        "legacy_english_context": legacy_english_prompt_metadata(legacy_english_context),
    }


def build_user_prompt(
    *,
    record: ClassificationCorpusRecord,
    run_id: str,
    source_text_path: Path,
    source_text_sha256: str,
    source_text_excerpt: str,
    response_json_schema: dict[str, Any],
    legacy_english_context: dict[str, Any] | None,
) -> str:
    metadata = corpus_metadata_for_prompt(record, legacy_english_context)
    output_identity = {
        "classification_id": f"classification:{run_id}:{safe_id_fragment(record.document_id)}",
        "document_id": record.document_id,
        "classification_run_id": run_id,
        "extractor_name": EXTRACTOR_NAME,
        "extractor_version": EXTRACTOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "source_text_path": str(source_text_path),
        "source_text_sha256": source_text_sha256,
    }
    return (
        "Classify this scientific document using only the metadata and source text below.\n"
        "Required output constraints:\n"
        "- Return one JSON object only.\n"
        "- Set requires_human_review to true and review_state to needs_review.\n"
        "- Include short evidence_spans copied from the source text for important claims.\n"
        "- Do not infer exact protocol details, dosage, or treatment recommendations.\n"
        "- Use English legacy context as the preferred baseline when it is provided.\n"
        "- If a scalar field is not supported and its enum permits cannot_determine, use "
        "cannot_determine and list that exact field name in missing_or_uncertain_fields.\n"
        "- If medical_conditions, cannabinoids_or_exposures, or outcome_domains has no "
        "defensible value, return an empty list and list that exact field name in "
        "missing_or_uncertain_fields. Never put cannot_determine inside a list.\n"
        "- missing_or_uncertain_fields is machine-readable and may contain only canonical "
        "field names from its schema enum. Put explanations in warnings, not in field names. "
        "Never list technical identity, evidence-offset, or provenance fields.\n"
        "- Do not add keys that are not present in the schema.\n\n"
        "Enum discipline:\n"
        "- Use only enum values that appear in the JSON schema.\n"
        "- study_design_category must use the English legacy study-type domain: "
        "meta_analysis, clinical_meta_analysis, clinical_trial, "
        "double_blind_clinical_trial, animal_study, laboratory_study, other, or "
        "cannot_determine. Do not output narrative_review, mechanistic_review, "
        "systematic_review, randomized_controlled_trial, animal_in_vivo, or in_vitro.\n"
        "- Use study_design_category=other for surveys, case reports or series, and "
        "observational studies that do not fit the legacy-compatible principal categories. "
        "Record the specific form in study_design_subtype. Do not relabel these designs as "
        "clinical_trial solely because humans were observed.\n"
        "- study_design_subtype carries the granular design. Use systematic_review, "
        "scoping_review, narrative_review, mechanistic_review, survey, "
        "case_report_or_series, observational_study, pilot_study, other, or "
        "cannot_determine. When the title or source explicitly names a subtype, use that "
        "exact subtype; for example, a scoping review is scoping_review, not the broader "
        "systematic_review. Structured fields and warnings must not contradict each other.\n"
        "- evidence_context describes the evidence setting; use review_or_synthesis "
        "there for review articles.\n"
        "- outcome_domains must use only efficacy, safety, adverse_events, biomarker, "
        "cognition, mechanism, pharmacokinetics, public_health, or use_pattern. Use cognition "
        "for memory, attention, executive function, neurocognitive performance, or cognitive "
        "impairment. Behavior is not automatically cognition; omit unsupported domains and "
        "mark outcome_domains uncertain when no permitted value is defensible.\n"
        "- overall_direction describes the direction of a source-supported effect or "
        "association relevant to the study question. Use null only when an effect or "
        "association was evaluated and no meaningful difference or association was found. "
        "Use not_applicable for descriptive surveys, prevalence or rate estimates, knowledge "
        "or perception studies, methodological reports, and other records without a "
        "beneficial/harmful effect question. Use cannot_determine only when a directional "
        "question exists but the source is insufficient to classify it.\n\n"
        "Output identity defaults:\n"
        f"{json.dumps(output_identity, ensure_ascii=False, indent=2)}\n\n"
        "Response JSON schema:\n"
        f"{json.dumps(response_json_schema, ensure_ascii=False, indent=2)}\n\n"
        f"Document metadata:\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        f"Source text excerpt:\n{source_text_excerpt}"
    )


def build_prompt_packet(
    *,
    record: ClassificationCorpusRecord,
    run_id: str,
    data_dir: Path,
    created_at: datetime,
    max_source_chars: int,
    target_model_provider: str | None,
    target_model_name: str | None,
    legacy_english_indexes: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> CandidateClassificationPromptPacket:
    source_text_path = resolve_data_path(data_dir, record.source_text_path)
    if source_text_path is None or not source_text_path.exists():
        msg = f"Missing source text path for {record.document_id}: {record.source_text_path}"
        raise FileNotFoundError(msg)
    source_text_sha256 = file_sha256(source_text_path)
    source_text_excerpt = load_source_text_for_prompt(source_text_path, max_chars=max_source_chars)
    response_json_schema = CandidateStudyClassification.model_json_schema()
    legacy_english_context = legacy_english_context_for_record(record, legacy_english_indexes)
    return CandidateClassificationPromptPacket(
        packet_id=f"prompt_packet:{run_id}:{safe_id_fragment(record.document_id)}",
        prompt_packet_run_id=run_id,
        document_id=record.document_id,
        prompt_version=PROMPT_VERSION,
        target_model_provider=target_model_provider,
        target_model_name=target_model_name,
        source_text_path=str(source_text_path),
        source_text_sha256=source_text_sha256,
        source_text_excerpt=source_text_excerpt,
        source_text_excerpt_chars=len(source_text_excerpt),
        system_prompt=build_system_prompt(),
        user_prompt=build_user_prompt(
            record=record,
            run_id=run_id,
            source_text_path=source_text_path,
            source_text_sha256=source_text_sha256,
            source_text_excerpt=source_text_excerpt,
            response_json_schema=response_json_schema,
            legacy_english_context=legacy_english_context,
        ),
        response_json_schema=response_json_schema,
        corpus_metadata=corpus_metadata_for_prompt(record, legacy_english_context),
        created_at=created_at,
        provenance={
            "method": "candidate_classification_prompt_packet_build",
            "corpus_record_provenance": record.provenance,
            "uses_legacy_english_context": legacy_english_context is not None,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "prompt_preparation_not_reviewed_knowledge",
        },
    )


def summarize_prompt_packets(
    *,
    run_id: str,
    input_path: Path,
    packets_path: Path,
    errors_path: Path,
    packets: list[CandidateClassificationPromptPacket],
    errors: list[ClassificationRunError],
    started_at: datetime,
    completed_at: datetime,
    max_source_chars: int,
    dataset_split: str | None,
    offset: int,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "input_path": str(input_path),
        "dataset_split_filter": dataset_split,
        "offset": offset,
        "packets_path": str(packets_path),
        "errors_path": str(errors_path),
        "max_source_chars": max_source_chars,
        "counts": {
            "input_records": len(packets) + len(errors),
            "prompt_packets": len(packets),
            "errors": len(errors),
        },
        "source_excerpt_chars": {
            "min": min((packet.source_text_excerpt_chars for packet in packets), default=0),
            "max": max((packet.source_text_excerpt_chars for packet in packets), default=0),
            "total": sum(packet.source_text_excerpt_chars for packet in packets),
        },
        "prompt_chars": {
            "system_total": sum(len(packet.system_prompt) for packet in packets),
            "user_total": sum(len(packet.user_prompt) for packet in packets),
        },
        "notes": [
            "Prompt packets are dry-run artifacts for inspection before provider calls.",
            "No LLM was called and no candidate classification was produced.",
            "This command does not mutate SQLite, review queues, review decisions, "
            "or reviewed knowledge.",
        ],
    }


def build_classification_prompt_packets(
    *,
    storage: LocalStorage,
    limit: int = 5,
    input_path: Path | None = None,
    run_id: str | None = None,
    max_source_chars: int = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_provider: str | None = None,
    target_model_name: str | None = None,
    dataset_split: str | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    corpus_records, resolved_input_path = load_smoke_corpus_records(
        data_dir=storage.root,
        input_path=input_path,
        limit=limit,
        dataset_split=dataset_split,
        offset=offset,
    )
    legacy_english_indexes = load_legacy_english_context_index(storage.root)
    packets: list[CandidateClassificationPromptPacket] = []
    errors: list[ClassificationRunError] = []
    for corpus_record in corpus_records:
        try:
            packets.append(
                build_prompt_packet(
                    record=corpus_record,
                    run_id=resolved_run_id,
                    data_dir=storage.root,
                    created_at=started_at,
                    max_source_chars=max_source_chars,
                    target_model_provider=target_model_provider,
                    target_model_name=target_model_name,
                    legacy_english_indexes=legacy_english_indexes,
                )
            )
        except (FileNotFoundError, ValidationError, ValueError) as exc:
            errors.append(
                ClassificationRunError(
                    classification_run_id=resolved_run_id,
                    document_id=corpus_record.document_id,
                    source_record_id=corpus_record.legacy_study_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    provenance={
                        "method": "candidate_classification_prompt_packet_error",
                        "does_not_call_llm": True,
                        "does_not_mutate_sqlite": True,
                    },
                )
            )

    packets_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_prompt_packets.jsonl",
        packets,
    )
    errors_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_prompt_packet_errors.jsonl",
        errors,
    )
    completed_at = datetime.now(UTC)
    summary = summarize_prompt_packets(
        run_id=resolved_run_id,
        input_path=resolved_input_path,
        packets_path=packets_path,
        errors_path=errors_path,
        packets=packets,
        errors=errors,
        started_at=started_at,
        completed_at=completed_at,
        max_source_chars=max_source_chars,
        dataset_split=dataset_split,
        offset=offset,
    )
    summary_path = storage.write_json(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_prompt_packet_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "packets_path": str(packets_path),
        "summary_path": str(summary_path),
        "errors_path": str(errors_path),
        "counts": summary["counts"],
    }


def redacted_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    messages = []
    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        content = str(message.get("content", ""))
        messages.append(
            {
                **message,
                "content_chars": len(content),
                "content_preview": content[:500],
                "content": "[redacted]",
            }
        )
    redacted["messages"] = messages
    return redacted


def write_dict_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def build_openai_chat_request(
    packet: CandidateClassificationPromptPacket,
    *,
    model: str,
    max_completion_tokens: int,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": packet.system_prompt},
            {"role": "user", "content": packet.user_prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": max_completion_tokens,
        "response_format": {"type": "json_object"},
    }


def repair_required_uncertainty_markers(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload)
    uncertainty_field_names = {
        "study_design_category",
        "study_design_subtype",
        "evidence_context",
        "medical_conditions",
        "cannabinoids_or_exposures",
        "intervention_or_exposure_role",
        "population_or_model",
        "outcome_domains",
        "overall_direction",
        "classification_confidence",
    }
    fields = [
        str(field)
        for field in repaired.get("missing_or_uncertain_fields") or []
        if field is not None and str(field) in uncertainty_field_names
    ]
    invalid_uncertainty_markers = [
        str(field)
        for field in repaired.get("missing_or_uncertain_fields") or []
        if field is not None and str(field) not in uncertainty_field_names
    ]
    technical_repairs: list[dict[str, Any]] = []
    valid_outcome_domains = {
        "efficacy",
        "safety",
        "adverse_events",
        "biomarker",
        "cognition",
        "mechanism",
        "pharmacokinetics",
        "public_health",
        "use_pattern",
    }
    outcome_domains = list(repaired.get("outcome_domains") or [])
    invalid_outcome_domains = [
        str(value)
        for value in outcome_domains
        if value is not None and str(value) not in valid_outcome_domains
    ]
    if invalid_outcome_domains:
        repaired["outcome_domains"] = [
            value for value in outcome_domains if str(value) in valid_outcome_domains
        ]
        fields.append("outcome_domains")
        technical_repairs.append(
            {
                "repair_type": "removed_invalid_enum_values",
                "field": "outcome_domains",
                "original_values": invalid_outcome_domains,
                "repaired_value": repaired["outcome_domains"],
                "reason": (
                    "Candidate output included outcome-domain labels outside the "
                    "retrieval schema. Unsupported values were removed and the field "
                    "was marked uncertain rather than silently mapped to another "
                    "scientific meaning."
                ),
            }
        )
    uncertainty_outcome_markers = [
        marker for marker in invalid_uncertainty_markers if marker in valid_outcome_domains
    ]
    if uncertainty_outcome_markers:
        fields.append("outcome_domains")
    if invalid_uncertainty_markers:
        technical_repairs.append(
            {
                "repair_type": "removed_invalid_uncertainty_markers",
                "field": "missing_or_uncertain_fields",
                "original_values": invalid_uncertainty_markers,
                "repaired_value": fields,
                "reason": (
                    "Candidate output placed values that are not canonical field names "
                    "inside missing_or_uncertain_fields. Unsupported markers were removed; "
                    "valid outcome-domain markers were represented by marking "
                    "outcome_domains uncertain."
                ),
            }
        )
    if repaired.get("study_design_subtype") in {"in_vitro", "in_vitro_or_cellular"}:
        original_value = str(repaired["study_design_subtype"])
        repaired["study_design_subtype"] = "other"
        fields.append("study_design_subtype")
        technical_repairs.append(
            {
                "repair_type": "normalized_invalid_enum_value",
                "field": "study_design_subtype",
                "original_value": original_value,
                "repaired_value": "other",
                "reason": (
                    "Candidate output used an in-vitro context marker in "
                    "study_design_subtype. The value was moved to a valid broad subtype "
                    "without changing evidence_context or study_design_category."
                ),
            }
        )
    if repaired.get("study_design_subtype") in {"meta_analysis", "clinical_meta_analysis"}:
        original_value = str(repaired["study_design_subtype"])
        repaired["study_design_subtype"] = "cannot_determine"
        fields.append("study_design_subtype")
        technical_repairs.append(
            {
                "repair_type": "normalized_invalid_enum_value",
                "field": "study_design_subtype",
                "original_value": original_value,
                "repaired_value": "cannot_determine",
                "reason": (
                    "Candidate output used a study_design_category enum value in "
                    "study_design_subtype. The category value remains preserved in "
                    "study_design_category, while subtype was marked uncertain."
                ),
            }
        )
    if repaired.get("study_design_subtype") == "randomized controlled trial":
        repaired["study_design_subtype"] = "other"
        fields.append("study_design_subtype")
        technical_repairs.append(
            {
                "repair_type": "normalized_invalid_enum_value",
                "field": "study_design_subtype",
                "original_value": "randomized controlled trial",
                "repaired_value": "other",
                "reason": (
                    "Candidate output used a clinical-trial design label that is not "
                    "supported by the current subtype enum. The valid broad subtype "
                    "was used without changing study_design_category or "
                    "evidence_context."
                ),
            }
        )
    if repaired.get("overall_direction") == "negative":
        repaired["overall_direction"] = "cannot_determine"
        fields.append("overall_direction")
        technical_repairs.append(
            {
                "repair_type": "normalized_invalid_enum_value",
                "field": "overall_direction",
                "original_value": "negative",
                "repaired_value": "cannot_determine",
                "reason": (
                    "Candidate output used an unsupported direction label. It was mapped "
                    "conservatively to cannot_determine rather than inferring clinical "
                    "benefit or harm."
                ),
            }
        )
    population_or_model = repaired.get("population_or_model")
    if isinstance(population_or_model, dict) and population_or_model.get("category") == "plants":
        repaired["population_or_model"] = {
            **population_or_model,
            "category": "cannot_determine",
        }
        fields.append("population_or_model")
        technical_repairs.append(
            {
                "repair_type": "normalized_invalid_enum_value",
                "field": "population_or_model",
                "original_value": "plants",
                "repaired_value": "cannot_determine",
                "reason": (
                    "Candidate output used a plant model category that is not supported "
                    "by the current population/model schema. It was mapped "
                    "conservatively to cannot_determine."
                ),
            }
        )
    required_fields = [
        field_name
        for field_name, cannot_determine in (
            (
                "study_design_category",
                repaired.get("study_design_category") == "cannot_determine",
            ),
            (
                "study_design_subtype",
                repaired.get("study_design_subtype") == "cannot_determine",
            ),
            ("evidence_context", repaired.get("evidence_context") == "cannot_determine"),
            (
                "intervention_or_exposure_role",
                repaired.get("intervention_or_exposure_role") == "cannot_determine",
            ),
            (
                "population_or_model",
                (repaired.get("population_or_model") or {}).get("category")
                == "cannot_determine",
            ),
            ("overall_direction", repaired.get("overall_direction") == "cannot_determine"),
            ("medical_conditions", not repaired.get("medical_conditions")),
            ("cannabinoids_or_exposures", not repaired.get("cannabinoids_or_exposures")),
            ("outcome_domains", not repaired.get("outcome_domains")),
        )
        if cannot_determine
    ]
    repaired_fields: list[str] = []
    duplicate_fields: list[str] = []
    for field in [*fields, *required_fields]:
        if field in repaired_fields:
            duplicate_fields.append(field)
            continue
        repaired_fields.append(field)
    added_fields = sorted(set(required_fields) - set(fields))
    if added_fields or duplicate_fields or technical_repairs:
        repaired["missing_or_uncertain_fields"] = repaired_fields
        provenance = dict(repaired.get("provenance") or {})
        repairs = list(provenance.get("technical_schema_repairs") or [])
        repairs.extend(technical_repairs)
        if added_fields:
            repairs.append(
                {
                    "repair_type": "added_missing_uncertainty_fields",
                    "fields": added_fields,
                    "reason": (
                        "Candidate output contained cannot_determine or empty retrieval "
                        "fields without the required uncertainty marker."
                    ),
                }
            )
        if duplicate_fields:
            repairs.append(
                {
                    "repair_type": "deduplicated_uncertainty_fields",
                    "fields": sorted(set(duplicate_fields)),
                    "reason": "Candidate output repeated uncertainty markers.",
                }
            )
        provenance["technical_schema_repairs"] = repairs
        repaired["provenance"] = provenance
    return repaired


def batch_custom_id(*, run_id: str, document_id: str) -> str:
    return f"classification_batch:{run_id}:{safe_id_fragment(document_id)}"


def build_openai_batch_request(
    packet: CandidateClassificationPromptPacket,
    *,
    run_id: str,
    model: str,
    max_completion_tokens: int,
) -> dict[str, Any]:
    return {
        "custom_id": batch_custom_id(run_id=run_id, document_id=packet.document_id),
        "method": "POST",
        "url": OPENAI_BATCH_CHAT_COMPLETIONS_ENDPOINT,
        "body": build_openai_chat_request(
            packet,
            model=model,
            max_completion_tokens=max_completion_tokens,
        ),
    }


def summarize_batch_requests(
    *,
    run_id: str,
    input_path: Path,
    batch_input_path: Path,
    manifest_path: Path,
    errors_path: Path,
    batch_requests: list[dict[str, Any]],
    packets: list[CandidateClassificationPromptPacket],
    errors: list[ClassificationRunError],
    started_at: datetime,
    completed_at: datetime,
    model: str,
    max_source_chars: int,
    max_completion_tokens: int,
    dataset_split: str | None,
    offset: int,
    max_estimated_enqueued_tokens: int,
) -> dict[str, Any]:
    request_body_chars = sum(
        len(json.dumps(request["body"], ensure_ascii=False, sort_keys=True))
        for request in batch_requests
    )
    estimated_input_tokens = request_body_chars // 4
    estimated_max_completion_tokens = len(batch_requests) * max_completion_tokens
    estimated_enqueued_tokens = estimated_input_tokens + estimated_max_completion_tokens
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "input_path": str(input_path),
        "dataset_split_filter": dataset_split,
        "offset": offset,
        "batch_input_path": str(batch_input_path),
        "manifest_path": str(manifest_path),
        "errors_path": str(errors_path),
        "endpoint": OPENAI_BATCH_CHAT_COMPLETIONS_ENDPOINT,
        "completion_window": "24h",
        "model": model,
        "max_source_chars": max_source_chars,
        "max_completion_tokens_per_request": max_completion_tokens,
        "counts": {
            "input_records": len(packets) + len(errors),
            "batch_requests": len(batch_requests),
            "errors": len(errors),
        },
        "source_excerpt_chars": {
            "min": min((packet.source_text_excerpt_chars for packet in packets), default=0),
            "max": max((packet.source_text_excerpt_chars for packet in packets), default=0),
            "total": sum(packet.source_text_excerpt_chars for packet in packets),
        },
        "prompt_chars": {
            "system_total": sum(len(packet.system_prompt) for packet in packets),
            "user_total": sum(len(packet.user_prompt) for packet in packets),
        },
        "batch_request_body_chars": request_body_chars,
        "estimated_tokens": {
            "method": "chars_divided_by_4.v1",
            "input": estimated_input_tokens,
            "max_completion": estimated_max_completion_tokens,
            "enqueued_total": estimated_enqueued_tokens,
            "max_enqueued_guard": max_estimated_enqueued_tokens,
        },
        "notes": [
            "Batch input was prepared locally only; no file was uploaded and no batch was created.",
            "Each JSONL line follows the OpenAI Batch request shape with custom_id, method, url, "
            "and body.",
            "This command does not call an LLM.",
            "This command does not mutate SQLite, review queues, review decisions, "
            "or reviewed knowledge.",
        ],
    }


def prepare_openai_batch_requests(
    *,
    storage: LocalStorage,
    limit: int = 50,
    input_path: Path | None = None,
    run_id: str | None = None,
    max_source_chars: int = DEFAULT_PROMPT_SOURCE_CHARS,
    model: str = DEFAULT_OPENAI_MODEL,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    dataset_split: str | None = None,
    offset: int = 0,
    max_estimated_enqueued_tokens: int = DEFAULT_MAX_ESTIMATED_BATCH_ENQUEUED_TOKENS,
) -> dict[str, Any]:
    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    corpus_records, resolved_input_path = load_smoke_corpus_records(
        data_dir=storage.root,
        input_path=input_path,
        limit=limit,
        dataset_split=dataset_split,
        offset=offset,
    )
    legacy_english_indexes = load_legacy_english_context_index(storage.root)
    packets: list[CandidateClassificationPromptPacket] = []
    batch_requests: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    errors: list[ClassificationRunError] = []
    seen_custom_ids: set[str] = set()
    for corpus_record in corpus_records:
        try:
            packet = build_prompt_packet(
                record=corpus_record,
                run_id=resolved_run_id,
                data_dir=storage.root,
                created_at=started_at,
                max_source_chars=max_source_chars,
                target_model_provider="openai",
                target_model_name=model,
                legacy_english_indexes=legacy_english_indexes,
            )
            request = build_openai_batch_request(
                packet,
                run_id=resolved_run_id,
                model=model,
                max_completion_tokens=max_completion_tokens,
            )
            if request["custom_id"] in seen_custom_ids:
                msg = f"Duplicate batch custom_id: {request['custom_id']}."
                raise ValueError(msg)
            seen_custom_ids.add(request["custom_id"])
            packets.append(packet)
            batch_requests.append(request)
            manifest_records.append(
                {
                    "batch_run_id": resolved_run_id,
                    "custom_id": request["custom_id"],
                    "document_id": packet.document_id,
                    "packet_id": packet.packet_id,
                    "source_record_id": corpus_record.legacy_study_id,
                    "source_text_path": packet.source_text_path,
                    "source_text_sha256": packet.source_text_sha256,
                    "prompt_version": packet.prompt_version,
                    "schema_version": packet.schema_version,
                    "classification_dataset_split": corpus_record.classification_dataset_split,
                    "source_strategy": corpus_record.source_strategy,
                    "primary_title": corpus_record.primary_title,
                    "publication_year": corpus_record.publication_year,
                    "model": model,
                    "max_completion_tokens": max_completion_tokens,
                    "provenance": {
                        "method": "openai_batch_candidate_classification_prepare",
                        "does_not_call_llm": True,
                        "does_not_upload_file": True,
                        "does_not_create_batch": True,
                        "does_not_mutate_sqlite": True,
                    },
                }
            )
        except (FileNotFoundError, ValidationError, ValueError) as exc:
            errors.append(
                ClassificationRunError(
                    classification_run_id=resolved_run_id,
                    document_id=corpus_record.document_id,
                    source_record_id=corpus_record.legacy_study_id,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    provenance={
                        "method": "openai_batch_candidate_classification_prepare_error",
                        "does_not_call_llm": True,
                        "does_not_upload_file": True,
                        "does_not_create_batch": True,
                        "does_not_mutate_sqlite": True,
                    },
                )
            )

    if not corpus_records:
        errors.append(
            ClassificationRunError(
                classification_run_id=resolved_run_id,
                error_type="empty_input",
                message="No source-ready records were selected for batch preparation.",
                provenance={
                    "method": "openai_batch_candidate_classification_prepare_input_selection",
                    "does_not_call_llm": True,
                },
            )
        )

    request_body_chars = sum(
        len(json.dumps(request["body"], ensure_ascii=False, sort_keys=True))
        for request in batch_requests
    )
    estimated_input_tokens = request_body_chars // 4
    estimated_max_completion_tokens = len(batch_requests) * max_completion_tokens
    estimated_enqueued_tokens = estimated_input_tokens + estimated_max_completion_tokens
    exceeds_enqueued_guard = (
        max_estimated_enqueued_tokens > 0
        and estimated_enqueued_tokens > max_estimated_enqueued_tokens
    )
    if exceeds_enqueued_guard:
        msg = (
            "Prepared OpenAI Batch would exceed the local estimated enqueued-token guard: "
            f"{estimated_enqueued_tokens:,} estimated tokens > "
            f"{max_estimated_enqueued_tokens:,} allowed. Reduce --limit, "
            "--max-source-chars, or --max-completion-tokens, or pass "
            "--max-estimated-enqueued-tokens 0 to disable this local guard."
        )
        raise ValueError(msg)

    output_dir = storage.path(Path("normalized/classification_batches"))
    batch_input_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_openai_batch_input.jsonl",
        batch_requests,
    )
    manifest_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_openai_batch_manifest.jsonl",
        manifest_records,
    )
    errors_path = storage.write_jsonl(
        Path("normalized/classification_batches")
        / f"{resolved_run_id}_openai_batch_prepare_errors.jsonl",
        errors,
    )
    completed_at = datetime.now(UTC)
    summary = summarize_batch_requests(
        run_id=resolved_run_id,
        input_path=resolved_input_path,
        batch_input_path=batch_input_path,
        manifest_path=manifest_path,
        errors_path=errors_path,
        batch_requests=batch_requests,
        packets=packets,
        errors=errors,
        started_at=started_at,
        completed_at=completed_at,
        model=model,
        max_source_chars=max_source_chars,
        max_completion_tokens=max_completion_tokens,
        dataset_split=dataset_split,
        offset=offset,
        max_estimated_enqueued_tokens=max_estimated_enqueued_tokens,
    )
    summary_path = storage.write_json(
        Path("normalized/classification_batches")
        / f"{resolved_run_id}_openai_batch_prepare_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "batch_input_path": str(batch_input_path),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "errors_path": str(errors_path),
        "counts": summary["counts"],
    }


def prepare_failed_openai_batch_retry(
    *,
    storage: LocalStorage,
    batch_input_path: Path,
    manifest_path: Path,
    error_output_path: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Prepare a new local Batch containing only remotely failed requests."""
    resolved_run_id = run_id or new_run_id()
    requests = read_jsonl(batch_input_path)
    manifests = read_jsonl(manifest_path)
    error_entries = read_jsonl(error_output_path)
    failed_custom_ids = {
        str(entry["custom_id"])
        for entry in error_entries
        if entry.get("custom_id")
        and int((entry.get("response") or {}).get("status_code") or 0) >= 400
    }
    if not failed_custom_ids:
        raise ValueError("The Batch error output contains no failed custom IDs.")

    requests_by_id = {str(item["custom_id"]): item for item in requests}
    manifests_by_id = {str(item["custom_id"]): item for item in manifests}
    missing_requests = sorted(failed_custom_ids - requests_by_id.keys())
    missing_manifests = sorted(failed_custom_ids - manifests_by_id.keys())
    if missing_requests or missing_manifests:
        raise ValueError(
            "Failed custom IDs were not found in the original artifacts: "
            f"missing_requests={missing_requests}, missing_manifests={missing_manifests}."
        )

    retry_requests: list[dict[str, Any]] = []
    retry_manifests: list[dict[str, Any]] = []
    for original_custom_id in sorted(failed_custom_ids):
        custom_id_suffix = original_custom_id.rsplit(":", 1)[-1]
        retry_custom_id = f"classification_batch:{resolved_run_id}:{custom_id_suffix}"
        request = {**requests_by_id[original_custom_id], "custom_id": retry_custom_id}
        manifest = {
            **manifests_by_id[original_custom_id],
            "batch_run_id": resolved_run_id,
            "custom_id": retry_custom_id,
            "provenance": {
                **(manifests_by_id[original_custom_id].get("provenance") or {}),
                "method": "openai_batch_failed_request_retry_prepare",
                "retry_of_custom_id": original_custom_id,
                "retry_error_output_path": str(error_output_path),
                "does_not_call_llm": True,
                "does_not_upload_file": True,
                "does_not_create_batch": True,
                "does_not_mutate_sqlite": True,
            },
        }
        retry_requests.append(request)
        retry_manifests.append(manifest)

    output_dir = storage.path(Path("normalized/classification_batches"))
    retry_input_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_openai_batch_input.jsonl", retry_requests
    )
    retry_manifest_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_openai_batch_manifest.jsonl", retry_manifests
    )
    summary = {
        "run_id": resolved_run_id,
        "retry_of_batch_input_path": str(batch_input_path),
        "retry_of_manifest_path": str(manifest_path),
        "retry_error_output_path": str(error_output_path),
        "batch_input_path": str(retry_input_path),
        "manifest_path": str(retry_manifest_path),
        "counts": {
            "failed_error_entries": len(error_entries),
            "unique_failed_custom_ids": len(failed_custom_ids),
            "batch_requests": len(retry_requests),
        },
        "notes": [
            "Only remotely failed requests from the supplied Batch error output are included.",
            "Preparation is local and does not call a model or mutate SQLite or review state.",
        ],
    }
    summary_path = storage.write_json(
        Path("normalized/classification_batches")
        / f"{resolved_run_id}_openai_batch_retry_prepare_summary.json",
        summary,
    )
    return {**summary, "summary_path": str(summary_path)}


def openai_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def raise_openai_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        safe_body = response.text[:2_000]
        msg = (
            f"OpenAI API request failed with status {response.status_code} "
            f"for {response.request.method} {response.request.url}: {safe_body}"
        )
        raise RuntimeError(msg) from exc


def upload_openai_batch_file(
    *,
    client: httpx.Client,
    api_key: str,
    batch_input_path: Path,
) -> dict[str, Any]:
    with batch_input_path.open("rb") as file:
        response = client.post(
            f"{OPENAI_API_BASE_URL}/files",
            headers=openai_headers(api_key),
            data={"purpose": "batch"},
            files={"file": (batch_input_path.name, file, "application/jsonl")},
        )
    raise_openai_for_status(response)
    return response.json()


def create_openai_batch(
    *,
    client: httpx.Client,
    api_key: str,
    input_file_id: str,
    completion_window: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    response = client.post(
        f"{OPENAI_API_BASE_URL}/batches",
        headers={**openai_headers(api_key), "Content-Type": "application/json"},
        json={
            "input_file_id": input_file_id,
            "endpoint": OPENAI_BATCH_CHAT_COMPLETIONS_ENDPOINT,
            "completion_window": completion_window,
            "metadata": metadata,
        },
    )
    raise_openai_for_status(response)
    return response.json()


def retrieve_openai_batch(
    *,
    client: httpx.Client,
    api_key: str,
    batch_id: str,
) -> dict[str, Any]:
    response = client.get(
        f"{OPENAI_API_BASE_URL}/batches/{batch_id}",
        headers={**openai_headers(api_key), "Content-Type": "application/json"},
    )
    raise_openai_for_status(response)
    return response.json()


def download_openai_file_text(
    *,
    client: httpx.Client,
    api_key: str,
    file_id: str,
) -> str:
    response = client.get(
        f"{OPENAI_API_BASE_URL}/files/{file_id}/content",
        headers=openai_headers(api_key),
    )
    raise_openai_for_status(response)
    return response.text


def infer_batch_run_id(path: Path) -> str:
    name = path.name
    for suffix in (
        "_openai_batch_input.jsonl",
        "_openai_batch_manifest.jsonl",
        "_openai_batch_prepare_summary.json",
        "_openai_batch_submission.json",
    ):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return new_run_id()


def submit_openai_batch(
    *,
    storage: LocalStorage,
    batch_input_path: Path,
    manifest_path: Path,
    completion_window: str = "24h",
    metadata: dict[str, str] | None = None,
) -> dict[str, Any]:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        msg = "OPENAI_API_KEY is not set."
        raise RuntimeError(msg)
    resolved_run_id = infer_batch_run_id(batch_input_path)
    started_at = datetime.now(UTC)
    metadata_payload = {
        "marygenai_run_id": resolved_run_id,
        "purpose": "candidate_classification_canary",
        "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
        **(metadata or {}),
    }
    with httpx.Client(timeout=180) as client:
        file_response = upload_openai_batch_file(
            client=client,
            api_key=api_key,
            batch_input_path=batch_input_path,
        )
        batch_response = create_openai_batch(
            client=client,
            api_key=api_key,
            input_file_id=str(file_response["id"]),
            completion_window=completion_window,
            metadata=metadata_payload,
        )
    completed_at = datetime.now(UTC)
    submission = {
        "run_id": resolved_run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "batch_input_path": str(batch_input_path),
        "manifest_path": str(manifest_path),
        "completion_window": completion_window,
        "file": file_response,
        "batch": batch_response,
        "notes": [
            "Remote OpenAI file upload and batch creation were executed.",
            "No SQLite, review queue, review decision, or reviewed knowledge state was mutated.",
            "Batch output remains candidate evidence until human review.",
        ],
    }
    submission_path = storage.write_json(
        Path("normalized/classification_batches")
        / f"{resolved_run_id}_openai_batch_submission.json",
        submission,
    )
    return {
        "run_id": resolved_run_id,
        "submission_path": str(submission_path),
        "batch_id": batch_response["id"],
        "input_file_id": file_response["id"],
        "status": batch_response.get("status"),
    }


def load_manifest_index(manifest_path: Path) -> dict[str, dict[str, Any]]:
    manifest_rows = read_jsonl(manifest_path)
    return {str(row["custom_id"]): row for row in manifest_rows}


def normalize_batch_model_payload(
    payload: dict[str, Any],
    *,
    manifest_record: dict[str, Any],
    run_id: str,
    batch_id: str,
    request_id: str | None,
    created_at: datetime,
    usage: dict[str, Any],
) -> dict[str, Any]:
    document_id = str(manifest_record["document_id"])
    normalized = repair_required_uncertainty_markers(payload)
    normalized.update(
        {
            "classification_id": f"classification:{run_id}:{safe_id_fragment(document_id)}",
            "document_id": document_id,
            "classification_run_id": run_id,
            "schema_version": CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION,
            "extractor_name": EXTRACTOR_NAME,
            "extractor_version": EXTRACTOR_VERSION,
            "model_provider": "openai",
            "model_name": str(manifest_record.get("model") or DEFAULT_OPENAI_MODEL),
            "prompt_version": str(manifest_record.get("prompt_version") or PROMPT_VERSION),
            "source_text_path": str(manifest_record["source_text_path"]),
            "source_text_sha256": str(manifest_record["source_text_sha256"]),
            "created_at": created_at.isoformat(),
            "requires_human_review": True,
            "review_state": "needs_review",
            "provenance": {
                **dict(normalized.get("provenance") or {}),
                "method": "openai_batch_candidate_classification",
                "prompt_packet_id": manifest_record.get("packet_id"),
                "provider": "openai",
                "model": manifest_record.get("model") or DEFAULT_OPENAI_MODEL,
                "batch_id": batch_id,
                "batch_custom_id": manifest_record["custom_id"],
                "request_id": request_id,
                "usage": usage,
                "does_not_mutate_sqlite": True,
                "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
            },
        }
    )
    return normalized


def raw_response_from_batch_line(
    *,
    run_id: str,
    batch_id: str,
    line: dict[str, Any],
    manifest_record: dict[str, Any] | None,
) -> dict[str, Any]:
    response = line.get("response") or {}
    response_body = response.get("body") or {}
    return {
        "run_id": run_id,
        "document_id": manifest_record.get("document_id") if manifest_record else None,
        "packet_id": manifest_record.get("packet_id") if manifest_record else None,
        "provider": "openai",
        "model": manifest_record.get("model") if manifest_record else None,
        "batch_id": batch_id,
        "batch_custom_id": line.get("custom_id"),
        "batch_request_id": line.get("id"),
        "status_code": response.get("status_code"),
        "response_json": response_body,
        "error": line.get("error"),
        "attempts": [
            {
                "attempt": 1,
                "status_code": response.get("status_code"),
                "batch_request_id": line.get("id"),
            }
        ],
    }


def convert_openai_batch_outputs(
    *,
    storage: LocalStorage,
    run_id: str,
    batch_id: str,
    manifest_path: Path,
    output_path: Path | None,
    error_output_path: Path | None = None,
) -> dict[str, Any]:
    created_at = datetime.now(UTC)
    manifest_index = load_manifest_index(manifest_path)
    output_lines = read_jsonl(output_path) if output_path and output_path.exists() else []
    error_lines = (
        read_jsonl(error_output_path) if error_output_path and error_output_path.exists() else []
    )
    records: list[CandidateStudyClassification] = []
    errors: list[ClassificationRunError] = []
    raw_responses: list[dict[str, Any]] = []
    for line in output_lines:
        custom_id = str(line.get("custom_id") or "")
        manifest_record = manifest_index.get(custom_id)
        raw_responses.append(
            raw_response_from_batch_line(
                run_id=run_id,
                batch_id=batch_id,
                line=line,
                manifest_record=manifest_record,
            )
        )
        if manifest_record is None:
            errors.append(
                ClassificationRunError(
                    classification_run_id=run_id,
                    error_type="UnknownBatchCustomId",
                    message=f"Batch output custom_id not found in manifest: {custom_id}.",
                    provenance={"method": "openai_batch_candidate_classification_convert"},
                )
            )
            continue
        response = line.get("response") or {}
        response_body = response.get("body") or {}
        status_code = response.get("status_code")
        if status_code != 200 or line.get("error"):
            errors.append(
                ClassificationRunError(
                    classification_run_id=run_id,
                    document_id=str(manifest_record.get("document_id")),
                    source_record_id=manifest_record.get("source_record_id"),
                    error_type="OpenAIBatchRequestError",
                    message=json.dumps(line.get("error") or response_body, sort_keys=True),
                    provenance={
                        "method": "openai_batch_candidate_classification_error",
                        "batch_id": batch_id,
                        "batch_custom_id": custom_id,
                        "status_code": status_code,
                        "does_not_mutate_sqlite": True,
                    },
                )
            )
            continue
        try:
            content = str(response_body["choices"][0]["message"]["content"])
            parsed = json.loads(content)
            normalized = normalize_batch_model_payload(
                parsed,
                manifest_record=manifest_record,
                run_id=run_id,
                batch_id=batch_id,
                request_id=response.get("request_id"),
                created_at=created_at,
                usage=response_body.get("usage") or {},
            )
            records.append(CandidateStudyClassification.model_validate(normalized))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                ClassificationRunError(
                    classification_run_id=run_id,
                    document_id=str(manifest_record.get("document_id")),
                    source_record_id=manifest_record.get("source_record_id"),
                    error_type=type(exc).__name__,
                    message=str(exc),
                    provenance={
                        "method": "openai_batch_candidate_classification_error",
                        "batch_id": batch_id,
                        "batch_custom_id": custom_id,
                        "does_not_mutate_sqlite": True,
                    },
                )
            )

    for line in error_lines:
        custom_id = str(line.get("custom_id") or "")
        manifest_record = manifest_index.get(custom_id)
        errors.append(
            ClassificationRunError(
                classification_run_id=run_id,
                document_id=str(manifest_record.get("document_id")) if manifest_record else None,
                source_record_id=manifest_record.get("source_record_id")
                if manifest_record
                else None,
                error_type="OpenAIBatchErrorFileEntry",
                message=json.dumps(line.get("error") or line, sort_keys=True),
                provenance={
                    "method": "openai_batch_candidate_classification_error_file",
                    "batch_id": batch_id,
                    "batch_custom_id": custom_id,
                    "does_not_mutate_sqlite": True,
                },
            )
        )

    records_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{run_id}_candidate_classification_records.jsonl",
        records,
    )
    errors_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{run_id}_candidate_classification_errors.jsonl",
        errors,
    )
    raw_responses_path = write_dict_jsonl(
        storage.path(
            Path("normalized/classification_runs")
            / f"{run_id}_candidate_classification_raw_responses.jsonl"
        ),
        raw_responses,
    )
    summary = summarize_smoke_run(
        run_id=run_id,
        input_path=manifest_path,
        records_path=records_path,
        errors_path=errors_path,
        records=records,
        errors=errors,
        raw_responses_path=raw_responses_path,
        raw_responses=raw_responses,
        started_at=created_at,
        completed_at=datetime.now(UTC),
        dry_run=False,
        provider="openai",
        model=str(next(iter(manifest_index.values())).get("model") or DEFAULT_OPENAI_MODEL)
        if manifest_index
        else DEFAULT_OPENAI_MODEL,
        dataset_split=None,
    )
    summary["batch_id"] = batch_id
    summary["batch_output_path"] = str(output_path) if output_path else None
    summary["batch_error_output_path"] = str(error_output_path) if error_output_path else None
    summary_path = storage.write_json(
        Path("normalized/classification_runs")
        / f"{run_id}_candidate_classification_summary.json",
        summary,
    )
    return {
        "run_id": run_id,
        "records_path": str(records_path),
        "errors_path": str(errors_path),
        "raw_responses_path": str(raw_responses_path),
        "summary_path": str(summary_path),
        "counts": summary["counts"],
    }


def retrieve_and_convert_openai_batch(
    *,
    storage: LocalStorage,
    submission_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        msg = "OPENAI_API_KEY is not set."
        raise RuntimeError(msg)
    submission = json.loads(submission_path.read_text(encoding="utf-8"))
    run_id = str(submission["run_id"])
    batch_id = str(submission["batch"]["id"])
    resolved_manifest_path = manifest_path or Path(str(submission["manifest_path"]))
    with httpx.Client(timeout=180) as client:
        batch = retrieve_openai_batch(client=client, api_key=api_key, batch_id=batch_id)
        status_path = storage.write_json(
            Path("normalized/classification_batches")
            / f"{run_id}_openai_batch_status.json",
            {
                "run_id": run_id,
                "batch_id": batch_id,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "batch": batch,
                "notes": [
                    "Remote batch status was retrieved.",
                    "No SQLite, review queue, review decision, or reviewed knowledge state was "
                    "mutated.",
                ],
            },
        )
        output_path = None
        error_output_path = None
        if batch.get("output_file_id"):
            output_text = download_openai_file_text(
                client=client,
                api_key=api_key,
                file_id=str(batch["output_file_id"]),
            )
            output_path = write_text(
                storage.path(
                    Path("normalized/classification_batches")
                    / f"{run_id}_openai_batch_output.jsonl"
                ),
                output_text,
            )
        if batch.get("error_file_id"):
            error_text = download_openai_file_text(
                client=client,
                api_key=api_key,
                file_id=str(batch["error_file_id"]),
            )
            error_output_path = write_text(
                storage.path(
                    Path("normalized/classification_batches")
                    / f"{run_id}_openai_batch_error_output.jsonl"
                ),
                error_text,
            )
    result: dict[str, Any] = {
        "run_id": run_id,
        "batch_id": batch_id,
        "status": batch.get("status"),
        "status_path": str(status_path),
        "output_path": str(output_path) if output_path else None,
        "error_output_path": str(error_output_path) if error_output_path else None,
    }
    if batch.get("status") == "completed" and output_path is not None:
        result["conversion"] = convert_openai_batch_outputs(
            storage=storage,
            run_id=run_id,
            batch_id=batch_id,
            manifest_path=resolved_manifest_path,
            output_path=output_path,
            error_output_path=error_output_path,
        )
    return result


TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}


def watch_openai_batch(
    *,
    storage: LocalStorage,
    submission_path: Path,
    manifest_path: Path | None = None,
    interval_seconds: int = 300,
    max_checks: int = 288,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    for check_number in range(1, max_checks + 1):
        last_result = retrieve_and_convert_openai_batch(
            storage=storage,
            submission_path=submission_path,
            manifest_path=manifest_path,
        )
        checks.append(
            {
                "check_number": check_number,
                "checked_at": datetime.now(UTC).isoformat(),
                "status": last_result.get("status"),
                "status_path": last_result.get("status_path"),
                "output_path": last_result.get("output_path"),
                "converted": bool(last_result.get("conversion")),
            }
        )
        if str(last_result.get("status")) in TERMINAL_BATCH_STATUSES:
            break
        if check_number < max_checks:
            time.sleep(interval_seconds)

    run_id = str(last_result.get("run_id")) if last_result else infer_batch_run_id(submission_path)
    watch_path = storage.write_json(
        Path("normalized/classification_batches") / f"{run_id}_openai_batch_watch.json",
        {
            "run_id": run_id,
            "submission_path": str(submission_path),
            "manifest_path": str(manifest_path) if manifest_path else None,
            "interval_seconds": interval_seconds,
            "max_checks": max_checks,
            "checks": checks,
            "last_result": last_result,
            "notes": [
                "Batch watch polls status and retrieves outputs when the remote Batch completes.",
                "No SQLite, review queue, review decision, or reviewed knowledge state is mutated.",
            ],
        },
    )
    return {
        **(last_result or {}),
        "checks": len(checks),
        "watch_path": str(watch_path),
    }


def retry_wait_seconds(response: httpx.Response, attempt_number: int) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), 20.0)
        except ValueError:
            pass
    return min(2.0**attempt_number, 20.0)


def post_openai_with_retries(
    *,
    client: httpx.Client,
    request_payload: dict[str, Any],
    api_key: str,
    max_attempts: int = 3,
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    response: httpx.Response | None = None
    last_error: Exception | None = None
    for attempt_number in range(1, max_attempts + 1):
        try:
            response = client.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            wait_seconds = min(2.0**attempt_number, 20.0)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "retry_wait_seconds": wait_seconds
                    if attempt_number < max_attempts
                    else None,
                }
            )
            if attempt_number < max_attempts:
                time.sleep(wait_seconds)
            continue

        attempt = {"attempt": attempt_number, "status_code": response.status_code}
        attempts.append(attempt)
        if response.status_code not in {429, 500, 502, 503, 504}:
            return response, attempts
        if attempt_number < max_attempts:
            wait_seconds = retry_wait_seconds(response, attempt_number)
            attempt["retry_wait_seconds"] = wait_seconds
            time.sleep(wait_seconds)
    if response is not None:
        return response, attempts
    if last_error is not None:
        raise RuntimeError(f"OpenAI request failed after {max_attempts} attempts: {last_error}")
    raise RuntimeError("OpenAI request did not execute.")


def normalize_model_payload(
    payload: dict[str, Any],
    *,
    packet: CandidateClassificationPromptPacket,
    run_id: str,
    model_provider: str,
    model_name: str,
    created_at: datetime,
    latency_seconds: float,
    usage: dict[str, Any],
) -> dict[str, Any]:
    normalized = repair_required_uncertainty_markers(payload)
    normalized.update(
        {
            "classification_id": f"classification:{run_id}:{safe_id_fragment(packet.document_id)}",
            "document_id": packet.document_id,
            "classification_run_id": run_id,
            "schema_version": CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION,
            "extractor_name": EXTRACTOR_NAME,
            "extractor_version": EXTRACTOR_VERSION,
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_version": packet.prompt_version,
            "source_text_path": packet.source_text_path,
            "source_text_sha256": packet.source_text_sha256,
            "created_at": created_at.isoformat(),
            "requires_human_review": True,
            "review_state": "needs_review",
            "provenance": {
                **dict(normalized.get("provenance") or {}),
                "method": "openai_candidate_classification",
                "prompt_packet_id": packet.packet_id,
                "prompt_packet_run_id": packet.prompt_packet_run_id,
                "provider": model_provider,
                "model": model_name,
                "latency_seconds": latency_seconds,
                "usage": usage,
                "does_not_mutate_sqlite": True,
                "review_boundary": "ai_classification_candidate_not_reviewed_knowledge",
            },
        }
    )
    return normalized


def run_openai_prompt_packet(
    packet: CandidateClassificationPromptPacket,
    *,
    run_id: str,
    model: str,
    api_key: str,
    created_at: datetime,
    max_completion_tokens: int,
) -> tuple[CandidateStudyClassification | None, ClassificationRunError | None, dict[str, Any]]:
    request_payload = build_openai_chat_request(
        packet,
        model=model,
        max_completion_tokens=max_completion_tokens,
    )
    raw_response: dict[str, Any] = {
        "run_id": run_id,
        "document_id": packet.document_id,
        "packet_id": packet.packet_id,
        "provider": "openai",
        "model": model,
        "request": redacted_request_payload(request_payload),
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=180) as client:
            response, attempts = post_openai_with_retries(
                client=client,
                request_payload=request_payload,
                api_key=api_key,
            )
        latency_seconds = round(time.monotonic() - started, 3)
        response_json = response.json()
        raw_response.update(
            {
                "latency_seconds": latency_seconds,
                "attempts": attempts,
                "status_code": response.status_code,
                "response_json": response_json,
            }
        )
        response.raise_for_status()
        content = str(response_json["choices"][0]["message"]["content"])
        parsed = json.loads(content)
        normalized = normalize_model_payload(
            parsed,
            packet=packet,
            run_id=run_id,
            model_provider="openai",
            model_name=model,
            created_at=created_at,
            latency_seconds=latency_seconds,
            usage=response_json.get("usage") or {},
        )
        return CandidateStudyClassification.model_validate(normalized), None, raw_response
    except Exception as exc:  # noqa: BLE001
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["error"] = str(exc)
        return (
            None,
            ClassificationRunError(
                classification_run_id=run_id,
                document_id=packet.document_id,
                source_record_id=str(packet.corpus_metadata.get("legacy_study_id") or ""),
                error_type=type(exc).__name__,
                message=str(exc),
                provenance={
                    "method": "openai_candidate_classification_error",
                    "prompt_packet_id": packet.packet_id,
                    "provider": "openai",
                    "model": model,
                    "does_not_mutate_sqlite": True,
                },
            ),
            raw_response,
        )


def summarize_smoke_run(
    *,
    run_id: str,
    input_path: Path,
    records_path: Path,
    errors_path: Path,
    records: list[CandidateStudyClassification],
    errors: list[ClassificationRunError],
    raw_responses_path: Path | None = None,
    raw_responses: list[dict[str, Any]] | None = None,
    started_at: datetime,
    completed_at: datetime,
    dry_run: bool,
    provider: str | None = None,
    model: str | None = None,
    dataset_split: str | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    field_cannot_determine_counts: Counter[str] = Counter()
    for record in records:
        for field_name in record.missing_or_uncertain_fields:
            field_cannot_determine_counts[field_name] += 1
    raw_responses = raw_responses or []
    usage_counter: Counter[str] = Counter()
    latency_seconds = []
    for raw_response in raw_responses:
        usage = (raw_response.get("response_json") or {}).get("usage") or {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage_counter[key] += int(usage.get(key) or 0)
        if raw_response.get("latency_seconds") is not None:
            latency_seconds.append(float(raw_response["latency_seconds"]))
    return {
        "run_id": run_id,
        "dry_run": dry_run,
        "provider": provider,
        "model": model,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "input_path": str(input_path),
        "dataset_split_filter": dataset_split,
        "offset": offset,
        "records_path": str(records_path),
        "errors_path": str(errors_path),
        "raw_responses_path": str(raw_responses_path) if raw_responses_path else None,
        "counts": {
            "input_records": len(records) + len(errors),
            "valid_classification_records": len(records),
            "errors": len(errors),
            "records_with_evidence_spans": sum(bool(record.evidence_spans) for record in records),
            "records_with_uncertainty": sum(
                bool(record.missing_or_uncertain_fields) for record in records
            ),
        },
        "study_design_category_counts": dict(
            Counter(record.study_design_category for record in records)
        ),
        "evidence_context_counts": dict(Counter(record.evidence_context for record in records)),
        "overall_direction_counts": dict(Counter(record.overall_direction for record in records)),
        "cannot_determine_field_counts": dict(field_cannot_determine_counts),
        "usage": dict(usage_counter),
        "latency_seconds": {
            "min": min(latency_seconds, default=0),
            "max": max(latency_seconds, default=0),
            "total": round(sum(latency_seconds), 3),
        },
        "notes": [
            "Dry-run records are deterministic mock outputs for Pydantic validation."
            if dry_run
            else "Provider outputs are AI-classified candidate evidence only.",
            "No reviewed knowledge was produced.",
            "This command does not mutate SQLite, review queues, review decisions, "
            "or reviewed knowledge.",
        ],
    }


def run_classification_smoke(
    *,
    storage: LocalStorage,
    limit: int = 5,
    input_path: Path | None = None,
    dry_run: bool = True,
    run_id: str | None = None,
    provider: str = "openai",
    model: str = DEFAULT_OPENAI_MODEL,
    max_source_chars: int = 6_000,
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    dataset_split: str | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    if not dry_run and provider != "openai":
        msg = "Only provider='openai' is implemented for the first real smoke run."
        raise NotImplementedError(msg)

    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    created_at = started_at
    corpus_records, resolved_input_path = load_smoke_corpus_records(
        data_dir=storage.root,
        input_path=input_path,
        limit=limit,
        dataset_split=dataset_split,
        offset=offset,
    )
    legacy_english_indexes = load_legacy_english_context_index(storage.root)
    records: list[CandidateStudyClassification] = []
    errors: list[ClassificationRunError] = []
    raw_responses: list[dict[str, Any]] = []
    if dry_run:
        for corpus_record in corpus_records:
            try:
                records.append(
                    build_mock_classification(
                        record=corpus_record,
                        run_id=resolved_run_id,
                        data_dir=storage.root,
                        created_at=created_at,
                    )
                )
            except (FileNotFoundError, ValidationError, ValueError) as exc:
                errors.append(
                    ClassificationRunError(
                        classification_run_id=resolved_run_id,
                        document_id=corpus_record.document_id,
                        source_record_id=corpus_record.legacy_study_id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                        provenance={
                            "method": "classification_smoke_dry_run_error",
                            "does_not_call_llm": True,
                            "does_not_mutate_sqlite": True,
                        },
                    )
                )
    else:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            msg = "OPENAI_API_KEY is not set."
            raise RuntimeError(msg)
        for corpus_record in corpus_records:
            try:
                packet = build_prompt_packet(
                    record=corpus_record,
                    run_id=resolved_run_id,
                    data_dir=storage.root,
                    created_at=created_at,
                    max_source_chars=max_source_chars,
                    target_model_provider=provider,
                    target_model_name=model,
                    legacy_english_indexes=legacy_english_indexes,
                )
            except (FileNotFoundError, ValidationError, ValueError) as exc:
                errors.append(
                    ClassificationRunError(
                        classification_run_id=resolved_run_id,
                        document_id=corpus_record.document_id,
                        source_record_id=corpus_record.legacy_study_id,
                        error_type=type(exc).__name__,
                        message=str(exc),
                        provenance={
                            "method": "classification_smoke_prompt_packet_error",
                            "does_not_mutate_sqlite": True,
                        },
                    )
                )
                continue
            record, error, raw_response = run_openai_prompt_packet(
                packet,
                run_id=resolved_run_id,
                model=model,
                api_key=api_key,
                created_at=created_at,
                max_completion_tokens=max_completion_tokens,
            )
            raw_responses.append(raw_response)
            if record is not None:
                records.append(record)
            if error is not None:
                errors.append(error)

    if not corpus_records:
        errors.append(
            ClassificationRunError(
                classification_run_id=resolved_run_id,
                error_type="empty_input",
                message="No source-ready records were selected for classification smoke run.",
                provenance={"method": "classification_smoke_input_selection"},
            )
        )

    records_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_records.jsonl",
        records,
    )
    errors_path = storage.write_jsonl(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_errors.jsonl",
        errors,
    )
    raw_responses_path = None
    if raw_responses:
        raw_responses_path = write_dict_jsonl(
            storage.path(
                Path("normalized/classification_runs")
                / f"{resolved_run_id}_candidate_classification_raw_responses.jsonl"
            ),
            raw_responses,
        )
    completed_at = datetime.now(UTC)
    summary = summarize_smoke_run(
        run_id=resolved_run_id,
        input_path=resolved_input_path,
        records_path=records_path,
        errors_path=errors_path,
        records=records,
        errors=errors,
        raw_responses_path=raw_responses_path,
        raw_responses=raw_responses,
        started_at=started_at,
        completed_at=completed_at,
        dry_run=dry_run,
        provider=provider if not dry_run else None,
        model=model if not dry_run else None,
        dataset_split=dataset_split,
        offset=offset,
    )
    summary_path = storage.write_json(
        Path("normalized/classification_runs")
        / f"{resolved_run_id}_candidate_classification_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "records_path": str(records_path),
        "summary_path": str(summary_path),
        "errors_path": str(errors_path),
        "raw_responses_path": str(raw_responses_path) if raw_responses_path else None,
        "counts": summary["counts"],
    }
