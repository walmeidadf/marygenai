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

PROMPT_VERSION = "candidate_study_classification_prompt.v3"
EXTRACTOR_NAME = "marygenai_candidate_classifier"
EXTRACTOR_VERSION = "0.1.0"
DRY_RUN_PROVIDER = "dry_run"
DRY_RUN_MODEL = "deterministic_mock_classifier"
DEFAULT_PROMPT_SOURCE_CHARS = 12_000
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
DEFAULT_MAX_COMPLETION_TOKENS = 3000


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
) -> tuple[list[ClassificationCorpusRecord], Path]:
    path = input_path or latest_path(
        data_dir,
        "normalized/classification_runs/*_classification_sample_records.jsonl",
    )
    rows = read_jsonl(path)
    records: list[ClassificationCorpusRecord] = []
    for row in rows:
        if "corpus_record" in row:
            record = ClassificationSampleRecord.model_validate(row).corpus_record
        else:
            record = ClassificationCorpusRecord.model_validate(row)
        if record.source_ready:
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
        "cannot_determine.\n"
        "- evidence_context describes the evidence setting; use review_or_synthesis "
        "there for review articles.\n"
        "- outcome_domains must use only efficacy, safety, adverse_events, biomarker, "
        "cognition, mechanism, pharmacokinetics, public_health, or use_pattern. Use cognition "
        "for memory, attention, executive function, neurocognitive performance, or cognitive "
        "impairment. Behavior is not automatically cognition; omit unsupported domains and "
        "mark outcome_domains uncertain when no permitted value is defensible.\n\n"
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
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "input_path": str(input_path),
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
) -> dict[str, Any]:
    resolved_run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    corpus_records, resolved_input_path = load_smoke_corpus_records(
        data_dir=storage.root,
        input_path=input_path,
        limit=limit,
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
    normalized = dict(payload)
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
                **dict(payload.get("provenance") or {}),
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
