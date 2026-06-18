from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from marygenai.classification.models import StudyDesignCategory, StudyDesignSubtype
from marygenai.classification.pipeline import (
    latest_path,
    legacy_english_context_for_record,
    load_legacy_english_context_index,
    new_run_id,
    normalize_lookup_text,
    read_jsonl,
    resolve_data_path,
)
from marygenai.classification_corpus.models import ClassificationCorpusRecord
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

BENCHMARK_SCHEMA_VERSION = "study_design_validation_benchmark_candidate.v1"


class StudyDesignTitleRule(NamedTuple):
    name: str
    phrases: tuple[str, ...]
    category: StudyDesignCategory
    subtype: StudyDesignSubtype


TITLE_RULES = (
    StudyDesignTitleRule(
        "scoping_review_title",
        ("scoping review",),
        "clinical_meta_analysis",
        "scoping_review",
    ),
    StudyDesignTitleRule(
        "meta_analysis_title",
        ("meta analysis",),
        "meta_analysis",
        "systematic_review",
    ),
    StudyDesignTitleRule(
        "systematic_review_title",
        ("systematic review",),
        "clinical_meta_analysis",
        "systematic_review",
    ),
    StudyDesignTitleRule(
        "case_report_or_series_title",
        ("case report", "case series"),
        "other",
        "case_report_or_series",
    ),
    StudyDesignTitleRule(
        "survey_title",
        ("survey", "questionnaire"),
        "other",
        "survey",
    ),
    StudyDesignTitleRule(
        "animal_study_title",
        (
            "animal model",
            "mouse model",
            "rat model",
            "in mice",
            "in rats",
            "canine",
        ),
        "animal_study",
        "other",
    ),
    StudyDesignTitleRule(
        "laboratory_study_title",
        ("in vitro", "cell line", "cellular model"),
        "laboratory_study",
        "other",
    ),
    StudyDesignTitleRule(
        "double_blind_trial_title",
        ("double blind", "double-blind"),
        "double_blind_clinical_trial",
        "other",
    ),
    StudyDesignTitleRule(
        "clinical_trial_title",
        (
            "clinical trial",
            "randomized trial",
            "randomised trial",
            "randomized controlled trial",
            "randomised controlled trial",
        ),
        "clinical_trial",
        "other",
    ),
    StudyDesignTitleRule(
        "observational_study_title",
        (
            "observational study",
            "cohort study",
            "prospective study",
            "retrospective study",
            "longitudinal study",
        ),
        "other",
        "observational_study",
    ),
    StudyDesignTitleRule(
        "pilot_study_title",
        ("pilot study", "pilot trial"),
        "other",
        "pilot_study",
    ),
)


class StudyDesignBenchmarkCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    benchmark_candidate_id: str
    benchmark_run_id: str
    schema_version: Literal["study_design_validation_benchmark_candidate.v1"] = (
        BENCHMARK_SCHEMA_VERSION
    )
    document_id: str
    primary_title: str
    publication_year: int | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    canonical_url: str | None = None
    source_text_path: str
    source_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_strategy: str | None = None
    classification_dataset_split: str

    candidate_study_design_category: StudyDesignCategory
    candidate_study_design_subtype: StudyDesignSubtype
    candidate_evidence_text: str
    candidate_evidence_scope: Literal["title"] = "title"
    selection_rule: str
    selection_basis: Literal["explicit_title_phrase"] = "explicit_title_phrase"
    matched_title_phrase: str

    legacy_english_type_of_study: str | None = None
    legacy_context_id: str | None = None
    exact_legacy_category_match: bool | None = None
    legacy_comparison: Literal[
        "exact_match",
        "compatible_refinement",
        "disagreement",
        "no_reference",
    ]

    requires_human_review: Literal[True] = True
    review_state: Literal["needs_review"] = "needs_review"
    reviewer: str | None = None
    reviewed_study_design_category: StudyDesignCategory | None = None
    reviewed_study_design_subtype: StudyDesignSubtype | None = None
    reviewed_at: datetime | None = None
    review_rationale: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


def title_rule_for_record(
    record: ClassificationCorpusRecord,
) -> StudyDesignTitleRule | None:
    title = normalize_lookup_text(record.primary_title)
    if not title:
        return None
    for rule in TITLE_RULES:
        if not any(
            f" {normalize_lookup_text(phrase)} " in f" {title} "
            for phrase in rule.phrases
        ):
            continue
        subtype = rule.subtype
        if (
            rule.name in {"double_blind_trial_title", "clinical_trial_title"}
            and " pilot " in f" {title} "
        ):
            subtype = "pilot_study"
        return StudyDesignTitleRule(rule.name, rule.phrases, rule.category, subtype)
    return None


def stable_candidate_order(document_id: str) -> str:
    return hashlib.sha256(document_id.encode()).hexdigest()


def matched_title_phrase(title: str, rule: StudyDesignTitleRule) -> str:
    normalized_title = f" {normalize_lookup_text(title)} "
    for phrase in rule.phrases:
        if f" {normalize_lookup_text(phrase)} " in normalized_title:
            return phrase
    msg = f"Rule {rule.name} does not match the candidate title."
    raise ValueError(msg)


def legacy_category(type_of_study: str | None) -> StudyDesignCategory | None:
    mapping: dict[str, StudyDesignCategory] = {
        "Meta-analysis": "meta_analysis",
        "Clinical Meta-analysis": "clinical_meta_analysis",
        "Clinical Trial": "clinical_trial",
        "Double Blind Clinical Trial": "double_blind_clinical_trial",
        "Animal Study": "animal_study",
        "Laboratory Study": "laboratory_study",
    }
    return mapping.get(type_of_study or "")


def compare_legacy_category(
    candidate: StudyDesignCategory,
    reference: StudyDesignCategory | None,
) -> Literal[
    "exact_match",
    "compatible_refinement",
    "disagreement",
    "no_reference",
]:
    if reference is None:
        return "no_reference"
    if candidate == reference:
        return "exact_match"
    if {candidate, reference} == {"meta_analysis", "clinical_meta_analysis"}:
        return "compatible_refinement"
    return "disagreement"


def build_benchmark_candidate(
    *,
    record: ClassificationCorpusRecord,
    rule: StudyDesignTitleRule,
    run_id: str,
    data_dir: Path,
    legacy_context: dict[str, Any] | None,
) -> StudyDesignBenchmarkCandidate:
    source_path = resolve_data_path(data_dir, record.source_text_path)
    if source_path is None or not source_path.is_file():
        msg = f"Source text is unavailable for {record.document_id}."
        raise FileNotFoundError(msg)
    title = (record.primary_title or "").strip()
    legacy_type = (legacy_context or {}).get("type_of_study")
    expected_legacy_category = legacy_category(legacy_type)
    legacy_comparison = compare_legacy_category(rule.category, expected_legacy_category)
    return StudyDesignBenchmarkCandidate(
        benchmark_candidate_id=f"benchmark:{run_id}:{record.document_id}",
        benchmark_run_id=run_id,
        document_id=record.document_id,
        primary_title=title,
        publication_year=record.publication_year,
        pmid=record.pmid,
        pmcid=record.pmcid,
        doi=record.doi,
        canonical_url=record.canonical_url,
        source_text_path=str(source_path),
        source_text_sha256=file_sha256(source_path),
        source_strategy=record.source_strategy,
        classification_dataset_split=record.classification_dataset_split,
        candidate_study_design_category=rule.category,
        candidate_study_design_subtype=rule.subtype,
        candidate_evidence_text=title,
        selection_rule=rule.name,
        matched_title_phrase=matched_title_phrase(title, rule),
        legacy_english_type_of_study=legacy_type,
        legacy_context_id=(legacy_context or {}).get("context_id"),
        exact_legacy_category_match=(
            expected_legacy_category == rule.category
            if expected_legacy_category is not None
            else None
        ),
        legacy_comparison=legacy_comparison,
        provenance={
            "method": "study_design_title_rule_candidate_selection",
            "corpus_record_provenance": record.provenance,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "candidate_not_reviewed_ground_truth": True,
            "review_boundary": "benchmark_candidate_needs_human_review",
        },
    )


def round_robin_sample(
    candidates_by_rule: dict[str, list[StudyDesignBenchmarkCandidate]],
    *,
    sample_size: int,
) -> list[StudyDesignBenchmarkCandidate]:
    for candidates in candidates_by_rule.values():
        candidates.sort(key=lambda item: stable_candidate_order(item.document_id))
    selected: list[StudyDesignBenchmarkCandidate] = []
    rule_names = sorted(candidates_by_rule)
    index = 0
    while len(selected) < sample_size:
        added = False
        for rule_name in rule_names:
            candidates = candidates_by_rule[rule_name]
            if index < len(candidates):
                selected.append(candidates[index])
                added = True
                if len(selected) >= sample_size:
                    break
        if not added:
            break
        index += 1
    return selected


def build_study_design_validation_benchmark(
    *,
    storage: LocalStorage,
    input_path: Path | None = None,
    sample_size: int = 48,
    run_id: str | None = None,
) -> dict[str, Any]:
    resolved_run_id = run_id or new_run_id()
    resolved_input_path = input_path or latest_path(
        storage.root,
        "normalized/classification_corpus/*_classification_corpus_records.jsonl",
    )
    legacy_indexes = load_legacy_english_context_index(storage.root)
    candidates_by_rule: dict[str, list[StudyDesignBenchmarkCandidate]] = defaultdict(list)
    rejected_counts: Counter[str] = Counter()
    for row in read_jsonl(resolved_input_path):
        record = ClassificationCorpusRecord.model_validate(row)
        if not record.source_ready:
            rejected_counts["not_source_ready"] += 1
            continue
        rule = title_rule_for_record(record)
        if rule is None:
            rejected_counts["no_explicit_title_rule"] += 1
            continue
        legacy_context = legacy_english_context_for_record(record, legacy_indexes)
        try:
            candidate = build_benchmark_candidate(
                record=record,
                rule=rule,
                run_id=resolved_run_id,
                data_dir=storage.root,
                legacy_context=legacy_context,
            )
        except FileNotFoundError:
            rejected_counts["source_text_unavailable"] += 1
            continue
        candidates_by_rule[rule.name].append(candidate)

    selected = round_robin_sample(candidates_by_rule, sample_size=sample_size)
    output_dir = Path("normalized/classification_evaluations")
    records_path = storage.write_jsonl(
        output_dir / f"{resolved_run_id}_study_design_benchmark_candidates.jsonl",
        selected,
    )
    summary = {
        "run_id": resolved_run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "input_path": str(resolved_input_path),
        "records_path": str(records_path),
        "counts": {
            "candidate_pool": sum(len(items) for items in candidates_by_rule.values()),
            "selected_candidates": len(selected),
            "selected_legacy_disagreements": sum(
                candidate.legacy_comparison == "disagreement" for candidate in selected
            ),
            "selected_legacy_compatible_refinements": sum(
                candidate.legacy_comparison == "compatible_refinement"
                for candidate in selected
            ),
            "selected_without_legacy_reference": sum(
                candidate.legacy_comparison == "no_reference" for candidate in selected
            ),
        },
        "selected_rule_counts": dict(Counter(item.selection_rule for item in selected)),
        "candidate_pool_rule_counts": {
            rule_name: len(items) for rule_name, items in sorted(candidates_by_rule.items())
        },
        "rejected_counts": dict(rejected_counts),
        "notes": [
            "Candidates are selected from explicit title phrases and require human review.",
            "This artifact is not a source-reviewed benchmark or reviewed knowledge.",
            "The command does not call an LLM or mutate SQLite.",
        ],
    }
    summary_path = storage.write_json(
        output_dir / f"{resolved_run_id}_study_design_benchmark_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "records_path": str(records_path),
        "summary_path": str(summary_path),
        "counts": summary["counts"],
        "selected_rule_counts": summary["selected_rule_counts"],
    }
