from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from marygenai.classification.retrieval_baseline import read_jsonl, resolve_source_path
from marygenai.classification.v4_models import (
    BROAD_V4_SCHEMA_VERSION,
    CANNABINOID_ROLE_SCHEMA_VERSION,
    CLINICAL_TOPIC_SCHEMA_VERSION,
    OUTCOMES_DIRECTION_SCHEMA_VERSION,
    POPULATION_STRUCTURE_SCHEMA_VERSION,
    BroadV4CandidateRecord,
    CannabinoidIdentityAndScientificRole,
    ClinicalTopicAnatomyOrganSystem,
    OutcomesAndOverallDirection,
    PopulationSampleGeographyStudyStructure,
    V4CandidateValue,
    V4EvidenceReference,
    V4PromptPacket,
    V4Uncertainty,
)
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

PACKET_BUILDER_VERSION = "classification_v4_packet_builder.v1"
TOKEN_ESTIMATOR_VERSION = "chars_divided_by_4.v1"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_INPUT_COST_PER_MILLION = 0.75
DEFAULT_OUTPUT_COST_PER_MILLION = 4.50
FAMILY_COMPLETION_LIMITS = {
    "broad_v4": 3000,
    "clinical_topic": 900,
    "cannabinoid_role": 800,
    "population_structure": 1100,
    "outcomes_direction": 900,
}
FAMILY_FIELDS = {
    "clinical_topic": [
        "medical_conditions",
        "pathologies_or_disease_families",
        "symptoms_or_indications",
        "anatomical_entities",
        "organ_systems",
        "comorbidities",
    ],
    "cannabinoid_role": [
        "cannabinoids_or_exposures",
        "principal_role",
        "products_or_formulations",
        "routes_of_administration",
        "comparators",
    ],
    "population_structure": [
        "population_category",
        "population_description",
        "age_groups",
        "sex_or_gender",
        "species",
        "sample_size",
        "sample_size_scope",
        "study_countries",
        "publication_type",
        "study_design_category",
        "study_design_subtype",
        "evidence_context",
        "randomization",
        "blinding",
    ],
    "outcomes_direction": [
        "outcome_domains",
        "outcome_entities",
        "adverse_events",
        "overall_direction",
        "direction_question",
        "key_findings",
    ],
}
FAMILY_MODELS: dict[str, type[BaseModel]] = {
    "clinical_topic": ClinicalTopicAnatomyOrganSystem,
    "cannabinoid_role": CannabinoidIdentityAndScientificRole,
    "population_structure": PopulationSampleGeographyStudyStructure,
    "outcomes_direction": OutcomesAndOverallDirection,
    "broad_v4": BroadV4CandidateRecord,
}
FAMILY_SCHEMA_VERSIONS = {
    "clinical_topic": CLINICAL_TOPIC_SCHEMA_VERSION,
    "cannabinoid_role": CANNABINOID_ROLE_SCHEMA_VERSION,
    "population_structure": POPULATION_STRUCTURE_SCHEMA_VERSION,
    "outcomes_direction": OUTCOMES_DIRECTION_SCHEMA_VERSION,
    "broad_v4": BROAD_V4_SCHEMA_VERSION,
}
BASELINE_TO_FAMILY = {
    "medical_conditions": "clinical_topic",
    "pathologies_or_disease_families": "clinical_topic",
    "organ_systems": "clinical_topic",
    "cannabinoid_role": "cannabinoid_role",
    "population_category": "population_structure",
    "sample_size_and_scope": "population_structure",
    "study_countries": "population_structure",
    "study_structure": "population_structure",
    "outcome_domains": "outcomes_direction",
    "overall_direction": "outcomes_direction",
}


def safe_fragment(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def evidence_candidates(record: dict[str, Any]) -> list[V4EvidenceReference]:
    evidence: list[V4EvidenceReference] = []
    groups = (
        ("sample_size", "sample_size_candidates"),
        ("route_of_administration", "route_candidates"),
        ("study_countries", "country_candidates"),
        ("population_category", "population_candidates"),
        ("species", "species_candidates"),
        ("study_structure", "study_design_signals"),
    )
    for field_name, key in groups:
        for index, candidate in enumerate(record.get(key) or [], start=1):
            item = candidate["evidence"]
            evidence.append(
                V4EvidenceReference(
                    evidence_id=f"{field_name}:{index}",
                    field_name=field_name,
                    text=item["text"],
                    source_text_path=item["source_text_path"],
                    char_start=item.get("char_start"),
                    char_end=item.get("char_end"),
                    extraction_method=candidate["extraction_method"],
                )
            )
    return evidence


def relevant_evidence(
    family: str, evidence: list[V4EvidenceReference]
) -> list[V4EvidenceReference]:
    allowed = {
        "clinical_topic": {"population_category", "species", "study_structure"},
        "cannabinoid_role": {"route_of_administration", "study_structure"},
        "population_structure": {
            "sample_size",
            "study_countries",
            "population_category",
            "species",
            "study_structure",
        },
        "outcomes_direction": {"study_structure"},
    }
    selected = [item for item in evidence if item.field_name in allowed[family]]
    bounded: list[V4EvidenceReference] = []
    field_counts: Counter[str] = Counter()
    for item in selected:
        if field_counts[item.field_name] >= 3:
            continue
        bounded.append(item)
        field_counts[item.field_name] += 1
    return bounded


def metadata_for_packet(sample: dict[str, Any], family: str) -> dict[str, Any]:
    corpus = sample.get("corpus_metadata_candidates") or {}
    common = {
        "primary_title": sample.get("primary_title"),
        "publication_year": sample.get("publication_year"),
        "classification_dataset_split": sample.get("classification_dataset_split"),
        "cannabinoid_focus_group": sample.get("cannabinoid_focus_group"),
    }
    if family == "clinical_topic":
        common.update(
            medical_condition_candidates=corpus.get("medical_condition_labels") or [],
            organ_system_candidates=corpus.get("organ_system_labels") or [],
        )
    elif family == "cannabinoid_role":
        common.update(cannabinoid_candidates=corpus.get("cannabinoid_labels") or [])
    elif family == "population_structure":
        common.update(
            publication_type_guardrail=(
                sample.get("legacy_reference_guardrails") or {}
            ).get("type_of_study")
        )
    elif family == "outcomes_direction":
        guardrails = sample.get("legacy_reference_guardrails") or {}
        common.update(
            key_findings_guardrail=guardrails.get("key_findings") or [],
            result_guardrail=guardrails.get("study_result"),
        )
    return common


def deterministic_fields(sample: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": sample["document_id"],
        "publication_year": sample.get("publication_year"),
        "source_strategy": sample.get("source_strategy"),
        "source_text_path": baseline["source_text_path"],
        "source_text_sha256": baseline["source_text_sha256"],
        "classification_dataset_split": sample["classification_dataset_split"],
        "trust_level": "source_text_available",
    }


def build_system_prompt(family: str) -> str:
    return (
        "Classify candidate retrieval metadata for cannabinoid scientific source "
        f"intelligence. Task family: {family}. Return one JSON object matching the schema. "
        "Use only supplied metadata and evidence candidates. Metadata and legacy values are "
        "guardrails, not truth. Prefer explicit source evidence, preserve ambiguity, and "
        "abstain through structured uncertainty. Evidence IDs must refer to supplied evidence. "
        "Do not provide medical advice or treatment recommendations."
    )


def build_user_prompt(
    *,
    family: str,
    requested_fields: list[str],
    deterministic: dict[str, Any],
    metadata: dict[str, Any],
    evidence: list[V4EvidenceReference],
    response_schema: dict[str, Any],
) -> str:
    payload = {
        "requested_fields": requested_fields,
        "deterministic_fields": deterministic,
        "metadata_candidates": metadata,
        "evidence_candidates": [item.model_dump(mode="json") for item in evidence],
        "response_json_schema": response_schema,
    }
    return (
        "Resolve only the requested semantic fields. Do not repeat unsupported candidates. "
        "A country mention in an affiliation is not study geography. A cited design, species, "
        "route, or sample is not automatically the primary study value. Direction must be tied "
        "to the document's question; descriptive results use not_applicable. Return JSON only.\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )


def packet_for_family(
    *,
    sample: dict[str, Any],
    baseline: dict[str, Any],
    run_id: str,
    family: str,
    strategy: str,
    provider: str,
    model: str,
    created_at: datetime,
) -> V4PromptPacket:
    all_evidence = evidence_candidates(baseline)
    selected_evidence = all_evidence if family == "broad_v4" else relevant_evidence(
        family, all_evidence
    )
    requested_fields = (
        [field for fields in FAMILY_FIELDS.values() for field in fields]
        if family == "broad_v4"
        else FAMILY_FIELDS[family]
    )
    metadata = (
        {name: metadata_for_packet(sample, name) for name in FAMILY_FIELDS}
        if family == "broad_v4"
        else metadata_for_packet(sample, family)
    )
    deterministic = deterministic_fields(sample, baseline)
    response_schema = FAMILY_MODELS[family].model_json_schema()
    system_prompt = build_system_prompt(family)
    user_prompt = build_user_prompt(
        family=family,
        requested_fields=requested_fields,
        deterministic=deterministic,
        metadata=metadata,
        evidence=selected_evidence,
        response_schema=response_schema,
    )
    return V4PromptPacket(
        packet_id=f"v4_packet:{run_id}:{safe_fragment(sample['document_id'])}:{family}",
        packet_run_id=run_id,
        strategy=strategy,
        semantic_family=family,
        document_id=sample["document_id"],
        response_schema_version=FAMILY_SCHEMA_VERSIONS[family],
        prompt_version=f"classification_v4_{family}_prompt.v1",
        target_model_provider=provider,
        target_model_name=model,
        max_completion_tokens=FAMILY_COMPLETION_LIMITS[family],
        requested_fields=requested_fields,
        deterministic_fields=deterministic,
        metadata_candidates=metadata,
        evidence_candidates=selected_evidence,
        source_text_path=baseline["source_text_path"],
        source_text_sha256=baseline["source_text_sha256"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_json_schema=response_schema,
        estimated_input_tokens=estimate_tokens(system_prompt + user_prompt),
        estimated_max_output_tokens=FAMILY_COMPLETION_LIMITS[family],
        created_at=created_at,
        provenance={
            "builder_version": PACKET_BUILDER_VERSION,
            "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
            "parser_baseline_id": baseline["baseline_id"],
            "sample_id": sample["sample_id"],
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "legacy_is_guardrail_not_ground_truth": True,
            "review_boundary": "prompt_preparation_not_reviewed_knowledge",
        },
    )


def semantic_families_for_record(baseline: dict[str, Any]) -> list[str]:
    unresolved = {
        BASELINE_TO_FAMILY[field]
        for field in baseline["fields_requiring_semantic_resolution"]
        if field in BASELINE_TO_FAMILY
    }
    return [family for family in FAMILY_FIELDS if family in unresolved]


def mock_value(label: str, evidence_id: str) -> V4CandidateValue:
    return V4CandidateValue(
        source_value=label,
        normalized_label=label,
        field_confidence="low",
        evidence_ids=[evidence_id],
        extraction_method="llm",
    )


def mock_family_response(family: str, packet: V4PromptPacket) -> BaseModel:
    evidence_id = (
        packet.evidence_candidates[0].evidence_id
        if packet.evidence_candidates
        else "source_excerpt:unavailable"
    )
    uncertainty = V4Uncertainty(
        field_name="mock_response",
        reason="insufficient_source_evidence",
        detail="Schema-valid deterministic mock; no semantic claim was made.",
    )
    if family == "clinical_topic":
        return ClinicalTopicAnatomyOrganSystem(uncertainties=[uncertainty])
    if family == "cannabinoid_role":
        return CannabinoidIdentityAndScientificRole(
            principal_role="cannot_determine", uncertainties=[uncertainty]
        )
    if family == "population_structure":
        return PopulationSampleGeographyStudyStructure(
            population_category="cannot_determine",
            sample_size=None,
            sample_size_scope="cannot_determine",
            publication_type="cannot_determine",
            study_design_category="cannot_determine",
            study_design_subtype="cannot_determine",
            evidence_context="cannot_determine",
            randomization="uncertain",
            blinding="uncertain",
            uncertainties=[uncertainty],
        )
    if family == "outcomes_direction":
        return OutcomesAndOverallDirection(
            overall_direction="cannot_determine", uncertainties=[uncertainty]
        )
    clinical = mock_family_response("clinical_topic", packet)
    cannabinoid = mock_family_response("cannabinoid_role", packet)
    population = mock_family_response("population_structure", packet)
    outcomes = mock_family_response("outcomes_direction", packet)
    return BroadV4CandidateRecord(
        candidate_id=f"mock:{packet.packet_id}",
        document_id=packet.document_id,
        classification_run_id=packet.packet_run_id,
        source_text_path=packet.source_text_path,
        source_text_sha256=packet.source_text_sha256,
        source_identity=packet.deterministic_fields,
        extractor_name="marygenai_v4_semantic_classifier",
        extractor_version="0.1.0",
        model_provider="dry_run",
        model_name="deterministic_schema_mock",
        prompt_version=packet.prompt_version,
        created_at=packet.created_at,
        clinical_topic=clinical,
        cannabinoid_role=cannabinoid,
        population_structure=population,
        outcomes_direction=outcomes,
        evidence=packet.evidence_candidates,
        warnings=[f"No provider call. Placeholder evidence ID: {evidence_id}."],
        provenance={
            "method": "classification_v4_schema_mock",
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "mock_candidate_not_reviewed_knowledge",
        },
    )


def strategy_metrics(
    packets: list[V4PromptPacket],
    *,
    input_cost_per_million: float,
    output_cost_per_million: float,
) -> dict[str, Any]:
    by_strategy: dict[str, Any] = {}
    for strategy in ("broad", "selective"):
        selected = [packet for packet in packets if packet.strategy == strategy]
        input_tokens = sum(packet.estimated_input_tokens for packet in selected)
        output_tokens = sum(packet.estimated_max_output_tokens for packet in selected)
        documents = {packet.document_id for packet in selected}
        requested = sum(len(packet.requested_fields) for packet in selected)
        cost = (
            input_tokens * input_cost_per_million
            + output_tokens * output_cost_per_million
        ) / 1_000_000
        by_strategy[strategy] = {
            "documents": len(documents),
            "packets_or_calls": len(selected),
            "prompt_characters": sum(
                len(packet.system_prompt) + len(packet.user_prompt) for packet in selected
            ),
            "estimated_input_tokens": input_tokens,
            "max_completion_tokens": output_tokens,
            "requested_field_instances": requested,
            "evidence_candidates": sum(
                len(packet.evidence_candidates) for packet in selected
            ),
            "packets_without_evidence_candidates": sum(
                not packet.evidence_candidates for packet in selected
            ),
            "requested_unique_fields": sorted(
                {field for packet in selected for field in packet.requested_fields}
            ),
            "projected_max_cost_usd": round(cost, 6),
        }
    return by_strategy


def build_v4_comparison_packets(
    *,
    storage: LocalStorage,
    sample_path: Path,
    parser_records_path: Path,
    limit: int = 8,
    run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    input_cost_per_million: float = DEFAULT_INPUT_COST_PER_MILLION,
    output_cost_per_million: float = DEFAULT_OUTPUT_COST_PER_MILLION,
) -> dict[str, Any]:
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    created_at = datetime.now(UTC)
    samples = read_jsonl(sample_path)[:limit]
    baselines = {row["document_id"]: row for row in read_jsonl(parser_records_path)}
    packets: list[V4PromptPacket] = []
    mocks: list[dict[str, Any]] = []
    deterministic_field_counts = Counter()
    llm_field_counts = Counter()
    selected_document_ids = []
    for sample in samples:
        baseline = baselines[sample["document_id"]]
        source_path = resolve_source_path(storage.root, baseline["source_text_path"])
        if file_sha256(source_path) != baseline["source_text_sha256"]:
            raise ValueError(f"Source hash changed for {sample['document_id']}.")
        selected_document_ids.append(sample["document_id"])
        deterministic_field_counts.update(
            ["document_id", "publication_year", "source_identity", "source_text_sha256"]
        )
        broad = packet_for_family(
            sample=sample,
            baseline=baseline,
            run_id=resolved_run_id,
            family="broad_v4",
            strategy="broad",
            provider=provider,
            model=model,
            created_at=created_at,
        )
        packets.append(broad)
        mocks.append(mock_family_response("broad_v4", broad).model_dump(mode="json"))
        for family in semantic_families_for_record(baseline):
            packet = packet_for_family(
                sample=sample,
                baseline=baseline,
                run_id=resolved_run_id,
                family=family,
                strategy="selective",
                provider=provider,
                model=model,
                created_at=created_at,
            )
            packets.append(packet)
            mocks.append(mock_family_response(family, packet).model_dump(mode="json"))
            llm_field_counts.update(packet.requested_fields)
    output_dir = storage.path("normalized/classification_evaluations")
    output_dir.mkdir(parents=True, exist_ok=True)
    packets_path = output_dir / f"{resolved_run_id}_classification_v4_comparison_packets.jsonl"
    mocks_path = output_dir / f"{resolved_run_id}_classification_v4_mock_responses.jsonl"
    with packets_path.open("w", encoding="utf-8") as file:
        for packet in packets:
            file.write(json.dumps(packet.model_dump(mode="json"), sort_keys=True) + "\n")
    with mocks_path.open("w", encoding="utf-8") as file:
        for mock in mocks:
            file.write(json.dumps(mock, sort_keys=True) + "\n")
    report = {
        "run_id": resolved_run_id,
        "builder_version": PACKET_BUILDER_VERSION,
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        "sample_path": str(sample_path),
        "parser_records_path": str(parser_records_path),
        "packets_path": str(packets_path),
        "mock_responses_path": str(mocks_path),
        "selected_document_ids": selected_document_ids,
        "fair_comparison": {
            "same_documents": True,
            "target_model_provider": provider,
            "target_model_name": model,
            "same_pricing_assumption": True,
            "provider_calls_executed": 0,
        },
        "pricing_assumption_usd_per_million_tokens": {
            "input": input_cost_per_million,
            "output": output_cost_per_million,
            "note": "Configurable experiment input; verify provider pricing before execution.",
        },
        "strategy_metrics": strategy_metrics(
            packets,
            input_cost_per_million=input_cost_per_million,
            output_cost_per_million=output_cost_per_million,
        ),
        "deterministic_field_instances": dict(deterministic_field_counts),
        "selective_llm_field_instances": dict(llm_field_counts),
        "selective_family_metrics": {
            family: {
                "packets": sum(
                    packet.semantic_family == family and packet.strategy == "selective"
                    for packet in packets
                ),
                "evidence_candidates": sum(
                    len(packet.evidence_candidates)
                    for packet in packets
                    if packet.semantic_family == family and packet.strategy == "selective"
                ),
                "packets_without_evidence_candidates": sum(
                    not packet.evidence_candidates
                    for packet in packets
                    if packet.semantic_family == family and packet.strategy == "selective"
                ),
            }
            for family in FAMILY_FIELDS
        },
        "schema_versions": FAMILY_SCHEMA_VERSIONS,
        "counts": {
            "documents": len(samples),
            "packets": len(packets),
            "broad_packets": sum(packet.strategy == "broad" for packet in packets),
            "selective_packets": sum(packet.strategy == "selective" for packet in packets),
            "schema_valid_mocks": len(mocks),
        },
        "notes": [
            "No provider or LLM call was executed.",
            "Token counts are deterministic character-based estimates, not provider usage.",
            "Projected cost uses maximum completion limits, so it is a ceiling estimate.",
            "Parser evidence remains candidate evidence; ambiguous values are not finalized.",
            "No SQLite, review queue, review decision, or reviewed knowledge was mutated.",
        ],
    }
    report_path = output_dir / f"{resolved_run_id}_classification_v4_comparison_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "run_id": resolved_run_id,
        "packets_path": str(packets_path),
        "mock_responses_path": str(mocks_path),
        "report_path": str(report_path),
        "counts": report["counts"],
        "strategy_metrics": report["strategy_metrics"],
    }
