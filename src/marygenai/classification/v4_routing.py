from __future__ import annotations

import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from marygenai.classification.v4_models import V4EvidenceReference

ROUTER_VERSION = "classification_v4_field_router.v1"
RoutingState = Literal[
    "deterministically_resolved",
    "semantic_resolution_required",
    "insufficient_evidence",
    "not_applicable",
]

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


class FieldRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    family: str
    state: RoutingState
    evidence_ids: list[str] = Field(default_factory=list)
    deterministic_value: Any = None
    reason: str


def matching_ids(
    evidence: list[V4EvidenceReference],
    *,
    fields: set[str],
    pattern: str | None = None,
) -> list[str]:
    selected = [item for item in evidence if item.field_name in fields]
    if pattern is not None:
        selected = [
            item
            for item in selected
            if re.search(pattern, item.text, re.IGNORECASE)
        ]
    return [item.evidence_id for item in selected]


def supported_country_ids(
    baseline: dict[str, Any], evidence: list[V4EvidenceReference]
) -> list[str]:
    supported_indexes = {
        index
        for index, candidate in enumerate(
            baseline.get("country_candidates") or [], start=1
        )
        if (candidate.get("attributes") or {}).get("support_scope") == "study_context"
    }
    supported_ids = {f"study_countries:{index}" for index in supported_indexes}
    return [item.evidence_id for item in evidence if item.evidence_id in supported_ids]


def field_evidence_ids(
    field_name: str,
    *,
    baseline: dict[str, Any],
    evidence: list[V4EvidenceReference],
) -> list[str]:
    if field_name in {
        "medical_conditions",
        "pathologies_or_disease_families",
        "symptoms_or_indications",
    }:
        return matching_ids(
            evidence, fields={"clinical_topic", "document_title"}
        )
    if field_name == "anatomical_entities":
        return matching_ids(
            evidence, fields={"anatomy_organ_system", "document_title"}
        )
    if field_name == "organ_systems":
        return matching_ids(evidence, fields={"anatomy_organ_system"})
    if field_name == "comorbidities":
        return matching_ids(
            evidence,
            fields={"clinical_topic"},
            pattern=r"\b(comorbid|concurrent|coexisting)\b",
        )
    if field_name in {"cannabinoids_or_exposures", "principal_role"}:
        return matching_ids(evidence, fields={"cannabinoid_identity"})
    if field_name == "products_or_formulations":
        return matching_ids(
            evidence,
            fields={"cannabinoid_identity"},
            pattern=r"\b(product|formulation|extract|oil|capsule|spray|solution)\b",
        )
    if field_name == "routes_of_administration":
        return matching_ids(evidence, fields={"route_of_administration"})
    if field_name == "comparators":
        return matching_ids(
            evidence,
            fields={"study_structure", "document_title"},
            pattern=r"\b(placebo|control|comparator|standard care)\b",
        )
    if field_name in {"population_category", "population_description"}:
        return matching_ids(
            evidence, fields={"population_category", "species", "document_title"}
        )
    if field_name == "age_groups":
        return matching_ids(
            evidence,
            fields={"population_category", "document_title"},
            pattern=r"\b(adult|pediatric|paediatric|child|children|adolescent|"
            r"older|aged|years? of age)\b",
        )
    if field_name == "sex_or_gender":
        return matching_ids(
            evidence,
            fields={"population_category", "document_title"},
            pattern=r"\b(male|female|men|women|sex|gender|pregnan|breastfeeding)\b",
        )
    if field_name == "species":
        return matching_ids(evidence, fields={"species", "document_title"})
    if field_name in {"sample_size", "sample_size_scope"}:
        return matching_ids(evidence, fields={"sample_size"})
    if field_name == "study_countries":
        return supported_country_ids(baseline, evidence)
    if field_name in {
        "publication_type",
        "study_design_category",
        "study_design_subtype",
        "evidence_context",
    }:
        return matching_ids(
            evidence, fields={"study_structure", "species", "document_title"}
        )
    if field_name == "randomization":
        return matching_ids(
            evidence,
            fields={"study_structure", "document_title"},
            pattern=r"\brandomi[sz]",
        )
    if field_name == "blinding":
        return matching_ids(
            evidence,
            fields={"study_structure", "document_title"},
            pattern=r"\b(blind|masked|open-label)\b",
        )
    if field_name in {
        "outcome_domains",
        "outcome_entities",
        "overall_direction",
        "direction_question",
        "key_findings",
    }:
        return matching_ids(
            evidence, fields={"outcomes_direction", "document_title"}
        )
    if field_name == "adverse_events":
        return matching_ids(
            evidence,
            fields={"outcomes_direction"},
            pattern=r"\b(adverse|side effect|safety|harm|toxicity)\b",
        )
    return []


def route_fields(
    *,
    sample: dict[str, Any],
    baseline: dict[str, Any],
    evidence: list[V4EvidenceReference],
) -> list[FieldRoute]:
    routes: dict[str, FieldRoute] = {}
    focus_group = sample.get("cannabinoid_focus_group")
    has_cannabinoid_identity_evidence = any(
        item.field_name == "cannabinoid_identity" for item in evidence
    )
    for family, fields in FAMILY_FIELDS.items():
        for field_name in fields:
            if field_name in routes:
                continue
            if family == "cannabinoid_role" and focus_group == "no_signal":
                routes[field_name] = FieldRoute(
                    field_name=field_name,
                    family=family,
                    state="not_applicable",
                    reason="Frozen sample profile found no cannabinoid signal.",
                )
                continue
            if (
                family == "cannabinoid_role"
                and not has_cannabinoid_identity_evidence
            ):
                routes[field_name] = FieldRoute(
                    field_name=field_name,
                    family=family,
                    state="insufficient_evidence",
                    reason=(
                        "No source-backed cannabinoid identity evidence was located; "
                        "route or formulation mentions alone cannot activate this family."
                    ),
                )
                continue
            ids = field_evidence_ids(
                field_name, baseline=baseline, evidence=evidence
            )
            state: RoutingState = (
                "semantic_resolution_required" if ids else "insufficient_evidence"
            )
            routes[field_name] = FieldRoute(
                field_name=field_name,
                family=family,
                state=state,
                evidence_ids=ids,
                reason=(
                    "Bounded candidate evidence requires semantic relation or selection."
                    if ids
                    else "No field-relevant evidence candidate was located."
                ),
            )
    ordered = [
        routes[field_name]
        for family_fields in FAMILY_FIELDS.values()
        for field_name in family_fields
    ]
    if len(ordered) != len({route.field_name for route in ordered}):
        raise ValueError("Field routes must be unique.")
    return ordered


def routing_summary(routes: list[FieldRoute]) -> dict[str, Any]:
    state_counts = Counter(route.state for route in routes)
    return {
        "state_counts": dict(state_counts),
        "semantic_fields": [
            route.field_name
            for route in routes
            if route.state == "semantic_resolution_required"
        ],
        "deterministic_fields": [
            route.field_name
            for route in routes
            if route.state == "deterministically_resolved"
        ],
        "insufficient_fields": [
            route.field_name
            for route in routes
            if route.state == "insufficient_evidence"
        ],
        "not_applicable_fields": [
            route.field_name for route in routes if route.state == "not_applicable"
        ],
    }
