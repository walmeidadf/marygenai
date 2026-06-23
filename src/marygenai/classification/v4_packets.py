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
from marygenai.classification.v4_assembly import (
    ASSEMBLER_VERSION,
    assemble_mock_candidate,
)
from marygenai.classification.v4_evidence import (
    EVIDENCE_LOCATOR_VERSION,
    locate_v4_evidence,
)
from marygenai.classification.v4_models import (
    BROAD_V4_SCHEMA_VERSION,
    CANNABINOID_ROLE_SCHEMA_VERSION,
    CLINICAL_TOPIC_SCHEMA_VERSION,
    OUTCOMES_DIRECTION_SCHEMA_VERSION,
    POPULATION_STRUCTURE_SCHEMA_VERSION,
    BroadV4CandidateRecord,
    CannabinoidIdentityAndScientificRole,
    ClinicalTopicAnatomyOrganSystem,
    MinimalSemanticFieldDecision,
    MinimalSemanticFieldResponse,
    OutcomesAndOverallDirection,
    PopulationSampleGeographyStudyStructure,
    V4CandidateValue,
    V4EvidenceReference,
    V4PromptPacket,
    V4Uncertainty,
)
from marygenai.classification.v4_routing import (
    FAMILY_FIELDS,
    ROUTER_VERSION,
    FieldRoute,
    route_fields,
    routing_summary,
)
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

PACKET_BUILDER_VERSION = "classification_v4_packet_builder.v2"
TOKEN_ESTIMATOR_VERSION = "chars_divided_by_4.v1"
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "gpt-5.4-mini"
DEFAULT_INPUT_COST_PER_MILLION = 0.75
DEFAULT_OUTPUT_COST_PER_MILLION = 4.50
FAMILY_COMPLETION_LIMITS = {
    "broad_v4": 3000,
    "clinical_topic": 450,
    "cannabinoid_role": 400,
    "population_structure": 600,
    "outcomes_direction": 450,
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


def select_comparison_samples(
    sample_rows: list[dict[str, Any]],
    *,
    limit: int,
    manifest_rows: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_document_id = {row["document_id"]: row for row in sample_rows}
    if manifest_rows is not None:
        selected = []
        for entry in manifest_rows:
            document_id = entry["document_id"]
            if document_id not in by_document_id:
                raise ValueError(f"Manifest document not found in sample: {document_id}")
            selected.append(by_document_id[document_id])
        if len(selected) != len({row["document_id"] for row in selected}):
            raise ValueError("Comparison manifest must not contain duplicate documents.")
        return selected, manifest_rows

    contrast_count = min(2, max(1, limit // 4))
    contrasts = [
        row
        for row in sample_rows
        if row.get("cannabinoid_focus_group") != "source_text_signal"
    ]
    direct = [
        row
        for row in sample_rows
        if row.get("cannabinoid_focus_group") == "source_text_signal"
    ]
    selected: list[dict[str, Any]] = []
    selected_strategies: Counter[str] = Counter()
    while direct and len(selected) < max(0, limit - contrast_count):
        direct.sort(
            key=lambda row: (
                selected_strategies[row.get("source_strategy") or "unknown"],
                row.get("source_strategy") or "",
                row["document_id"],
            )
        )
        row = direct.pop(0)
        selected.append(row)
        selected_strategies[row.get("source_strategy") or "unknown"] += 1
    contrasts_by_group = {
        group: sorted(
            [
                row
                for row in contrasts
                if row.get("cannabinoid_focus_group") == group
            ],
            key=lambda row: (
                row.get("source_strategy") or "",
                row["document_id"],
            ),
        )
        for group in ("metadata_label_only", "no_signal")
    }
    selected_contrasts: list[dict[str, Any]] = []
    for group in ("metadata_label_only", "no_signal"):
        if contrasts_by_group[group] and len(selected_contrasts) < contrast_count:
            selected_contrasts.append(contrasts_by_group[group][0])
    if len(selected_contrasts) < contrast_count:
        selected_contrast_ids = {
            row["document_id"] for row in selected_contrasts
        }
        selected_contrasts.extend(
            row
            for row in sorted(contrasts, key=lambda row: row["document_id"])
            if row["document_id"] not in selected_contrast_ids
        )
    selected.extend(selected_contrasts[:contrast_count])
    if len(selected) < limit:
        selected_ids = {row["document_id"] for row in selected}
        selected.extend(
            row
            for row in sample_rows
            if row["document_id"] not in selected_ids
        )
        selected = selected[:limit]
    manifest = [
        {
            "manifest_position": index,
            "document_id": row["document_id"],
            "selection_reason": (
                "contrast"
                if row.get("cannabinoid_focus_group") != "source_text_signal"
                else "direct_signal_source_strategy_balance"
            ),
            "cannabinoid_focus_group": row.get("cannabinoid_focus_group"),
            "classification_dataset_split": row.get("classification_dataset_split"),
            "source_strategy": row.get("source_strategy"),
        }
        for index, row in enumerate(selected, start=1)
    ]
    return selected, manifest


def evidence_routing_audit(
    *,
    routing_records: list[dict[str, Any]],
    packets: list[V4PromptPacket],
) -> dict[str, Any]:
    selective = [packet for packet in packets if packet.strategy == "selective"]
    family_calls_by_document = Counter(packet.document_id for packet in selective)
    evidence_usage = Counter(
        f"{packet.document_id}:{evidence.evidence_id}"
        for packet in selective
        for evidence in packet.evidence_candidates
    )
    return {
        "documents_with_all_four_selective_families": sum(
            count == 4 for count in family_calls_by_document.values()
        ),
        "documents_with_suppressed_families": sum(
            count < 4 for count in family_calls_by_document.values()
        ),
        "selective_calls_avoided_against_four_per_document": (
            len(routing_records) * 4 - len(selective)
        ),
        "evidence_reused_across_packets": sum(
            count > 1 for count in evidence_usage.values()
        ),
        "maximum_evidence_reuse_count": max(evidence_usage.values(), default=0),
        "documents_with_insufficient_fields": sum(
            bool(record["summary"]["insufficient_fields"])
            for record in routing_records
        ),
        "documents_with_not_applicable_fields": sum(
            bool(record["summary"]["not_applicable_fields"])
            for record in routing_records
        ),
    }


def safe_fragment(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def parser_evidence_candidates(record: dict[str, Any]) -> list[V4EvidenceReference]:
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
    family: str,
    evidence: list[V4EvidenceReference],
    routes: list[FieldRoute],
) -> list[V4EvidenceReference]:
    allowed_ids = {
        evidence_id
        for route in routes
        if route.family == family and route.state == "semantic_resolution_required"
        for evidence_id in route.evidence_ids
    }
    selected = [item for item in evidence if item.evidence_id in allowed_ids]
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
    field_routes: list[FieldRoute],
) -> str:
    payload = {
        "requested_fields": requested_fields,
        "document_context": {
            "document_id": deterministic["document_id"],
            "publication_year": deterministic["publication_year"],
        },
        "metadata_candidates": metadata,
        "evidence_candidates": [item.model_dump(mode="json") for item in evidence],
        "field_evidence_constraints": {
            route.field_name: route.evidence_ids for route in field_routes
        },
    }
    return (
        "Resolve only the requested semantic fields. Do not repeat unsupported candidates. "
        "A country mention in an affiliation is not study geography. A cited design, species, "
        "route, or sample is not automatically the primary study value. Direction must be tied "
        "to the document's question; descriptive results use not_applicable. The response "
        "schema is supplied separately. Return JSON only.\n"
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
    all_evidence: list[V4EvidenceReference],
    routes: list[FieldRoute],
) -> V4PromptPacket:
    family_routes = (
        routes
        if family == "broad_v4"
        else [
            route
            for route in routes
            if route.family == family and route.state == "semantic_resolution_required"
        ]
    )
    selected_evidence = (
        all_evidence
        if family == "broad_v4"
        else relevant_evidence(family, all_evidence, routes)
    )
    requested_fields = (
        [field for fields in FAMILY_FIELDS.values() for field in fields]
        if family == "broad_v4"
        else [route.field_name for route in family_routes]
    )
    metadata = (
        {name: metadata_for_packet(sample, name) for name in FAMILY_FIELDS}
        if family == "broad_v4"
        else metadata_for_packet(sample, family)
    )
    deterministic = deterministic_fields(sample, baseline)
    response_schema = (
        FAMILY_MODELS[family].model_json_schema()
        if family == "broad_v4"
        else MinimalSemanticFieldResponse.model_json_schema()
    )
    system_prompt = build_system_prompt(family)
    user_prompt = build_user_prompt(
        family=family,
        requested_fields=requested_fields,
        deterministic=deterministic,
        metadata=metadata,
        evidence=selected_evidence,
        field_routes=family_routes,
    )
    return V4PromptPacket(
        packet_id=f"v4_packet:{run_id}:{safe_fragment(sample['document_id'])}:{family}",
        packet_run_id=run_id,
        strategy=strategy,
        semantic_family=family,
        document_id=sample["document_id"],
        response_schema_version=(
            FAMILY_SCHEMA_VERSIONS[family]
            if family == "broad_v4"
            else "minimal_semantic_field_response.v1"
        ),
        prompt_version=f"classification_v4_{family}_prompt.v2",
        target_model_provider=provider,
        target_model_name=model,
        max_completion_tokens=FAMILY_COMPLETION_LIMITS[family],
        requested_fields=requested_fields,
        field_routes=[route.model_dump(mode="json") for route in family_routes],
        deterministic_fields=deterministic,
        metadata_candidates=metadata,
        evidence_candidates=selected_evidence,
        source_text_path=baseline["source_text_path"],
        source_text_sha256=baseline["source_text_sha256"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_json_schema=response_schema,
        estimated_input_tokens=estimate_tokens(
            system_prompt
            + user_prompt
            + json.dumps(response_schema, separators=(",", ":"), sort_keys=True)
        ),
        estimated_max_output_tokens=FAMILY_COMPLETION_LIMITS[family],
        created_at=created_at,
        provenance={
            "builder_version": PACKET_BUILDER_VERSION,
            "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
            "parser_baseline_id": baseline["baseline_id"],
            "sample_id": sample["sample_id"],
            "evidence_locator_version": EVIDENCE_LOCATOR_VERSION,
            "field_router_version": ROUTER_VERSION,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "legacy_is_guardrail_not_ground_truth": True,
            "review_boundary": "prompt_preparation_not_reviewed_knowledge",
        },
    )


def semantic_families_for_record(routes: list[FieldRoute]) -> list[str]:
    return [
        family
        for family in FAMILY_FIELDS
        if any(
            route.family == family and route.state == "semantic_resolution_required"
            for route in routes
        )
    ]


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
    if family == "clinical_topic":
        return MinimalSemanticFieldResponse(
            decisions=[
                MinimalSemanticFieldDecision(
                    field_name=field_name,
                    field_confidence="low",
                    uncertainty_reason="insufficient_source_evidence",
                )
                for field_name in packet.requested_fields
            ]
        )
    if family == "cannabinoid_role":
        return MinimalSemanticFieldResponse(
            decisions=[
                MinimalSemanticFieldDecision(
                    field_name=field_name,
                    field_confidence="low",
                    uncertainty_reason="insufficient_source_evidence",
                )
                for field_name in packet.requested_fields
            ]
        )
    if family == "population_structure":
        return MinimalSemanticFieldResponse(
            decisions=[
                MinimalSemanticFieldDecision(
                    field_name=field_name,
                    field_confidence="low",
                    uncertainty_reason="insufficient_source_evidence",
                )
                for field_name in packet.requested_fields
            ]
        )
    if family == "outcomes_direction":
        return MinimalSemanticFieldResponse(
            decisions=[
                MinimalSemanticFieldDecision(
                    field_name=field_name,
                    field_confidence="low",
                    uncertainty_reason="insufficient_source_evidence",
                )
                for field_name in packet.requested_fields
            ]
        )
    uncertainty = V4Uncertainty(
        field_name="mock_response",
        reason="insufficient_source_evidence",
        detail="Schema-valid deterministic mock; no semantic claim was made.",
    )
    clinical = ClinicalTopicAnatomyOrganSystem(uncertainties=[uncertainty])
    cannabinoid = CannabinoidIdentityAndScientificRole(
        principal_role="cannot_determine", uncertainties=[uncertainty]
    )
    population = PopulationSampleGeographyStudyStructure(
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
    outcomes = OutcomesAndOverallDirection(
        overall_direction="cannot_determine", uncertainties=[uncertainty]
    )
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
        maximum_field_instances = len(documents) * sum(
            len(fields) for fields in FAMILY_FIELDS.values()
        )
        by_strategy[strategy] = {
            "documents": len(documents),
            "packets_or_calls": len(selected),
            "prompt_characters": sum(
                len(packet.system_prompt) + len(packet.user_prompt) for packet in selected
            ),
            "estimated_input_tokens": input_tokens,
            "max_completion_tokens": output_tokens,
            "requested_field_instances": requested,
            "field_instances_not_requested": maximum_field_instances - requested,
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
            "projected_max_cost_per_document_usd": round(
                cost / len(documents), 6
            )
            if documents
            else None,
            "projected_max_cost_per_requested_field_usd": round(
                cost / requested, 8
            )
            if requested
            else None,
        }
    return by_strategy


def build_v4_comparison_packets(
    *,
    storage: LocalStorage,
    sample_path: Path,
    parser_records_path: Path,
    manifest_path: Path | None = None,
    limit: int = 8,
    run_id: str | None = None,
    provider: str = DEFAULT_PROVIDER,
    model: str = DEFAULT_MODEL,
    input_cost_per_million: float = DEFAULT_INPUT_COST_PER_MILLION,
    output_cost_per_million: float = DEFAULT_OUTPUT_COST_PER_MILLION,
) -> dict[str, Any]:
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    created_at = datetime.now(UTC)
    sample_rows = read_jsonl(sample_path)
    input_manifest_rows = read_jsonl(manifest_path) if manifest_path else None
    samples, comparison_manifest = select_comparison_samples(
        sample_rows,
        limit=limit,
        manifest_rows=input_manifest_rows,
    )
    baselines = {row["document_id"]: row for row in read_jsonl(parser_records_path)}
    packets: list[V4PromptPacket] = []
    mocks: list[dict[str, Any]] = []
    assembled_records: list[BroadV4CandidateRecord] = []
    deterministic_field_counts = Counter()
    llm_field_counts = Counter()
    selected_document_ids = []
    routing_records: list[dict[str, Any]] = []
    for sample in samples:
        baseline = baselines[sample["document_id"]]
        source_path = resolve_source_path(storage.root, baseline["source_text_path"])
        if file_sha256(source_path) != baseline["source_text_sha256"]:
            raise ValueError(f"Source hash changed for {sample['document_id']}.")
        all_evidence = parser_evidence_candidates(baseline)
        all_evidence.extend(
            locate_v4_evidence(
                sample=sample,
                source_path=source_path,
                stored_source_path=baseline["source_text_path"],
            )
        )
        routes = route_fields(sample=sample, baseline=baseline, evidence=all_evidence)
        routing_records.append(
            {
                "document_id": sample["document_id"],
                "router_version": ROUTER_VERSION,
                "routes": [route.model_dump(mode="json") for route in routes],
                "summary": routing_summary(routes),
            }
        )
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
            all_evidence=all_evidence,
            routes=routes,
        )
        packets.append(broad)
        broad_mock = mock_family_response("broad_v4", broad)
        mocks.append(
            {
                "packet_id": broad.packet_id,
                "document_id": broad.document_id,
                "strategy": broad.strategy,
                "semantic_family": broad.semantic_family,
                "response": broad_mock.model_dump(mode="json"),
            }
        )
        selective_responses: dict[str, MinimalSemanticFieldResponse] = {}
        for family in semantic_families_for_record(routes):
            packet = packet_for_family(
                sample=sample,
                baseline=baseline,
                run_id=resolved_run_id,
                family=family,
                strategy="selective",
                provider=provider,
                model=model,
                created_at=created_at,
                all_evidence=all_evidence,
                routes=routes,
            )
            packets.append(packet)
            mock = mock_family_response(family, packet)
            if not isinstance(mock, MinimalSemanticFieldResponse):
                raise TypeError(f"Expected minimal semantic response for {family}.")
            selective_responses[family] = mock
            mocks.append(
                {
                    "packet_id": packet.packet_id,
                    "document_id": packet.document_id,
                    "strategy": packet.strategy,
                    "semantic_family": packet.semantic_family,
                    "response": mock.model_dump(mode="json"),
                }
            )
            llm_field_counts.update(packet.requested_fields)
        assembled_records.append(
            assemble_mock_candidate(
                run_id=resolved_run_id,
                document_id=sample["document_id"],
                source_text_path=baseline["source_text_path"],
                source_text_sha256=baseline["source_text_sha256"],
                source_identity=deterministic_fields(sample, baseline),
                routes=routes,
                evidence=all_evidence,
                responses=selective_responses,
                created_at=created_at,
            )
        )
    output_dir = storage.path("normalized/classification_evaluations")
    output_dir.mkdir(parents=True, exist_ok=True)
    packets_path = output_dir / f"{resolved_run_id}_classification_v4_comparison_packets.jsonl"
    mocks_path = output_dir / f"{resolved_run_id}_classification_v4_mock_responses.jsonl"
    routing_path = output_dir / f"{resolved_run_id}_classification_v4_field_routes.jsonl"
    assembled_path = (
        output_dir / f"{resolved_run_id}_classification_v4_assembled_mock_records.jsonl"
    )
    manifest_output_path = (
        output_dir / f"{resolved_run_id}_classification_v4_comparison_manifest.jsonl"
    )
    with packets_path.open("w", encoding="utf-8") as file:
        for packet in packets:
            file.write(json.dumps(packet.model_dump(mode="json"), sort_keys=True) + "\n")
    with mocks_path.open("w", encoding="utf-8") as file:
        for mock in mocks:
            file.write(json.dumps(mock, sort_keys=True) + "\n")
    with routing_path.open("w", encoding="utf-8") as file:
        for routing_record in routing_records:
            file.write(json.dumps(routing_record, sort_keys=True) + "\n")
    with assembled_path.open("w", encoding="utf-8") as file:
        for record in assembled_records:
            file.write(
                json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n"
            )
    with manifest_output_path.open("w", encoding="utf-8") as file:
        for entry in comparison_manifest:
            file.write(json.dumps(entry, sort_keys=True) + "\n")
    report = {
        "run_id": resolved_run_id,
        "builder_version": PACKET_BUILDER_VERSION,
        "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
        "sample_path": str(sample_path),
        "input_manifest_path": str(manifest_path) if manifest_path else None,
        "comparison_manifest_path": str(manifest_output_path),
        "parser_records_path": str(parser_records_path),
        "packets_path": str(packets_path),
        "mock_responses_path": str(mocks_path),
        "field_routes_path": str(routing_path),
        "assembled_mock_records_path": str(assembled_path),
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
        "field_routing_state_counts": dict(
            Counter(
                route["state"]
                for record in routing_records
                for route in record["routes"]
            )
        ),
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
        "evidence_routing_audit": evidence_routing_audit(
            routing_records=routing_records,
            packets=packets,
        ),
        "schema_versions": FAMILY_SCHEMA_VERSIONS,
        "assembler_version": ASSEMBLER_VERSION,
        "counts": {
            "documents": len(samples),
            "packets": len(packets),
            "broad_packets": sum(packet.strategy == "broad" for packet in packets),
            "selective_packets": sum(packet.strategy == "selective" for packet in packets),
            "schema_valid_mocks": len(mocks),
            "assembled_mock_records": len(assembled_records),
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
        "field_routes_path": str(routing_path),
        "assembled_mock_records_path": str(assembled_path),
        "comparison_manifest_path": str(manifest_output_path),
        "report_path": str(report_path),
        "counts": report["counts"],
        "strategy_metrics": report["strategy_metrics"],
    }
