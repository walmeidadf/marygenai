from __future__ import annotations

from typing import Any, Literal

RETRIEVAL_CONFIDENCE_VERSION = "retrieval_confidence.v1"
RETRIEVAL_CONFIDENCE_WEIGHTS = {
    "technical_integrity": 0.20,
    "source_quality": 0.20,
    "evidence_grounding": 0.30,
    "metadata_consistency": 0.20,
    "retrieval_completeness": 0.10,
}
FILTER_FIELDS = (
    "study_design_category",
    "evidence_context",
    "medical_conditions",
    "cannabinoids_or_exposures",
    "intervention_or_exposure_role",
    "population_or_model",
    "outcome_domains",
    "overall_direction",
)
ConfidenceBand = Literal["high", "medium", "low"]


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def rounded(value: float) -> float:
    return round(clamp(value), 4)


def confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.95:
        return "high"
    if score >= 0.75:
        return "medium"
    return "low"


def technical_integrity_component(
    record: dict[str, Any],
    raw_response: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    required_values = (
        record.get("document_id"),
        record.get("schema_version"),
        record.get("model_provider"),
        record.get("model_name"),
        record.get("prompt_version"),
        record.get("source_text_path"),
        record.get("source_text_sha256"),
        record.get("provenance"),
    )
    presence = sum(bool(value) for value in required_values) / len(required_values)
    reasons: list[str] = []
    execution = 1.0
    if raw_response is None:
        execution = 0.8
        reasons.append("provider_response_provenance_unavailable")
    else:
        attempts = raw_response.get("attempts") or []
        status_code = raw_response.get("status_code")
        if status_code != 200:
            execution = 0.4
            reasons.append("provider_response_not_http_200")
        elif len(attempts) > 1:
            execution = 0.9
            reasons.append("provider_retries")
    return rounded((presence * 0.7) + (execution * 0.3)), reasons


def source_quality_component(source_record: dict[str, Any] | None) -> tuple[float, list[str]]:
    if source_record is None:
        return 0.5, ["source_corpus_metadata_unavailable"]
    if source_record.get("classification_ready"):
        readiness = 1.0
    elif source_record.get("source_ready"):
        readiness = 0.75
    else:
        readiness = 0.35
    section_signal = min(float(source_record.get("scientific_section_hit_count") or 0) / 4, 1.0)
    text_signal = min(float(source_record.get("extracted_text_chars") or 0) / 6_000, 1.0)
    reasons = []
    if readiness < 1.0:
        reasons.append("source_not_strict_classification_ready")
    if section_signal < 0.5:
        reasons.append("weak_scientific_section_signal")
    if text_signal < 0.5:
        reasons.append("short_source_text")
    score = (readiness * 0.5) + (section_signal * 0.25) + (text_signal * 0.25)
    return rounded(score), reasons


def evidence_grounding_component(
    *,
    exact_grounded: int,
    tolerant_grounded: int,
    total_spans: int,
) -> tuple[float, list[str]]:
    if total_spans <= 0:
        return 0.0, ["missing_evidence_spans"]
    exact_fraction = exact_grounded / total_spans
    tolerant_only_fraction = max(tolerant_grounded - exact_grounded, 0) / total_spans
    score = exact_fraction + (tolerant_only_fraction * 0.85)
    reasons = []
    if tolerant_grounded < total_spans:
        reasons.append("evidence_spans_require_grounding_review")
    elif exact_grounded < total_spans:
        reasons.append("extraction_tolerant_grounding")
    return rounded(score), reasons


def metadata_consistency_component(
    disagreement_status: str | None,
    *,
    structured_contradiction: bool,
) -> tuple[float, list[str]]:
    status_scores = {
        None: 0.8,
        "exact_match": 1.0,
        "compatible_refinement": 0.95,
        "source_supported_override": 0.9,
        "unresolved_disagreement": 0.4,
    }
    score = status_scores.get(disagreement_status, 0.5)
    reasons = []
    if disagreement_status == "compatible_refinement":
        reasons.append("legacy_compatible_refinement")
    elif disagreement_status == "source_supported_override":
        reasons.append("source_supported_legacy_override")
    elif disagreement_status == "unresolved_disagreement":
        reasons.append("unresolved_metadata_disagreement")
    elif disagreement_status is None:
        reasons.append("trusted_reference_unavailable")
    if structured_contradiction:
        score = min(score, 0.35)
        reasons.append("structured_source_contradiction")
    return rounded(score), reasons


def retrieval_completeness_component(record: dict[str, Any]) -> tuple[float, list[str]]:
    populated = 0
    missing_fields = []
    for field in FILTER_FIELDS:
        value = record.get(field)
        if field == "population_or_model":
            value = (value or {}).get("category")
        if value and value != "cannot_determine":
            populated += 1
        else:
            missing_fields.append(field)
    reasons = [f"missing_filter_field:{field}" for field in missing_fields]
    return rounded(populated / len(FILTER_FIELDS)), reasons


def compute_retrieval_confidence(
    *,
    record: dict[str, Any],
    source_record: dict[str, Any] | None,
    raw_response: dict[str, Any] | None,
    exact_grounded: int,
    tolerant_grounded: int,
    total_spans: int,
    disagreement_status: str | None,
    structured_contradiction: bool,
    uncertainty_is_machine_readable: bool,
) -> dict[str, Any]:
    component_values: dict[str, float] = {}
    reasons: list[str] = []
    component_values["technical_integrity"], component_reasons = (
        technical_integrity_component(record, raw_response)
    )
    reasons.extend(component_reasons)
    component_values["source_quality"], component_reasons = source_quality_component(
        source_record
    )
    reasons.extend(component_reasons)
    component_values["evidence_grounding"], component_reasons = (
        evidence_grounding_component(
            exact_grounded=exact_grounded,
            tolerant_grounded=tolerant_grounded,
            total_spans=total_spans,
        )
    )
    reasons.extend(component_reasons)
    component_values["metadata_consistency"], component_reasons = (
        metadata_consistency_component(
            disagreement_status,
            structured_contradiction=structured_contradiction,
        )
    )
    reasons.extend(component_reasons)
    component_values["retrieval_completeness"], component_reasons = (
        retrieval_completeness_component(record)
    )
    reasons.extend(component_reasons)

    weighted_base = sum(
        component_values[name] * weight
        for name, weight in RETRIEVAL_CONFIDENCE_WEIGHTS.items()
    )
    uncertain_fields = list(record.get("missing_or_uncertain_fields") or [])
    if not uncertainty_is_machine_readable:
        reasons.append("invalid_uncertainty_contract")
    uncertainty_contract_penalty = 0.15 if not uncertainty_is_machine_readable else 0.0
    base_penalty = min(len(uncertain_fields) * 0.025, 0.15)
    score = rounded(weighted_base - base_penalty - uncertainty_contract_penalty)
    broad_recall_score = rounded(
        weighted_base
        - min(len(uncertain_fields) * 0.01, 0.06)
        - uncertainty_contract_penalty
    )
    high_precision_score = rounded(
        weighted_base
        - min(len(uncertain_fields) * 0.04, 0.20)
        - uncertainty_contract_penalty
    )
    if uncertain_fields:
        reasons.append("declared_field_uncertainty")

    return {
        "version": RETRIEVAL_CONFIDENCE_VERSION,
        "document_id": record.get("document_id"),
        "score": score,
        "band": confidence_band(score),
        "broad_recall_score": broad_recall_score,
        "high_precision_score": high_precision_score,
        "components": component_values,
        "weights": RETRIEVAL_CONFIDENCE_WEIGHTS,
        "declared_uncertain_fields": uncertain_fields,
        "reasons": sorted(set(reasons)),
        "model_declared_classification_confidence": record.get(
            "classification_confidence"
        ),
        "semantics": (
            "Deterministic heuristic retrieval-ranking score; not a calibrated "
            "probability and not clinical evidence strength."
        ),
    }
