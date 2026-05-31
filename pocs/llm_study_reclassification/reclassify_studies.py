"""Generate LLM candidate study reclassification records for human review.

This POC is intentionally audit-only. It reads the identity-confirmed English
legacy cohort plus already persisted access-enrichment artifacts, then writes
candidate JSONL outputs. It does not validate identity, download full text, or
mutate SQLite review state.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import typer
from dotenv import load_dotenv
from lxml import etree, html
from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console
from rich.table import Table

from marygenai.initial_load.files import file_sha256
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.schemas import InputArtifact, OutputArtifact, RunManifest
from marygenai.settings import get_settings

ProviderName = Literal["groq", "openai", "anthropic", "cerebras"]

DEFAULT_COHORT_PATH = Path(
    "data/normalized/legacy_identity_validation/"
    "20260526T143818Z_identity_confirmed_for_triage.jsonl"
)
DEFAULT_OUTPUT_SUBDIR = Path("normalized/llm_study_reclassification")
DEFAULT_RAW_SUBDIR = Path("raw/llm_study_reclassification")
DEFAULT_EVIDENCE_INDEX_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "evidence_index"
DEFAULT_TASK_PACKET_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "task_packets"
DEFAULT_TASK_RUN_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "task_runs"
DEFAULT_SUMMARY_PACKET_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "evidence_summary_packets"
DEFAULT_SUMMARY_RUN_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "evidence_summary_runs"
DEFAULT_MODEL_COMPARISON_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "model_comparison"
DEFAULT_MICRO_EXTRACTION_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "micro_extraction"
DEFAULT_SEMANTIC_PARAGRAPH_INDEX_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "semantic_paragraph_index"
DEFAULT_UNIT_CLASSIFICATION_SUBDIR = DEFAULT_OUTPUT_SUBDIR / "unit_classification"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_PROVIDER = "groq"
DEFAULT_PROVIDER_MODELS = {
    "groq": DEFAULT_MODEL,
    "openai": "gpt-4.1",
    "anthropic": "claude-3-5-sonnet-latest",
    "cerebras": "gpt-oss-120b",
}
PROMPT_VERSION = "llm_study_reclassification_v0.1"
GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
CEREBRAS_CHAT_COMPLETIONS_URL = "https://api.cerebras.ai/v1/chat/completions"
ANTHROPIC_VERSION = "2023-06-01"
COMPARISON_TASKS = (
    "intervention_exposure",
    "condition_organ_system_extraction",
    "study_design_verification",
)
MICRO_EXTRACTION_FIELDS = (
    "cannabinoid_role",
    "target_condition",
    "study_design",
)
UNIT_CLASSIFICATION_TASKS = (
    "condition_classification",
    "cannabinoid_classification",
    "study_classification",
)
SEMANTIC_PARAGRAPH_LABELS = (
    "study_design",
    "population_model",
    "intervention_or_exposure",
    "condition_or_target",
    "comparator_control",
    "dose_route_duration",
    "outcomes_results",
    "safety_adverse_events",
    "background",
    "not_relevant",
)
FULL_TEXT_ARTIFACT_PRIORITY = {
    "pmc_nxml": 0,
    "europe_pmc_full_text_xml": 1,
    "pmc_html": 2,
}
TARGET_STUDY_TYPES = (
    "Meta-analysis",
    "Clinical Trial",
    "Double Blind Clinical Trial",
    "Animal Study",
    "Laboratory Study",
    "Clinical Meta-analysis",
)
TARGET_PATHOLOGIES = (
    "Pain",
    "Cancer",
    "Inflammation",
    "Cannabis Adverse Effects",
    "Addiction",
)
MAX_SOURCE_CHARS = 8_000
MAX_LEGACY_CHARS = 4_000
DIRECT_FULL_TEXT_CHAR_LIMIT = 12_000
LARGE_FULL_TEXT_CHAR_LIMIT = 80_000
CHUNK_MAX_CHARS = 1_800
CHUNK_OVERLAP_CHARS = 180
SUMMARY_MAX_OUTPUT_TOKENS = 2400
SEMANTIC_PARAGRAPH_MAX_OUTPUT_TOKENS = 3200
UNIT_EVIDENCE_TEXT_MAX_CHARS = 220
EVIDENCE_TOPICS = {
    "study_design": (
        "randomized",
        "trial",
        "double blind",
        "placebo",
        "meta-analysis",
        "systematic review",
        "cohort",
        "case-control",
        "case report",
        "in vitro",
        "animal",
        "mouse",
        "rat",
    ),
    "population_sample": (
        "participants",
        "patients",
        "subjects",
        "sample size",
        "n =",
        "male",
        "female",
        "human",
        "mice",
        "rats",
        "cells",
        "model",
    ),
    "conditions": (
        "pain",
        "cancer",
        "inflammation",
        "addiction",
        "dependence",
        "withdrawal",
        "adverse",
        "nausea",
        "vomiting",
        "tumor",
        "tumour",
    ),
    "cannabinoids": (
        "cannabinoid",
        "cannabis",
        "cannabidiol",
        "cbd",
        "thc",
        "dronabinol",
        "nabilone",
        "nabiximols",
        "endocannabinoid",
    ),
    "dosage_duration_route": (
        "dose",
        "dosage",
        "mg",
        "kg",
        "administered",
        "oral",
        "inhaled",
        "injection",
        "duration",
        "week",
        "day",
        "treatment",
    ),
    "comparator_control": (
        "placebo",
        "control",
        "comparator",
        "vehicle",
        "standard care",
        "baseline",
        "versus",
    ),
    "results_safety": (
        "result",
        "significant",
        "improved",
        "reduced",
        "increased",
        "outcome",
        "adverse event",
        "side effect",
        "safety",
        "toxicity",
        "mortality",
    ),
}
TASK_SEQUENCE = (
    "study_design_verification",
    "population_model_sample",
    "condition_organ_system_extraction",
    "intervention_exposure",
    "outcomes_safety",
    "legacy_adjudication",
)
TASK_TOPIC_FILTERS = {
    "study_design_verification": {"study_design", "population_sample"},
    "population_model_sample": {"population_sample", "study_design"},
    "condition_organ_system_extraction": {"conditions", "results_safety", "study_design"},
    "intervention_exposure": {
        "cannabinoids",
        "dosage_duration_route",
        "comparator_control",
        "study_design",
    },
    "outcomes_safety": {
        "results_safety",
        "conditions",
        "dosage_duration_route",
        "comparator_control",
    },
    "legacy_adjudication": set(EVIDENCE_TOPICS),
}

console = Console()
app = typer.Typer(help="Run the LLM study reclassification POC.")


class ArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    document_id: str
    artifact_type: str
    source: str
    payload_path: str | None = None
    payload_sha256: str | None = None
    payload_size_bytes: int | None = None
    raw_payload: dict[str, Any] | None = None
    url: str | None = None
    license: str | None = None
    created_at: str


class StudyCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    context_id: str | None = None
    title: str | None = None
    publication_year: int | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    legacy_study_type: str | None = None
    legacy_study_result: str | None = None
    legacy_sample_size: str | None = None
    legacy_context: dict[str, Any]
    selected_artifact: ArtifactReference | None = None
    metadata_artifacts: list[ArtifactReference] = Field(default_factory=list)
    publication_abstract: str | None = None
    pathologies: list[str] = Field(default_factory=list)
    selection_reasons: list[str] = Field(default_factory=list)


class EvidenceChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    artifact_id: str | None = None
    artifact_path: str | None = None
    section: str
    text: str
    char_start: int | None = None
    char_end: int | None = None
    score: float = 0.0
    matched_topics: list[str] = Field(default_factory=list)


class EvidenceParagraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paragraph_id: str
    document_id: str
    ordinal: int
    section: str
    unit_type: Literal[
        "paragraph",
        "abstract",
        "section",
        "table",
        "figure_caption",
        "list_item",
    ] = "paragraph"
    text: str
    artifact_id: str | None = None
    artifact_path: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    source_kind: Literal["full_text", "abstract_metadata", "legacy_context"]


class ParagraphWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_id: str
    document_id: str
    ordinal: int
    paragraph_ids: list[str]
    paragraphs: list[EvidenceParagraph]


class EvidencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_source_used: Literal["full_text", "abstract_metadata", "legacy_context_only"]
    context_strategy: str
    strategy_reason: str
    evidence_text: str
    full_text_chars: int | None = None
    source_payload_size_bytes: int | None = None
    source_chunks: list[EvidenceChunk] = Field(default_factory=list)
    retrieval_method: str


class PromptPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    evidence_source_used: Literal["full_text", "abstract_metadata", "legacy_context_only"]
    context_strategy: str
    strategy_reason: str
    prompt: str
    source_text_chars: int
    full_text_chars: int | None = None
    legacy_context_chars: int
    selected_artifact: ArtifactReference | None
    metadata_artifacts: list[ArtifactReference] = Field(default_factory=list)
    source_chunks: list[EvidenceChunk] = Field(default_factory=list)
    retrieval_method: str


class EvidenceIndexRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    document_id: str
    context_id: str | None = None
    title: str | None = None
    legacy_study_type: str | None = None
    evidence_source_used: Literal["full_text", "abstract_metadata", "legacy_context_only"]
    context_strategy: str
    strategy_reason: str
    retrieval_method: str
    selected_artifact: dict[str, Any] | None = None
    metadata_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    source_payload_size_bytes: int | None = None
    full_text_chars: int | None = None
    selected_chunk_count: int
    selected_chunks: list[dict[str, Any]] = Field(default_factory=list)
    legacy_guardrail_chars: int
    evidence_text_chars: int
    provenance: dict[str, Any]


class TaskPacketRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    document_id: str
    context_id: str | None = None
    task_name: str
    task_order: int
    task_goal: str
    model_tier_hint: str
    prompt_version: str
    prompt: str
    expected_output_schema: dict[str, Any]
    selected_chunk_ids: list[str] = Field(default_factory=list)
    context_strategy: str
    evidence_source_used: Literal["full_text", "abstract_metadata", "legacy_context_only"]
    provenance: dict[str, Any]


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str
    chunk_id: str | None = None
    section: str
    text: str
    score: float
    matched_topics: list[str] = Field(default_factory=list)
    source_kind: Literal["full_text_chunk", "metadata_or_legacy"]


class EvidenceSummaryPacketRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    document_id: str
    context_id: str | None = None
    task_name: str
    task_goal: str
    prompt_version: str
    prompt: str
    expected_output_schema: dict[str, Any]
    selected_span_ids: list[str] = Field(default_factory=list)
    selected_chunk_ids: list[str] = Field(default_factory=list)
    spans: list[EvidenceSpan] = Field(default_factory=list)
    context_strategy: str
    evidence_source_used: Literal["full_text", "abstract_metadata", "legacy_context_only"]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class RunPaths:
    records_path: Path
    summary_path: Path
    manifest_path: Path
    prompt_preview_path: Path
    raw_responses_path: Path


@app.callback()
def main() -> None:
    """Run LLM study reclassification commands."""


@app.command()
def run(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Normalized output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw response and prompt preview directory."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum unprocessed candidates to run."),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", help="Groq model name."),
    ] = DEFAULT_MODEL,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Prepare prompts without calling Groq."),
    ] = False,
    prompt_preview_count: Annotated[
        int,
        typer.Option("--prompt-preview-count", min=0, help="Prompt previews to write."),
    ] = 5,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=5_000, help="Maximum source evidence chars."),
    ] = MAX_SOURCE_CHARS,
    direct_full_text_char_limit: Annotated[
        int,
        typer.Option(
            "--direct-full-text-char-limit",
            min=1_000,
            help="Use compact direct full text when extracted text is at or below this size.",
        ),
    ] = DIRECT_FULL_TEXT_CHAR_LIMIT,
    large_full_text_char_limit: Annotated[
        int,
        typer.Option(
            "--large-full-text-char-limit",
            min=10_000,
            help="Mark larger full texts as large retrieval candidates in provenance.",
        ),
    ] = LARGE_FULL_TEXT_CHAR_LIMIT,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between Groq calls."),
    ] = 8.0,
    retry_errors: Annotated[
        bool,
        typer.Option("--retry-errors", help="Do not treat previous error records as processed."),
    ] = False,
) -> None:
    """Run a checkpointable Groq-backed candidate extraction sample."""
    load_dotenv()
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_reclassification")
    paths = build_run_paths(
        output_dir=resolved_output_dir,
        raw_output_dir=resolved_raw_output_dir,
        run_id=run_id,
    )

    cohort_records = load_jsonl(cohort_path)
    processed_document_ids = load_processed_document_ids(
        resolved_output_dir,
        retry_errors=retry_errors,
    )
    with sqlite3.connect(resolved_database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifacts_by_document_id = load_artifacts_by_document_id(
            connection,
            [str(record["document_id"]) for record in cohort_records],
        )
        abstracts_by_document_id = load_publication_abstracts(
            connection,
            [str(record["document_id"]) for record in cohort_records],
        )

    candidates = build_candidates(
        cohort_records,
        artifacts_by_document_id=artifacts_by_document_id,
        abstracts_by_document_id=abstracts_by_document_id,
    )
    selected = select_stratified_candidates(
        candidates,
        processed_document_ids=processed_document_ids,
        limit=limit,
    )

    api_key = os.getenv("GROQ_API_KEY")
    if not dry_run and not api_key:
        raise typer.BadParameter("GROQ_API_KEY is required unless --dry-run is set.")

    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    prompt_previews: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        prompt_package = build_prompt_package(
            candidate,
            max_source_chars=max_source_chars,
            direct_full_text_char_limit=direct_full_text_char_limit,
            large_full_text_char_limit=large_full_text_char_limit,
        )
        if index < prompt_preview_count:
            prompt_previews.append(prompt_preview_record(prompt_package))
        if dry_run:
            records.append(dry_run_record(candidate, prompt_package, model=model, run_id=run_id))
            continue
        record, raw_response = classify_with_groq(
            candidate,
            prompt_package,
            model=model,
            api_key=str(api_key),
            run_id=run_id,
        )
        records.append(record)
        raw_responses.append(raw_response)
        append_jsonl(paths.records_path, [record])
        append_jsonl(paths.raw_responses_path, [raw_response])
        if sleep_seconds and index < len(selected) - 1:
            time.sleep(sleep_seconds)

    if dry_run:
        append_jsonl(paths.records_path, records)
    append_jsonl(paths.prompt_preview_path, prompt_previews)
    if raw_responses and not paths.raw_responses_path.exists():
        append_jsonl(paths.raw_responses_path, raw_responses)

    summary = build_summary(
        run_id=run_id,
        dry_run=dry_run,
        model=model,
        cohort_path=cohort_path,
        database_path=resolved_database_path,
        selected=selected,
        records=records,
        processed_document_ids=processed_document_ids,
        paths=paths,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(paths.summary_path, summary)
    write_manifest(
        paths=paths,
        run_id=run_id,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
        cohort_path=cohort_path,
        summary=summary,
    )
    print_summary(summary, paths)


@app.command("prepare-evidence-index")
def prepare_evidence_index(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Evidence index output directory."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates to index."),
    ] = None,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=5_000, help="Maximum evidence packet chars."),
    ] = MAX_SOURCE_CHARS,
    direct_full_text_char_limit: Annotated[
        int,
        typer.Option(
            "--direct-full-text-char-limit",
            min=1_000,
            help="Use compact direct full text when extracted text is at or below this size.",
        ),
    ] = DIRECT_FULL_TEXT_CHAR_LIMIT,
    large_full_text_char_limit: Annotated[
        int,
        typer.Option(
            "--large-full-text-char-limit",
            min=10_000,
            help="Mark larger full texts as large retrieval candidates.",
        ),
    ] = LARGE_FULL_TEXT_CHAR_LIMIT,
) -> None:
    """Prepare an auditable local evidence index before any Groq classification."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_EVIDENCE_INDEX_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_evidence_index")

    cohort_records = load_jsonl(cohort_path)
    with sqlite3.connect(resolved_database_path) as connection:
        connection.row_factory = sqlite3.Row
        artifacts_by_document_id = load_artifacts_by_document_id(
            connection,
            [str(record["document_id"]) for record in cohort_records],
        )
        abstracts_by_document_id = load_publication_abstracts(
            connection,
            [str(record["document_id"]) for record in cohort_records],
        )

    candidates = build_candidates(
        cohort_records,
        artifacts_by_document_id=artifacts_by_document_id,
        abstracts_by_document_id=abstracts_by_document_id,
    )
    selected = select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)
    records = [
        build_evidence_index_record(
            candidate,
            run_id=run_id,
            max_source_chars=max_source_chars,
            direct_full_text_char_limit=direct_full_text_char_limit,
            large_full_text_char_limit=large_full_text_char_limit,
        )
        for candidate in selected
    ]
    records_path = resolved_output_dir / f"{run_id}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_summary.json"
    append_jsonl(records_path, [record.model_dump(mode="json") for record in records])
    summary = {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "prepare_adaptive_evidence_index",
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(resolved_database_path),
        "records_path": str(records_path),
        "selected_count": len(records),
        "context_strategy_counts": dict(
            Counter(record.context_strategy for record in records).most_common()
        ),
        "evidence_source_counts": dict(
            Counter(record.evidence_source_used for record in records).most_common()
        ),
        "selected_chunk_count": sum(record.selected_chunk_count for record in records),
        "notes": [
            "Evidence index records are pre-LLM retrieval inputs for candidate extraction.",
            "This command does not call Groq and does not mutate SQLite review state.",
            "Embeddings are intentionally not computed in this first adaptive index pass.",
        ],
    }
    write_json(summary_path, summary)
    print_evidence_index_summary(summary, records_path, summary_path)


@app.command("prepare-task-packets")
def prepare_task_packets(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Task packet output directory."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates to prepare."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Task name or 'all'."),
    ] = "all",
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=5_000, help="Maximum evidence packet chars."),
    ] = MAX_SOURCE_CHARS,
) -> None:
    """Prepare decomposed task prompts for manual/model evaluation without calling an LLM."""
    selected_tasks = resolve_task_names(task)
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_TASK_PACKET_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_task_packets")

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)
    records: list[TaskPacketRecord] = []
    for candidate in selected:
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=max_source_chars,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        for task_name in selected_tasks:
            records.append(
                build_task_packet_record(
                    candidate,
                    evidence_plan=evidence_plan,
                    task_name=task_name,
                    run_id=run_id,
                )
            )

    records_path = resolved_output_dir / f"{run_id}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_summary.json"
    append_jsonl(records_path, [record.model_dump(mode="json") for record in records])
    summary = {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "prepare_decomposed_task_packets",
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(resolved_database_path),
        "records_path": str(records_path),
        "candidate_count": len(selected),
        "task_packet_count": len(records),
        "task_counts": dict(Counter(record.task_name for record in records).most_common()),
        "model_tier_hint_counts": dict(
            Counter(record.model_tier_hint for record in records).most_common()
        ),
        "notes": [
            "Task packets are decomposed prompt candidates for evaluation.",
            "This command does not call Groq and does not mutate SQLite review state.",
            "Use these packets to compare small-model extraction against high-tier adjudication.",
        ],
    }
    write_json(summary_path, summary)
    print_task_packet_summary(summary, records_path, summary_path)


@app.command("run-task-batch")
def run_task_batch(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Task run output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw task response output directory."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Single task name to run."),
    ] = "study_design_verification",
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum candidates to run."),
    ] = 3,
    model: Annotated[
        str,
        typer.Option("--model", help="Groq model name."),
    ] = DEFAULT_MODEL,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between Groq calls."),
    ] = 15.0,
) -> None:
    """Run a small decomposed task batch through Groq for evaluation."""
    selected_tasks = resolve_task_names(task)
    if len(selected_tasks) != 1:
        raise typer.BadParameter("run-task-batch accepts exactly one task name, not 'all'.")
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise typer.BadParameter("GROQ_API_KEY is required to run a task batch.")

    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_TASK_RUN_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_task_run")
    records_path = resolved_output_dir / f"{run_id}_{task}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_{task}_summary.json"
    raw_responses_path = resolved_raw_output_dir / f"{run_id}_{task}_raw_responses.jsonl"
    packet_previews_path = resolved_raw_output_dir / f"{run_id}_{task}_packet_previews.jsonl"

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)
    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    packet_previews: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=MAX_SOURCE_CHARS,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        packet = build_task_packet_record(
            candidate,
            evidence_plan=evidence_plan,
            task_name=task,
            run_id=run_id,
        )
        packet_previews.append(task_packet_preview(packet))
        record, raw_response = run_task_packet_with_groq(
            packet,
            model=model,
            api_key=api_key,
        )
        records.append(record)
        raw_responses.append(raw_response)
        append_jsonl(records_path, [record])
        append_jsonl(raw_responses_path, [raw_response])
        if sleep_seconds and index < len(selected) - 1:
            time.sleep(sleep_seconds)
    append_jsonl(packet_previews_path, packet_previews)

    summary = {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "run_decomposed_task_batch",
        "task": task,
        "model": model,
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(resolved_database_path),
        "records_path": str(records_path),
        "raw_responses_path": str(raw_responses_path),
        "packet_previews_path": str(packet_previews_path),
        "selected_count": len(selected),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "recommended_action_counts": dict(
            Counter(str(record.get("recommended_action")) for record in records).most_common()
        ),
        "legacy_alignment_counts": dict(
            Counter(str(record.get("legacy_alignment")) for record in records).most_common()
        ),
        "notes": [
            "Task run outputs are candidate evidence for human review.",
            "This command does not mutate SQLite review state.",
        ],
    }
    write_json(summary_path, summary)
    print_task_run_summary(summary, records_path, raw_responses_path)


@app.command("prepare-summary-packets")
def prepare_summary_packets(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Evidence summary packet output directory."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates to prepare."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Task name or 'all'."),
    ] = "all",
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=5_000, help="Maximum evidence packet chars."),
    ] = MAX_SOURCE_CHARS,
    max_spans: Annotated[
        int,
        typer.Option("--max-spans", min=3, max=24, help="Maximum extractive spans per task."),
    ] = 10,
) -> None:
    """Prepare extractive evidence spans plus synthesis prompts without calling an LLM."""
    selected_tasks = resolve_task_names(task)
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_SUMMARY_PACKET_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_summary_packets")

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)
    records: list[EvidenceSummaryPacketRecord] = []
    for candidate in selected:
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=max_source_chars,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        for task_name in selected_tasks:
            records.append(
                build_evidence_summary_packet_record(
                    candidate,
                    evidence_plan=evidence_plan,
                    task_name=task_name,
                    run_id=run_id,
                    max_spans=max_spans,
                )
            )

    records_path = resolved_output_dir / f"{run_id}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_summary.json"
    append_jsonl(records_path, [record.model_dump(mode="json") for record in records])
    summary = {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "prepare_task_evidence_summary_packets",
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(resolved_database_path),
        "records_path": str(records_path),
        "candidate_count": len(selected),
        "summary_packet_count": len(records),
        "task_counts": dict(Counter(record.task_name for record in records).most_common()),
        "span_count": sum(len(record.spans) for record in records),
        "context_strategy_counts": dict(
            Counter(record.context_strategy for record in records).most_common()
        ),
        "notes": [
            "Summary packets use deterministic extractive spans before any LLM synthesis.",
            "Synthesis prompts require span citations and forbid unsupported facts.",
            "This command does not call Groq and does not mutate SQLite review state.",
        ],
    }
    write_json(summary_path, summary)
    print_summary_packet_summary(summary, records_path, summary_path)


@app.command("run-summary-batch")
def run_summary_batch(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Evidence summary run output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw summary response output directory."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Single task name to summarize."),
    ] = "condition_organ_system_extraction",
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum candidates to run."),
    ] = 3,
    model: Annotated[
        str,
        typer.Option("--model", help="Groq model name."),
    ] = DEFAULT_MODEL,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between Groq calls."),
    ] = 15.0,
    max_spans: Annotated[
        int,
        typer.Option("--max-spans", min=3, max=24, help="Maximum extractive spans per task."),
    ] = 10,
) -> None:
    """Run a small evidence-synthesis batch through Groq for evaluation."""
    selected_tasks = resolve_task_names(task)
    if len(selected_tasks) != 1:
        raise typer.BadParameter("run-summary-batch accepts exactly one task name, not 'all'.")
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise typer.BadParameter("GROQ_API_KEY is required to run a summary batch.")

    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_SUMMARY_RUN_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_summary_run")
    records_path = resolved_output_dir / f"{run_id}_{task}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_{task}_summary.json"
    raw_responses_path = resolved_raw_output_dir / f"{run_id}_{task}_raw_responses.jsonl"
    packet_previews_path = (
        resolved_raw_output_dir / f"{run_id}_{task}_summary_packet_previews.jsonl"
    )

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)
    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    packet_previews: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected):
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=MAX_SOURCE_CHARS,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        packet = build_evidence_summary_packet_record(
            candidate,
            evidence_plan=evidence_plan,
            task_name=task,
            run_id=run_id,
            max_spans=max_spans,
        )
        packet_previews.append(evidence_summary_packet_preview(packet))
        record, raw_response = run_summary_packet_with_groq(
            packet,
            model=model,
            api_key=api_key,
        )
        records.append(record)
        raw_responses.append(raw_response)
        append_jsonl(records_path, [record])
        append_jsonl(raw_responses_path, [raw_response])
        if sleep_seconds and index < len(selected) - 1:
            time.sleep(sleep_seconds)
    append_jsonl(packet_previews_path, packet_previews)

    summary = {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "run_task_evidence_summary_batch",
        "task": task,
        "model": model,
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(resolved_database_path),
        "records_path": str(records_path),
        "raw_responses_path": str(raw_responses_path),
        "packet_previews_path": str(packet_previews_path),
        "selected_count": len(selected),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "cited_span_count": sum(
            len(record.get("cited_span_ids", []))
            for record in records
            if isinstance(record.get("cited_span_ids"), list)
        ),
        "notes": [
            "Summary outputs are intermediate candidate evidence, not reviewed knowledge.",
            "This command does not mutate SQLite review state.",
        ],
    }
    write_json(summary_path, summary)
    print_summary_run_summary(summary, records_path, raw_responses_path)


@app.command("compare-model-batch")
def compare_model_batch(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Model comparison output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw model response output directory."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Single task name to compare."),
    ] = "intervention_exposure",
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, help="Maximum candidates to compare."),
    ] = 5,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Provider name or comma-separated providers: groq, openai, anthropic.",
        ),
    ] = DEFAULT_PROVIDER,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name when exactly one provider is selected."),
    ] = None,
    model_overrides: Annotated[
        str | None,
        typer.Option(
            "--model-overrides",
            help="Comma-separated provider:model overrides for multi-provider comparisons.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Prepare packets without calling model APIs."),
    ] = False,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between model calls."),
    ] = 15.0,
    max_spans: Annotated[
        int,
        typer.Option("--max-spans", min=3, max=24, help="Maximum extractive spans per task."),
    ] = 10,
    retry_errors: Annotated[
        bool,
        typer.Option("--retry-errors", help="Do not treat previous error records as processed."),
    ] = False,
) -> None:
    """Compare providers on the same task-specific evidence spans."""
    selected_tasks = resolve_task_names(task)
    if len(selected_tasks) != 1 or task not in COMPARISON_TASKS:
        raise typer.BadParameter(
            "compare-model-batch accepts one of: " + ", ".join(COMPARISON_TASKS)
        )
    provider_models = resolve_provider_models(
        provider,
        model=model,
        model_overrides=model_overrides,
    )
    load_dotenv()
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_MODEL_COMPARISON_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_model_comparison")
    records_path = resolved_output_dir / f"{run_id}_{task}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_{task}_summary.json"
    raw_responses_path = (
        resolved_raw_output_dir / f"{run_id}_{task}_model_comparison_raw_responses.jsonl"
    )
    packet_previews_path = (
        resolved_raw_output_dir / f"{run_id}_{task}_model_comparison_packet_previews.jsonl"
    )

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    processed_keys = load_processed_model_comparison_keys(
        resolved_output_dir,
        retry_errors=retry_errors,
    )
    selected = select_candidates_for_model_comparison(
        candidates,
        processed_keys=processed_keys,
        provider_models=provider_models,
        task_name=task,
        limit=limit,
    )

    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    packet_previews: list[dict[str, Any]] = []
    pending_calls = 0
    for candidate in selected:
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=MAX_SOURCE_CHARS,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        packet = build_evidence_summary_packet_record(
            candidate,
            evidence_plan=evidence_plan,
            task_name=task,
            run_id=run_id,
            max_spans=max_spans,
        )
        packet_previews.append(evidence_summary_packet_preview(packet))
        for provider_name, model_name in provider_models:
            key = model_comparison_key(candidate.document_id, task, provider_name, model_name)
            if key in processed_keys:
                continue
            if dry_run:
                record = dry_run_summary_comparison_record(
                    packet,
                    provider=provider_name,
                    model=model_name,
                )
                records.append(record)
                append_jsonl(records_path, [record])
                continue
            api_key = resolve_provider_api_key(provider_name)
            if not api_key:
                record = error_summary_record(
                    packet,
                    provider=provider_name,
                    model=model_name,
                    error=f"{api_key_env_var(provider_name)} is not set.",
                )
                records.append(record)
                append_jsonl(records_path, [record])
                continue
            record, raw_response = run_summary_packet_with_provider(
                packet,
                provider=provider_name,
                model=model_name,
                api_key=api_key,
            )
            records.append(record)
            raw_responses.append(raw_response)
            pending_calls += 1
            append_jsonl(records_path, [record])
            append_jsonl(raw_responses_path, [raw_response])
            if sleep_seconds:
                time.sleep(sleep_seconds)
    append_jsonl(packet_previews_path, packet_previews)

    summary = build_model_comparison_summary(
        run_id=run_id,
        task_name=task,
        dry_run=dry_run,
        provider_models=provider_models,
        cohort_path=cohort_path,
        database_path=resolved_database_path,
        records_path=records_path,
        raw_responses_path=raw_responses_path,
        packet_previews_path=packet_previews_path,
        selected=selected,
        records=records,
        processed_keys=processed_keys,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    print_model_comparison_summary(summary, records_path, raw_responses_path)
    if pending_calls == 0 and not dry_run:
        console.print("No model API calls were made.")


@app.command("compare-micro-extraction-batch")
def compare_micro_extraction_batch(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Micro-extraction output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw model response output directory."),
    ] = None,
    field: Annotated[
        str,
        typer.Option("--field", help="Micro field name or 'all'."),
    ] = "all",
    document_id: Annotated[
        list[str] | None,
        typer.Option("--document-id", help="Document id to include; repeat for fixed samples."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates when document ids are omitted."),
    ] = None,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Provider name or comma-separated providers: groq, openai, anthropic.",
        ),
    ] = DEFAULT_PROVIDER,
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name when exactly one provider is selected."),
    ] = None,
    model_overrides: Annotated[
        str | None,
        typer.Option(
            "--model-overrides",
            help="Comma-separated provider:model overrides for multi-provider comparisons.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Prepare prompts without calling model APIs."),
    ] = False,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between model calls."),
    ] = 15.0,
    max_spans: Annotated[
        int,
        typer.Option("--max-spans", min=3, max=24, help="Maximum extractive spans per field."),
    ] = 10,
) -> None:
    """Compare providers on atomic field extraction instead of narrative synthesis."""
    selected_fields = resolve_micro_extraction_fields(field)
    provider_models = resolve_provider_models(
        provider,
        model=model,
        model_overrides=model_overrides,
    )
    load_dotenv()
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_MICRO_EXTRACTION_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_llm_study_micro_extraction")
    field_slug = "all" if len(selected_fields) > 1 else selected_fields[0]
    records_path = resolved_output_dir / f"{run_id}_{field_slug}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_{field_slug}_summary.json"
    raw_responses_path = (
        resolved_raw_output_dir / f"{run_id}_{field_slug}_micro_extraction_raw_responses.jsonl"
    )
    prompt_previews_path = (
        resolved_raw_output_dir / f"{run_id}_{field_slug}_micro_extraction_prompt_previews.jsonl"
    )

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_micro_extraction_candidates(
        candidates,
        document_ids=document_id or [],
        limit=limit,
    )

    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    prompt_previews: list[dict[str, Any]] = []
    for candidate in selected:
        evidence_plan = build_evidence_plan(
            candidate,
            max_source_chars=MAX_SOURCE_CHARS,
            direct_full_text_char_limit=DIRECT_FULL_TEXT_CHAR_LIMIT,
            large_full_text_char_limit=LARGE_FULL_TEXT_CHAR_LIMIT,
        )
        for field_name in selected_fields:
            packet = build_micro_extraction_packet(
                candidate,
                evidence_plan=evidence_plan,
                field_name=field_name,
                run_id=run_id,
                max_spans=max_spans,
            )
            prompt_previews.append(micro_extraction_packet_preview(packet))
            for provider_name, model_name in provider_models:
                if dry_run:
                    record = dry_run_micro_extraction_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                    )
                    records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                api_key = resolve_provider_api_key(provider_name)
                if not api_key:
                    record = error_micro_extraction_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                        error=f"{api_key_env_var(provider_name)} is not set.",
                    )
                    records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                record, raw_response = run_micro_extraction_packet_with_provider(
                    packet,
                    provider=provider_name,
                    model=model_name,
                    api_key=api_key,
                )
                records.append(record)
                raw_responses.append(raw_response)
                append_jsonl(records_path, [record])
                append_jsonl(raw_responses_path, [raw_response])
                if sleep_seconds:
                    time.sleep(sleep_seconds)
    append_jsonl(prompt_previews_path, prompt_previews)

    summary = build_micro_extraction_summary(
        run_id=run_id,
        dry_run=dry_run,
        selected_fields=selected_fields,
        provider_models=provider_models,
        cohort_path=cohort_path,
        database_path=resolved_database_path,
        records_path=records_path,
        raw_responses_path=raw_responses_path,
        prompt_previews_path=prompt_previews_path,
        selected=selected,
        records=records,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    print_micro_extraction_summary(summary, records_path, raw_responses_path)


@app.command("compare-semantic-paragraph-index")
def compare_semantic_paragraph_index(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Semantic paragraph index output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw model response output directory."),
    ] = None,
    document_id: Annotated[
        list[str] | None,
        typer.Option("--document-id", help="Document id to include; repeat for fixed samples."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates when document ids are omitted."),
    ] = None,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Provider name or comma-separated providers: groq, openai, anthropic.",
        ),
    ] = "openai",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name when exactly one provider is selected."),
    ] = None,
    model_overrides: Annotated[
        str | None,
        typer.Option(
            "--model-overrides",
            help="Comma-separated provider:model overrides for multi-provider comparisons.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Prepare paragraph windows without calling model APIs."),
    ] = False,
    window_paragraphs: Annotated[
        int,
        typer.Option("--window-paragraphs", min=3, help="Paragraphs per model window."),
    ] = 12,
    overlap_paragraphs: Annotated[
        int,
        typer.Option("--overlap-paragraphs", min=0, help="Overlapping paragraphs per window."),
    ] = 3,
    max_windows_per_document: Annotated[
        int | None,
        typer.Option("--max-windows-per-document", min=1, help="Cap windows per document."),
    ] = 4,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between model calls."),
    ] = 3.0,
) -> None:
    """Build a candidate semantic paragraph index from literal cleaned paragraphs."""
    provider_models = resolve_provider_models(
        provider,
        model=model,
        model_overrides=model_overrides,
    )
    if overlap_paragraphs >= window_paragraphs:
        raise typer.BadParameter("--overlap-paragraphs must be smaller than --window-paragraphs.")
    load_dotenv()
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_SEMANTIC_PARAGRAPH_INDEX_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_semantic_paragraph_index")
    records_path = resolved_output_dir / f"{run_id}_window_records.jsonl"
    merged_index_path = resolved_output_dir / f"{run_id}_merged_index.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_summary.json"
    raw_responses_path = (
        resolved_raw_output_dir / f"{run_id}_semantic_paragraph_index_raw_responses.jsonl"
    )
    window_previews_path = (
        resolved_raw_output_dir / f"{run_id}_semantic_paragraph_index_window_previews.jsonl"
    )

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_micro_extraction_candidates(
        candidates,
        document_ids=document_id or [],
        limit=limit,
    )

    window_records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    window_previews: list[dict[str, Any]] = []
    paragraph_index_inputs: dict[str, list[EvidenceParagraph]] = {}
    for candidate in selected:
        paragraphs = load_candidate_paragraphs(candidate)
        paragraph_index_inputs[candidate.document_id] = paragraphs
        windows = build_paragraph_windows(
            candidate.document_id,
            paragraphs,
            window_paragraphs=window_paragraphs,
            overlap_paragraphs=overlap_paragraphs,
            max_windows=max_windows_per_document,
        )
        for window in windows:
            packet = build_semantic_paragraph_window_packet(
                candidate,
                window=window,
                run_id=run_id,
            )
            window_previews.append(semantic_paragraph_window_preview(packet))
            for provider_name, model_name in provider_models:
                if dry_run:
                    record = dry_run_semantic_paragraph_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                    )
                    window_records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                api_key = resolve_provider_api_key(provider_name)
                if not api_key:
                    record = error_semantic_paragraph_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                        error=f"{api_key_env_var(provider_name)} is not set.",
                    )
                    window_records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                record, raw_response = run_semantic_paragraph_window_with_provider(
                    packet,
                    provider=provider_name,
                    model=model_name,
                    api_key=api_key,
                )
                window_records.append(record)
                raw_responses.append(raw_response)
                append_jsonl(records_path, [record])
                append_jsonl(raw_responses_path, [raw_response])
                if sleep_seconds:
                    time.sleep(sleep_seconds)
    append_jsonl(window_previews_path, window_previews)

    merged_records = build_merged_semantic_paragraph_indexes(
        window_records,
        paragraph_index_inputs=paragraph_index_inputs,
    )
    append_jsonl(merged_index_path, merged_records)
    summary = build_semantic_paragraph_index_summary(
        run_id=run_id,
        dry_run=dry_run,
        provider_models=provider_models,
        cohort_path=cohort_path,
        database_path=resolved_database_path,
        records_path=records_path,
        merged_index_path=merged_index_path,
        raw_responses_path=raw_responses_path,
        window_previews_path=window_previews_path,
        selected=selected,
        paragraphs_by_document=paragraph_index_inputs,
        window_records=window_records,
        merged_records=merged_records,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
        window_paragraphs=window_paragraphs,
        overlap_paragraphs=overlap_paragraphs,
        max_windows_per_document=max_windows_per_document,
    )
    write_json(summary_path, summary)
    print_semantic_paragraph_index_summary(summary, records_path, merged_index_path)


@app.command("compare-unit-classification-batch")
def compare_unit_classification_batch(
    cohort_path: Annotated[
        Path,
        typer.Option("--cohort-path", help="Identity-confirmed English triage cohort JSONL."),
    ] = DEFAULT_COHORT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Document-unit classification output directory."),
    ] = None,
    raw_output_dir: Annotated[
        Path | None,
        typer.Option("--raw-output-dir", help="Raw model response output directory."),
    ] = None,
    task: Annotated[
        str,
        typer.Option("--task", help="Classification task name or 'all'."),
    ] = "all",
    document_id: Annotated[
        list[str] | None,
        typer.Option("--document-id", help="Document id to include; repeat for fixed samples."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum candidates when document ids are omitted."),
    ] = None,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="Provider name or comma-separated providers: groq, openai, anthropic.",
        ),
    ] = "openai",
    model: Annotated[
        str | None,
        typer.Option("--model", help="Model name when exactly one provider is selected."),
    ] = None,
    model_overrides: Annotated[
        str | None,
        typer.Option(
            "--model-overrides",
            help="Comma-separated provider:model overrides for multi-provider comparisons.",
        ),
    ] = None,
    semantic_index_path: Annotated[
        Path | None,
        typer.Option(
            "--semantic-index-path",
            help="Optional merged semantic document-unit index JSONL used to boost retrieval.",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Prepare task prompts without calling model APIs."),
    ] = False,
    max_units: Annotated[
        int,
        typer.Option("--max-units", min=4, max=40, help="Maximum document units per task."),
    ] = 18,
    sleep_seconds: Annotated[
        float,
        typer.Option("--sleep-seconds", min=0.0, help="Delay between model calls."),
    ] = 3.0,
) -> None:
    """Classify studies from selected semantic document units."""
    selected_tasks = resolve_unit_classification_tasks(task)
    provider_models = resolve_provider_models(
        provider,
        model=model,
        model_overrides=model_overrides,
    )
    load_dotenv()
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_UNIT_CLASSIFICATION_SUBDIR
    resolved_raw_output_dir = raw_output_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_raw_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ_unit_classification")
    task_slug = "all" if len(selected_tasks) > 1 else selected_tasks[0]
    records_path = resolved_output_dir / f"{run_id}_{task_slug}_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_{task_slug}_summary.json"
    raw_responses_path = (
        resolved_raw_output_dir / f"{run_id}_{task_slug}_unit_classification_raw_responses.jsonl"
    )
    prompt_previews_path = (
        resolved_raw_output_dir / f"{run_id}_{task_slug}_unit_classification_prompt_previews.jsonl"
    )
    label_index = load_semantic_label_index(semantic_index_path) if semantic_index_path else {}

    candidates = load_candidates_for_poc(
        cohort_path=cohort_path,
        database_path=resolved_database_path,
    )
    selected = select_micro_extraction_candidates(
        candidates,
        document_ids=document_id or [],
        limit=limit,
    )

    records: list[dict[str, Any]] = []
    raw_responses: list[dict[str, Any]] = []
    prompt_previews: list[dict[str, Any]] = []
    for candidate in selected:
        units = load_candidate_paragraphs(candidate)
        labels_by_unit = label_index.get(candidate.document_id, {})
        for task_name in selected_tasks:
            selected_units = select_units_for_classification_task(
                units,
                task_name=task_name,
                labels_by_unit=labels_by_unit,
                max_units=max_units,
            )
            packet = build_unit_classification_packet(
                candidate,
                task_name=task_name,
                units=selected_units,
                labels_by_unit=labels_by_unit,
                run_id=run_id,
                semantic_index_path=semantic_index_path,
            )
            prompt_previews.append(unit_classification_packet_preview(packet))
            for provider_name, model_name in provider_models:
                if dry_run:
                    record = dry_run_unit_classification_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                    )
                    records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                api_key = resolve_provider_api_key(provider_name)
                if not api_key:
                    record = error_unit_classification_record(
                        packet,
                        provider=provider_name,
                        model=model_name,
                        error=f"{api_key_env_var(provider_name)} is not set.",
                    )
                    records.append(record)
                    append_jsonl(records_path, [record])
                    continue
                record, raw_response = run_unit_classification_packet_with_provider(
                    packet,
                    provider=provider_name,
                    model=model_name,
                    api_key=api_key,
                )
                records.append(record)
                raw_responses.append(raw_response)
                append_jsonl(records_path, [record])
                append_jsonl(raw_responses_path, [raw_response])
                if sleep_seconds:
                    time.sleep(sleep_seconds)
    append_jsonl(prompt_previews_path, prompt_previews)

    summary = build_unit_classification_summary(
        run_id=run_id,
        dry_run=dry_run,
        selected_tasks=selected_tasks,
        provider_models=provider_models,
        cohort_path=cohort_path,
        database_path=resolved_database_path,
        semantic_index_path=semantic_index_path,
        records_path=records_path,
        raw_responses_path=raw_responses_path,
        prompt_previews_path=prompt_previews_path,
        selected=selected,
        records=records,
        started_at=run_started_at,
        completed_at=datetime.now(UTC),
        max_units=max_units,
    )
    write_json(summary_path, summary)
    print_unit_classification_summary(summary, records_path, raw_responses_path)


def build_run_paths(*, output_dir: Path, raw_output_dir: Path, run_id: str) -> RunPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        records_path=output_dir / f"{run_id}_records.jsonl",
        summary_path=output_dir / f"{run_id}_summary.json",
        manifest_path=output_dir / f"{run_id}_manifest.json",
        prompt_preview_path=raw_output_dir / f"{run_id}_prompt_previews.jsonl",
        raw_responses_path=raw_output_dir / f"{run_id}_raw_responses.jsonl",
    )


def resolve_provider_models(
    provider: str,
    *,
    model: str | None,
    model_overrides: str | None,
) -> list[tuple[ProviderName, str]]:
    providers = [
        resolve_provider(value.strip())
        for value in provider.split(",")
        if value.strip()
    ]
    if not providers:
        raise typer.BadParameter("At least one provider is required.")
    if model and len(providers) != 1:
        raise typer.BadParameter("--model can only be used with a single --provider.")
    overrides = parse_model_overrides(model_overrides)
    provider_models: list[tuple[ProviderName, str]] = []
    for provider_name in providers:
        model_name = (
            model
            or overrides.get(provider_name)
            or default_model_for_provider(provider_name)
        )
        provider_models.append((provider_name, model_name))
    return provider_models


def parse_model_overrides(value: str | None) -> dict[ProviderName, str]:
    overrides: dict[ProviderName, str] = {}
    if not value:
        return overrides
    for item in value.split(","):
        if not item.strip():
            continue
        provider_value, separator, model_name = item.partition(":")
        if not separator or not model_name.strip():
            raise typer.BadParameter(
                "--model-overrides must use provider:model entries."
            )
        overrides[resolve_provider(provider_value.strip())] = model_name.strip()
    return overrides


def model_comparison_key(
    document_id: str,
    task_name: str,
    provider: ProviderName,
    model: str,
) -> tuple[str, str, str, str]:
    return (document_id, task_name, provider, model)


def load_processed_model_comparison_keys(
    output_dir: Path,
    *,
    retry_errors: bool,
) -> set[tuple[str, str, str, str]]:
    processed: set[tuple[str, str, str, str]] = set()
    if not output_dir.exists():
        return processed
    for path in sorted(output_dir.glob("*_records.jsonl")):
        for record in load_jsonl(path):
            if record.get("poc_status") == "dry_run_prompt_prepared":
                continue
            if retry_errors and record.get("poc_status") == "error":
                continue
            document_id = record.get("document_id")
            task_name = record.get("task_name")
            provider = record.get("provider")
            model = record.get("model")
            if document_id and task_name and provider and model:
                processed.add(
                    (
                        str(document_id),
                        str(task_name),
                        str(provider),
                        str(model),
                    )
                )
    return processed


def select_candidates_for_model_comparison(
    candidates: list[StudyCandidate],
    *,
    processed_keys: set[tuple[str, str, str, str]],
    provider_models: list[tuple[ProviderName, str]],
    task_name: str,
    limit: int,
) -> list[StudyCandidate]:
    fully_processed_document_ids = {
        candidate.document_id
        for candidate in candidates
        if all(
            model_comparison_key(candidate.document_id, task_name, provider, model)
            in processed_keys
            for provider, model in provider_models
        )
    }
    return select_stratified_candidates(
        candidates,
        processed_document_ids=fully_processed_document_ids,
        limit=limit,
    )


def dry_run_summary_comparison_record(
    packet: EvidenceSummaryPacketRecord,
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    record = {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "provider": provider,
        "model": model,
        "poc_status": "dry_run_prompt_prepared",
        "errors": [],
        "needs_human_review": True,
        "review_reasons": ["Dry run only; no model evidence synthesis was generated."],
        "cited_span_ids": [],
        "span_grounding_audit": build_span_grounding_audit({}, packet),
        "provenance": {
            **packet.provenance,
            "provider": provider,
            "model": model,
            "prompt_version": packet.prompt_version,
            "selected_span_ids": packet.selected_span_ids,
            "selected_chunk_ids": packet.selected_chunk_ids,
            "context_strategy": packet.context_strategy,
            "evidence_source_used": packet.evidence_source_used,
            "input_prompt_chars": len(packet.prompt),
            "rough_input_token_estimate": rough_token_count(packet.prompt),
        },
    }
    record["comparison_audit"] = {
        "latency_seconds": None,
        "status_code": None,
        "attempt_count": 0,
        "not_found_or_insufficient_evidence_count": 0,
        "conflict_count": 0,
        "unsupported_evidence_text_count": 0,
        "evidence_text_coverage": {"evidence_text_count": 0, "evidence_texts_with_cited_spans": 0},
        "needs_human_review": True,
        "review_reason_count": 1,
    }
    return record


def resolve_micro_extraction_fields(field: str) -> list[str]:
    if field == "all":
        return list(MICRO_EXTRACTION_FIELDS)
    if field not in MICRO_EXTRACTION_FIELDS:
        raise typer.BadParameter(
            "field must be 'all' or one of: " + ", ".join(MICRO_EXTRACTION_FIELDS)
        )
    return [field]


def select_micro_extraction_candidates(
    candidates: list[StudyCandidate],
    *,
    document_ids: list[str],
    limit: int | None,
) -> list[StudyCandidate]:
    if document_ids:
        requested = set(document_ids)
        selected = [candidate for candidate in candidates if candidate.document_id in requested]
        missing = sorted(requested.difference({candidate.document_id for candidate in selected}))
        if missing:
            raise typer.BadParameter("Unknown document ids: " + ", ".join(missing))
        return selected
    return select_stratified_candidates(candidates, processed_document_ids=set(), limit=limit)


def micro_field_task_name(field_name: str) -> str:
    return {
        "cannabinoid_role": "intervention_exposure",
        "target_condition": "condition_organ_system_extraction",
        "study_design": "study_design_verification",
    }[field_name]


def build_micro_extraction_packet(
    candidate: StudyCandidate,
    *,
    evidence_plan: EvidencePlan,
    field_name: str,
    run_id: str,
    max_spans: int,
) -> dict[str, Any]:
    task_name = micro_field_task_name(field_name)
    spans = select_task_evidence_spans(
        candidate,
        evidence_plan=evidence_plan,
        task_name=task_name,
        max_spans=max_spans,
    )
    legacy_guardrail = build_legacy_guardrail_text(candidate)
    schema = micro_extraction_output_schema(field_name)
    prompt = build_micro_extraction_prompt(
        candidate=candidate,
        field_name=field_name,
        task_name=task_name,
        schema=schema,
        spans=spans,
        legacy_context_text=legacy_guardrail,
    )
    source_artifacts = [candidate.selected_artifact] if candidate.selected_artifact else []
    source_artifacts.extend(candidate.metadata_artifacts)
    return {
        "run_id": run_id,
        "document_id": candidate.document_id,
        "context_id": candidate.context_id,
        "task_name": task_name,
        "field_name": field_name,
        "prompt_version": f"{PROMPT_VERSION}_micro_{field_name}",
        "prompt": prompt,
        "expected_output_schema": schema,
        "selected_span_ids": [span.span_id for span in spans],
        "selected_chunk_ids": sorted(
            {span.chunk_id for span in spans if span.chunk_id is not None}
        ),
        "spans": spans,
        "context_strategy": evidence_plan.context_strategy,
        "evidence_source_used": evidence_plan.evidence_source_used,
        "provenance": {
            "source": "llm_study_reclassification_poc",
            "method": "micro_field_extraction_packet",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "micro_extraction_candidate_not_reviewed_knowledge",
            "retrieval_method": evidence_plan.retrieval_method,
            "compression_method": "deterministic_extractive_spans_v0.1",
            "source_artifact_ids": [
                artifact.artifact_id for artifact in source_artifacts
            ],
            "source_artifact_paths": [
                artifact.payload_path
                for artifact in source_artifacts
                if artifact.payload_path
            ],
            "legacy_context_id": candidate.context_id,
        },
    }


def micro_extraction_output_schema(field_name: str) -> dict[str, Any]:
    support_status_values = (
        "supported | conflicting | partial | not_found | insufficient_evidence"
    )
    common = {
        "document_id": "string",
        "field_name": field_name,
        "candidate": {
            "candidate_value": "string | boolean | null",
            "support_status": support_status_values,
            "explicit_or_inferred": "explicit | inferred | unclear",
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim substring from cited spans, or empty string",
            "confidence": "high | medium | low",
        },
        "legacy_alignment": {
            "alignment": "supports | conflicts | partial | not_in_legacy | insufficient_evidence",
            "note": "string",
            "cited_span_ids": ["span_id"],
        },
        "needs_human_review": "boolean",
        "review_reasons": ["string"],
    }
    if field_name == "cannabinoid_role":
        common["candidate"] = {
            "role_of_cannabinoid": (
                "intervention | exposure | condition_context | population_context | "
                "background_only | not_found | unclear"
            ),
            "is_primary_study_target": "boolean | unclear",
            "support_status": support_status_values,
            "explicit_or_inferred": "explicit | inferred | unclear",
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim substring from cited spans, or empty string",
            "confidence": "high | medium | low",
        }
    if field_name == "target_condition":
        common["candidate"] = {
            "condition_name": "string | null",
            "condition_role": (
                "primary_target | secondary_target | comorbidity | context | "
                "outcome | not_found | unclear"
            ),
            "organ_system": "string | null",
            "organ_system_support": "explicit | inferred | not_found | unclear",
            "support_status": support_status_values,
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim substring from cited spans, or empty string",
            "confidence": "high | medium | low",
        }
    if field_name == "study_design":
        common["candidate"] = {
            "study_design": "string | null",
            "study_design_family": (
                "evidence_synthesis | human_clinical | human_observational | animal | "
                "laboratory | case_report | mixed | not_found | unclear"
            ),
            "support_status": support_status_values,
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim substring from cited spans, or empty string",
            "confidence": "high | medium | low",
        }
    return common


def build_micro_extraction_prompt(
    *,
    candidate: StudyCandidate,
    field_name: str,
    task_name: str,
    schema: dict[str, Any],
    spans: list[EvidenceSpan],
    legacy_context_text: str,
) -> str:
    span_text = "\n\n".join(
        "\n".join(
            [
                f"[span_id={span.span_id}]",
                f"chunk_id: {span.chunk_id or ''}",
                f"section: {span.section}",
                f"text: {span.text}",
            ]
        )
        for span in spans
    )
    return (
        f"You are extracting one atomic field for a human-reviewed cannabinoid "
        f"""evidence knowledge base.

Task: {task_name}
Atomic field: {field_name}

Rules:
- Do not provide medical advice, treatment recommendations, or clinical instructions.
- Return only valid JSON matching the schema.
- Use English only.
- Use only the evidence spans below for source support.
- Use the legacy English context only as a guardrail and comparison baseline.
- Do not write a narrative synthesis.
- Do not extract a value unless the cited spans support that exact field.
- Evidence text must be a short verbatim substring from the cited spans.
- If support_status is supported, conflicting, or partial, cited_span_ids must be non-empty.
- If evidence is missing, set support_status to not_found or insufficient_evidence.
- Mark needs_human_review true when source evidence and legacy context conflict.
- For cannabinoid_role, distinguish intervention, exposure, condition_context,
  population_context, background_only, not_found, and unclear.
- For target_condition, do not treat a comorbidity or setting as the primary study target.
- For study_design, prefer the span wording over legacy when they conflict, and preserve
  the conflict for human review.

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Evidence spans:
{span_text}
"""
    )


def micro_extraction_packet_preview(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "field_name": packet["field_name"],
        "prompt_chars": len(packet["prompt"]),
        "selected_span_ids": packet["selected_span_ids"],
        "selected_chunk_ids": packet["selected_chunk_ids"],
        "context_strategy": packet["context_strategy"],
        "evidence_source_used": packet["evidence_source_used"],
        "prompt": packet["prompt"],
    }


def resolve_unit_classification_tasks(task: str) -> list[str]:
    if task == "all":
        return list(UNIT_CLASSIFICATION_TASKS)
    if task not in UNIT_CLASSIFICATION_TASKS:
        raise typer.BadParameter(
            "task must be 'all' or one of: " + ", ".join(UNIT_CLASSIFICATION_TASKS)
        )
    return [task]


def load_semantic_label_index(path: Path) -> dict[str, dict[str, list[str]]]:
    label_index: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for row in load_jsonl(path):
        document_id = str(row.get("document_id") or "")
        annotations = row.get("merged_annotations", [])
        if not document_id or not isinstance(annotations, list):
            continue
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            paragraph_id = str(annotation.get("paragraph_id") or "")
            labels = annotation.get("labels", [])
            if paragraph_id and isinstance(labels, list):
                label_index[document_id][paragraph_id] = [str(label) for label in labels]
    return dict(label_index)


def select_units_for_classification_task(
    units: list[EvidenceParagraph],
    *,
    task_name: str,
    labels_by_unit: dict[str, list[str]],
    max_units: int,
) -> list[EvidenceParagraph]:
    scored = [
        (score_unit_for_classification_task(unit, task_name, labels_by_unit), unit)
        for unit in units
    ]
    selected = [
        unit
        for score, unit in sorted(scored, key=lambda item: (-item[0], item[1].ordinal))
        if score > 0
    ][:max_units]
    if len(selected) < min(max_units, 4):
        selected_ids = {unit.paragraph_id for unit in selected}
        for unit in units:
            if unit.paragraph_id not in selected_ids:
                selected.append(unit)
                selected_ids.add(unit.paragraph_id)
            if len(selected) >= min(max_units, 4):
                break
    return sorted(selected, key=lambda unit: unit.ordinal)


def score_unit_for_classification_task(
    unit: EvidenceParagraph,
    task_name: str,
    labels_by_unit: dict[str, list[str]],
) -> int:
    labels = set(labels_by_unit.get(unit.paragraph_id, []))
    text = normalize_label(" ".join([unit.section, unit.text]))
    score = 0
    label_weights = {
        "condition_classification": {
            "condition_or_target": 10,
            "population_model": 4,
            "outcomes_results": 3,
            "safety_adverse_events": 2,
        },
        "cannabinoid_classification": {
            "intervention_or_exposure": 10,
            "dose_route_duration": 6,
            "outcomes_results": 3,
            "safety_adverse_events": 3,
        },
        "study_classification": {
            "study_design": 10,
            "population_model": 6,
            "comparator_control": 5,
            "outcomes_results": 4,
        },
    }[task_name]
    score += sum(label_weights.get(label, 0) for label in labels)
    keywords = {
        "condition_classification": (
            "condition",
            "disease",
            "pain",
            "cancer",
            "inflammation",
            "depression",
            "anxiety",
            "epilepsy",
            "symptom",
            "diagnosis",
            "patient",
        ),
        "cannabinoid_classification": (
            "cannabis",
            "cannabinoid",
            "cannabidiol",
            "cbd",
            "thc",
            "marijuana",
            "nabiximols",
            "dronabinol",
            "nabilone",
            "dose",
            "route",
        ),
        "study_classification": (
            "randomized",
            "trial",
            "cohort",
            "case-control",
            "cross-sectional",
            "systematic review",
            "meta-analysis",
            "sample",
            "participants",
            "subjects",
            "country",
            "placebo",
        ),
    }[task_name]
    score += sum(2 for keyword in keywords if keyword in text)
    if unit.unit_type == "table":
        score += 2
    if normalize_label(unit.section) in {"methods", "results", "abstract"}:
        score += 1
    return score


def build_unit_classification_packet(
    candidate: StudyCandidate,
    *,
    task_name: str,
    units: list[EvidenceParagraph],
    labels_by_unit: dict[str, list[str]],
    run_id: str,
    semantic_index_path: Path | None,
) -> dict[str, Any]:
    schema = unit_classification_output_schema(task_name)
    prompt = build_unit_classification_prompt(
        candidate=candidate,
        task_name=task_name,
        schema=schema,
        units=units,
        labels_by_unit=labels_by_unit,
        legacy_context_text=build_legacy_guardrail_text(candidate),
    )
    source_artifacts = [candidate.selected_artifact] if candidate.selected_artifact else []
    source_artifacts.extend(candidate.metadata_artifacts)
    return {
        "run_id": run_id,
        "document_id": candidate.document_id,
        "context_id": candidate.context_id,
        "task_name": task_name,
        "prompt_version": f"{PROMPT_VERSION}_unit_{task_name}",
        "prompt": prompt,
        "expected_output_schema": schema,
        "selected_unit_ids": [unit.paragraph_id for unit in units],
        "units": units,
        "provenance": {
            "source": "llm_study_reclassification_poc",
            "method": "unit_index_task_classification",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "unit_classification_candidate_not_reviewed_knowledge",
            "retrieval_method": "semantic_document_unit_label_keyword_selection_v0.1",
            "semantic_index_path": str(semantic_index_path) if semantic_index_path else None,
            "source_artifact_ids": [
                artifact.artifact_id for artifact in source_artifacts
            ],
            "source_artifact_paths": [
                artifact.payload_path
                for artifact in source_artifacts
                if artifact.payload_path
            ],
            "legacy_context_id": candidate.context_id,
        },
    }


def unit_classification_output_schema(task_name: str) -> dict[str, Any]:
    common: dict[str, Any] = {
        "document_id": "string",
        "task_name": task_name,
        "task_support_status": (
            "supported | conflicting | partial | not_found | insufficient_evidence"
        ),
        "legacy_alignment": {
            "alignment": "supports | conflicts | partial | not_in_legacy | insufficient_evidence",
            "note": "string",
            "cited_unit_ids": ["unit id"],
        },
        "needs_human_review": "boolean",
        "review_reasons": ["string"],
    }
    evidence_entry = {
        "support_status": "supported | conflicting | partial | not_found | insufficient_evidence",
        "explicit_or_inferred": "explicit | inferred | unclear",
        "cited_unit_ids": ["one unit id for evidence_text support"],
        "evidence_text": (
            "single short verbatim substring from one cited unit, max "
            f"{UNIT_EVIDENCE_TEXT_MAX_CHARS} characters, or empty string"
        ),
        "evidence_note": "optional synthesis or explanation; not a source quote",
        "confidence": "high | medium | low",
    }
    if task_name == "condition_classification":
        common["condition_classification"] = {
            "conditions": [
                {
                    "condition_name": "string",
                    "condition_role": (
                        "primary_target | secondary_target | comorbidity | context | "
                        "outcome | not_found | unclear"
                    ),
                    "organ_systems": ["string"],
                    **evidence_entry,
                }
            ],
            "human_relevance": {
                "population_type": "human | animal | in_vitro | mixed | unclear",
                **evidence_entry,
            },
        }
    elif task_name == "cannabinoid_classification":
        common["cannabinoid_classification"] = {
            "role_of_cannabinoid": (
                "intervention | exposure | condition_context | population_context | "
                "background_only | not_found | unclear"
            ),
            "is_primary_study_target": "boolean | unclear",
            "cannabinoids_or_products": [
                {
                    "name": "string",
                    "composition": "string | null",
                    "dose_route_duration": "string | null",
                    **evidence_entry,
                }
            ],
            **evidence_entry,
        }
    elif task_name == "study_classification":
        common["study_classification"] = {
            "study_design": "string | null",
            "study_design_family": (
                "evidence_synthesis | human_clinical | human_observational | animal | "
                "laboratory | case_report | mixed | not_found | unclear"
            ),
            "sample_size": "string | null",
            "country_or_setting": "string | null",
            "result_direction": (
                "positive | negative | mixed | neutral | safety_signal | "
                "not_reported | unclear"
            ),
            **evidence_entry,
        }
    return common


def build_unit_classification_prompt(
    *,
    candidate: StudyCandidate,
    task_name: str,
    schema: dict[str, Any],
    units: list[EvidenceParagraph],
    labels_by_unit: dict[str, list[str]],
    legacy_context_text: str,
) -> str:
    unit_text = "\n\n".join(
        "\n".join(
            [
                f"[unit_id={unit.paragraph_id}]",
                f"unit_type: {unit.unit_type}",
                f"section: {unit.section}",
                f"candidate_index_labels: {', '.join(labels_by_unit.get(unit.paragraph_id, []))}",
                f"text: {unit.text}",
            ]
        )
        for unit in units
    )
    return (
        f"You are classifying one study-level task for a human-reviewed cannabinoid "
        f"""evidence knowledge base.

Task: {task_name}

Rules:
- Do not provide medical advice, treatment recommendations, or clinical instructions.
- Return only valid JSON matching the schema.
- Use English only.
- Use only the selected document units below for source support.
- Use the legacy English context only as a guardrail and comparison baseline.
- Treat candidate_index_labels as retrieval hints, not truth.
- Do not extract a field unless cited document units support that exact field.
- evidence_text is a quote field, not a summary field.
- Every non-empty evidence_text must be one short contiguous substring from exactly
  one cited unit.
- evidence_text must be {UNIT_EVIDENCE_TEXT_MAX_CHARS} characters or fewer.
- evidence_text must not contain ellipses, bracketed omissions, or joined clauses
  from multiple places.
- If you need to explain or synthesize across units, put that explanation in
  evidence_note, not evidence_text.
- If support_status is supported, conflicting, or partial, cited_unit_ids must be non-empty.
- If evidence is missing, use not_found or insufficient_evidence.
- Mark needs_human_review true when source evidence and legacy context conflict.
- Prefer explicit source wording over legacy values when they conflict, but preserve
  the conflict for human review.
- legacy_alignment must be conflicts when the note says the source units and legacy
  context describe different studies, populations, interventions, or conditions.
- For study_classification, randomized trials, controlled trials, double-blind trials,
  and open-label intervention trials are human_clinical unless the units clearly show
  animal, laboratory, observational, or evidence-synthesis design.

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Selected document units:
{unit_text}
"""
    )


def unit_classification_packet_preview(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "prompt_version": packet["prompt_version"],
        "prompt_chars": len(packet["prompt"]),
        "selected_unit_ids": packet["selected_unit_ids"],
        "unit_types": [unit.unit_type for unit in packet["units"]],
        "prompt": packet["prompt"],
    }


def load_candidate_paragraphs(candidate: StudyCandidate) -> list[EvidenceParagraph]:
    paragraphs = load_source_paragraphs(candidate)
    if paragraphs:
        return paragraphs
    fallback_texts: list[tuple[str, str]] = []
    if candidate.publication_abstract:
        fallback_texts.append(("abstract_metadata", candidate.publication_abstract))
    legacy_text = build_legacy_guardrail_text(candidate)
    if legacy_text:
        fallback_texts.append(("legacy_context", legacy_text))
    paragraphs = []
    for section, text in fallback_texts:
        for sentence in split_sentences(text):
            if len(sentence) < 30:
                continue
            paragraphs.append(
                EvidenceParagraph(
                    paragraph_id=f"p{len(paragraphs) + 1:04d}",
                    document_id=candidate.document_id,
                    ordinal=len(paragraphs) + 1,
                    section=section,
                    unit_type=(
                        "abstract" if section == "abstract_metadata" else "paragraph"
                    ),
                    text=truncate_text(sentence, 1_200),
                    source_kind=(
                        "abstract_metadata"
                        if section == "abstract_metadata"
                        else "legacy_context"
                    ),
                )
            )
    return paragraphs


def load_source_paragraphs(candidate: StudyCandidate) -> list[EvidenceParagraph]:
    artifact = candidate.selected_artifact
    if not artifact or not artifact.payload_path:
        return []
    path = Path(artifact.payload_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return []
    raw = path.read_bytes()
    if artifact.artifact_type in {"pmc_nxml", "europe_pmc_full_text_xml"}:
        return extract_xml_paragraphs(raw, artifact=artifact)
    if artifact.artifact_type == "pmc_html":
        return extract_html_paragraphs(raw, artifact=artifact)
    return []


def extract_xml_paragraphs(raw: bytes, *, artifact: ArtifactReference) -> list[EvidenceParagraph]:
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        return paragraphs_from_plain_text(
            decode_raw_text(raw),
            artifact=artifact,
            section="unparsed_full_text",
        )
    if etree.QName(root).localname.lower() == "html":
        return extract_html_paragraphs(raw, artifact=artifact)
    for xpath in (".//*[local-name()='ref-list']", ".//*[local-name()='back']"):
        for element in root.xpath(xpath):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

    paragraphs: list[EvidenceParagraph] = []
    for element in root.xpath(".//*[local-name()='abstract']//*[local-name()='p']"):
        append_paragraph_from_element(
            paragraphs,
            element,
            artifact=artifact,
            section="abstract",
            unit_type="abstract",
        )
    for index, section_element in enumerate(root.xpath(".//*[local-name()='sec']")):
        section = section_title(section_element) or f"section_{index + 1}"
        for paragraph_element in section_element.xpath(".//*[local-name()='p']"):
            if has_xml_ancestor(paragraph_element, {"table-wrap", "fig"}):
                continue
            append_paragraph_from_element(
                paragraphs,
                paragraph_element,
                artifact=artifact,
                section=section,
            )
    for index, table_element in enumerate(root.xpath(".//*[local-name()='table-wrap']")):
        append_document_unit_from_text(
            paragraphs,
            clean_text(" ".join(table_element.itertext())),
            artifact=artifact,
            section=nearest_xml_section_title(table_element) or f"table_{index + 1}",
            unit_type="table",
            max_chars=2_500,
        )
    for index, figure_element in enumerate(root.xpath(".//*[local-name()='fig']")):
        caption_text = clean_text(
            " ".join(
                caption_part
                for caption in figure_element.xpath(".//*[local-name()='caption']")
                for caption_part in caption.itertext()
            )
        )
        append_document_unit_from_text(
            paragraphs,
            caption_text,
            artifact=artifact,
            section=nearest_xml_section_title(figure_element) or f"figure_{index + 1}",
            unit_type="figure_caption",
            max_chars=2_000,
        )
    if not paragraphs:
        return paragraphs_from_plain_text(
            extract_xml_text(raw),
            artifact=artifact,
            section="full_text",
        )
    return deduplicate_paragraphs(paragraphs)


def extract_html_paragraphs(raw: bytes, *, artifact: ArtifactReference) -> list[EvidenceParagraph]:
    document = html.fromstring(raw)
    for element in document.xpath("//script|//style|//nav|//footer|//aside"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    paragraphs: list[EvidenceParagraph] = []
    for element in document.xpath("//p"):
        if has_html_ancestor(element, {"table", "figure"}):
            continue
        append_paragraph_from_element(
            paragraphs,
            element,
            artifact=artifact,
            section=nearest_html_section(element),
        )
    for index, table_element in enumerate(document.xpath("//table")):
        append_document_unit_from_text(
            paragraphs,
            clean_text(" ".join(table_element.itertext())),
            artifact=artifact,
            section=nearest_html_section(table_element) or f"table_{index + 1}",
            unit_type="table",
            max_chars=2_500,
        )
    for index, figure_element in enumerate(document.xpath("//figure")):
        caption_text = clean_text(
            " ".join(
                caption_part
                for caption in figure_element.xpath(".//figcaption|.//*[@class='caption']")
                for caption_part in caption.itertext()
            )
        )
        append_document_unit_from_text(
            paragraphs,
            caption_text,
            artifact=artifact,
            section=nearest_html_section(figure_element) or f"figure_{index + 1}",
            unit_type="figure_caption",
            max_chars=2_000,
        )
    if not paragraphs:
        return paragraphs_from_plain_text(
            document.text_content(),
            artifact=artifact,
            section="html_full_text",
        )
    return deduplicate_paragraphs(paragraphs)


def append_paragraph_from_element(
    paragraphs: list[EvidenceParagraph],
    element: etree._Element,
    *,
    artifact: ArtifactReference,
    section: str,
    unit_type: Literal["paragraph", "abstract", "list_item"] = "paragraph",
) -> None:
    append_document_unit_from_text(
        paragraphs,
        clean_text(" ".join(element.itertext())),
        artifact=artifact,
        section=section,
        unit_type=unit_type,
    )


def append_document_unit_from_text(
    paragraphs: list[EvidenceParagraph],
    text: str,
    *,
    artifact: ArtifactReference,
    section: str,
    unit_type: Literal[
        "paragraph",
        "abstract",
        "section",
        "table",
        "figure_caption",
        "list_item",
    ],
    max_chars: int = 1_500,
) -> None:
    if len(text) < 30 or is_boilerplate_paragraph(text):
        return
    paragraphs.append(
        EvidenceParagraph(
            paragraph_id=f"p{len(paragraphs) + 1:04d}",
            document_id=artifact.document_id,
            ordinal=len(paragraphs) + 1,
            section=section,
            unit_type=unit_type,
            text=truncate_text(text, max_chars),
            artifact_id=artifact.artifact_id,
            artifact_path=artifact.payload_path,
            source_kind="full_text",
        )
    )


def paragraphs_from_plain_text(
    text: str,
    *,
    artifact: ArtifactReference,
    section: str,
) -> list[EvidenceParagraph]:
    paragraphs: list[EvidenceParagraph] = []
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(parts) <= 1:
        parts = split_sentences(text)
    for part in parts:
        normalized = clean_text(part)
        if len(normalized) < 30 or is_boilerplate_paragraph(normalized):
            continue
        paragraphs.append(
            EvidenceParagraph(
                paragraph_id=f"p{len(paragraphs) + 1:04d}",
                document_id=artifact.document_id,
                ordinal=len(paragraphs) + 1,
                section=section,
                unit_type="paragraph",
                text=truncate_text(normalized, 1_500),
                artifact_id=artifact.artifact_id,
                artifact_path=artifact.payload_path,
                source_kind="full_text",
            )
        )
    return deduplicate_paragraphs(paragraphs)


def nearest_html_section(element: etree._Element) -> str:
    current = element
    while current is not None:
        previous = current.getprevious()
        while previous is not None:
            if previous.tag is not None and str(previous.tag).lower() in {
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            }:
                heading = clean_text(previous.text_content())
                if heading:
                    return heading
            previous = previous.getprevious()
        current = current.getparent()
    return "html_full_text"


def has_html_ancestor(element: etree._Element, tag_names: set[str]) -> bool:
    current = element.getparent()
    while current is not None:
        tag = str(current.tag).lower() if current.tag is not None else ""
        if tag in tag_names:
            return True
        current = current.getparent()
    return False


def nearest_xml_section_title(element: etree._Element) -> str | None:
    current = element.getparent()
    while current is not None:
        if etree.QName(current).localname == "sec":
            title = section_title(current)
            if title:
                return title
        current = current.getparent()
    return None


def has_xml_ancestor(element: etree._Element, local_names: set[str]) -> bool:
    current = element.getparent()
    while current is not None:
        if etree.QName(current).localname in local_names:
            return True
        current = current.getparent()
    return False


def is_boilerplate_paragraph(text: str) -> bool:
    normalized = normalize_label(text)
    boilerplate_prefixes = (
        "an official website of the united states government",
        "official websites use gov",
        "secure gov websites use https",
        "a lock locked padlock icon",
        "correspondence to",
        "correspondence may be sent",
        "address correspondence",
        "received ",
        "accepted ",
        "issue date ",
        "authors contributed equally",
    )
    return any(normalized.startswith(prefix) for prefix in boilerplate_prefixes)


def deduplicate_paragraphs(paragraphs: list[EvidenceParagraph]) -> list[EvidenceParagraph]:
    seen: set[str] = set()
    deduplicated: list[EvidenceParagraph] = []
    for paragraph in paragraphs:
        normalized = normalize_label(paragraph.text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(
            paragraph.model_copy(
                update={
                    "paragraph_id": f"p{len(deduplicated) + 1:04d}",
                    "ordinal": len(deduplicated) + 1,
                }
            )
        )
    return deduplicated


def build_paragraph_windows(
    document_id: str,
    paragraphs: list[EvidenceParagraph],
    *,
    window_paragraphs: int,
    overlap_paragraphs: int,
    max_windows: int | None,
) -> list[ParagraphWindow]:
    if not paragraphs:
        return []
    step = max(1, window_paragraphs - overlap_paragraphs)
    windows: list[ParagraphWindow] = []
    for start in range(0, len(paragraphs), step):
        selected = paragraphs[start : start + window_paragraphs]
        if not selected:
            continue
        windows.append(
            ParagraphWindow(
                window_id=f"{document_id}:window:{len(windows) + 1:04d}",
                document_id=document_id,
                ordinal=len(windows) + 1,
                paragraph_ids=[paragraph.paragraph_id for paragraph in selected],
                paragraphs=selected,
            )
        )
        if start + window_paragraphs >= len(paragraphs):
            break
        if max_windows is not None and len(windows) >= max_windows:
            break
    return windows


def build_semantic_paragraph_window_packet(
    candidate: StudyCandidate,
    *,
    window: ParagraphWindow,
    run_id: str,
) -> dict[str, Any]:
    schema = semantic_paragraph_output_schema()
    prompt = build_semantic_paragraph_prompt(
        candidate=candidate,
        window=window,
        schema=schema,
        legacy_context_text=build_legacy_guardrail_text(candidate),
    )
    return {
        "run_id": run_id,
        "document_id": candidate.document_id,
        "context_id": candidate.context_id,
        "window_id": window.window_id,
        "window_ordinal": window.ordinal,
        "prompt_version": f"{PROMPT_VERSION}_semantic_paragraph_index",
        "prompt": prompt,
        "expected_output_schema": schema,
        "paragraph_ids": window.paragraph_ids,
        "paragraphs": window.paragraphs,
        "provenance": {
            "source": "llm_study_reclassification_poc",
            "method": "semantic_paragraph_window_classification",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "semantic_paragraph_labels_are_candidate_index_metadata",
            "legacy_context_id": candidate.context_id,
        },
    }


def semantic_paragraph_output_schema() -> dict[str, Any]:
    return {
        "document_id": "string",
        "window_id": "string",
        "paragraph_annotations": [
            {
                "paragraph_id": "string",
                "labels": list(SEMANTIC_PARAGRAPH_LABELS),
                "question_relevance": {
                    "cannabinoid_role": "high | medium | low | none",
                    "target_condition": "high | medium | low | none",
                    "study_design": "high | medium | low | none",
                },
                "evidence_terms": ["short verbatim terms from this paragraph"],
                "needs_human_review_hint": "boolean",
            }
        ],
        "window_notes": ["string"],
    }


def build_semantic_paragraph_prompt(
    *,
    candidate: StudyCandidate,
    window: ParagraphWindow,
    schema: dict[str, Any],
    legacy_context_text: str,
) -> str:
    paragraph_text = "\n\n".join(
        "\n".join(
            [
                f"[paragraph_id={paragraph.paragraph_id}]",
                f"unit_type: {paragraph.unit_type}",
                f"section: {paragraph.section}",
                f"text: {paragraph.text}",
            ]
        )
        for paragraph in window.paragraphs
    )
    return (
        f"You are creating candidate document-unit index metadata for a "
        f"""human-reviewed cannabinoid evidence knowledge base.

Rules:
- Do not provide medical advice, recommendations, or clinical instructions.
- Return only valid JSON matching the schema.
- Use English only.
- Classify each paragraph_id in the window exactly once. Each paragraph_id may
  refer to a paragraph, abstract sentence, table text, or figure caption.
- Do not paraphrase or rewrite the article.
- Labels are candidate retrieval metadata, not reviewed truth.
- Use only these labels: {", ".join(SEMANTIC_PARAGRAPH_LABELS)}.
- Use not_relevant only when no more specific label applies.
- evidence_terms must be short verbatim substrings from the same unit.
- evidence_terms must not use ellipses, approximations, or combined non-contiguous text.
- Use the legacy English context only as a guardrail for relevance; do not copy
  legacy claims into unit labels unless the unit itself supports them.

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Document-unit window:
window_id: {window.window_id}
unit_count: {len(window.paragraphs)}

Document units:
{paragraph_text}
"""
    )


def semantic_paragraph_window_preview(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "window_id": packet["window_id"],
        "prompt_chars": len(packet["prompt"]),
        "paragraph_ids": packet["paragraph_ids"],
        "unit_types": [
            paragraph.unit_type
            for paragraph in packet["paragraphs"]
            if isinstance(paragraph, EvidenceParagraph)
        ],
        "prompt": packet["prompt"],
    }


def prompt_preview_record(prompt_package: PromptPackage) -> dict[str, Any]:
    return {
        "document_id": prompt_package.document_id,
        "evidence_source_used": prompt_package.evidence_source_used,
        "prompt": prompt_package.prompt,
        "source_text_chars": prompt_package.source_text_chars,
        "legacy_context_chars": prompt_package.legacy_context_chars,
        "selected_artifact": slim_artifact(prompt_package.selected_artifact),
        "metadata_artifacts": [
            slim_artifact(artifact) for artifact in prompt_package.metadata_artifacts
        ],
        "retrieval_method": prompt_package.retrieval_method,
        "source_chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "artifact_id": chunk.artifact_id,
                "artifact_path": chunk.artifact_path,
                "section": chunk.section,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "score": chunk.score,
                "matched_topics": chunk.matched_topics,
                "text_chars": len(chunk.text),
            }
            for chunk in prompt_package.source_chunks
        ],
    }


def slim_artifact(artifact: ArtifactReference | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "artifact_id": artifact.artifact_id,
        "document_id": artifact.document_id,
        "artifact_type": artifact.artifact_type,
        "source": artifact.source,
        "payload_path": artifact.payload_path,
        "payload_sha256": artifact.payload_sha256,
        "payload_size_bytes": artifact.payload_size_bytes,
        "url": artifact.url,
        "license": artifact.license,
        "created_at": artifact.created_at,
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_processed_document_ids(output_dir: Path, *, retry_errors: bool = False) -> set[str]:
    processed: set[str] = set()
    if not output_dir.exists():
        return processed
    for path in sorted(output_dir.glob("*_records.jsonl")):
        for record in load_jsonl(path):
            if record.get("poc_status") == "dry_run_prompt_prepared":
                continue
            if retry_errors and record.get("poc_status") == "error":
                continue
            document_id = record.get("document_id")
            if document_id:
                processed.add(str(document_id))
    return processed


def load_artifacts_by_document_id(
    connection: sqlite3.Connection,
    document_ids: list[str],
) -> dict[str, list[ArtifactReference]]:
    artifacts: dict[str, list[ArtifactReference]] = defaultdict(list)
    for chunk in chunks(document_ids, 800):
        placeholders = ", ".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT artifact_id, document_id, source, artifact_type, url, license,
                   payload_path, payload_sha256, payload_size_bytes, raw_payload_json,
                   created_at
            FROM access_enrichment_artifact
            WHERE document_id IN ({placeholders})
            ORDER BY document_id, created_at DESC
            """,
            chunk,
        ).fetchall()
        for row in rows:
            raw_payload = json.loads(row["raw_payload_json"] or "{}")
            artifacts[str(row["document_id"])].append(
                ArtifactReference(
                    artifact_id=str(row["artifact_id"]),
                    document_id=str(row["document_id"]),
                    artifact_type=str(row["artifact_type"]),
                    source=str(row["source"]),
                    payload_path=row["payload_path"],
                    payload_sha256=row["payload_sha256"],
                    payload_size_bytes=row["payload_size_bytes"],
                    raw_payload=raw_payload,
                    url=row["url"],
                    license=row["license"],
                    created_at=str(row["created_at"]),
                )
            )
    return artifacts


def load_publication_abstracts(
    connection: sqlite3.Connection,
    document_ids: list[str],
) -> dict[str, str]:
    abstracts: dict[str, str] = {}
    for chunk in chunks(document_ids, 800):
        placeholders = ", ".join("?" for _ in chunk)
        rows = connection.execute(
            f"""
            SELECT document_id, abstract
            FROM publication
            WHERE document_id IN ({placeholders}) AND abstract IS NOT NULL
            """,
            chunk,
        ).fetchall()
        for row in rows:
            abstract = clean_text(str(row["abstract"] or ""))
            if abstract:
                abstracts[str(row["document_id"])] = abstract
    return abstracts


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def load_candidates_for_poc(*, cohort_path: Path, database_path: Path) -> list[StudyCandidate]:
    cohort_records = load_jsonl(cohort_path)
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        document_ids = [str(record["document_id"]) for record in cohort_records]
        artifacts_by_document_id = load_artifacts_by_document_id(connection, document_ids)
        abstracts_by_document_id = load_publication_abstracts(connection, document_ids)
    return build_candidates(
        cohort_records,
        artifacts_by_document_id=artifacts_by_document_id,
        abstracts_by_document_id=abstracts_by_document_id,
    )


def build_candidates(
    cohort_records: list[dict[str, Any]],
    *,
    artifacts_by_document_id: dict[str, list[ArtifactReference]],
    abstracts_by_document_id: dict[str, str],
) -> list[StudyCandidate]:
    candidates: list[StudyCandidate] = []
    for record in cohort_records:
        document_id = str(record["document_id"])
        artifacts = artifacts_by_document_id.get(document_id, [])
        selected_artifact = select_best_full_text_artifact(artifacts)
        metadata_artifacts = [
            artifact
            for artifact in artifacts
            if artifact.artifact_type in {"europe_pmc_metadata", "unpaywall_metadata"}
        ]
        candidate = StudyCandidate(
            document_id=document_id,
            context_id=record.get("context_id"),
            title=record.get("title"),
            publication_year=record.get("publication_year"),
            pmid=record.get("pmid"),
            pmcid=record.get("pmcid"),
            doi=record.get("doi"),
            legacy_study_type=record.get("type_of_study"),
            legacy_study_result=record.get("study_result"),
            legacy_sample_size=record.get("study_sample_size"),
            legacy_context=record,
            selected_artifact=selected_artifact,
            metadata_artifacts=metadata_artifacts,
            publication_abstract=abstracts_by_document_id.get(document_id)
            or abstract_from_metadata(metadata_artifacts),
            pathologies=detect_pathologies(record),
            selection_reasons=selection_reasons(record, selected_artifact),
        )
        candidates.append(candidate)
    return candidates


def select_best_full_text_artifact(
    artifacts: list[ArtifactReference],
) -> ArtifactReference | None:
    full_text_artifacts = [
        artifact
        for artifact in artifacts
        if artifact.artifact_type in FULL_TEXT_ARTIFACT_PRIORITY and artifact.payload_path
    ]
    if not full_text_artifacts:
        return None
    return sorted(
        full_text_artifacts,
        key=lambda artifact: (
            FULL_TEXT_ARTIFACT_PRIORITY[artifact.artifact_type],
            -(artifact.payload_size_bytes or 0),
            artifact.created_at,
        ),
    )[0]


def abstract_from_metadata(metadata_artifacts: list[ArtifactReference]) -> str | None:
    for artifact in metadata_artifacts:
        if artifact.artifact_type != "europe_pmc_metadata" or not artifact.raw_payload:
            continue
        results = artifact.raw_payload.get("resultList", {}).get("result", [])
        if results:
            abstract = clean_text(str(results[0].get("abstractText") or ""))
            if abstract:
                return abstract
    return None


def detect_pathologies(record: dict[str, Any]) -> list[str]:
    haystack_values: list[str] = [
        str(record.get("title") or ""),
        str(record.get("key_findings") or ""),
        str(record.get("source_filenames") or ""),
        json.dumps(record.get("list_fields", {}), ensure_ascii=False),
        json.dumps(record.get("text_fields", {}), ensure_ascii=False),
    ]
    haystack = " ".join(haystack_values).lower()
    patterns = {
        "Pain": ("pain", "analges", "neuropath"),
        "Cancer": ("cancer", "tumor", "tumour", "neoplasm", "chemotherapy", "oncolog"),
        "Inflammation": ("inflammation", "inflammatory", "arthritis", "colitis"),
        "Cannabis Adverse Effects": (
            "adverse",
            "withdrawal",
            "intoxication",
            "cannabis use disorder",
        ),
        "Addiction": ("addiction", "dependence", "opioid", "alcohol", "substance use"),
    }
    return [
        pathology
        for pathology, terms in patterns.items()
        if any(term in haystack for term in terms)
    ]


def selection_reasons(
    record: dict[str, Any],
    selected_artifact: ArtifactReference | None,
) -> list[str]:
    reasons = [f"legacy_study_type={record.get('type_of_study') or 'unknown'}"]
    if selected_artifact:
        reasons.append(f"full_text_artifact={selected_artifact.artifact_type}")
    else:
        reasons.append("no_full_text_artifact")
    pathologies = detect_pathologies(record)
    if pathologies:
        reasons.append("target_pathology=" + ",".join(pathologies))
    return reasons


def select_stratified_candidates(
    candidates: list[StudyCandidate],
    *,
    processed_document_ids: set[str],
    limit: int | None,
) -> list[StudyCandidate]:
    target_types = {normalize_label(value): value for value in TARGET_STUDY_TYPES}
    eligible = [
        candidate
        for candidate in candidates
        if candidate.document_id not in processed_document_ids
        and normalize_label(candidate.legacy_study_type) in target_types
    ]
    grouped: dict[str, list[StudyCandidate]] = defaultdict(list)
    for candidate in eligible:
        grouped[target_types[normalize_label(candidate.legacy_study_type)]].append(candidate)
    for group in grouped.values():
        group.sort(key=candidate_sort_key)

    selected: list[StudyCandidate] = []
    group_names = list(TARGET_STUDY_TYPES)
    while any(grouped.values()) and (limit is None or len(selected) < limit):
        for group_name in group_names:
            if limit is not None and len(selected) >= limit:
                break
            group = grouped.get(group_name)
            if group:
                selected.append(group.pop(0))
    return selected


def candidate_sort_key(candidate: StudyCandidate) -> tuple[int, int, int, str]:
    artifact_rank = (
        FULL_TEXT_ARTIFACT_PRIORITY.get(candidate.selected_artifact.artifact_type, 99)
        if candidate.selected_artifact
        else 99
    )
    pathology_rank = (
        0
        if any(pathology in TARGET_PATHOLOGIES for pathology in candidate.pathologies)
        else 1
    )
    source_rank = 0 if candidate.publication_abstract else 1
    return (artifact_rank, pathology_rank, source_rank, candidate.document_id)


def normalize_label(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def build_prompt_package(
    candidate: StudyCandidate,
    *,
    max_source_chars: int,
    direct_full_text_char_limit: int = DIRECT_FULL_TEXT_CHAR_LIMIT,
    large_full_text_char_limit: int = LARGE_FULL_TEXT_CHAR_LIMIT,
) -> PromptPackage:
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=max_source_chars,
        direct_full_text_char_limit=direct_full_text_char_limit,
        large_full_text_char_limit=large_full_text_char_limit,
    )
    legacy_context_text = build_legacy_guardrail_text(candidate)
    prompt = build_prompt(
        candidate=candidate,
        evidence_source_used=evidence_plan.evidence_source_used,
        source_text=evidence_plan.evidence_text,
        legacy_context_text=legacy_context_text,
    )
    return PromptPackage(
        document_id=candidate.document_id,
        evidence_source_used=evidence_plan.evidence_source_used,
        context_strategy=evidence_plan.context_strategy,
        strategy_reason=evidence_plan.strategy_reason,
        prompt=prompt,
        source_text_chars=len(evidence_plan.evidence_text),
        full_text_chars=evidence_plan.full_text_chars,
        legacy_context_chars=len(legacy_context_text),
        selected_artifact=candidate.selected_artifact,
        metadata_artifacts=candidate.metadata_artifacts,
        source_chunks=evidence_plan.source_chunks,
        retrieval_method=evidence_plan.retrieval_method,
    )


def build_evidence_plan(
    candidate: StudyCandidate,
    *,
    max_source_chars: int,
    direct_full_text_char_limit: int,
    large_full_text_char_limit: int,
) -> EvidencePlan:
    source_payload_size_bytes = (
        candidate.selected_artifact.payload_size_bytes if candidate.selected_artifact else None
    )
    full_text = load_full_source_text(candidate)
    full_text_chars = len(full_text) if full_text else None
    if full_text:
        direct_prompt_limit = min(direct_full_text_char_limit, max_source_chars)
        if len(full_text) <= direct_prompt_limit:
            evidence_text = format_direct_full_text_packet(
                candidate,
                truncate_text(full_text, max_source_chars),
            )
            return EvidencePlan(
                evidence_source_used="full_text",
                context_strategy="full_text_compact",
                strategy_reason=(
                    f"full_text_chars={len(full_text)} <= "
                    f"direct_prompt_limit={direct_prompt_limit}"
                ),
                evidence_text=evidence_text,
                full_text_chars=len(full_text),
                source_payload_size_bytes=source_payload_size_bytes,
                retrieval_method="direct_full_text_v0.1",
            )

        source_chunks = select_evidence_chunks(candidate, max_source_chars=max_source_chars)
        context_strategy = (
            "large_section_keyword_chunks"
            if len(full_text) > large_full_text_char_limit
            else "section_keyword_chunks"
        )
        return EvidencePlan(
            evidence_source_used="full_text",
            context_strategy=context_strategy,
            strategy_reason=(
                f"full_text_chars={len(full_text)} > "
                f"direct_full_text_char_limit={direct_full_text_char_limit}; "
                f"selected_chunks={len(source_chunks)}"
            ),
            evidence_text=format_evidence_packet(candidate, source_chunks),
            full_text_chars=len(full_text),
            source_payload_size_bytes=source_payload_size_bytes,
            source_chunks=source_chunks,
            retrieval_method="section_chunk_keyword_scoring_v0.1",
        )

    if candidate.publication_abstract:
        return EvidencePlan(
            evidence_source_used="abstract_metadata",
            context_strategy="abstract_metadata",
            strategy_reason="no full text artifact text was available; using abstract metadata",
            evidence_text=build_metadata_text(candidate),
            full_text_chars=full_text_chars,
            source_payload_size_bytes=source_payload_size_bytes,
            retrieval_method="metadata_direct_v0.1",
        )

    return EvidencePlan(
        evidence_source_used="legacy_context_only",
        context_strategy="legacy_context_only",
        strategy_reason="no full text or abstract metadata text was available",
        evidence_text=build_metadata_text(candidate, include_abstract=False),
        full_text_chars=full_text_chars,
        source_payload_size_bytes=source_payload_size_bytes,
        retrieval_method="legacy_context_only_v0.1",
    )


def build_evidence_index_record(
    candidate: StudyCandidate,
    *,
    run_id: str,
    max_source_chars: int,
    direct_full_text_char_limit: int,
    large_full_text_char_limit: int,
) -> EvidenceIndexRecord:
    evidence_plan = build_evidence_plan(
        candidate,
        max_source_chars=max_source_chars,
        direct_full_text_char_limit=direct_full_text_char_limit,
        large_full_text_char_limit=large_full_text_char_limit,
    )
    legacy_guardrail = build_legacy_guardrail_text(candidate)
    return EvidenceIndexRecord(
        run_id=run_id,
        document_id=candidate.document_id,
        context_id=candidate.context_id,
        title=candidate.title,
        legacy_study_type=candidate.legacy_study_type,
        evidence_source_used=evidence_plan.evidence_source_used,
        context_strategy=evidence_plan.context_strategy,
        strategy_reason=evidence_plan.strategy_reason,
        retrieval_method=evidence_plan.retrieval_method,
        selected_artifact=slim_artifact(candidate.selected_artifact),
        metadata_artifacts=[
            slim_artifact(artifact) or {} for artifact in candidate.metadata_artifacts
        ],
        source_payload_size_bytes=evidence_plan.source_payload_size_bytes,
        full_text_chars=evidence_plan.full_text_chars,
        selected_chunk_count=len(evidence_plan.source_chunks),
        selected_chunks=[
            {
                "chunk_id": chunk.chunk_id,
                "artifact_id": chunk.artifact_id,
                "artifact_path": chunk.artifact_path,
                "section": chunk.section,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "score": chunk.score,
                "matched_topics": chunk.matched_topics,
                "text_chars": len(chunk.text),
                "text": chunk.text,
            }
            for chunk in evidence_plan.source_chunks
        ],
        legacy_guardrail_chars=len(legacy_guardrail),
        evidence_text_chars=len(evidence_plan.evidence_text),
        provenance={
            "source": "llm_study_reclassification_poc",
            "method": "prepare_adaptive_evidence_index",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "pre_llm_evidence_packet_candidate_input",
            "embeddings_computed": False,
        },
    )


def resolve_task_names(task: str) -> list[str]:
    if task == "all":
        return list(TASK_SEQUENCE)
    if task not in TASK_SEQUENCE:
        raise typer.BadParameter(
            "task must be 'all' or one of: " + ", ".join(TASK_SEQUENCE)
        )
    return [task]


def build_task_packet_record(
    candidate: StudyCandidate,
    *,
    evidence_plan: EvidencePlan,
    task_name: str,
    run_id: str,
) -> TaskPacketRecord:
    task_order = TASK_SEQUENCE.index(task_name) + 1
    chunks = select_task_chunks(evidence_plan.source_chunks, task_name)
    evidence_text = format_task_evidence(candidate, evidence_plan, chunks)
    legacy_guardrail = build_legacy_guardrail_text(candidate)
    schema = task_output_schema(task_name)
    prompt = build_task_prompt(
        candidate=candidate,
        task_name=task_name,
        task_goal=task_goal(task_name),
        schema=schema,
        evidence_text=evidence_text,
        legacy_context_text=legacy_guardrail,
    )
    return TaskPacketRecord(
        run_id=run_id,
        document_id=candidate.document_id,
        context_id=candidate.context_id,
        task_name=task_name,
        task_order=task_order,
        task_goal=task_goal(task_name),
        model_tier_hint=model_tier_hint(task_name),
        prompt_version=f"{PROMPT_VERSION}_{task_name}",
        prompt=prompt,
        expected_output_schema=schema,
        selected_chunk_ids=[chunk.chunk_id for chunk in chunks],
        context_strategy=evidence_plan.context_strategy,
        evidence_source_used=evidence_plan.evidence_source_used,
        provenance={
            "source": "llm_study_reclassification_poc",
            "method": "prepare_decomposed_task_packets",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "task_prompt_candidate_input_not_reviewed_knowledge",
            "retrieval_method": evidence_plan.retrieval_method,
        },
    )


def select_task_chunks(chunks: list[EvidenceChunk], task_name: str) -> list[EvidenceChunk]:
    if not chunks:
        return []
    topic_filter = TASK_TOPIC_FILTERS[task_name]
    selected = [
        chunk
        for chunk in chunks
        if task_name == "legacy_adjudication"
        or topic_filter.intersection(set(chunk.matched_topics))
    ]
    if not selected:
        selected = sorted(chunks, key=lambda chunk: (-chunk.score, chunk.chunk_id))[:3]
    limit = 5 if task_name == "legacy_adjudication" else 3
    return sorted(selected, key=lambda chunk: (-chunk.score, chunk.chunk_id))[:limit]


def format_task_evidence(
    candidate: StudyCandidate,
    evidence_plan: EvidencePlan,
    chunks: list[EvidenceChunk],
) -> str:
    if chunks:
        return format_evidence_packet(candidate, chunks)
    return evidence_plan.evidence_text


def task_goal(task_name: str) -> str:
    goals = {
        "study_design_verification": (
            "Verify the study design classification against source evidence and legacy context."
        ),
        "population_model_sample": (
            "Extract whether the study is human, animal, in vitro, mixed, or unclear, "
            "including sample size and species/model."
        ),
        "condition_organ_system_extraction": (
            "Extract explicit pathologies, conditions, symptoms, and conservative organ system "
            "mappings with evidence."
        ),
        "intervention_exposure": (
            "Extract cannabinoid/exposure, route, dose, duration, and comparator/control."
        ),
        "outcomes_safety": (
            "Extract result direction, key findings, and adverse events without medical advice."
        ),
        "legacy_adjudication": (
            "Adjudicate conflicts between task outputs/source evidence and legacy context."
        ),
    }
    return goals[task_name]


def model_tier_hint(task_name: str) -> str:
    if task_name in {"study_design_verification", "legacy_adjudication"}:
        return "high_tier_recommended"
    return "small_or_high_tier_evaluation"


def task_output_schema(task_name: str) -> dict[str, Any]:
    common = {
        "document_id": "string",
        "task_name": task_name,
        "needs_human_review": "boolean",
        "review_reasons": ["string"],
        "field_evidence_text": {"field_name": ["short verbatim evidence text"]},
        "field_evidence_chunks": {"field_name": ["chunk_id"]},
    }
    schemas = {
        "study_design_verification": {
            **common,
            "legacy_study_type": "string or null",
            "recommended_action": "keep_legacy | change_legacy | insufficient_evidence",
            "study_type": (
                "Meta-analysis | Systematic Review | Clinical Trial | Randomized Controlled "
                "Trial | Double Blind Clinical Trial | Observational Study | Animal Study | "
                "Laboratory Study | Case Report | Other | unclear"
            ),
            "study_design_family": (
                "evidence_synthesis | human_clinical | human_observational | animal | "
                "laboratory | case_report | mixed | unclear"
            ),
            "confidence": "high | medium | low",
            "legacy_alignment": "supports | conflicts | partial | insufficient_evidence",
        },
        "population_model_sample": {
            **common,
            "human_or_nonhuman": "human | nonhuman | mixed | not_applicable | unclear",
            "human_sample_size": "integer or null",
            "animal_sample_size": "integer or null",
            "species_or_model": ["string"],
            "confidence": {"field_name": "high | medium | low"},
        },
        "condition_organ_system_extraction": {
            **common,
            "pathologies_or_conditions": [
                {
                    "name": "string",
                    "category": "disease | symptom | outcome | exposure_context | unclear",
                    "explicit_or_inferred": "explicit | inferred",
                    "confidence": "high | medium | low",
                    "evidence_text": "string",
                    "evidence_chunk_id": "string or null",
                }
            ],
            "organ_systems": [
                {
                    "name": "string",
                    "explicit_or_inferred": "explicit | inferred",
                    "inferred_from_condition": "string or null",
                    "confidence": "high | medium | low",
                    "evidence_or_rationale": "string",
                }
            ],
            "legacy_condition_alignment": (
                "supports | conflicts | partial | not_in_legacy | insufficient_evidence"
            ),
        },
        "intervention_exposure": {
            **common,
            "role_of_cannabinoid": (
                "intervention | exposure | condition_context | population_context | "
                "background_only | unclear"
            ),
            "is_primary_study_target": "boolean | unclear",
            "cannabinoids": ["string"],
            "terpenes": ["string"],
            "route_of_administration": ["string"],
            "dosage": ["string"],
            "treatment_duration": ["string"],
            "comparator_or_control": ["string"],
            "support_status": {
                "field_name": (
                    "supported | conflicting | partial | not_found | insufficient_evidence"
                )
            },
            "explicit_or_inferred": {"field_name": "explicit | inferred | unclear"},
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim evidence text",
            "confidence": {"field_name": "high | medium | low"},
        },
        "outcomes_safety": {
            **common,
            "study_result_direction": (
                "positive | negative | mixed | neutral | safety_signal | unclear"
            ),
            "key_findings_generated": ["string"],
            "adverse_events": ["string"],
            "confidence": {"field_name": "high | medium | low"},
        },
        "legacy_adjudication": {
            **common,
            "overall_alignment": (
                "supports_legacy | conflicts_with_legacy | partial | insufficient_evidence"
            ),
            "conflict_fields": ["string"],
            "recommended_next_step": (
                "accept_candidate | keep_legacy | require_human_review | rerun_with_more_context"
            ),
            "rationale": "string",
        },
    }
    return schemas[task_name]


def build_task_prompt(
    *,
    candidate: StudyCandidate,
    task_name: str,
    task_goal: str,
    schema: dict[str, Any],
    evidence_text: str,
    legacy_context_text: str,
) -> str:
    if task_name == "study_design_verification":
        task_instruction = (
            "Start from the legacy study type. Keep it unless the source evidence clearly "
            "supports a different class. Prefer insufficient_evidence over speculative changes."
        )
    elif task_name == "condition_organ_system_extraction":
        task_instruction = (
            "Extract conditions that are explicit in the source text. Organ systems may be "
            "inferred only from a specific extracted condition, and the inference must be "
            "marked as inferred. Do not invent clinical categories."
        )
    elif task_name == "legacy_adjudication":
        task_instruction = (
            "Compare source evidence to legacy context. Do not resolve conflicts automatically; "
            "identify what a human reviewer should inspect."
        )
    else:
        task_instruction = (
            "Extract only this task's fields. Do not infer fields that are not textually supported."
        )
    return (
        f"You are preparing candidate evidence for a human-reviewed cannabinoid evidence "
        f"""knowledge base.

Task: {task_name}
Goal: {task_goal}

Rules:
- Do not provide medical advice, treatment recommendations, or clinical instructions.
- Return only valid JSON matching the schema.
- Use English only.
- Cite chunk ids in field_evidence_chunks when chunk ids are present.
- {task_instruction}

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Task evidence packet:
{evidence_text}
"""
    )


def task_packet_preview(packet: TaskPacketRecord) -> dict[str, Any]:
    return {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "task_order": packet.task_order,
        "model_tier_hint": packet.model_tier_hint,
        "prompt_chars": len(packet.prompt),
        "selected_chunk_ids": packet.selected_chunk_ids,
        "context_strategy": packet.context_strategy,
        "evidence_source_used": packet.evidence_source_used,
        "prompt": packet.prompt,
    }


def build_evidence_summary_packet_record(
    candidate: StudyCandidate,
    *,
    evidence_plan: EvidencePlan,
    task_name: str,
    run_id: str,
    max_spans: int,
) -> EvidenceSummaryPacketRecord:
    spans = select_task_evidence_spans(
        candidate,
        evidence_plan=evidence_plan,
        task_name=task_name,
        max_spans=max_spans,
    )
    legacy_guardrail = build_legacy_guardrail_text(candidate)
    schema = evidence_summary_output_schema(task_name)
    source_artifacts = [candidate.selected_artifact] if candidate.selected_artifact else []
    source_artifacts.extend(candidate.metadata_artifacts)
    prompt = build_evidence_summary_prompt(
        candidate=candidate,
        task_name=task_name,
        task_goal=task_goal(task_name),
        schema=schema,
        spans=spans,
        legacy_context_text=legacy_guardrail,
    )
    return EvidenceSummaryPacketRecord(
        run_id=run_id,
        document_id=candidate.document_id,
        context_id=candidate.context_id,
        task_name=task_name,
        task_goal=task_goal(task_name),
        prompt_version=f"{PROMPT_VERSION}_{task_name}_evidence_summary",
        prompt=prompt,
        expected_output_schema=schema,
        selected_span_ids=[span.span_id for span in spans],
        selected_chunk_ids=sorted(
            {span.chunk_id for span in spans if span.chunk_id is not None}
        ),
        spans=spans,
        context_strategy=evidence_plan.context_strategy,
        evidence_source_used=evidence_plan.evidence_source_used,
        provenance={
            "source": "llm_study_reclassification_poc",
            "method": "prepare_task_evidence_summary_packet",
            "does_not_mutate_sqlite_review_state": True,
            "review_boundary": "summary_candidate_input_not_reviewed_knowledge",
            "retrieval_method": evidence_plan.retrieval_method,
            "compression_method": "deterministic_extractive_spans_v0.1",
            "source_artifact_ids": [
                artifact.artifact_id for artifact in source_artifacts
            ],
            "source_artifact_paths": [
                artifact.payload_path
                for artifact in source_artifacts
                if artifact.payload_path
            ],
            "legacy_context_id": candidate.context_id,
        },
    )


def select_task_evidence_spans(
    candidate: StudyCandidate,
    *,
    evidence_plan: EvidencePlan,
    task_name: str,
    max_spans: int,
) -> list[EvidenceSpan]:
    chunks = select_task_chunks(evidence_plan.source_chunks, task_name)
    spans = spans_from_chunks(chunks, task_name=task_name)
    if not spans:
        spans = spans_from_metadata_packet(
            evidence_plan.evidence_text,
            task_name=task_name,
        )
    if not spans:
        return []

    scored = score_evidence_spans(spans, candidate=candidate, task_name=task_name)
    required = required_span_candidates(scored)
    selected: list[EvidenceSpan] = []
    selected_ids: set[str] = set()
    for span in required:
        selected.append(span)
        selected_ids.add(span.span_id)
    for span in sorted(scored, key=lambda value: (-value.score, value.span_id)):
        if span.span_id in selected_ids:
            continue
        selected.append(span)
        selected_ids.add(span.span_id)
        if len(selected) >= max_spans:
            break
    return selected[:max_spans]


def spans_from_chunks(chunks: list[EvidenceChunk], *, task_name: str) -> list[EvidenceSpan]:
    spans: list[EvidenceSpan] = []
    for chunk in chunks:
        sentences = split_sentences(chunk.text)
        if not sentences:
            continue
        for index, sentence in enumerate(sentences, start=1):
            if len(sentence) < 30:
                continue
            spans.append(
                EvidenceSpan(
                    span_id=f"{chunk.chunk_id}:span:{index}",
                    chunk_id=chunk.chunk_id,
                    section=chunk.section,
                    text=truncate_text(sentence, 650),
                    score=chunk.score,
                    matched_topics=chunk.matched_topics,
                    source_kind="full_text_chunk",
                )
            )
    return spans


def spans_from_metadata_packet(evidence_text: str, *, task_name: str) -> list[EvidenceSpan]:
    del task_name
    spans: list[EvidenceSpan] = []
    for index, sentence in enumerate(split_sentences(evidence_text), start=1):
        if len(sentence) < 30:
            continue
        spans.append(
            EvidenceSpan(
                span_id=f"metadata_or_legacy:span:{index}",
                chunk_id=None,
                section="metadata_or_legacy",
                text=truncate_text(sentence, 650),
                score=0.0,
                matched_topics=[],
                source_kind="metadata_or_legacy",
            )
        )
    return spans


def split_sentences(text: str) -> list[str]:
    normalized = clean_text(text)
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9([])", normalized)
    return [part.strip() for part in parts if part.strip()]


def score_evidence_spans(
    spans: list[EvidenceSpan],
    *,
    candidate: StudyCandidate,
    task_name: str,
) -> list[EvidenceSpan]:
    topic_filter = TASK_TOPIC_FILTERS[task_name]
    task_terms = tuple(
        term.lower()
        for topic in topic_filter
        for term in EVIDENCE_TOPICS.get(topic, ())
    )
    legacy_terms = tuple(term.lower() for term in candidate.pathologies)
    scored: list[EvidenceSpan] = []
    for span in spans:
        text = span.text.lower()
        matched_topics = set(span.matched_topics)
        score = span.score
        for topic in topic_filter:
            terms = EVIDENCE_TOPICS.get(topic, ())
            topic_score = sum(text.count(term.lower()) for term in terms)
            if topic_score:
                matched_topics.add(topic)
                score += min(topic_score * 2, 10)
        for term in legacy_terms:
            if term and term in text:
                matched_topics.add("legacy_pathology")
                score += 3
        if any(term in text for term in task_terms):
            score += 2
        scored.append(
            span.model_copy(
                update={
                    "score": score,
                    "matched_topics": sorted(matched_topics),
                }
            )
        )
    return scored


def required_span_candidates(spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
    required_sections = ("abstract", "methods", "materials and methods", "results")
    selected: list[EvidenceSpan] = []
    selected_ids: set[str] = set()
    for section in required_sections:
        matches = [
            span
            for span in spans
            if normalize_label(span.section).startswith(normalize_label(section))
        ]
        if not matches:
            continue
        span = sorted(matches, key=lambda value: (-value.score, value.span_id))[0]
        if span.span_id not in selected_ids:
            selected.append(span)
            selected_ids.add(span.span_id)
    return selected


def evidence_summary_output_schema(task_name: str) -> dict[str, Any]:
    schema = {
        "document_id": "string",
        "task_name": task_name,
        "evidence_synthesis": [
            {
                "claim": "one concise evidence-grounded statement",
                "cited_span_ids": ["span_id"],
                "confidence": "high | medium | low",
            }
        ],
        "field_support": {
            "field_name": [
                {
                    "candidate_value": "string or null",
                    "support_status": (
                        "supported | conflicting | partial | not_found | insufficient_evidence"
                    ),
                    "cited_span_ids": ["span_id"],
                    "evidence_text": "short verbatim evidence text",
                    "confidence": "high | medium | low",
                }
            ]
        },
        "source_limitations": ["string"],
        "missing_evidence": ["string"],
        "legacy_alignment_notes": [
            {
                "field_name": "string",
                "alignment": (
                    "supports | conflicts | partial | not_in_legacy | insufficient_evidence"
                ),
                "cited_span_ids": ["span_id"],
                "note": "string",
            }
        ],
        "cited_span_ids": ["span_id"],
        "needs_human_review": "boolean",
        "review_reasons": ["string"],
    }
    if task_name == "intervention_exposure":
        schema["intervention_exposure_summary"] = {
            "role_of_cannabinoid": (
                "intervention | exposure | condition_context | population_context | "
                "background_only | unclear"
            ),
            "is_primary_study_target": "boolean | unclear",
            "explicit_or_inferred": "explicit | inferred | unclear",
            "support_status": (
                "supported | conflicting | partial | not_found | insufficient_evidence"
            ),
            "cited_span_ids": ["span_id"],
            "evidence_text": "short verbatim evidence text",
            "confidence": "high | medium | low",
        }
    return schema


def build_evidence_summary_prompt(
    *,
    candidate: StudyCandidate,
    task_name: str,
    task_goal: str,
    schema: dict[str, Any],
    spans: list[EvidenceSpan],
    legacy_context_text: str,
) -> str:
    task_instruction = evidence_summary_task_instruction(task_name)
    span_text = "\n\n".join(
        "\n".join(
            [
                f"[span_id={span.span_id}]",
                f"chunk_id: {span.chunk_id or ''}",
                f"section: {span.section}",
                f"matched_topics: {', '.join(span.matched_topics) or 'none'}",
                f"text: {span.text}",
            ]
        )
        for span in spans
    )
    return (
        f"You are creating an evidence synthesis for a later structured extraction task "
        f"""in a human-reviewed cannabinoid evidence knowledge base.

Task: {task_name}
Goal: {task_goal}

Rules:
- Do not provide medical advice, treatment recommendations, or clinical instructions.
- Return only valid JSON matching the schema.
- Use English only.
- Use only the evidence spans below and the legacy English context for comparison.
- The legacy English context is a guardrail, not absolute truth.
- Every synthesized claim must cite at least one span_id.
- Evidence text must be a short verbatim substring from the cited span.
- Do not add background knowledge, mechanisms, organ systems, interventions, or outcomes
  that are not supported by the spans.
- Mark insufficient_evidence or not_found when the spans do not support a field.
- Mark conflicts when span evidence and legacy context disagree.
- Keep the synthesis short enough to be used as input for a downstream extraction prompt.
- {task_instruction}

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Evidence spans:
{span_text}
"""
    )


def evidence_summary_task_instruction(task_name: str) -> str:
    if task_name == "condition_organ_system_extraction":
        return (
            "For conditions, the candidate_value must be explicitly named in the cited span "
            "or be marked not_found. For organ systems, prefer not_found unless the organ "
            "system is explicitly named or conservatively inferred from an explicit extracted "
            "condition; do not infer organ systems from generic outcomes alone."
        )
    if task_name == "intervention_exposure":
        return (
            "Separate cannabinoid intervention or exposure from background cannabis context. "
            "Classify role_of_cannabinoid as intervention, exposure, condition_context, "
            "population_context, background_only, or unclear, and mark whether the "
            "cannabinoid is the primary study target. "
            "Do not extract route, dose, duration, or comparator unless those details are "
            "explicitly tied to the study intervention or exposure in the cited span."
        )
    if task_name == "study_design_verification":
        return (
            "Start from the legacy study type and mark conflicts only when the cited span "
            "clearly supports a different study design."
        )
    return "Do not infer task fields that are not textually supported by the cited spans."


def evidence_summary_packet_preview(packet: EvidenceSummaryPacketRecord) -> dict[str, Any]:
    return {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "prompt_chars": len(packet.prompt),
        "selected_span_ids": packet.selected_span_ids,
        "selected_chunk_ids": packet.selected_chunk_ids,
        "context_strategy": packet.context_strategy,
        "evidence_source_used": packet.evidence_source_used,
        "prompt": packet.prompt,
    }


def resolve_provider(provider: str) -> ProviderName:
    if provider not in DEFAULT_PROVIDER_MODELS:
        raise typer.BadParameter(
            "provider must be one of: " + ", ".join(DEFAULT_PROVIDER_MODELS)
        )
    return provider  # type: ignore[return-value]


def default_model_for_provider(provider: ProviderName) -> str:
    return DEFAULT_PROVIDER_MODELS[provider]


def api_key_env_var(provider: ProviderName) -> str:
    return {
        "groq": "GROQ_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
    }[provider]


def resolve_provider_api_key(provider: ProviderName) -> str | None:
    return os.getenv(api_key_env_var(provider))


def build_summary_chat_request(
    packet: EvidenceSummaryPacketRecord,
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    system_content = (
        "You create concise auditable evidence syntheses as JSON only. "
        "You never provide medical advice."
    )
    if provider == "anthropic":
        return {
            "model": model,
            "system": system_content,
            "messages": [{"role": "user", "content": packet.prompt}],
            "temperature": 0,
            "max_tokens": SUMMARY_MAX_OUTPUT_TOKENS,
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": packet.prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": SUMMARY_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }


def run_summary_packet_with_provider(
    packet: EvidenceSummaryPacketRecord,
    *,
    provider: ProviderName,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = build_summary_chat_request(packet, provider=provider, model=model)
    raw_response: dict[str, Any] = {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "provider": provider,
        "model": model,
        "request": redacted_request_payload(request_payload),
        "provenance": packet.provenance,
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=120) as client:
            response, attempts = post_provider_with_retries(
                client,
                provider=provider,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = response_content_text(
            raw_response["response_json"],
            provider=provider,
        )
        parsed = json.loads(content)
        record = dict(parsed)
        record.update(
            {
                "run_id": packet.run_id,
                "document_id": packet.document_id,
                "task_name": packet.task_name,
                "provider": provider,
                "model": model,
                "poc_status": "candidate_evidence_summary",
                "errors": [],
                "provenance": {
                    **packet.provenance,
                    "provider": provider,
                    "model": model,
                    "prompt_version": packet.prompt_version,
                    "selected_span_ids": packet.selected_span_ids,
                    "selected_chunk_ids": packet.selected_chunk_ids,
                    "source_artifact_ids": source_artifact_ids_from_packet(packet),
                    "source_artifact_paths": source_artifact_paths_from_packet(packet),
                    "legacy_context_id": packet.context_id,
                    "context_strategy": packet.context_strategy,
                    "evidence_source_used": packet.evidence_source_used,
                    "input_prompt_chars": len(packet.prompt),
                    "rough_input_token_estimate": rough_token_count(packet.prompt),
                    "latency_seconds": raw_response["latency_seconds"],
                },
            }
        )
        record["span_grounding_audit"] = build_span_grounding_audit(record, packet)
        record["comparison_audit"] = build_model_comparison_record_audit(
            record,
            raw_response=raw_response,
        )
        return record, raw_response
    except Exception as exc:
        record = error_summary_record(
            packet,
            provider=provider,
            model=model,
            error=str(exc),
        )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["error"] = str(exc)
        return record, raw_response


def run_summary_packet_with_groq(
    packet: EvidenceSummaryPacketRecord,
    *,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return run_summary_packet_with_provider(
        packet,
        provider="groq",
        model=model,
        api_key=api_key,
    )


def build_micro_extraction_chat_request(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    system_content = (
        "You extract one auditable scientific field as compact JSON only. "
        "You never provide medical advice."
    )
    if provider == "anthropic":
        return {
            "model": model,
            "system": system_content,
            "messages": [{"role": "user", "content": packet["prompt"]}],
            "temperature": 0,
            "max_tokens": 900,
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": packet["prompt"]},
        ],
        "temperature": 0,
        "max_completion_tokens": 900,
        "response_format": {"type": "json_object"},
    }


def run_micro_extraction_packet_with_provider(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = build_micro_extraction_chat_request(
        packet,
        provider=provider,
        model=model,
    )
    raw_response: dict[str, Any] = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "field_name": packet["field_name"],
        "provider": provider,
        "model": model,
        "request": redacted_request_payload(request_payload),
        "provenance": packet["provenance"],
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=120) as client:
            response, attempts = post_provider_with_retries(
                client,
                provider=provider,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = response_content_text(raw_response["response_json"], provider=provider)
        parsed = json.loads(content)
        record = dict(parsed)
        record.update(
            {
                "run_id": packet["run_id"],
                "document_id": packet["document_id"],
                "task_name": packet["task_name"],
                "field_name": packet["field_name"],
                "provider": provider,
                "model": model,
                "poc_status": "candidate_micro_extraction",
                "errors": [],
                "provenance": micro_extraction_provenance(
                    packet,
                    provider=provider,
                    model=model,
                    latency_seconds=raw_response["latency_seconds"],
                ),
            }
        )
        record["span_grounding_audit"] = build_micro_span_grounding_audit(record, packet)
        record["comparison_audit"] = build_model_comparison_record_audit(
            record,
            raw_response=raw_response,
        )
        return record, raw_response
    except Exception as exc:
        record = error_micro_extraction_record(
            packet,
            provider=provider,
            model=model,
            error=str(exc),
        )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["error"] = str(exc)
        return record, raw_response


def micro_extraction_provenance(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    latency_seconds: float | None,
) -> dict[str, Any]:
    provenance = {
        **packet["provenance"],
        "provider": provider,
        "model": model,
        "prompt_version": packet["prompt_version"],
        "selected_span_ids": packet["selected_span_ids"],
        "selected_chunk_ids": packet["selected_chunk_ids"],
        "context_strategy": packet["context_strategy"],
        "evidence_source_used": packet["evidence_source_used"],
        "input_prompt_chars": len(packet["prompt"]),
        "rough_input_token_estimate": rough_token_count(packet["prompt"]),
    }
    if latency_seconds is not None:
        provenance["latency_seconds"] = latency_seconds
    return provenance


def dry_run_micro_extraction_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    record = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "field_name": packet["field_name"],
        "provider": provider,
        "model": model,
        "poc_status": "dry_run_prompt_prepared",
        "errors": [],
        "needs_human_review": True,
        "review_reasons": ["Dry run only; no micro extraction was generated."],
        "candidate": {},
        "legacy_alignment": {},
        "provenance": micro_extraction_provenance(
            packet,
            provider=provider,
            model=model,
            latency_seconds=None,
        ),
    }
    record["span_grounding_audit"] = build_micro_span_grounding_audit(record, packet)
    return record


def error_micro_extraction_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    error: str,
) -> dict[str, Any]:
    record = dry_run_micro_extraction_record(packet, provider=provider, model=model)
    record["poc_status"] = "error"
    record["errors"] = [error]
    record["review_reasons"] = ["Micro extraction failed; inspect raw response before retry."]
    return record


def build_micro_span_grounding_audit(
    record: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    span_text_by_id = {span.span_id: span.text for span in packet["spans"]}
    cited_span_ids = collect_cited_span_ids(record)
    unknown_span_ids = sorted(
        span_id for span_id in cited_span_ids if span_id not in span_text_by_id
    )
    unsupported_evidence_texts: list[dict[str, Any]] = []
    for value in iter_nested_values(record):
        if not isinstance(value, dict):
            continue
        evidence_text = clean_text(str(value.get("evidence_text") or ""))
        if not evidence_text:
            continue
        entry_span_ids = [
            str(span_id)
            for span_id in value.get("cited_span_ids", [])
            if span_id is not None
        ]
        cited_text = " ".join(span_text_by_id.get(span_id, "") for span_id in entry_span_ids)
        if normalize_label(evidence_text) not in normalize_label(cited_text):
            unsupported_evidence_texts.append(
                {
                    "field_name": str(record.get("field_name", "")),
                    "candidate_value": value.get("candidate_value")
                    or value.get("role_of_cannabinoid")
                    or value.get("condition_name")
                    or value.get("study_design"),
                    "evidence_text": evidence_text,
                    "cited_span_ids": entry_span_ids,
                }
            )
    candidate = record.get("candidate")
    missing_required_citations = False
    if isinstance(candidate, dict):
        support_status = normalize_label(str(candidate.get("support_status", "")))
        if support_status in {"supported", "conflicting", "partial"}:
            missing_required_citations = not bool(candidate.get("cited_span_ids"))
    return {
        "known_span_count": len(span_text_by_id),
        "cited_span_ids": sorted(cited_span_ids),
        "unknown_span_ids": unknown_span_ids,
        "unsupported_evidence_texts": unsupported_evidence_texts,
        "missing_required_citations": missing_required_citations,
        "passes_basic_grounding": (
            not unknown_span_ids
            and not unsupported_evidence_texts
            and not missing_required_citations
        ),
    }


def build_unit_classification_chat_request(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    system_content = (
        "You classify auditable scientific evidence from selected document units "
        "as compact JSON only. You never provide medical advice."
    )
    if provider == "anthropic":
        return {
            "model": model,
            "system": system_content,
            "messages": [{"role": "user", "content": packet["prompt"]}],
            "temperature": 0,
            "max_tokens": 1800,
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": packet["prompt"]},
        ],
        "temperature": 0,
        "max_completion_tokens": 1800,
        "response_format": {"type": "json_object"},
    }


def run_unit_classification_packet_with_provider(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = build_unit_classification_chat_request(
        packet,
        provider=provider,
        model=model,
    )
    raw_response: dict[str, Any] = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "provider": provider,
        "model": model,
        "request": redacted_request_payload(request_payload),
        "provenance": packet["provenance"],
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=180) as client:
            response, attempts = post_provider_with_retries(
                client,
                provider=provider,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = response_content_text(raw_response["response_json"], provider=provider)
        parsed = json.loads(content)
        record = dict(parsed)
        record.update(
            {
                "run_id": packet["run_id"],
                "document_id": packet["document_id"],
                "task_name": packet["task_name"],
                "provider": provider,
                "model": model,
                "poc_status": "candidate_unit_classification",
                "errors": [],
                "provenance": unit_classification_provenance(
                    packet,
                    provider=provider,
                    model=model,
                    latency_seconds=raw_response["latency_seconds"],
                    output_text=content,
                ),
            }
        )
        record["unit_grounding_audit"] = build_unit_grounding_audit(record, packet)
        return record, raw_response
    except Exception as exc:
        record = error_unit_classification_record(
            packet,
            provider=provider,
            model=model,
            error=str(exc),
        )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["error"] = str(exc)
        return record, raw_response


def unit_classification_provenance(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    latency_seconds: float | None,
    output_text: str | None = None,
) -> dict[str, Any]:
    provenance = {
        **packet["provenance"],
        "provider": provider,
        "model": model,
        "prompt_version": packet["prompt_version"],
        "selected_unit_ids": packet["selected_unit_ids"],
        "input_prompt_chars": len(packet["prompt"]),
        "rough_input_token_estimate": rough_token_count(packet["prompt"]),
    }
    if latency_seconds is not None:
        provenance["latency_seconds"] = latency_seconds
    if output_text is not None:
        provenance["output_chars"] = len(output_text)
        provenance["rough_output_token_estimate"] = rough_token_count(output_text)
    return provenance


def dry_run_unit_classification_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    record = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "task_name": packet["task_name"],
        "provider": provider,
        "model": model,
        "poc_status": "dry_run_prompt_prepared",
        "errors": [],
        "task_support_status": "insufficient_evidence",
        "needs_human_review": True,
        "review_reasons": ["Dry run only; no unit classification was generated."],
        "legacy_alignment": {},
        "provenance": unit_classification_provenance(
            packet,
            provider=provider,
            model=model,
            latency_seconds=None,
        ),
    }
    record["unit_grounding_audit"] = build_unit_grounding_audit(record, packet)
    return record


def error_unit_classification_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    error: str,
) -> dict[str, Any]:
    record = dry_run_unit_classification_record(packet, provider=provider, model=model)
    record["poc_status"] = "error"
    record["errors"] = [error]
    record["review_reasons"] = [
        "Unit classification failed; inspect raw response before retry."
    ]
    return record


def build_unit_grounding_audit(
    record: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    unit_text_by_id = {unit.paragraph_id: unit.text for unit in packet["units"]}
    cited_unit_ids = collect_cited_unit_ids(record)
    unknown_unit_ids = sorted(
        unit_id for unit_id in cited_unit_ids if unit_id not in unit_text_by_id
    )
    unsupported_evidence_texts: list[dict[str, Any]] = []
    evidence_text_policy_violations: list[dict[str, Any]] = []
    for value in iter_nested_values(record):
        if not isinstance(value, dict):
            continue
        evidence_text = clean_text(str(value.get("evidence_text") or ""))
        if not evidence_text:
            continue
        entry_unit_ids = [
            str(unit_id)
            for unit_id in value.get("cited_unit_ids", [])
            if unit_id is not None
        ]
        policy_violations = unit_evidence_text_policy_violations(
            evidence_text,
            cited_unit_ids=entry_unit_ids,
        )
        if policy_violations:
            evidence_text_policy_violations.append(
                {
                    "task_name": str(record.get("task_name", "")),
                    "evidence_text": evidence_text,
                    "cited_unit_ids": entry_unit_ids,
                    "violations": policy_violations,
                }
            )
        cited_texts = [
            unit_text_by_id[unit_id]
            for unit_id in entry_unit_ids
            if unit_id in unit_text_by_id
        ]
        if not any(
            normalize_label(evidence_text) in normalize_label(cited_text)
            for cited_text in cited_texts
        ):
            unsupported_evidence_texts.append(
                {
                    "task_name": str(record.get("task_name", "")),
                    "evidence_text": evidence_text,
                    "cited_unit_ids": entry_unit_ids,
                }
            )
    missing_required_citations = False
    for value in iter_nested_values(record):
        if not isinstance(value, dict):
            continue
        support_status = normalize_label(str(value.get("support_status", "")))
        if support_status in {"supported", "conflicting", "partial"}:
            missing_required_citations = missing_required_citations or not bool(
                value.get("cited_unit_ids")
            )
    return {
        "known_unit_count": len(unit_text_by_id),
        "cited_unit_ids": sorted(cited_unit_ids),
        "unknown_unit_ids": unknown_unit_ids,
        "unsupported_evidence_texts": unsupported_evidence_texts,
        "evidence_text_policy_violations": evidence_text_policy_violations,
        "missing_required_citations": missing_required_citations,
        "grounding_repair_needed": (
            bool(unknown_unit_ids)
            or bool(unsupported_evidence_texts)
            or bool(evidence_text_policy_violations)
            or missing_required_citations
        ),
        "passes_basic_grounding": (
            not unknown_unit_ids
            and not unsupported_evidence_texts
            and not evidence_text_policy_violations
            and not missing_required_citations
        ),
    }


def unit_evidence_text_policy_violations(
    evidence_text: str,
    *,
    cited_unit_ids: list[str],
) -> list[str]:
    violations: list[str] = []
    if len(evidence_text) > UNIT_EVIDENCE_TEXT_MAX_CHARS:
        violations.append("evidence_text_too_long")
    if "..." in evidence_text or "…" in evidence_text:
        violations.append("evidence_text_contains_ellipsis")
    if "[...]" in evidence_text or "(...)" in evidence_text:
        violations.append("evidence_text_contains_omission_marker")
    if len(cited_unit_ids) != 1:
        violations.append("evidence_text_requires_exactly_one_cited_unit")
    return violations


def build_semantic_paragraph_chat_request(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    system_content = (
        "You classify literal article paragraphs as compact JSON index metadata. "
        "You never provide medical advice."
    )
    if provider == "anthropic":
        return {
            "model": model,
            "system": system_content,
            "messages": [{"role": "user", "content": packet["prompt"]}],
            "temperature": 0,
            "max_tokens": SEMANTIC_PARAGRAPH_MAX_OUTPUT_TOKENS,
        }
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": packet["prompt"]},
        ],
        "temperature": 0,
        "max_completion_tokens": SEMANTIC_PARAGRAPH_MAX_OUTPUT_TOKENS,
        "response_format": {"type": "json_object"},
    }


def run_semantic_paragraph_window_with_provider(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = build_semantic_paragraph_chat_request(
        packet,
        provider=provider,
        model=model,
    )
    raw_response: dict[str, Any] = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "window_id": packet["window_id"],
        "provider": provider,
        "model": model,
        "request": redacted_request_payload(request_payload),
        "provenance": packet["provenance"],
    }
    started = time.monotonic()
    try:
        with httpx.Client(timeout=120) as client:
            response, attempts = post_provider_with_retries(
                client,
                provider=provider,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = response_content_text(raw_response["response_json"], provider=provider)
        parsed = json.loads(content)
        record = dict(parsed)
        record.update(
            {
                "run_id": packet["run_id"],
                "document_id": packet["document_id"],
                "window_id": packet["window_id"],
                "poc_status": "candidate_semantic_paragraph_index",
                "provider": provider,
                "model": model,
                "errors": [],
                "provenance": semantic_paragraph_provenance(
                    packet,
                    provider=provider,
                    model=model,
                    latency_seconds=raw_response["latency_seconds"],
                    output_text=content,
                ),
            }
        )
        record["paragraph_index_audit"] = build_paragraph_index_audit(record, packet)
        return record, raw_response
    except Exception as exc:
        record = error_semantic_paragraph_record(
            packet,
            provider=provider,
            model=model,
            error=str(exc),
        )
        raw_response["latency_seconds"] = round(time.monotonic() - started, 3)
        raw_response["error"] = str(exc)
        return record, raw_response


def semantic_paragraph_provenance(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    latency_seconds: float | None,
    output_text: str | None = None,
) -> dict[str, Any]:
    provenance = {
        **packet["provenance"],
        "provider": provider,
        "model": model,
        "prompt_version": packet["prompt_version"],
        "paragraph_ids": packet["paragraph_ids"],
        "input_prompt_chars": len(packet["prompt"]),
        "rough_input_token_estimate": rough_token_count(packet["prompt"]),
    }
    if latency_seconds is not None:
        provenance["latency_seconds"] = latency_seconds
    if output_text is not None:
        provenance["output_chars"] = len(output_text)
        provenance["rough_output_token_estimate"] = rough_token_count(output_text)
    return provenance


def dry_run_semantic_paragraph_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
) -> dict[str, Any]:
    record = {
        "run_id": packet["run_id"],
        "document_id": packet["document_id"],
        "window_id": packet["window_id"],
        "paragraph_annotations": [],
        "window_notes": ["Dry run only; no semantic paragraph labels were generated."],
        "poc_status": "dry_run_prompt_prepared",
        "provider": provider,
        "model": model,
        "errors": [],
        "provenance": semantic_paragraph_provenance(
            packet,
            provider=provider,
            model=model,
            latency_seconds=None,
        ),
    }
    record["paragraph_index_audit"] = build_paragraph_index_audit(record, packet)
    return record


def error_semantic_paragraph_record(
    packet: dict[str, Any],
    *,
    provider: ProviderName,
    model: str,
    error: str,
) -> dict[str, Any]:
    record = dry_run_semantic_paragraph_record(packet, provider=provider, model=model)
    record["poc_status"] = "error"
    record["errors"] = [error]
    record["window_notes"] = ["Semantic paragraph classification failed; inspect raw response."]
    return record


def build_paragraph_index_audit(
    record: dict[str, Any],
    packet: dict[str, Any],
) -> dict[str, Any]:
    known_ids = set(packet["paragraph_ids"])
    annotations = record.get("paragraph_annotations", [])
    observed_ids: list[str] = []
    invalid_labels: list[dict[str, Any]] = []
    evidence_term_issues: list[dict[str, Any]] = []
    text_by_id = {paragraph.paragraph_id: paragraph.text for paragraph in packet["paragraphs"]}
    if isinstance(annotations, list):
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            paragraph_id = str(annotation.get("paragraph_id", ""))
            observed_ids.append(paragraph_id)
            labels = annotation.get("labels", [])
            if isinstance(labels, list):
                for label in labels:
                    if str(label) not in SEMANTIC_PARAGRAPH_LABELS:
                        invalid_labels.append(
                            {"paragraph_id": paragraph_id, "label": str(label)}
                        )
            terms = annotation.get("evidence_terms", [])
            if isinstance(terms, list):
                paragraph_text = normalize_label(text_by_id.get(paragraph_id, ""))
                for term in terms:
                    normalized_term = normalize_label(str(term))
                    if normalized_term and normalized_term not in paragraph_text:
                        evidence_term_issues.append(
                            {"paragraph_id": paragraph_id, "evidence_term": str(term)}
                        )
    observed_set = set(observed_ids)
    passes_structure_audit = (
        not known_ids.difference(observed_set)
        and not observed_set.difference(known_ids)
        and not invalid_labels
    )
    return {
        "known_paragraph_count": len(known_ids),
        "annotation_count": len(observed_ids),
        "missing_paragraph_ids": sorted(known_ids.difference(observed_set)),
        "unknown_paragraph_ids": sorted(observed_set.difference(known_ids)),
        "duplicate_paragraph_ids": sorted(
            paragraph_id
            for paragraph_id, count in Counter(observed_ids).items()
            if count > 1
        ),
        "invalid_labels": invalid_labels,
        "evidence_term_issues": evidence_term_issues,
        "passes_structure_audit": passes_structure_audit,
        "passes_evidence_term_audit": not evidence_term_issues,
        "passes_basic_audit": passes_structure_audit,
    }


def build_merged_semantic_paragraph_indexes(
    window_records: list[dict[str, Any]],
    *,
    paragraph_index_inputs: dict[str, list[EvidenceParagraph]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    records_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in window_records:
        if record.get("poc_status") == "dry_run_prompt_prepared":
            continue
        key = (
            str(record.get("document_id")),
            str(record.get("provider")),
            str(record.get("model")),
        )
        records_by_key[key].append(record)
    for (document_id, provider, model), records in records_by_key.items():
        paragraphs = paragraph_index_inputs.get(document_id, [])
        paragraph_text_by_id = {paragraph.paragraph_id: paragraph for paragraph in paragraphs}
        annotations_by_paragraph: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            annotations = record.get("paragraph_annotations", [])
            if not isinstance(annotations, list):
                continue
            for annotation in annotations:
                if isinstance(annotation, dict) and annotation.get("paragraph_id"):
                    annotations_by_paragraph[str(annotation["paragraph_id"])].append(annotation)
        merged_annotations = []
        for paragraph_id, paragraph in paragraph_text_by_id.items():
            annotations = annotations_by_paragraph.get(paragraph_id, [])
            merged_annotations.append(
                merge_paragraph_annotations(
                    paragraph,
                    annotations=annotations,
                )
            )
        merged.append(
            {
                "document_id": document_id,
                "provider": provider,
                "model": model,
                "paragraph_count": len(paragraphs),
                "annotated_paragraph_count": sum(
                    bool(annotation["label_votes"]) for annotation in merged_annotations
                ),
                "merged_annotations": merged_annotations,
                "label_counts": dict(
                    Counter(
                        label
                        for annotation in merged_annotations
                        for label in annotation["labels"]
                    ).most_common()
                ),
                "provenance": {
                    "source": "llm_study_reclassification_poc",
                    "method": "merge_semantic_paragraph_window_votes",
                    "review_boundary": "semantic_paragraph_labels_are_candidate_index_metadata",
                },
            }
        )
    return merged


def merge_paragraph_annotations(
    paragraph: EvidenceParagraph,
    *,
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    label_counter: Counter[str] = Counter()
    relevance: dict[str, Counter[str]] = defaultdict(Counter)
    evidence_terms: set[str] = set()
    review_hint_votes = 0
    for annotation in annotations:
        labels = annotation.get("labels", [])
        if isinstance(labels, list):
            label_counter.update(
                str(label)
                for label in labels
                if str(label) in SEMANTIC_PARAGRAPH_LABELS
            )
        relevance_map = annotation.get("question_relevance", {})
        if isinstance(relevance_map, dict):
            for question, value in relevance_map.items():
                relevance[str(question)][str(value)] += 1
        terms = annotation.get("evidence_terms", [])
        if isinstance(terms, list):
            for term in terms:
                term_text = clean_text(str(term))
                if term_text:
                    evidence_terms.add(term_text)
        if annotation.get("needs_human_review_hint") is True:
            review_hint_votes += 1
    labels = [
        label
        for label, _count in label_counter.most_common()
        if label != "not_relevant" or len(label_counter) == 1
    ]
    return {
        "paragraph_id": paragraph.paragraph_id,
        "section": paragraph.section,
        "unit_type": paragraph.unit_type,
        "ordinal": paragraph.ordinal,
        "text": paragraph.text,
        "labels": labels,
        "label_votes": dict(label_counter.most_common()),
        "question_relevance_votes": {
            question: dict(counter.most_common()) for question, counter in relevance.items()
        },
        "evidence_terms": sorted(evidence_terms),
        "needs_human_review_hint_votes": review_hint_votes,
    }


def build_span_grounding_audit(
    record: dict[str, Any],
    packet: EvidenceSummaryPacketRecord,
) -> dict[str, Any]:
    span_text_by_id = {span.span_id: span.text for span in packet.spans}
    cited_span_ids = collect_cited_span_ids(record)
    unknown_span_ids = sorted(
        span_id for span_id in cited_span_ids if span_id not in span_text_by_id
    )
    unsupported_evidence_texts: list[dict[str, Any]] = []
    field_support = record.get("field_support")
    if isinstance(field_support, dict):
        for field_name, entries in field_support.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                evidence_text = clean_text(str(entry.get("evidence_text") or ""))
                if not evidence_text:
                    continue
                entry_span_ids = [
                    str(span_id)
                    for span_id in entry.get("cited_span_ids", [])
                    if span_id is not None
                ]
                cited_text = " ".join(
                    span_text_by_id.get(span_id, "") for span_id in entry_span_ids
                )
                if normalize_label(evidence_text) not in normalize_label(cited_text):
                    unsupported_evidence_texts.append(
                        {
                            "field_name": str(field_name),
                            "candidate_value": entry.get("candidate_value"),
                            "evidence_text": evidence_text,
                            "cited_span_ids": entry_span_ids,
                        }
                    )
    return {
        "known_span_count": len(span_text_by_id),
        "cited_span_ids": sorted(cited_span_ids),
        "unknown_span_ids": unknown_span_ids,
        "unsupported_evidence_texts": unsupported_evidence_texts,
        "passes_basic_grounding": not unknown_span_ids and not unsupported_evidence_texts,
    }


def collect_cited_span_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        span_ids: set[str] = set()
        for key, nested in value.items():
            if key == "cited_span_ids" and isinstance(nested, list):
                span_ids.update(str(item) for item in nested if item is not None)
            else:
                span_ids.update(collect_cited_span_ids(nested))
        return span_ids
    if isinstance(value, list):
        span_ids: set[str] = set()
        for item in value:
            span_ids.update(collect_cited_span_ids(item))
        return span_ids
    return set()


def collect_cited_unit_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        unit_ids: set[str] = set()
        for key, nested in value.items():
            if key == "cited_unit_ids" and isinstance(nested, list):
                unit_ids.update(str(item) for item in nested if item is not None)
            else:
                unit_ids.update(collect_cited_unit_ids(nested))
        return unit_ids
    if isinstance(value, list):
        unit_ids: set[str] = set()
        for item in value:
            unit_ids.update(collect_cited_unit_ids(item))
        return unit_ids
    return set()


def run_task_packet_with_groq(
    packet: TaskPacketRecord,
    *,
    model: str,
    api_key: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract auditable scientific metadata as JSON only. "
                    "You never provide medical advice."
                ),
            },
            {"role": "user", "content": packet.prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    raw_response: dict[str, Any] = {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "request": redacted_request_payload(request_payload),
        "provenance": packet.provenance,
    }
    try:
        with httpx.Client(timeout=120) as client:
            response, attempts = post_groq_with_retries(
                client,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = raw_response["response_json"]["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        record = dict(parsed)
        record.update(
            {
                "run_id": packet.run_id,
                "document_id": packet.document_id,
                "task_name": packet.task_name,
                "poc_status": "candidate_task_output",
                "errors": [],
                "provenance": {
                    **packet.provenance,
                    "model": model,
                    "prompt_version": packet.prompt_version,
                    "selected_chunk_ids": packet.selected_chunk_ids,
                    "context_strategy": packet.context_strategy,
                    "evidence_source_used": packet.evidence_source_used,
                },
            }
        )
        return record, raw_response
    except Exception as exc:
        record = {
            "run_id": packet.run_id,
            "document_id": packet.document_id,
            "task_name": packet.task_name,
            "poc_status": "error",
            "errors": [str(exc)],
            "needs_human_review": True,
            "review_reasons": ["Task extraction failed; inspect raw response before retry."],
            "provenance": {
                **packet.provenance,
                "model": model,
                "prompt_version": packet.prompt_version,
                "selected_chunk_ids": packet.selected_chunk_ids,
                "context_strategy": packet.context_strategy,
                "evidence_source_used": packet.evidence_source_used,
            },
        }
        raw_response["error"] = str(exc)
        return record, raw_response


def load_full_source_text(candidate: StudyCandidate) -> str:
    artifact = candidate.selected_artifact
    if not artifact or not artifact.payload_path:
        return ""
    path = Path(artifact.payload_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if artifact.artifact_type in {"pmc_nxml", "europe_pmc_full_text_xml"}:
        return extract_xml_or_html_text(raw)
    if artifact.artifact_type == "pmc_html":
        return extract_html_text(raw)
    return ""


def select_evidence_chunks(
    candidate: StudyCandidate,
    *,
    max_source_chars: int,
) -> list[EvidenceChunk]:
    chunks = load_source_chunks(candidate)
    if not chunks:
        return []
    scored_chunks = score_evidence_chunks(chunks, candidate)
    selected: list[EvidenceChunk] = []
    used_chunk_ids: set[str] = set()
    remaining_chars = max_source_chars

    for chunk in required_evidence_chunks(scored_chunks):
        if chunk.chunk_id in used_chunk_ids:
            continue
        if len(chunk.text) > remaining_chars and selected:
            continue
        selected.append(chunk)
        used_chunk_ids.add(chunk.chunk_id)
        remaining_chars -= len(chunk.text)

    for chunk in sorted(scored_chunks, key=lambda value: (-value.score, value.chunk_id)):
        if chunk.chunk_id in used_chunk_ids:
            continue
        if chunk.score <= 0 and selected:
            continue
        if len(chunk.text) > remaining_chars and selected:
            continue
        selected.append(chunk)
        used_chunk_ids.add(chunk.chunk_id)
        remaining_chars -= len(chunk.text)
        if remaining_chars <= 0:
            break
    return selected


def required_evidence_chunks(chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
    preferred_sections = ("abstract", "methods", "materials and methods", "results")
    selected: list[EvidenceChunk] = []
    for preferred in preferred_sections:
        matches = [
            chunk
            for chunk in chunks
            if normalize_label(chunk.section).startswith(normalize_label(preferred))
        ]
        if matches:
            selected.append(sorted(matches, key=lambda value: (-value.score, value.chunk_id))[0])
    return selected


def load_source_chunks(candidate: StudyCandidate) -> list[EvidenceChunk]:
    artifact = candidate.selected_artifact
    if not artifact or not artifact.payload_path:
        return []
    path = Path(artifact.payload_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists():
        return []
    raw = path.read_bytes()
    if artifact.artifact_type in {"pmc_nxml", "europe_pmc_full_text_xml"}:
        return extract_xml_chunks(raw, artifact=artifact)
    if artifact.artifact_type == "pmc_html":
        return extract_html_chunks(raw, artifact=artifact)
    return []


def score_evidence_chunks(
    chunks: list[EvidenceChunk],
    candidate: StudyCandidate,
) -> list[EvidenceChunk]:
    legacy_terms = tuple(term.lower() for term in candidate.pathologies)
    scored: list[EvidenceChunk] = []
    for chunk in chunks:
        text = chunk.text.lower()
        matched_topics: list[str] = []
        score = 0.0
        section = normalize_label(chunk.section)
        if section in {"abstract", "methods", "materials and methods", "results"}:
            score += 3.0
        if section in {"discussion", "conclusion", "conclusions"}:
            score += 1.0
        for topic, terms in EVIDENCE_TOPICS.items():
            topic_score = sum(text.count(term.lower()) for term in terms)
            if topic_score:
                matched_topics.append(topic)
                score += min(topic_score, 8)
        for term in legacy_terms:
            if term and term in text:
                score += 2.0
                if "legacy_pathology" not in matched_topics:
                    matched_topics.append("legacy_pathology")
        scored.append(
            chunk.model_copy(
                update={
                    "score": score,
                    "matched_topics": sorted(matched_topics),
                }
            )
        )
    return scored


def format_evidence_packet(candidate: StudyCandidate, chunks: list[EvidenceChunk]) -> str:
    parts = [build_metadata_text(candidate, include_abstract=False)]
    if candidate.publication_abstract:
        parts.append(f"\n[abstract_metadata]\n{candidate.publication_abstract}")
    if chunks:
        parts.append("\n[retrieved_full_text_chunks]")
    for chunk in chunks:
        topics = ", ".join(chunk.matched_topics) if chunk.matched_topics else "none"
        parts.append(
            "\n".join(
                [
                    f"[chunk_id={chunk.chunk_id}]",
                    f"section: {chunk.section}",
                    f"score: {chunk.score:.2f}",
                    f"matched_topics: {topics}",
                    f"artifact_id: {chunk.artifact_id or ''}",
                    f"artifact_path: {chunk.artifact_path or ''}",
                    f"text: {chunk.text}",
                ]
            )
        )
    return "\n\n".join(part for part in parts if part.strip())


def format_direct_full_text_packet(candidate: StudyCandidate, full_text: str) -> str:
    parts = [
        build_metadata_text(candidate, include_abstract=False),
        "\n[direct_full_text_compact]",
        full_text,
    ]
    if candidate.publication_abstract:
        parts.insert(1, f"\n[abstract_metadata]\n{candidate.publication_abstract}")
    return "\n\n".join(part for part in parts if part.strip())


def extract_xml_or_html_text(raw: bytes) -> str:
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        return clean_text(decode_raw_text(raw))
    if etree.QName(root).localname.lower() == "html":
        return extract_html_text(raw)
    return extract_xml_text(raw)


def extract_xml_text(raw: bytes) -> str:
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        return clean_text(decode_raw_text(raw))
    for xpath in (".//ref-list", ".//table-wrap", ".//fig", ".//back"):
        for element in root.findall(xpath):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)
    return clean_text(" ".join(root.itertext()))


def extract_xml_chunks(raw: bytes, *, artifact: ArtifactReference) -> list[EvidenceChunk]:
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(raw, parser=parser)
    if root is None:
        return split_text_into_chunks(
            decode_raw_text(raw),
            section="unparsed_full_text",
            artifact=artifact,
            chunk_prefix="unparsed_full_text",
        )
    if etree.QName(root).localname.lower() == "html":
        return extract_html_chunks(raw, artifact=artifact)
    for xpath in (".//*[local-name()='ref-list']", ".//*[local-name()='back']"):
        for element in root.xpath(xpath):
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)

    chunks: list[EvidenceChunk] = []
    for element in root.xpath(".//*[local-name()='abstract']"):
        text = clean_text(" ".join(element.itertext()))
        chunks.extend(
            split_text_into_chunks(
                text,
                section="abstract",
                artifact=artifact,
                chunk_prefix="abstract",
            )
        )
    for index, element in enumerate(root.xpath(".//*[local-name()='sec']")):
        section = section_title(element) or f"section_{index + 1}"
        text = clean_text(" ".join(element.itertext()))
        chunks.extend(
            split_text_into_chunks(
                text,
                section=section,
                artifact=artifact,
                chunk_prefix=f"sec_{index + 1}",
            )
        )
    for index, element in enumerate(root.xpath(".//*[local-name()='table-wrap']")):
        text = clean_text(" ".join(element.itertext()))
        chunks.extend(
            split_text_into_chunks(
                text,
                section="table_or_caption",
                artifact=artifact,
                chunk_prefix=f"table_{index + 1}",
            )
        )
    if not chunks:
        chunks = split_text_into_chunks(
            extract_xml_text(raw),
            section="full_text",
            artifact=artifact,
            chunk_prefix="full_text",
        )
    return deduplicate_chunks(chunks)


def extract_html_chunks(raw: bytes, *, artifact: ArtifactReference) -> list[EvidenceChunk]:
    document = html.fromstring(raw)
    for element in document.xpath("//script|//style|//nav|//footer|//aside"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    chunks = split_text_into_chunks(
        clean_text(document.text_content()),
        section="html_full_text",
        artifact=artifact,
        chunk_prefix="html_full_text",
    )
    return deduplicate_chunks(chunks)


def decode_raw_text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="ignore")


def section_title(element: etree._Element) -> str | None:
    for child in element:
        if etree.QName(child).localname == "title":
            title = clean_text(" ".join(child.itertext()))
            if title:
                return title
    return None


def split_text_into_chunks(
    text: str,
    *,
    section: str,
    artifact: ArtifactReference,
    chunk_prefix: str,
) -> list[EvidenceChunk]:
    text = clean_text(text)
    if not text:
        return []
    chunks: list[EvidenceChunk] = []
    start = 0
    index = 1
    while start < len(text):
        end = min(start + CHUNK_MAX_CHARS, len(text))
        if end < len(text):
            end = max(start + 1, text.rfind(" ", start, end))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(
                EvidenceChunk(
                    chunk_id=f"{artifact.artifact_id}:{chunk_prefix}:{index}",
                    artifact_id=artifact.artifact_id,
                    artifact_path=artifact.payload_path,
                    section=section,
                    text=chunk_text,
                    char_start=start,
                    char_end=end,
                )
            )
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
        index += 1
    return chunks


def deduplicate_chunks(chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
    seen: set[str] = set()
    deduplicated: list[EvidenceChunk] = []
    for chunk in chunks:
        normalized = normalize_label(chunk.text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(chunk)
    return deduplicated


def extract_html_text(raw: bytes) -> str:
    document = html.fromstring(raw)
    for element in document.xpath("//script|//style|//nav|//footer|//aside"):
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)
    return clean_text(document.text_content())


def build_metadata_text(candidate: StudyCandidate, *, include_abstract: bool = True) -> str:
    parts = [
        f"Title: {candidate.title or ''}",
        f"Publication year: {candidate.publication_year or ''}",
        f"PMID: {candidate.pmid or ''}",
        f"PMCID: {candidate.pmcid or ''}",
        f"DOI: {candidate.doi or ''}",
    ]
    if include_abstract and candidate.publication_abstract:
        parts.append(f"Abstract: {candidate.publication_abstract}")
    return clean_text("\n".join(parts))


def build_legacy_guardrail_text(candidate: StudyCandidate) -> str:
    record = candidate.legacy_context
    guardrail = {
        "context_id": candidate.context_id,
        "document_id": candidate.document_id,
        "title": candidate.title,
        "publication_year": candidate.publication_year,
        "pmid": candidate.pmid,
        "pmcid": candidate.pmcid,
        "doi": candidate.doi,
        "canonical_url": record.get("canonical_url"),
        "legacy_study_type": candidate.legacy_study_type,
        "legacy_study_result": candidate.legacy_study_result,
        "legacy_sample_size": candidate.legacy_sample_size,
        "key_findings": record.get("key_findings", []),
        "list_fields": record.get("list_fields", {}),
        "text_fields": record.get("text_fields", {}),
        "source_filenames": record.get("source_filenames", []),
        "identity_confirmation_status": record.get("identity_confirmation_status"),
        "identity_validation_bucket": record.get("identity_validation_bucket"),
    }
    return truncate_text(json.dumps(guardrail, ensure_ascii=False, indent=2), MAX_LEGACY_CHARS)


def build_prompt(
    *,
    candidate: StudyCandidate,
    evidence_source_used: str,
    source_text: str,
    legacy_context_text: str,
) -> str:
    schema = {
        "document_id": "string",
        "evidence_source_used": "full_text | abstract_metadata | legacy_context_only",
        "study_type_reclassified": "string or null",
        "study_design_family": (
            "human_clinical | human_observational | evidence_synthesis | animal | "
            "laboratory | mixed | unclear"
        ),
        "human_or_nonhuman": "human | nonhuman | mixed | not_applicable | unclear",
        "human_sample_size": "integer or null",
        "species_or_model": ["string"],
        "pathologies_or_conditions": ["string"],
        "organ_systems": ["string"],
        "cannabinoids": ["string"],
        "terpenes": ["string"],
        "receptors": ["string"],
        "route_of_administration": ["string"],
        "dosage": ["string"],
        "treatment_duration": ["string"],
        "comparator_or_control": ["string"],
        "study_result_direction": "positive | negative | mixed | neutral | safety_signal | unclear",
        "key_findings_generated": ["string"],
        "adverse_events": ["string"],
        "field_confidence": {"field_name": "high | medium | low"},
        "field_evidence_text": {"field_name": ["short verbatim evidence text"]},
        "field_evidence_chunks": {"field_name": ["chunk_id"]},
        "legacy_alignment": {
            "field_name": "supports | conflicts | partial | not_in_legacy | insufficient_evidence"
        },
        "needs_human_review": "boolean",
        "review_reasons": ["string"],
        "provenance": {
            "model": "string",
            "prompt_version": PROMPT_VERSION,
            "source_artifact_ids": ["string"],
            "source_artifact_paths": ["string"],
            "legacy_context_id": "string or null",
        },
    }
    return (
        f"You are preparing candidate evidence for a human-reviewed cannabinoid evidence "
        f"""knowledge base.

Safety and scope:
- Do not provide medical advice, treatment recommendations, dosing guidance for use, or
  clinical instructions.
- Extract and classify what the cited study reports. Treat every output as unreviewed
  candidate evidence.
- The legacy English context is a guardrail and comparison baseline, not absolute truth.
- Prefer the full text when available. If full text and legacy context disagree, mark
  conflicts explicitly.
- Use insufficient_evidence when the provided text does not support a field.
- Return only valid JSON. Do not wrap the JSON in Markdown.
- Use English only.
- Include short textual evidence for critical fields such as study type, population/model,
  condition, cannabinoid, dosage, duration, comparator, result direction, key findings,
  and adverse events.
- When source text includes chunk_id markers, cite supporting chunk ids in
  field_evidence_chunks. Use the provided chunk ids exactly.

Output JSON schema:
{json.dumps(schema, indent=2)}

Document metadata:
document_id: {candidate.document_id}
title: {candidate.title or ""}
publication_year: {candidate.publication_year or ""}
pmid: {candidate.pmid or ""}
pmcid: {candidate.pmcid or ""}
doi: {candidate.doi or ""}
evidence_source_used: {evidence_source_used}
legacy_study_type: {candidate.legacy_study_type or ""}
legacy_study_result: {candidate.legacy_study_result or ""}
legacy_sample_size: {candidate.legacy_sample_size or ""}

Legacy English context:
{legacy_context_text}

Source evidence packet:
{source_text}
"""
    )


def classify_with_groq(
    candidate: StudyCandidate,
    prompt_package: PromptPackage,
    *,
    model: str,
    api_key: str,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract auditable scientific metadata as JSON only. "
                    "You never provide medical advice."
                ),
            },
            {"role": "user", "content": prompt_package.prompt},
        ],
        "temperature": 0,
        "max_completion_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    raw_response: dict[str, Any] = {
        "run_id": run_id,
        "document_id": candidate.document_id,
        "request": redacted_request_payload(request_payload),
        "provenance": prompt_provenance(candidate, prompt_package, model=model),
    }
    try:
        with httpx.Client(timeout=120) as client:
            response, attempts = post_groq_with_retries(
                client,
                request_payload=request_payload,
                api_key=api_key,
            )
        raw_response["attempts"] = attempts
        raw_response["status_code"] = response.status_code
        raw_response["response_json"] = response.json()
        response.raise_for_status()
        content = raw_response["response_json"]["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        record = normalize_llm_record(
            parsed,
            candidate=candidate,
            prompt_package=prompt_package,
            model=model,
            run_id=run_id,
        )
        return record, raw_response
    except Exception as exc:
        record = error_record(
            candidate,
            prompt_package,
            model=model,
            run_id=run_id,
            error=str(exc),
        )
        raw_response["error"] = str(exc)
        return record, raw_response


def post_groq_with_retries(
    client: httpx.Client,
    *,
    request_payload: dict[str, Any],
    api_key: str,
    max_attempts: int = 3,
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    response: httpx.Response | None = None
    for attempt_number in range(1, max_attempts + 1):
        response = client.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
        )
        attempt = {"attempt": attempt_number, "status_code": response.status_code}
        attempts.append(attempt)
        if (
            response.status_code != 429
            or attempt_number == max_attempts
            or is_daily_token_limit(response)
        ):
            return response, attempts
        wait_seconds = retry_wait_seconds(response)
        attempt["retry_wait_seconds"] = wait_seconds
        time.sleep(wait_seconds)
    if response is None:
        raise RuntimeError("Groq request did not execute.")
    return response, attempts


def post_provider_with_retries(
    client: httpx.Client,
    *,
    provider: ProviderName,
    request_payload: dict[str, Any],
    api_key: str,
    max_attempts: int = 3,
) -> tuple[httpx.Response, list[dict[str, Any]]]:
    if provider == "groq":
        return post_groq_with_retries(
            client,
            request_payload=request_payload,
            api_key=api_key,
            max_attempts=max_attempts,
        )

    attempts: list[dict[str, Any]] = []
    response: httpx.Response | None = None
    for attempt_number in range(1, max_attempts + 1):
        response = client.post(
            provider_url(provider),
            headers=provider_headers(provider, api_key),
            json=request_payload,
        )
        attempt = {"attempt": attempt_number, "status_code": response.status_code}
        attempts.append(attempt)
        if response.status_code not in {429, 500, 502, 503, 504} or attempt_number == max_attempts:
            return response, attempts
        wait_seconds = retry_wait_seconds(response)
        attempt["retry_wait_seconds"] = wait_seconds
        time.sleep(wait_seconds)
    if response is None:
        raise RuntimeError(f"{provider} request did not execute.")
    return response, attempts


def provider_url(provider: ProviderName) -> str:
    return {
        "groq": GROQ_CHAT_COMPLETIONS_URL,
        "openai": OPENAI_CHAT_COMPLETIONS_URL,
        "anthropic": ANTHROPIC_MESSAGES_URL,
        "cerebras": CEREBRAS_CHAT_COMPLETIONS_URL,
    }[provider]


def provider_headers(provider: ProviderName, api_key: str) -> dict[str, str]:
    if provider == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def response_content_text(response_json: dict[str, Any], *, provider: ProviderName) -> str:
    if provider == "anthropic":
        parts = response_json.get("content", [])
        text_parts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part).strip()
    return str(response_json["choices"][0]["message"]["content"])


def retry_wait_seconds(response: httpx.Response) -> float:
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), 90.0)
        except ValueError:
            pass
    try:
        message = str(response.json().get("error", {}).get("message", ""))
    except ValueError:
        message = response.text
    match = re.search(r"try again in ([0-9.]+)s", message, flags=re.IGNORECASE)
    if match:
        return min(max(float(match.group(1)) + 1.0, 1.0), 90.0)
    return 20.0


def is_daily_token_limit(response: httpx.Response) -> bool:
    try:
        message = str(response.json().get("error", {}).get("message", ""))
    except ValueError:
        message = response.text
    return "tokens per day" in message.lower() or " tpd" in message.lower()


def redacted_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    redacted["messages"] = [
        {"role": message["role"], "content_chars": len(message["content"])}
        for message in payload["messages"]
    ]
    if "system" in payload:
        redacted["system_chars"] = len(str(payload["system"]))
        redacted.pop("system", None)
    return redacted


def source_artifact_ids_from_packet(packet: EvidenceSummaryPacketRecord) -> list[str]:
    ids = packet.provenance.get("source_artifact_ids", [])
    return [str(value) for value in ids] if isinstance(ids, list) else []


def source_artifact_paths_from_packet(packet: EvidenceSummaryPacketRecord) -> list[str]:
    paths = packet.provenance.get("source_artifact_paths", [])
    return [str(value) for value in paths] if isinstance(paths, list) else []


def rough_token_count(text: str) -> int:
    return max(1, round(len(text) / 4))


def error_summary_record(
    packet: EvidenceSummaryPacketRecord,
    *,
    provider: ProviderName,
    model: str,
    error: str,
) -> dict[str, Any]:
    return {
        "run_id": packet.run_id,
        "document_id": packet.document_id,
        "task_name": packet.task_name,
        "provider": provider,
        "model": model,
        "poc_status": "error",
        "errors": [error],
        "needs_human_review": True,
        "review_reasons": ["Evidence summary failed; inspect raw response before retry."],
        "provenance": {
            **packet.provenance,
            "provider": provider,
            "model": model,
            "prompt_version": packet.prompt_version,
            "selected_span_ids": packet.selected_span_ids,
            "selected_chunk_ids": packet.selected_chunk_ids,
            "context_strategy": packet.context_strategy,
            "evidence_source_used": packet.evidence_source_used,
            "input_prompt_chars": len(packet.prompt),
            "rough_input_token_estimate": rough_token_count(packet.prompt),
        },
    }


def build_model_comparison_record_audit(
    record: dict[str, Any],
    *,
    raw_response: dict[str, Any],
) -> dict[str, Any]:
    grounding = record.get("span_grounding_audit")
    unsupported_count = 0
    if isinstance(grounding, dict):
        unsupported = grounding.get("unsupported_evidence_texts", [])
        unsupported_count = len(unsupported) if isinstance(unsupported, list) else 0
    return {
        "latency_seconds": raw_response.get("latency_seconds"),
        "status_code": raw_response.get("status_code"),
        "attempt_count": len(raw_response.get("attempts", [])),
        "not_found_or_insufficient_evidence_count": count_support_statuses(
            record,
            {"not_found", "insufficient_evidence"},
        ),
        "conflict_count": count_support_statuses(record, {"conflicting"})
        + count_legacy_conflicts(record),
        "unsupported_evidence_text_count": unsupported_count,
        "evidence_text_coverage": evidence_text_coverage(record),
        "needs_human_review": bool(record.get("needs_human_review")),
        "review_reason_count": (
            len(record.get("review_reasons", []))
            if isinstance(record.get("review_reasons"), list)
            else 0
        ),
    }


def count_support_statuses(record: dict[str, Any], statuses: set[str]) -> int:
    count = 0
    for value in iter_nested_values(record):
        if isinstance(value, dict):
            status = normalize_label(str(value.get("support_status", "")))
            if status in statuses:
                count += 1
    return count


def count_legacy_conflicts(record: dict[str, Any]) -> int:
    count = 0
    for value in iter_nested_values(record):
        if isinstance(value, dict):
            alignment = normalize_label(str(value.get("alignment", "")))
            if alignment in {"conflicts", "conflicting", "conflicts with legacy"}:
                count += 1
    return count


def evidence_text_coverage(record: dict[str, Any]) -> dict[str, int]:
    evidence_text_count = 0
    supported_evidence_text_count = 0
    for value in iter_nested_values(record):
        if not isinstance(value, dict):
            continue
        evidence_text = clean_text(str(value.get("evidence_text", "")))
        if not evidence_text:
            continue
        evidence_text_count += 1
        if value.get("cited_span_ids"):
            supported_evidence_text_count += 1
    return {
        "evidence_text_count": evidence_text_count,
        "evidence_texts_with_cited_spans": supported_evidence_text_count,
    }


def iter_nested_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for nested in value.values():
            values.extend(iter_nested_values(nested))
    elif isinstance(value, list):
        for nested in value:
            values.extend(iter_nested_values(nested))
    return values


def normalize_llm_record(
    parsed: dict[str, Any],
    *,
    candidate: StudyCandidate,
    prompt_package: PromptPackage,
    model: str,
    run_id: str,
) -> dict[str, Any]:
    record = dict(parsed)
    record["document_id"] = candidate.document_id
    record["evidence_source_used"] = prompt_package.evidence_source_used
    record["run_id"] = run_id
    record["poc_status"] = "candidate_evidence"
    record["errors"] = []
    record["provenance"] = {
        **record.get("provenance", {}),
        **prompt_provenance(candidate, prompt_package, model=model),
    }
    record["legacy_comparison_audit"] = build_legacy_comparison_audit(record, candidate)
    return record


def build_legacy_comparison_audit(
    record: dict[str, Any],
    candidate: StudyCandidate,
) -> dict[str, Any]:
    legacy_sample_size = parse_int(candidate.legacy_sample_size)
    generated_sample_size = parse_int(record.get("human_sample_size"))
    return {
        "legacy_study_type": candidate.legacy_study_type,
        "generated_study_type": record.get("study_type_reclassified"),
        "study_type_normalized_match": normalized_equal(
            candidate.legacy_study_type,
            record.get("study_type_reclassified"),
        ),
        "legacy_study_result": candidate.legacy_study_result,
        "generated_study_result_direction": record.get("study_result_direction"),
        "result_normalized_match": result_direction_matches(
            candidate.legacy_study_result,
            record.get("study_result_direction"),
        ),
        "legacy_sample_size": candidate.legacy_sample_size,
        "generated_human_sample_size": generated_sample_size,
        "sample_size_match": (
            legacy_sample_size == generated_sample_size
            if legacy_sample_size is not None and generated_sample_size is not None
            else None
        ),
        "llm_legacy_alignment": record.get("legacy_alignment", {}),
    }


def normalized_equal(left: Any, right: Any) -> bool | None:
    if left in (None, "") or right in (None, ""):
        return None
    return normalize_label(str(left)) == normalize_label(str(right))


def result_direction_matches(legacy_result: Any, generated_direction: Any) -> bool | None:
    if legacy_result in (None, "") or generated_direction in (None, ""):
        return None
    legacy = normalize_label(str(legacy_result))
    generated = normalize_label(str(generated_direction))
    mapping = {
        "positive": {"positive"},
        "negative": {"negative", "safety signal"},
        "mixed": {"mixed", "neutral"},
        "neutral": {"neutral", "mixed"},
    }
    return generated in mapping.get(legacy, {legacy})


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d+", str(value).replace(",", ""))
    if not match:
        return None
    return int(match.group(0))


def dry_run_record(
    candidate: StudyCandidate,
    prompt_package: PromptPackage,
    *,
    model: str,
    run_id: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "document_id": candidate.document_id,
        "evidence_source_used": prompt_package.evidence_source_used,
        "poc_status": "dry_run_prompt_prepared",
        "study_type_reclassified": None,
        "study_design_family": "unclear",
        "human_or_nonhuman": "unclear",
        "human_sample_size": None,
        "species_or_model": [],
        "pathologies_or_conditions": [],
        "organ_systems": [],
        "cannabinoids": [],
        "terpenes": [],
        "receptors": [],
        "route_of_administration": [],
        "dosage": [],
        "treatment_duration": [],
        "comparator_or_control": [],
        "study_result_direction": "unclear",
        "key_findings_generated": [],
        "adverse_events": [],
        "field_confidence": {},
        "field_evidence_text": {},
        "field_evidence_chunks": {},
        "legacy_alignment": {},
        "needs_human_review": True,
        "review_reasons": ["Dry run only; no LLM classification was generated."],
        "errors": [],
        "provenance": prompt_provenance(candidate, prompt_package, model=model),
    }


def error_record(
    candidate: StudyCandidate,
    prompt_package: PromptPackage,
    *,
    model: str,
    run_id: str,
    error: str,
) -> dict[str, Any]:
    record = dry_run_record(candidate, prompt_package, model=model, run_id=run_id)
    record["poc_status"] = "error"
    record["errors"] = [error]
    record["review_reasons"] = ["LLM extraction failed; inspect raw response before retry."]
    return record


def prompt_provenance(
    candidate: StudyCandidate,
    prompt_package: PromptPackage,
    *,
    model: str,
) -> dict[str, Any]:
    source_artifacts = [candidate.selected_artifact] if candidate.selected_artifact else []
    source_artifacts.extend(candidate.metadata_artifacts)
    return {
        "source": "llm_study_reclassification_poc",
        "method": "groq_candidate_study_reclassification",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "source_artifact_ids": [artifact.artifact_id for artifact in source_artifacts],
        "source_artifact_paths": [
            artifact.payload_path for artifact in source_artifacts if artifact.payload_path
        ],
        "source_chunk_ids": [chunk.chunk_id for chunk in prompt_package.source_chunks],
        "retrieval_method": prompt_package.retrieval_method,
        "context_strategy": prompt_package.context_strategy,
        "strategy_reason": prompt_package.strategy_reason,
        "full_text_chars": prompt_package.full_text_chars,
        "legacy_context_id": candidate.context_id,
        "review_boundary": "candidate_evidence_not_reviewed_knowledge",
        "does_not_mutate_sqlite_review_state": True,
        "evidence_source_used": prompt_package.evidence_source_used,
    }


def build_summary(
    *,
    run_id: str,
    dry_run: bool,
    model: str,
    cohort_path: Path,
    database_path: Path,
    selected: list[StudyCandidate],
    records: list[dict[str, Any]],
    processed_document_ids: set[str],
    paths: RunPaths,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "groq_candidate_study_reclassification",
        "prompt_version": PROMPT_VERSION,
        "dry_run": dry_run,
        "model": model,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(database_path),
        "records_path": str(paths.records_path),
        "prompt_preview_path": str(paths.prompt_preview_path),
        "raw_responses_path": str(paths.raw_responses_path),
        "selected_count": len(selected),
        "already_processed_count": len(processed_document_ids),
        "status_counts": dict(Counter(str(record.get("poc_status")) for record in records)),
        "evidence_source_counts": dict(
            Counter(str(record.get("evidence_source_used")) for record in records)
        ),
        "context_strategy_counts": dict(
            Counter(
                str(record.get("provenance", {}).get("context_strategy", "unknown"))
                for record in records
            )
        ),
        "legacy_study_type_counts": dict(
            Counter(candidate.legacy_study_type or "unknown" for candidate in selected)
        ),
        "selected_full_text_chunk_count": sum(
            len(record.get("provenance", {}).get("source_chunk_ids", [])) for record in records
        ),
        "legacy_comparison_audit_counts": legacy_comparison_audit_counts(records),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "notes": [
            "Outputs are candidate evidence for human review.",
            "This POC does not validate identity or mutate SQLite review state.",
            "Full text is read only from existing access_enrichment_artifact payloads.",
        ],
    }


def build_model_comparison_summary(
    *,
    run_id: str,
    task_name: str,
    dry_run: bool,
    provider_models: list[tuple[ProviderName, str]],
    cohort_path: Path,
    database_path: Path,
    records_path: Path,
    raw_responses_path: Path,
    packet_previews_path: Path,
    selected: list[StudyCandidate],
    records: list[dict[str, Any]],
    processed_keys: set[tuple[str, str, str, str]],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    provider_model_counts = Counter(
        f"{record.get('provider')}:{record.get('model')}" for record in records
    )
    provider_model_grounding: dict[str, dict[str, Any]] = {}
    for provider, model in provider_models:
        label = f"{provider}:{model}"
        subset = [
            record
            for record in records
            if record.get("provider") == provider and record.get("model") == model
        ]
        grounding_records = [
            record
            for record in subset
            if isinstance(record.get("span_grounding_audit"), dict)
        ]
        passing = [
            record
            for record in grounding_records
            if record["span_grounding_audit"].get("passes_basic_grounding") is True
        ]
        provider_model_grounding[label] = {
            "record_count": len(subset),
            "grounding_audited_count": len(grounding_records),
            "grounding_pass_count": len(passing),
            "grounding_pass_rate": (
                round(len(passing) / len(grounding_records), 4)
                if grounding_records
                else None
            ),
            "unsupported_evidence_count": sum(
                len(
                    record.get("span_grounding_audit", {}).get(
                        "unsupported_evidence_texts",
                        [],
                    )
                )
                for record in grounding_records
            ),
            "cited_span_count": sum(
                len(record.get("cited_span_ids", []))
                for record in subset
                if isinstance(record.get("cited_span_ids"), list)
            ),
            "records_with_errors": sum(bool(record.get("errors")) for record in subset),
            "needs_human_review_count": sum(
                bool(record.get("needs_human_review")) for record in subset
            ),
            "mean_latency_seconds": mean_latency_seconds(subset),
        }
    return {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "compare_models_on_task_evidence_summary_packets",
        "task": task_name,
        "prompt_version": f"{PROMPT_VERSION}_{task_name}_evidence_summary",
        "dry_run": dry_run,
        "provider_models": [
            {"provider": provider, "model": model} for provider, model in provider_models
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(database_path),
        "records_path": str(records_path),
        "raw_responses_path": str(raw_responses_path),
        "packet_previews_path": str(packet_previews_path),
        "selected_count": len(selected),
        "record_count": len(records),
        "already_processed_key_count": len(processed_keys),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "status_counts": dict(Counter(str(record.get("poc_status")) for record in records)),
        "task_provider_model_counts": dict(provider_model_counts.most_common()),
        "provider_model_grounding": provider_model_grounding,
        "records_needing_human_review": sum(
            bool(record.get("needs_human_review")) for record in records
        ),
        "notes": [
            "Comparison records use the same deterministic evidence spans per document.",
            "Outputs are candidate evidence only, not reviewed knowledge.",
            "This command does not validate identity, download full text, mutate SQLite, "
            "or update review workflow state.",
            preliminary_model_comparison_note(provider_model_grounding, dry_run=dry_run),
        ],
    }


def build_micro_extraction_summary(
    *,
    run_id: str,
    dry_run: bool,
    selected_fields: list[str],
    provider_models: list[tuple[ProviderName, str]],
    cohort_path: Path,
    database_path: Path,
    records_path: Path,
    raw_responses_path: Path,
    prompt_previews_path: Path,
    selected: list[StudyCandidate],
    records: list[dict[str, Any]],
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    provider_field_metrics: dict[str, dict[str, Any]] = {}
    for provider, model in provider_models:
        for field_name in selected_fields:
            label = f"{field_name}:{provider}:{model}"
            subset = [
                record
                for record in records
                if record.get("provider") == provider
                and record.get("model") == model
                and record.get("field_name") == field_name
            ]
            grounding_records = [
                record
                for record in subset
                if isinstance(record.get("span_grounding_audit"), dict)
            ]
            passing = [
                record
                for record in grounding_records
                if record["span_grounding_audit"].get("passes_basic_grounding") is True
            ]
            provider_field_metrics[label] = {
                "record_count": len(subset),
                "grounding_pass_count": len(passing),
                "grounding_pass_rate": (
                    round(len(passing) / len(grounding_records), 4)
                    if grounding_records
                    else None
                ),
                "unsupported_evidence_count": sum(
                    len(
                        record.get("span_grounding_audit", {}).get(
                            "unsupported_evidence_texts",
                            [],
                        )
                    )
                    for record in grounding_records
                ),
                "missing_required_citation_count": sum(
                    bool(
                        record.get("span_grounding_audit", {}).get(
                            "missing_required_citations"
                        )
                    )
                    for record in grounding_records
                ),
                "records_with_errors": sum(bool(record.get("errors")) for record in subset),
                "needs_human_review_count": sum(
                    bool(record.get("needs_human_review")) for record in subset
                ),
                "mean_latency_seconds": mean_latency_seconds(subset),
            }
    return {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "compare_models_on_atomic_micro_extraction",
        "prompt_version": f"{PROMPT_VERSION}_micro",
        "dry_run": dry_run,
        "fields": selected_fields,
        "provider_models": [
            {"provider": provider, "model": model} for provider, model in provider_models
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(database_path),
        "records_path": str(records_path),
        "raw_responses_path": str(raw_responses_path),
        "prompt_previews_path": str(prompt_previews_path),
        "selected_count": len(selected),
        "record_count": len(records),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "status_counts": dict(Counter(str(record.get("poc_status")) for record in records)),
        "provider_field_metrics": provider_field_metrics,
        "notes": [
            "Micro extraction records avoid narrative synthesis and classify one field at a time.",
            "Outputs are candidate evidence only, not reviewed knowledge.",
            "This command does not validate identity, download full text, mutate SQLite, "
            "or update review workflow state.",
        ],
    }


def build_unit_classification_summary(
    *,
    run_id: str,
    dry_run: bool,
    selected_tasks: list[str],
    provider_models: list[tuple[ProviderName, str]],
    cohort_path: Path,
    database_path: Path,
    semantic_index_path: Path | None,
    records_path: Path,
    raw_responses_path: Path,
    prompt_previews_path: Path,
    selected: list[StudyCandidate],
    records: list[dict[str, Any]],
    started_at: datetime,
    completed_at: datetime,
    max_units: int,
) -> dict[str, Any]:
    provider_task_metrics: dict[str, dict[str, Any]] = {}
    for provider, model in provider_models:
        for task_name in selected_tasks:
            label = f"{task_name}:{provider}:{model}"
            subset = [
                record
                for record in records
                if record.get("provider") == provider
                and record.get("model") == model
                and record.get("task_name") == task_name
            ]
            grounding_records = [
                record
                for record in subset
                if isinstance(record.get("unit_grounding_audit"), dict)
            ]
            passing = [
                record
                for record in grounding_records
                if record["unit_grounding_audit"].get("passes_basic_grounding") is True
            ]
            provider_task_metrics[label] = {
                "record_count": len(subset),
                "grounding_pass_count": len(passing),
                "grounding_pass_rate": (
                    round(len(passing) / len(grounding_records), 4)
                    if grounding_records
                    else None
                ),
                "unsupported_evidence_count": sum(
                    len(
                        record.get("unit_grounding_audit", {}).get(
                            "unsupported_evidence_texts",
                            [],
                        )
                    )
                    for record in grounding_records
                ),
                "evidence_text_policy_violation_count": sum(
                    len(
                        record.get("unit_grounding_audit", {}).get(
                            "evidence_text_policy_violations",
                            [],
                        )
                    )
                    for record in grounding_records
                ),
                "missing_required_citation_count": sum(
                    bool(
                        record.get("unit_grounding_audit", {}).get(
                            "missing_required_citations"
                        )
                    )
                    for record in grounding_records
                ),
                "grounding_repair_needed_count": sum(
                    bool(
                        record.get("unit_grounding_audit", {}).get(
                            "grounding_repair_needed"
                        )
                    )
                    for record in grounding_records
                ),
                "records_with_errors": sum(bool(record.get("errors")) for record in subset),
                "needs_human_review_count": sum(
                    bool(record.get("needs_human_review")) for record in subset
                ),
                "mean_latency_seconds": mean_latency_seconds(subset),
                "throughput": throughput_metrics(subset),
            }
    return {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "compare_models_on_unit_index_task_classification",
        "prompt_version": f"{PROMPT_VERSION}_unit_classification",
        "dry_run": dry_run,
        "tasks": selected_tasks,
        "provider_models": [
            {"provider": provider, "model": model} for provider, model in provider_models
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(database_path),
        "semantic_index_path": str(semantic_index_path) if semantic_index_path else None,
        "records_path": str(records_path),
        "raw_responses_path": str(raw_responses_path),
        "prompt_previews_path": str(prompt_previews_path),
        "selected_count": len(selected),
        "record_count": len(records),
        "records_with_errors": sum(bool(record.get("errors")) for record in records),
        "status_counts": dict(Counter(str(record.get("poc_status")) for record in records)),
        "throughput": throughput_metrics(records),
        "provider_task_metrics": provider_task_metrics,
        "retrieval_policy": {
            "max_units": max_units,
            "method": "semantic labels when provided plus deterministic keyword scoring",
        },
        "notes": [
            "Unit classification records use selected literal document units, "
            "not narrative synthesis.",
            "Semantic labels are retrieval hints only and remain candidate metadata.",
            "Outputs are candidate evidence only, not reviewed knowledge.",
            "This command does not validate identity, download full text, mutate SQLite, "
            "or update review workflow state.",
        ],
    }


def build_semantic_paragraph_index_summary(
    *,
    run_id: str,
    dry_run: bool,
    provider_models: list[tuple[ProviderName, str]],
    cohort_path: Path,
    database_path: Path,
    records_path: Path,
    merged_index_path: Path,
    raw_responses_path: Path,
    window_previews_path: Path,
    selected: list[StudyCandidate],
    paragraphs_by_document: dict[str, list[EvidenceParagraph]],
    window_records: list[dict[str, Any]],
    merged_records: list[dict[str, Any]],
    started_at: datetime,
    completed_at: datetime,
    window_paragraphs: int,
    overlap_paragraphs: int,
    max_windows_per_document: int | None,
) -> dict[str, Any]:
    provider_model_metrics: dict[str, dict[str, Any]] = {}
    for provider, model in provider_models:
        label = f"{provider}:{model}"
        subset = [
            record
            for record in window_records
            if record.get("provider") == provider and record.get("model") == model
        ]
        audited = [
            record
            for record in subset
            if isinstance(record.get("paragraph_index_audit"), dict)
        ]
        passing = [
            record
            for record in audited
            if record["paragraph_index_audit"].get("passes_basic_audit") is True
        ]
        provider_model_metrics[label] = {
            "window_record_count": len(subset),
            "records_with_errors": sum(bool(record.get("errors")) for record in subset),
            "audit_pass_count": len(passing),
            "audit_pass_rate": round(len(passing) / len(audited), 4) if audited else None,
            "missing_paragraph_id_count": sum(
                len(record.get("paragraph_index_audit", {}).get("missing_paragraph_ids", []))
                for record in audited
            ),
            "unknown_paragraph_id_count": sum(
                len(record.get("paragraph_index_audit", {}).get("unknown_paragraph_ids", []))
                for record in audited
            ),
            "invalid_label_count": sum(
                len(record.get("paragraph_index_audit", {}).get("invalid_labels", []))
                for record in audited
            ),
            "evidence_term_issue_count": sum(
                len(record.get("paragraph_index_audit", {}).get("evidence_term_issues", []))
                for record in audited
            ),
            "mean_latency_seconds": mean_latency_seconds(subset),
            "throughput": throughput_metrics(subset),
        }
    return {
        "run_id": run_id,
        "source": "llm_study_reclassification_poc",
        "method": "compare_models_on_semantic_paragraph_index",
        "prompt_version": f"{PROMPT_VERSION}_semantic_paragraph_index",
        "dry_run": dry_run,
        "provider_models": [
            {"provider": provider, "model": model} for provider, model in provider_models
        ],
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "cohort_path": str(cohort_path),
        "database_path": str(database_path),
        "records_path": str(records_path),
        "merged_index_path": str(merged_index_path),
        "raw_responses_path": str(raw_responses_path),
        "window_previews_path": str(window_previews_path),
        "selected_count": len(selected),
        "paragraph_counts": {
            document_id: len(paragraphs)
            for document_id, paragraphs in paragraphs_by_document.items()
        },
        "unit_type_counts": {
            document_id: dict(
                Counter(paragraph.unit_type for paragraph in paragraphs).most_common()
            )
            for document_id, paragraphs in paragraphs_by_document.items()
        },
        "window_record_count": len(window_records),
        "merged_record_count": len(merged_records),
        "records_with_errors": sum(bool(record.get("errors")) for record in window_records),
        "status_counts": dict(
            Counter(str(record.get("poc_status")) for record in window_records)
        ),
        "throughput": throughput_metrics(window_records),
        "provider_model_metrics": provider_model_metrics,
        "window_policy": {
            "window_paragraphs": window_paragraphs,
            "overlap_paragraphs": overlap_paragraphs,
            "max_windows_per_document": max_windows_per_document,
        },
        "notes": [
            "Semantic document-unit labels are candidate retrieval metadata, not reviewed truth.",
            "Unit text is literal cleaned source text, not paraphrased synthesis.",
            "Tables and figure captions are mapped as text units for future enrichment; "
            "this POC does not interpret images or charts visually.",
            "Window size is an empirical calibration parameter monitored through audit "
            "scores, downstream extraction quality, latency, and review burden.",
            "This command does not validate identity, download full text, mutate SQLite, "
            "or update review workflow state.",
        ],
    }


def mean_latency_seconds(records: list[dict[str, Any]]) -> float | None:
    latencies = [
        float(record["provenance"]["latency_seconds"])
        for record in records
        if isinstance(record.get("provenance"), dict)
        and record["provenance"].get("latency_seconds") is not None
    ]
    if not latencies:
        return None
    return round(sum(latencies) / len(latencies), 3)


def throughput_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize prompt/output size and latency from record provenance."""
    provenances = [
        record["provenance"]
        for record in records
        if isinstance(record.get("provenance"), dict)
    ]
    prompt_chars = [
        int(provenance["input_prompt_chars"])
        for provenance in provenances
        if provenance.get("input_prompt_chars") is not None
    ]
    input_tokens = [
        int(provenance["rough_input_token_estimate"])
        for provenance in provenances
        if provenance.get("rough_input_token_estimate") is not None
    ]
    output_chars = [
        int(provenance["output_chars"])
        for provenance in provenances
        if provenance.get("output_chars") is not None
    ]
    output_tokens = [
        int(provenance["rough_output_token_estimate"])
        for provenance in provenances
        if provenance.get("rough_output_token_estimate") is not None
    ]
    latencies = [
        float(provenance["latency_seconds"])
        for provenance in provenances
        if provenance.get("latency_seconds") is not None
    ]
    return {
        "record_count": len(records),
        "prompt_record_count": len(prompt_chars),
        "total_prompt_chars": sum(prompt_chars),
        "mean_prompt_chars": rounded_mean(prompt_chars),
        "total_rough_input_tokens": sum(input_tokens),
        "mean_rough_input_tokens": rounded_mean(input_tokens),
        "output_record_count": len(output_chars),
        "total_output_chars": sum(output_chars),
        "mean_output_chars": rounded_mean(output_chars),
        "total_rough_output_tokens": sum(output_tokens),
        "mean_rough_output_tokens": rounded_mean(output_tokens),
        "latency_record_count": len(latencies),
        "total_latency_seconds": round(sum(latencies), 3),
        "mean_latency_seconds": rounded_mean(latencies),
    }


def rounded_mean(values: list[int] | list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def preliminary_model_comparison_note(
    provider_model_grounding: dict[str, dict[str, Any]],
    *,
    dry_run: bool,
) -> str:
    if dry_run:
        return "Dry run prepared prompts and spans; no model quality interpretation is available."
    if not provider_model_grounding:
        return "No comparison records were generated."
    ranked = sorted(
        provider_model_grounding.items(),
        key=lambda item: (
            item[1].get("grounding_pass_rate") is None,
            -(item[1].get("grounding_pass_rate") or 0),
            item[1].get("unsupported_evidence_count") or 0,
        ),
    )
    best_label, best_metrics = ranked[0]
    return (
        f"Preliminary audit leader by basic grounding is {best_label} with "
        f"pass_rate={best_metrics.get('grounding_pass_rate')}; human review is still required."
    )


def legacy_comparison_audit_counts(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counters: dict[str, Counter[str]] = {
        "study_type_normalized_match": Counter(),
        "result_normalized_match": Counter(),
        "sample_size_match": Counter(),
    }
    for record in records:
        audit = record.get("legacy_comparison_audit")
        if not isinstance(audit, dict):
            continue
        for field, counter in counters.items():
            counter[str(audit.get(field))] += 1
    return {field: dict(counter) for field, counter in counters.items()}


def write_manifest(
    *,
    paths: RunPaths,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    cohort_path: Path,
    summary: dict[str, Any],
) -> None:
    output_artifacts = [
        OutputArtifact(
            path=str(paths.records_path),
            record_count=summary["selected_count"],
            sha256=file_sha256(paths.records_path),
        ),
        OutputArtifact(
            path=str(paths.summary_path),
            record_count=1,
            sha256=file_sha256(paths.summary_path),
        ),
    ]
    if paths.prompt_preview_path.exists():
        output_artifacts.append(
            OutputArtifact(
                path=str(paths.prompt_preview_path),
                record_count=count_jsonl(paths.prompt_preview_path),
                sha256=file_sha256(paths.prompt_preview_path),
            )
        )
    if paths.raw_responses_path.exists():
        output_artifacts.append(
            OutputArtifact(
                path=str(paths.raw_responses_path),
                record_count=count_jsonl(paths.raw_responses_path),
                sha256=file_sha256(paths.raw_responses_path),
            )
        )
    manifest = RunManifest(
        run_id=run_id,
        job_type="llm_study_reclassification_poc",
        source="groq",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        software_version="0.1.0",
        input_artifacts=[
            InputArtifact(
                path=str(cohort_path),
                sha256=file_sha256(cohort_path),
                size_bytes=cohort_path.stat().st_size,
            )
        ],
        output_artifacts=output_artifacts,
        counts={
            "selected_records": summary["selected_count"],
            "records_with_errors": summary["records_with_errors"],
        },
        notes=summary["notes"],
    )
    write_json(paths.manifest_path, manifest.model_dump(mode="json"))


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def count_jsonl(path: Path) -> int:
    with path.open(encoding="utf-8") as file:
        return sum(1 for line in file if line.strip())


def clean_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", without_tags).strip()


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0] + "\n[TRUNCATED]"


def print_summary(summary: dict[str, Any], paths: RunPaths) -> None:
    table = Table(title="LLM study reclassification POC")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("already_processed", str(summary["already_processed_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for source, count in summary["evidence_source_counts"].items():
        table.add_row(f"evidence_source:{source}", str(count))
    console.print(table)
    console.print(
        {
            "records": str(paths.records_path),
            "summary": str(paths.summary_path),
            "manifest": str(paths.manifest_path),
            "prompt_previews": str(paths.prompt_preview_path),
            "raw_responses": str(paths.raw_responses_path),
        }
    )


def print_evidence_index_summary(
    summary: dict[str, Any],
    records_path: Path,
    summary_path: Path,
) -> None:
    table = Table(title="LLM study evidence index")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("selected_chunks", str(summary["selected_chunk_count"]))
    for strategy, count in summary["context_strategy_counts"].items():
        table.add_row(f"context_strategy:{strategy}", str(count))
    console.print(table)
    console.print({"records": str(records_path), "summary": str(summary_path)})


def print_task_packet_summary(
    summary: dict[str, Any],
    records_path: Path,
    summary_path: Path,
) -> None:
    table = Table(title="LLM study task packets")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("candidates", str(summary["candidate_count"]))
    table.add_row("task_packets", str(summary["task_packet_count"]))
    for task_name, count in summary["task_counts"].items():
        table.add_row(f"task:{task_name}", str(count))
    console.print(table)
    console.print({"records": str(records_path), "summary": str(summary_path)})


def print_task_run_summary(
    summary: dict[str, Any],
    records_path: Path,
    raw_responses_path: Path,
) -> None:
    table = Table(title="LLM study task run")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for action, count in summary["recommended_action_counts"].items():
        table.add_row(f"recommended_action:{action}", str(count))
    console.print(table)
    console.print({"records": str(records_path), "raw_responses": str(raw_responses_path)})


def print_summary_packet_summary(
    summary: dict[str, Any],
    records_path: Path,
    summary_path: Path,
) -> None:
    table = Table(title="LLM study evidence summary packets")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("candidates", str(summary["candidate_count"]))
    table.add_row("summary_packets", str(summary["summary_packet_count"]))
    table.add_row("spans", str(summary["span_count"]))
    for task_name, count in summary["task_counts"].items():
        table.add_row(f"task:{task_name}", str(count))
    console.print(table)
    console.print({"records": str(records_path), "summary": str(summary_path)})


def print_summary_run_summary(
    summary: dict[str, Any],
    records_path: Path,
    raw_responses_path: Path,
) -> None:
    table = Table(title="LLM study evidence summary run")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    table.add_row("cited_spans", str(summary["cited_span_count"]))
    console.print(table)
    console.print({"records": str(records_path), "raw_responses": str(raw_responses_path)})


def print_model_comparison_summary(
    summary: dict[str, Any],
    records_path: Path,
    raw_responses_path: Path,
) -> None:
    table = Table(title="LLM study model comparison")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("records", str(summary["record_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for label, metrics in summary["provider_model_grounding"].items():
        table.add_row(
            f"grounding_pass_rate:{label}",
            str(metrics["grounding_pass_rate"]),
        )
    console.print(table)
    console.print({"records": str(records_path), "raw_responses": str(raw_responses_path)})


def print_micro_extraction_summary(
    summary: dict[str, Any],
    records_path: Path,
    raw_responses_path: Path,
) -> None:
    table = Table(title="LLM study micro extraction")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("records", str(summary["record_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for label, metrics in summary["provider_field_metrics"].items():
        table.add_row(
            f"grounding_pass_rate:{label}",
            str(metrics["grounding_pass_rate"]),
        )
    console.print(table)
    console.print({"records": str(records_path), "raw_responses": str(raw_responses_path)})


def print_unit_classification_summary(
    summary: dict[str, Any],
    records_path: Path,
    raw_responses_path: Path,
) -> None:
    table = Table(title="LLM document-unit classification")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("records", str(summary["record_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for label, metrics in summary["provider_task_metrics"].items():
        table.add_row(
            f"grounding_pass_rate:{label}",
            str(metrics["grounding_pass_rate"]),
        )
    console.print(table)
    console.print({"records": str(records_path), "raw_responses": str(raw_responses_path)})


def print_semantic_paragraph_index_summary(
    summary: dict[str, Any],
    records_path: Path,
    merged_index_path: Path,
) -> None:
    table = Table(title="LLM semantic paragraph index")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("selected", str(summary["selected_count"]))
    table.add_row("window_records", str(summary["window_record_count"]))
    table.add_row("records_with_errors", str(summary["records_with_errors"]))
    for label, metrics in summary["provider_model_metrics"].items():
        table.add_row(f"audit_pass_rate:{label}", str(metrics["audit_pass_rate"]))
    console.print(table)
    console.print({"records": str(records_path), "merged_index": str(merged_index_path)})


if __name__ == "__main__":
    app()
