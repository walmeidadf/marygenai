from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marygenai.storage import LocalStorage

PROFILE_VERSION = "retrieval_field_profile.v1"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def latest_path(data_dir: Path, pattern: str) -> Path:
    paths = sorted(data_dir.glob(pattern))
    if not paths:
        msg = f"No files matched {data_dir / pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def count_percent(count: int, total: int) -> dict[str, int | float]:
    return {
        "count": count,
        "total": total,
        "percent": round((count / total) * 100, 2) if total else 0.0,
    }


def corpus_field_coverage(records: list[dict[str, Any]]) -> dict[str, dict[str, int | float]]:
    fields = (
        "publication_year",
        "medical_condition_labels",
        "organ_system_labels",
        "cannabinoid_labels",
        "legacy_study_type",
        "legacy_result",
        "source_text_path",
    )
    return {
        field: count_percent(sum(bool(record.get(field)) for record in records), len(records))
        for field in fields
    }


def legacy_context_by_document_id(
    contexts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for context in contexts:
        for match in context.get("document_matches") or []:
            document_id = match.get("document_id")
            if document_id:
                index.setdefault(str(document_id), context)
    return index


def has_list_field(context: dict[str, Any], field: str) -> bool:
    return bool((context.get("list_fields") or {}).get(field))


def legacy_reference_coverage(
    records: list[dict[str, Any]],
    *,
    contexts_by_document_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matched = [
        (record, contexts_by_document_id[record["document_id"]])
        for record in records
        if record["document_id"] in contexts_by_document_id
    ]
    matched_total = len(matched)
    fields = {
        "publication_year": lambda context: bool(context.get("publication_year")),
        "type_of_study": lambda context: bool(context.get("type_of_study")),
        "study_result": lambda context: bool(context.get("study_result")),
        "study_sample_size": lambda context: bool(context.get("study_sample_size")),
        "key_findings": lambda context: bool(context.get("key_findings")),
        "study_locations": lambda context: has_list_field(context, "Study Location(s)"),
        "cannabinoids_studied": lambda context: has_list_field(
            context, "Cannabinoids Studied"
        ),
        "route_of_administration": lambda context: has_list_field(
            context, "Route of Administration"
        ),
        "adverse_events": lambda context: has_list_field(context, "Adverse Events"),
    }
    coverage = {
        field: count_percent(
            sum(predicate(context) for _, context in matched),
            matched_total,
        )
        for field, predicate in fields.items()
    }
    year_pairs = [
        (record.get("publication_year"), context.get("publication_year"))
        for record, context in matched
        if record.get("publication_year") and context.get("publication_year")
    ]
    year_disagreements = [
        {
            "document_id": record["document_id"],
            "corpus_publication_year": record.get("publication_year"),
            "legacy_publication_year": context.get("publication_year"),
            "title": record.get("primary_title"),
        }
        for record, context in matched
        if record.get("publication_year")
        and context.get("publication_year")
        and record.get("publication_year") != context.get("publication_year")
    ]
    return {
        "matched_records": count_percent(matched_total, len(records)),
        "field_coverage_among_matched": coverage,
        "publication_year_comparison": {
            "comparable_records": len(year_pairs),
            "exact_matches": sum(
                corpus_year == legacy_year for corpus_year, legacy_year in year_pairs
            ),
            "disagreements": len(year_disagreements),
            "disagreement_records": year_disagreements,
        },
    }


def source_strategy_group(record: dict[str, Any]) -> str:
    strategy = str(record.get("source_strategy") or "unknown")
    split = str(record.get("classification_dataset_split") or "unknown")
    return f"{split}:{strategy}"


def cannabinoid_focus_group(record: dict[str, Any]) -> str:
    if int(record.get("cannabinoid_term_hit_count") or 0) >= 1:
        return "source_text_signal"
    if record.get("cannabinoid_labels"):
        return "metadata_label_only"
    return "no_signal"


def round_robin_sample(
    records: list[dict[str, Any]],
    *,
    sample_size: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in sorted(records, key=lambda item: str(item["document_id"])):
        grouped[source_strategy_group(record)].append(record)
    selected: list[dict[str, Any]] = []
    group_names = sorted(grouped)
    while len(selected) < sample_size:
        added = False
        for group_name in group_names:
            group = grouped[group_name]
            if not group:
                continue
            selected.append(group.pop(0))
            added = True
            if len(selected) >= sample_size:
                break
        if not added:
            break
    return selected


def patient_oriented_sample(
    records: list[dict[str, Any]],
    *,
    sample_size: int,
) -> list[dict[str, Any]]:
    direct_records = [
        record for record in records if cannabinoid_focus_group(record) == "source_text_signal"
    ]
    contrast_records = [
        record for record in records if cannabinoid_focus_group(record) != "source_text_signal"
    ]
    contrast_size = min(len(contrast_records), max(1, sample_size // 4))
    direct_size = min(len(direct_records), sample_size - contrast_size)
    if direct_size + contrast_size < sample_size:
        contrast_size = min(len(contrast_records), sample_size - direct_size)
    return [
        *round_robin_sample(direct_records, sample_size=direct_size),
        *round_robin_sample(contrast_records, sample_size=contrast_size),
    ]


def validation_sample_record(
    record: dict[str, Any],
    *,
    context: dict[str, Any] | None,
    run_id: str,
) -> dict[str, Any]:
    list_fields = (context or {}).get("list_fields") or {}
    return {
        "sample_id": f"retrieval_field_sample:{run_id}:{record['document_id']}",
        "sample_run_id": run_id,
        "document_id": record["document_id"],
        "primary_title": record.get("primary_title"),
        "publication_year": record.get("publication_year"),
        "canonical_url": record.get("canonical_url"),
        "source_text_path": record.get("source_text_path"),
        "source_strategy": record.get("source_strategy"),
        "classification_dataset_split": record.get("classification_dataset_split"),
        "cannabinoid_focus_group": cannabinoid_focus_group(record),
        "corpus_metadata_candidates": {
            "medical_condition_labels": record.get("medical_condition_labels") or [],
            "organ_system_labels": record.get("organ_system_labels") or [],
            "cannabinoid_labels": record.get("cannabinoid_labels") or [],
            "legacy_study_type": record.get("legacy_study_type"),
        },
        "legacy_reference_guardrails": {
            "available": context is not None,
            "context_id": (context or {}).get("context_id"),
            "publication_year": (context or {}).get("publication_year"),
            "type_of_study": (context or {}).get("type_of_study"),
            "study_result": (context or {}).get("study_result"),
            "study_sample_size": (context or {}).get("study_sample_size"),
            "study_locations": list_fields.get("Study Location(s)") or [],
            "cannabinoids_studied": list_fields.get("Cannabinoids Studied") or [],
            "route_of_administration": list_fields.get("Route of Administration") or [],
            "key_findings": (context or {}).get("key_findings") or [],
        },
        "provenance": {
            "profile_version": PROFILE_VERSION,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "legacy_is_guardrail_not_ground_truth": True,
            "review_boundary": "validation_sample_not_reviewed_knowledge",
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def profile_retrieval_fields(
    *,
    storage: LocalStorage,
    corpus_path: Path | None = None,
    legacy_context_path: Path | None = None,
    sample_size: int = 12,
    run_id: str | None = None,
) -> dict[str, Any]:
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    resolved_corpus_path = corpus_path or latest_path(
        storage.root,
        "normalized/classification_corpus/*_classification_corpus_records.jsonl",
    )
    resolved_legacy_path = legacy_context_path or latest_path(
        storage.root,
        "normalized/legacy_english_context/*_legacy_english_context_records.jsonl",
    )
    corpus_records = read_jsonl(resolved_corpus_path)
    legacy_contexts = read_jsonl(resolved_legacy_path)
    contexts_by_document_id = legacy_context_by_document_id(legacy_contexts)
    source_ready_records = [record for record in corpus_records if record.get("source_ready")]
    strict_records = [
        record
        for record in corpus_records
        if record.get("classification_dataset_split") == "strict_classification_ready"
    ]
    broader_records = [
        record
        for record in corpus_records
        if record.get("classification_dataset_split") == "broader_source_ready"
    ]
    selected = patient_oriented_sample(source_ready_records, sample_size=sample_size)
    sample_rows = [
        validation_sample_record(
            record,
            context=contexts_by_document_id.get(record["document_id"]),
            run_id=resolved_run_id,
        )
        for record in selected
    ]
    output_dir = storage.path("normalized/classification_evaluations")
    sample_path = write_jsonl(
        output_dir / f"{resolved_run_id}_retrieval_field_validation_sample.jsonl",
        sample_rows,
    )
    report = {
        "profile_version": PROFILE_VERSION,
        "run_id": resolved_run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "corpus_path": str(resolved_corpus_path),
            "legacy_context_path": str(resolved_legacy_path),
        },
        "execution_universe": {
            "downloaded_canonical_corpus_records": len(corpus_records),
            "source_ready_records": len(source_ready_records),
            "strict_classification_ready_records": len(strict_records),
            "broader_source_ready_records": len(broader_records),
            "not_source_ready_records": len(corpus_records) - len(source_ready_records),
            "semantics": (
                "Classification scale and provider cost are based on the downloaded "
                "source-ready corpus, not the legacy reference size."
            ),
        },
        "corpus_field_coverage": corpus_field_coverage(corpus_records),
        "source_ready_field_coverage": corpus_field_coverage(source_ready_records),
        "legacy_reference": {
            "records": len(legacy_contexts),
            "semantics": (
                "Normative bootstrap and guardrail; not the classification queue or "
                "automatic ground truth."
            ),
            "corpus_alignment": legacy_reference_coverage(
                corpus_records,
                contexts_by_document_id=contexts_by_document_id,
            ),
            "source_ready_alignment": legacy_reference_coverage(
                source_ready_records,
                contexts_by_document_id=contexts_by_document_id,
            ),
        },
        "validation_sample": {
            "requested_size": sample_size,
            "selected_size": len(sample_rows),
            "path": str(sample_path),
            "source_strategy_split_counts": dict(
                Counter(source_strategy_group(record) for record in selected)
            ),
            "cannabinoid_focus_group_counts": dict(
                Counter(cannabinoid_focus_group(record) for record in selected)
            ),
        },
        "notes": [
            "No LLM was called.",
            "No SQLite or reviewed knowledge was mutated.",
            "Legacy fields are comparison guardrails and may disagree with source evidence.",
            "The sample is a reproducible worklist for metadata, parser, and later LLM tests.",
        ],
    }
    report_path = storage.write_json(
        Path("normalized/classification_evaluations")
        / f"{resolved_run_id}_retrieval_field_profile.json",
        report,
    )
    return {
        "run_id": resolved_run_id,
        "report_path": str(report_path),
        "sample_path": str(sample_path),
        "counts": report["execution_universe"],
    }
