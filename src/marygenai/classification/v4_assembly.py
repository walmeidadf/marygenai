from __future__ import annotations

from datetime import datetime
from typing import Any

from marygenai.classification.v4_models import (
    BroadV4CandidateRecord,
    CannabinoidIdentityAndScientificRole,
    ClinicalTopicAnatomyOrganSystem,
    MinimalSemanticFieldResponse,
    OutcomesAndOverallDirection,
    PopulationSampleGeographyStudyStructure,
    V4EvidenceReference,
    V4Uncertainty,
)
from marygenai.classification.v4_routing import FieldRoute

ASSEMBLER_VERSION = "classification_v4_candidate_assembler.v1"


def uncertainties_for_family(
    family: str, routes: list[FieldRoute]
) -> list[V4Uncertainty]:
    return [
        V4Uncertainty(
            field_name=route.field_name,
            reason=(
                "not_applicable"
                if route.state == "not_applicable"
                else "insufficient_source_evidence"
            ),
            detail=route.reason,
        )
        for route in routes
        if route.family == family and route.state != "deterministically_resolved"
    ]


def validate_semantic_responses(
    *,
    routes: list[FieldRoute],
    evidence: list[V4EvidenceReference],
    responses: dict[str, MinimalSemanticFieldResponse],
) -> None:
    valid_evidence_ids = {item.evidence_id for item in evidence}
    requested_by_family = {
        family: {
            route.field_name
            for route in routes
            if route.family == family and route.state == "semantic_resolution_required"
        }
        for family in responses
    }
    for family, response in responses.items():
        seen_fields: set[str] = set()
        for decision in response.decisions:
            if decision.field_name not in requested_by_family[family]:
                raise ValueError(
                    f"Unexpected semantic field {decision.field_name} for {family}."
                )
            if decision.field_name in seen_fields:
                raise ValueError(f"Duplicate semantic decision for {decision.field_name}.")
            unknown_ids = sorted(set(decision.evidence_ids) - valid_evidence_ids)
            if unknown_ids:
                raise ValueError(
                    f"Unknown evidence IDs for {decision.field_name}: {', '.join(unknown_ids)}"
                )
            seen_fields.add(decision.field_name)
        missing = requested_by_family[family] - seen_fields
        if missing:
            raise ValueError(
                f"Missing semantic decisions for {family}: {', '.join(sorted(missing))}"
            )


def assemble_mock_candidate(
    *,
    run_id: str,
    document_id: str,
    source_text_path: str,
    source_text_sha256: str,
    source_identity: dict[str, Any],
    routes: list[FieldRoute],
    evidence: list[V4EvidenceReference],
    responses: dict[str, MinimalSemanticFieldResponse],
    created_at: datetime,
) -> BroadV4CandidateRecord:
    validate_semantic_responses(routes=routes, evidence=evidence, responses=responses)
    no_cannabinoid_focus = any(
        route.family == "cannabinoid_role" and route.state == "not_applicable"
        for route in routes
    )
    return BroadV4CandidateRecord(
        candidate_id=f"assembled_mock:{run_id}:{document_id}",
        document_id=document_id,
        classification_run_id=run_id,
        source_text_path=source_text_path,
        source_text_sha256=source_text_sha256,
        source_identity=source_identity,
        extractor_name="marygenai_v4_candidate_assembler",
        extractor_version=ASSEMBLER_VERSION,
        model_provider="dry_run",
        model_name="deterministic_semantic_abstention_mock",
        prompt_version="classification_v4_selective_assembly.v1",
        created_at=created_at,
        clinical_topic=ClinicalTopicAnatomyOrganSystem(
            uncertainties=uncertainties_for_family("clinical_topic", routes)
        ),
        cannabinoid_role=CannabinoidIdentityAndScientificRole(
            principal_role=(
                "not_cannabinoid_focused"
                if no_cannabinoid_focus
                else "cannot_determine"
            ),
            uncertainties=uncertainties_for_family("cannabinoid_role", routes),
        ),
        population_structure=PopulationSampleGeographyStudyStructure(
            population_category="cannot_determine",
            sample_size=None,
            sample_size_scope="cannot_determine",
            publication_type="cannot_determine",
            study_design_category="cannot_determine",
            study_design_subtype="cannot_determine",
            evidence_context="cannot_determine",
            randomization="uncertain",
            blinding="uncertain",
            uncertainties=uncertainties_for_family("population_structure", routes),
        ),
        outcomes_direction=OutcomesAndOverallDirection(
            overall_direction="cannot_determine",
            uncertainties=uncertainties_for_family("outcomes_direction", routes),
        ),
        evidence=evidence,
        warnings=[
            "Assembled from deterministic routing and schema-valid semantic abstention mocks.",
            "No provider call was executed and no semantic value was inferred.",
        ],
        provenance={
            "assembler_version": ASSEMBLER_VERSION,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "assembled_mock_candidate_not_reviewed_knowledge",
        },
    )
