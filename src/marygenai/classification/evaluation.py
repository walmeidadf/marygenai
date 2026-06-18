from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from marygenai.classification.pipeline import (
    clean_doi,
    latest_legacy_english_context_path,
    load_legacy_english_context_index,
    normalize_lookup_text,
)
from marygenai.storage import LocalStorage

LEGACY_STUDY_DESIGN_MAP = {
    "Meta-analysis": "meta_analysis",
    "Clinical Meta-analysis": "clinical_meta_analysis",
    "Clinical Trial": "clinical_trial",
    "Double Blind Clinical Trial": "double_blind_clinical_trial",
    "Animal Study": "animal_study",
    "Laboratory Study": "laboratory_study",
}
CANONICAL_UNCERTAINTY_FIELDS = {
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
SCHEMA_V2_OUTCOME_DOMAINS = {
    "efficacy",
    "safety",
    "adverse_events",
    "biomarker",
    "mechanism",
    "pharmacokinetics",
    "public_health",
    "use_pattern",
}
CURRENT_OUTCOME_DOMAINS = SCHEMA_V2_OUTCOME_DOMAINS | {"cognition"}
EVIDENCE_NGRAM_GROUNDING_THRESHOLD = 0.8
EVIDENCE_NGRAM_MIN_TOKENS = 6


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def latest_candidate_records_path(data_dir: Path) -> Path:
    paths = sorted(
        data_dir.glob("normalized/classification_runs/*_candidate_classification_records.jsonl")
    )
    provider_paths = [
        path
        for path in paths
        if sibling_run_path(
            path,
            run_id_from_records_path(path),
            "candidate_classification_raw_responses.jsonl",
        ).exists()
    ]
    if not provider_paths:
        msg = "No provider-backed candidate classification records were found."
        raise FileNotFoundError(msg)
    return provider_paths[-1]


def run_id_from_records_path(path: Path) -> str:
    suffix = "_candidate_classification_records.jsonl"
    if not path.name.endswith(suffix):
        msg = f"Classification records path must end with {suffix}: {path}"
        raise ValueError(msg)
    return path.name.removesuffix(suffix)


def sibling_run_path(records_path: Path, run_id: str, suffix: str) -> Path:
    return records_path.with_name(f"{run_id}_{suffix}")


def resolve_run_input_path(
    *,
    data_dir: Path,
    summary: dict[str, Any],
    input_path: Path | None,
) -> Path:
    if input_path is not None:
        return input_path
    stored_path = Path(str(summary["input_path"]))
    if stored_path.is_absolute():
        return stored_path
    if stored_path.parts and stored_path.parts[0] == data_dir.name:
        return data_dir.parent / stored_path
    return data_dir / stored_path


def corpus_row(sample_row: dict[str, Any]) -> dict[str, Any]:
    return sample_row.get("corpus_record") or sample_row


def find_legacy_context(
    record: dict[str, Any],
    indexes: dict[str, dict[str, dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str | None]:
    document_id = record.get("document_id")
    if document_id and document_id in indexes["document_id"]:
        return indexes["document_id"][document_id], "document_id"
    for field in ("pmid", "pmcid"):
        value = record.get(field)
        if value and str(value) in indexes[field]:
            return indexes[field][str(value)], field
    doi = clean_doi(record.get("doi"))
    if doi and doi in indexes["doi"]:
        return indexes["doi"][doi], "doi"
    title_year = (
        f"{normalize_lookup_text(record.get('primary_title'))}|{record.get('publication_year')}"
    )
    context = indexes["title_year"].get(title_year)
    return (context, "title_year") if context else (None, None)


def normalized_contains(source_text: str, evidence_text: str) -> bool:
    return normalize_lookup_text(evidence_text) in normalize_lookup_text(source_text)


def token_ngram_grounding_score(
    source_text: str,
    evidence_text: str,
    *,
    ngram_size: int = 2,
) -> float:
    source_tokens = normalize_lookup_text(source_text).split()
    evidence_tokens = normalize_lookup_text(evidence_text).split()
    if not evidence_tokens:
        return 0.0
    if len(evidence_tokens) < ngram_size:
        return float(all(token in source_tokens for token in evidence_tokens))
    source_ngrams = {
        tuple(source_tokens[index : index + ngram_size])
        for index in range(len(source_tokens) - ngram_size + 1)
    }
    evidence_ngrams = [
        tuple(evidence_tokens[index : index + ngram_size])
        for index in range(len(evidence_tokens) - ngram_size + 1)
    ]
    return sum(ngram in source_ngrams for ngram in evidence_ngrams) / len(
        evidence_ngrams
    )


def source_grounding_for_record(
    record: dict[str, Any],
    *,
    data_dir: Path,
) -> tuple[int, int, int, list[dict[str, Any]]]:
    source_path = Path(str(record.get("source_text_path") or ""))
    if not source_path.is_absolute():
        source_path = data_dir.parent / source_path if source_path.parts[:1] == ("data",) else (
            data_dir / source_path
        )
    source_text = (
        source_path.read_text(encoding="utf-8", errors="ignore")
        if source_path.exists() and source_path.is_file()
        else ""
    )
    exact_supported = 0
    ngram_supported = 0
    grounding_review: list[dict[str, Any]] = []
    spans = record.get("evidence_spans") or []
    for span in spans:
        evidence_text = str(span.get("text") or "")
        if source_text and evidence_text and normalized_contains(source_text, evidence_text):
            exact_supported += 1
            ngram_supported += 1
        else:
            grounding_score = token_ngram_grounding_score(source_text, evidence_text)
            evidence_token_count = len(normalize_lookup_text(evidence_text).split())
            if (
                evidence_token_count >= EVIDENCE_NGRAM_MIN_TOKENS
                and grounding_score >= EVIDENCE_NGRAM_GROUNDING_THRESHOLD
            ):
                ngram_supported += 1
            else:
                grounding_review.append(
                    {
                        "document_id": record.get("document_id"),
                        "section": span.get("section"),
                        "text": evidence_text,
                        "source_text_path": str(source_path),
                        "evidence_token_count": evidence_token_count,
                        "token_bigram_grounding_score": round(grounding_score, 4),
                    }
                )
    return exact_supported, ngram_supported, len(spans), grounding_review


def scalar_cannot_determine_fields(record: dict[str, Any]) -> set[str]:
    fields = {
        field
        for field in (
            "study_design_category",
            "study_design_subtype",
            "evidence_context",
            "intervention_or_exposure_role",
            "overall_direction",
        )
        if record.get(field) == "cannot_determine"
    }
    if (record.get("population_or_model") or {}).get("category") == "cannot_determine":
        fields.add("population_or_model")
    return fields


def machine_readable_uncertainty(record: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    entries = record.get("missing_or_uncertain_fields") or []
    invalid = [entry for entry in entries if entry not in CANONICAL_UNCERTAINTY_FIELDS]
    required = scalar_cannot_determine_fields(record)
    for field in ("medical_conditions", "cannabinoids_or_exposures", "outcome_domains"):
        if not record.get(field):
            required.add(field)
    missing = sorted(required - set(entries))
    return not invalid and not missing, invalid, missing


def parse_raw_response_content(
    raw_response: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        content = raw_response["response_json"]["choices"][0]["message"]["content"]
        return json.loads(content), None
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        return None, str(exc)


def compatible_direction(legacy_result: str | None, predicted: str | None) -> bool:
    compatible = {
        "Positive": {"beneficial", "mixed"},
        "Negative": {"null", "harmful", "mixed"},
        "Inconclusive": {"mixed", "null", "cannot_determine"},
    }
    return predicted in compatible.get(legacy_result or "", set())


def evaluate_classification_run(
    *,
    storage: LocalStorage,
    records_path: Path | None = None,
    errors_path: Path | None = None,
    raw_responses_path: Path | None = None,
    summary_path: Path | None = None,
    input_path: Path | None = None,
    legacy_context_path: Path | None = None,
    evaluation_run_id: str | None = None,
    estimated_cost_usd: float | None = None,
) -> dict[str, Any]:
    resolved_records_path = records_path or latest_candidate_records_path(storage.root)
    classification_run_id = run_id_from_records_path(resolved_records_path)
    resolved_errors_path = errors_path or sibling_run_path(
        resolved_records_path,
        classification_run_id,
        "candidate_classification_errors.jsonl",
    )
    resolved_raw_path = raw_responses_path or sibling_run_path(
        resolved_records_path,
        classification_run_id,
        "candidate_classification_raw_responses.jsonl",
    )
    resolved_summary_path = summary_path or sibling_run_path(
        resolved_records_path,
        classification_run_id,
        "candidate_classification_summary.json",
    )
    summary = read_json(resolved_summary_path)
    resolved_input_path = resolve_run_input_path(
        data_dir=storage.root,
        summary=summary,
        input_path=input_path,
    )
    resolved_legacy_path = legacy_context_path or latest_legacy_english_context_path(storage.root)
    if resolved_legacy_path is None:
        msg = "No normalized English legacy context was found."
        raise FileNotFoundError(msg)

    records = read_jsonl(resolved_records_path)
    errors = read_jsonl(resolved_errors_path)
    raw_responses = read_jsonl(resolved_raw_path) if resolved_raw_path.exists() else []
    sample_rows = read_jsonl(resolved_input_path)
    sample_by_document_id = {
        corpus_row(row)["document_id"]: row for row in sample_rows
    }
    legacy_indexes = load_legacy_english_context_index(storage.root)
    if legacy_context_path is not None:
        legacy_indexes = {
            "document_id": {},
            "pmid": {},
            "pmcid": {},
            "doi": {},
            "title_year": {},
        }
        for context in read_jsonl(resolved_legacy_path):
            for match in context.get("document_matches") or []:
                if match.get("document_id"):
                    legacy_indexes["document_id"].setdefault(match["document_id"], context)
            if context.get("pmid"):
                legacy_indexes["pmid"][str(context["pmid"])] = context
            if context.get("pmcid"):
                legacy_indexes["pmcid"][str(context["pmcid"])] = context
            if context.get("doi"):
                legacy_indexes["doi"][clean_doi(context["doi"])] = context
            if context.get("normalized_title") and context.get("publication_year"):
                key = f"{context['normalized_title']}|{context['publication_year']}"
                legacy_indexes["title_year"][key] = context

    raw_valid_json = 0
    raw_json_errors: list[dict[str, Any]] = []
    declared_schema_invalid_outcome_values: Counter[str] = Counter()
    current_contract_invalid_outcome_values: Counter[str] = Counter()
    for raw_response in raw_responses:
        payload, parse_error = parse_raw_response_content(raw_response)
        if payload is None:
            raw_json_errors.append(
                {
                    "document_id": raw_response.get("document_id"),
                    "error": parse_error,
                }
            )
            continue
        raw_valid_json += 1
        declared_schema_version = payload.get("schema_version")
        for value in payload.get("outcome_domains") or []:
            if (
                declared_schema_version == "candidate_study_classification.v2"
                and value not in SCHEMA_V2_OUTCOME_DOMAINS
            ):
                declared_schema_invalid_outcome_values[str(value)] += 1
            if value not in CURRENT_OUTCOME_DOMAINS:
                current_contract_invalid_outcome_values[str(value)] += 1

    retry_count = sum(max(len(raw.get("attempts") or []) - 1, 0) for raw in raw_responses)
    http_success_count = sum(raw.get("status_code") == 200 for raw in raw_responses)
    provider_error_count = sum(raw.get("status_code") not in {None, 200} for raw in raw_responses)

    uncertainty_invalid_entries: list[dict[str, Any]] = []
    uncertainty_missing_fields: list[dict[str, Any]] = []
    machine_readable_count = 0
    records_with_source_traceability = 0
    evidence_span_records = 0
    evidence_spans_exactly_grounded = 0
    evidence_spans_ngram_grounded = 0
    evidence_spans_total = 0
    evidence_spans_requiring_grounding_review: list[dict[str, Any]] = []
    filter_coverage: Counter[str] = Counter()
    for record in records:
        is_machine_readable, invalid, missing = machine_readable_uncertainty(record)
        machine_readable_count += is_machine_readable
        if invalid:
            uncertainty_invalid_entries.append(
                {"document_id": record["document_id"], "invalid_entries": invalid}
            )
        if missing:
            uncertainty_missing_fields.append(
                {"document_id": record["document_id"], "missing_fields": missing}
            )
        records_with_source_traceability += bool(
            record.get("document_id")
            and record.get("source_text_path")
            and record.get("source_text_sha256")
            and record.get("provenance")
        )
        evidence_span_records += bool(record.get("evidence_spans"))
        exact_supported, ngram_supported, total, grounding_review = (
            source_grounding_for_record(
                record,
                data_dir=storage.root,
            )
        )
        evidence_spans_exactly_grounded += exact_supported
        evidence_spans_ngram_grounded += ngram_supported
        evidence_spans_total += total
        evidence_spans_requiring_grounding_review.extend(grounding_review)
        for field in (
            "study_design_category",
            "evidence_context",
            "medical_conditions",
            "cannabinoids_or_exposures",
            "intervention_or_exposure_role",
            "population_or_model",
            "outcome_domains",
            "overall_direction",
        ):
            value = record.get(field)
            if field == "population_or_model":
                value = (value or {}).get("category")
            if value and value != "cannot_determine":
                filter_coverage[field] += 1

    disagreements: list[dict[str, Any]] = []
    legacy_match_methods: Counter[str] = Counter()
    study_design_reference_count = 0
    study_design_exact_count = 0
    direction_reference_count = 0
    direction_compatible_count = 0
    for record in records:
        sample_row = sample_by_document_id.get(record["document_id"])
        if sample_row is None:
            continue
        source_record = corpus_row(sample_row)
        context, match_method = find_legacy_context(source_record, legacy_indexes)
        if context is None:
            continue
        legacy_match_methods[str(match_method)] += 1
        legacy_type = context.get("type_of_study")
        expected_design = LEGACY_STUDY_DESIGN_MAP.get(legacy_type)
        if expected_design:
            study_design_reference_count += 1
            if record.get("study_design_category") == expected_design:
                study_design_exact_count += 1
            else:
                disagreements.append(
                    {
                        "document_id": record["document_id"],
                        "title": source_record.get("primary_title"),
                        "legacy_context_id": context.get("context_id"),
                        "legacy_type_of_study": legacy_type,
                        "expected_study_design_category": expected_design,
                        "predicted_study_design_category": record.get(
                            "study_design_category"
                        ),
                        "predicted_study_design_subtype": record.get(
                            "study_design_subtype"
                        ),
                        "classification_confidence": record.get(
                            "classification_confidence"
                        ),
                        "evidence_spans": record.get("evidence_spans") or [],
                        "warnings": record.get("warnings") or [],
                    }
                )
        legacy_result = context.get("study_result")
        if legacy_result:
            direction_reference_count += 1
            direction_compatible_count += compatible_direction(
                legacy_result,
                record.get("overall_direction"),
            )

    rerun_reasons: dict[str, set[str]] = {}
    for error in errors:
        document_id = error.get("document_id")
        if document_id:
            rerun_reasons.setdefault(document_id, set()).add("technical_validation_error")
    for disagreement in disagreements:
        rerun_reasons.setdefault(disagreement["document_id"], set()).add(
            "study_design_disagreement"
        )
    rerun_documents = [
        {
            "document_id": document_id,
            "reasons": sorted(reasons),
            "sample_record": sample_by_document_id.get(document_id),
        }
        for document_id, reasons in sorted(rerun_reasons.items())
    ]
    targeted_input_rows = [
        item["sample_record"] for item in rerun_documents if item["sample_record"] is not None
    ]

    resolved_evaluation_run_id = evaluation_run_id or datetime.now(UTC).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    output_dir = storage.path("normalized/classification_evaluations")
    disagreements_path = write_jsonl(
        output_dir / f"{resolved_evaluation_run_id}_study_design_disagreements.jsonl",
        disagreements,
    )
    rerun_documents_path = write_jsonl(
        output_dir / f"{resolved_evaluation_run_id}_documents_requiring_rerun.jsonl",
        rerun_documents,
    )
    targeted_input_path = write_jsonl(
        output_dir / f"{resolved_evaluation_run_id}_targeted_rerun_input.jsonl",
        targeted_input_rows,
    )
    grounding_review_path = write_jsonl(
        output_dir
        / f"{resolved_evaluation_run_id}_evidence_spans_requiring_grounding_review.jsonl",
        evidence_spans_requiring_grounding_review,
    )
    report = {
        "evaluation_run_id": resolved_evaluation_run_id,
        "classification_run_id": classification_run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "inputs": {
            "classification_records_path": str(resolved_records_path),
            "classification_errors_path": str(resolved_errors_path),
            "raw_responses_path": str(resolved_raw_path),
            "classification_summary_path": str(resolved_summary_path),
            "classification_input_path": str(resolved_input_path),
            "legacy_english_context_path": str(resolved_legacy_path),
        },
        "technical_validity": {
            "input_records": len(sample_rows),
            "provider_responses": len(raw_responses),
            "http_200_responses": http_success_count,
            "provider_error_responses": provider_error_count,
            "valid_json_responses": raw_valid_json,
            "strict_schema_valid_records": len(records),
            "strict_schema_errors": len(errors),
            "retry_count": retry_count,
            "error_type_counts": dict(Counter(error["error_type"] for error in errors)),
            "declared_schema_invalid_outcome_domain_values": dict(
                declared_schema_invalid_outcome_values
            ),
            "current_contract_invalid_outcome_domain_values": dict(
                current_contract_invalid_outcome_values
            ),
            "raw_json_errors": raw_json_errors,
            "usage": summary.get("usage") or {},
            "latency_seconds": summary.get("latency_seconds") or {},
            "estimated_cost_usd": estimated_cost_usd,
        },
        "retrieval_utility": {
            "valid_records": len(records),
            "records_with_evidence_spans": evidence_span_records,
            "evidence_spans_total": evidence_spans_total,
            "evidence_spans_exactly_grounded_in_source_text": (
                evidence_spans_exactly_grounded
            ),
            "evidence_spans_grounded_with_extraction_tolerance": (
                evidence_spans_ngram_grounded
            ),
            "evidence_ngram_grounding_threshold": EVIDENCE_NGRAM_GROUNDING_THRESHOLD,
            "evidence_ngram_min_tokens": EVIDENCE_NGRAM_MIN_TOKENS,
            "evidence_spans_requiring_grounding_review": len(
                evidence_spans_requiring_grounding_review
            ),
            "records_with_source_traceability": records_with_source_traceability,
            "machine_readable_uncertainty_records": machine_readable_count,
            "records_with_invalid_uncertainty_entries": len(
                uncertainty_invalid_entries
            ),
            "records_missing_required_uncertainty_fields": len(
                uncertainty_missing_fields
            ),
            "filter_field_coverage_counts": dict(filter_coverage),
            "uncertainty_invalid_entries": uncertainty_invalid_entries,
            "uncertainty_missing_fields": uncertainty_missing_fields,
        },
        "inference_quality": {
            "legacy_english_matches": sum(legacy_match_methods.values()),
            "legacy_match_methods": dict(legacy_match_methods),
            "study_design_reference_records": study_design_reference_count,
            "study_design_exact_matches": study_design_exact_count,
            "study_design_disagreements": len(disagreements),
            "direction_reference_records": direction_reference_count,
            "direction_compatible_matches": direction_compatible_count,
            "classification_confidence_semantics": (
                "Categorical model assessment; not a calibrated probability."
            ),
        },
        "outputs": {
            "study_design_disagreements_path": str(disagreements_path),
            "documents_requiring_rerun_path": str(rerun_documents_path),
            "targeted_rerun_input_path": str(targeted_input_path),
            "evidence_spans_requiring_grounding_review_path": str(
                grounding_review_path
            ),
        },
        "rerun_document_count": len(rerun_documents),
        "notes": [
            "English normalized legacy context is the primary comparison reference.",
            (
                "Legacy disagreement is an evaluation signal, not proof that the candidate "
                "label is wrong."
            ),
            (
                "Classification confidence is categorical model self-assessment, "
                "not calibrated probability."
            ),
            (
                "This evaluation reads candidate artifacts and does not mutate SQLite "
                "or reviewed knowledge."
            ),
            (
                "Evidence grounding reports exact normalized substrings separately from "
                "token-bigram matches that tolerate extraction artifacts."
            ),
        ],
    }
    report_path = storage.write_json(
        Path("normalized/classification_evaluations")
        / f"{resolved_evaluation_run_id}_classification_evaluation_report.json",
        report,
    )
    return {
        "evaluation_run_id": resolved_evaluation_run_id,
        "report_path": str(report_path),
        **report["outputs"],
        "technical_validity": report["technical_validity"],
        "retrieval_utility": report["retrieval_utility"],
        "inference_quality": report["inference_quality"],
        "rerun_document_count": report["rerun_document_count"],
    }
