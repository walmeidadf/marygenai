from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from starlette.middleware.trustedhost import TrustedHostMiddleware

from marygenai.retrieval.models import FilterGroup, SearchFilters, SearchRequest
from marygenai.retrieval.service import RetrievalService

ZERO_RESULT_MESSAGE = (
    "No candidate records were retrieved from the current MaryGenAI index for the "
    "effective query. This does not establish absence from the scientific literature."
)


def _group(value: str | None) -> FilterGroup | None:
    return FilterGroup(values=[value]) if value else None


def _labels(values: list[Any]) -> list[str]:
    labels: list[str] = []
    for row in values:
        value = row.get("value") if isinstance(row, dict) else getattr(row, "value", None)
        if value:
            labels.append(value)
    return labels


def _condition_labels(metadata: dict[str, Any]) -> list[str]:
    return [
        value.get("normalized_label") or value.get("free_text_label")
        for value in metadata.get("medical_conditions", [])
        if value.get("normalized_label") or value.get("free_text_label")
    ]


def _exposure_labels(metadata: dict[str, Any]) -> list[str]:
    return [
        value.get("normalized_label") or value.get("free_text_label")
        for value in metadata.get("cannabinoids_or_exposures", [])
        if value.get("normalized_label") or value.get("free_text_label")
    ]


def _population_label(metadata: dict[str, Any]) -> str:
    population = metadata.get("population_or_model") or {}
    return population.get("category") or population.get("description") or "not represented"


def _summary(result: Any, *, trust_level: str) -> dict[str, Any]:
    preferred = result.preferred_access_url
    return {
        "documentId": result.document_id,
        "title": result.title or "Untitled publication",
        "year": result.publication_year,
        "conditions": result.medical_conditions,
        "cannabinoids": result.cannabinoids_or_exposures,
        "studyDesign": result.study_design_category,
        "population": result.population_category,
        "outcomeDomains": result.outcome_domains,
        "classificationConfidence": result.classification_confidence,
        "retrievalConfidenceBand": result.retrieval_confidence.band or "low",
        "retrievalConfidenceScore": result.retrieval_confidence.score or 0,
        "reviewState": result.review_state,
        "trustLevel": trust_level,
        "hasUncertainty": result.has_uncertainty,
        "matchKind": result.match.kind,
        "identifiers": {
            "pmid": result.identifiers.pmid,
            "pmcid": result.identifiers.pmcid,
            "doi": result.identifiers.doi,
        },
        "preferredAccessUrl": preferred.url if preferred else None,
        "preferredAccessLabel": preferred.label if preferred else None,
    }


def _detail(service: RetrievalService, document_id: str) -> dict[str, Any]:
    detail = service.get_study(document_id)
    candidate = detail.candidate_classification
    projected = detail.projected_identity
    preferred = projected.preferred_access_url
    retrieval = detail.retrieval_confidence or {}
    metadata = {
        "medical_conditions": candidate.get("medical_conditions", []),
        "cannabinoids_or_exposures": candidate.get("cannabinoids_or_exposures", []),
        "population_or_model": candidate.get("population_or_model", {}),
    }
    evidence: list[dict[str, Any]] = []
    for field, values in (
        ("medical_conditions", candidate.get("medical_conditions", [])),
        ("cannabinoids_or_exposures", candidate.get("cannabinoids_or_exposures", [])),
    ):
        for value in values:
            label = value.get("normalized_label") or value.get("free_text_label")
            text = value.get("evidence_text")
            if label and text:
                evidence.append(
                    {
                        "field": field,
                        "value": label,
                        "quote": text,
                        "sourceSection": "Candidate field evidence",
                        "confidence": value.get("confidence", "low"),
                    }
                )
    for span in candidate.get("evidence_spans", []):
        if span.get("text"):
            evidence.append(
                {
                    "field": "candidate_evidence_span",
                    "value": span.get("section") or "Supporting evidence",
                    "quote": span["text"],
                    "sourceSection": span.get("section") or "Source text",
                    "confidence": candidate.get("classification_confidence", "low"),
                }
            )
    return {
        "documentId": detail.document_id,
        "title": detail.source_identity.title or "Untitled publication",
        "year": detail.source_identity.publication_year,
        "conditions": _condition_labels(metadata),
        "cannabinoids": _exposure_labels(metadata),
        "studyDesign": candidate.get("study_design_category") or "not represented",
        "population": _population_label(metadata),
        "outcomeDomains": candidate.get("outcome_domains") or [],
        "classificationConfidence": candidate.get("classification_confidence", "low"),
        "retrievalConfidenceBand": retrieval.get("band") or "low",
        "retrievalConfidenceScore": retrieval.get("score") or 0,
        "reviewState": detail.review_state,
        "trustLevel": detail.trust_boundary.trust_level,
        "hasUncertainty": bool(candidate.get("missing_or_uncertain_fields")),
        "matchKind": "not_assessed",
        "identifiers": {
            "pmid": projected.pmid,
            "pmcid": projected.pmcid,
            "doi": projected.doi,
        },
        "preferredAccessUrl": preferred.url if preferred else None,
        "preferredAccessLabel": preferred.label if preferred else None,
        "evidence": evidence,
        "uncertainties": candidate.get("missing_or_uncertain_fields") or [],
        "warnings": candidate.get("warnings") or [],
        "provenance": {
            "sourceTrustLevel": detail.source_trust_level or "not recorded",
            "sourceHash": detail.source_text_sha256,
            "model": detail.provenance.get("model_name") or "not recorded",
            "promptVersion": detail.provenance.get("prompt_version") or "not recorded",
            "schemaVersion": detail.provenance.get("schema_version") or "not recorded",
            "extractorVersion": detail.provenance.get("extractor_version") or "not recorded",
            "indexBuildId": detail.provenance.get("index_build_id") or "not recorded",
        },
    }


def create_app(
    index_path: Path,
    *,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """Create a web API over one immutable retrieval index."""
    service = RetrievalService(index_path)
    app = FastAPI(
        title="MaryGenAI Dataset Viewer API",
        summary="Read-only web projection of the candidate retrieval contract.",
        version="0.1.0",
    )
    if allowed_hosts is not None:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def private_no_store(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/api/viewer/meta")
    def viewer_meta() -> dict[str, Any]:
        capabilities = service.capabilities()
        facets = service.facets(SearchRequest(limit=1), top=100).facets
        manifest = service.manifest()
        return {
            "mode": "index",
            "snapshotId": service.build_id,
            "snapshotLabel": f"Candidate index · {service.build_id}",
            "documentCount": capabilities.document_count,
            "sortOptions": [{"value": "confidence", "label": "Retrieval confidence"}],
            "facets": {
                "conditions": _labels(facets.get("medical_conditions", [])),
                "cannabinoids": _labels(facets.get("cannabinoids_or_exposures", [])),
                "studyDesigns": _labels(facets.get("study_design_categories", [])),
                "populations": _labels(facets.get("population_categories", [])),
                "outcomeDomains": _labels(facets.get("outcome_domains", [])),
                "classificationConfidences": _labels(facets.get("classification_confidences", [])),
                "reviewStates": _labels(facets.get("review_states", [])),
                "years": [],
            },
            "limitations": manifest.get("limitations", []),
        }

    @app.get("/api/viewer/studies")
    def viewer_studies(
        query: Annotated[str | None, Query(max_length=500)] = None,
        condition: str | None = None,
        cannabinoid: str | None = None,
        studyDesign: str | None = None,
        population: str | None = None,
        outcome: str | None = None,
        confidence: str | None = None,
        reviewState: str | None = None,
        yearFrom: Annotated[int | None, Query(ge=1800, le=2200)] = None,
        yearTo: Annotated[int | None, Query(ge=1800, le=2200)] = None,
        page: Annotated[int, Query(ge=1, le=1000)] = 1,
        pageSize: Annotated[int, Query(ge=1, le=25)] = 6,
        sort: str = "confidence",
    ) -> dict[str, Any]:
        if sort != "confidence":
            raise HTTPException(
                status_code=422,
                detail=(
                    "The current index supports its documented retrieval-confidence "
                    "order only."
                ),
            )
        if yearFrom is not None and yearTo is not None and yearFrom > yearTo:
            raise HTTPException(status_code=422, detail="yearFrom must not exceed yearTo.")
        filters = SearchFilters(
            medical_conditions=_group(condition),
            cannabinoids_or_exposures=_group(cannabinoid),
            study_design_categories=_group(studyDesign),
            population_categories=_group(population),
            outcome_domains=_group(outcome),
            classification_confidences=_group(confidence),
            review_states=_group(reviewState),
            publication_year_from=yearFrom,
            publication_year_to=yearTo,
        )
        cursor = service.cursor_for_offset((page - 1) * pageSize)
        response = service.search(
            SearchRequest(query=query, filters=filters, limit=pageSize, cursor=cursor)
        )
        total_pages = max(1, math.ceil(response.total / pageSize))
        effective_page = min(page, total_pages)
        if page > total_pages:
            cursor = service.cursor_for_offset((effective_page - 1) * pageSize)
            response = service.search(
                SearchRequest(query=query, filters=filters, limit=pageSize, cursor=cursor)
            )
        return {
            "mode": "index",
            "snapshotId": service.build_id,
            "total": response.total,
            "page": effective_page,
            "pageSize": pageSize,
            "totalPages": total_pages,
            "sort": sort,
            "results": [
                _summary(
                    result,
                    trust_level=response.trust_boundary.trust_level,
                )
                for result in response.results
            ],
            "zeroResultMessage": ZERO_RESULT_MESSAGE,
        }

    @app.get("/api/viewer/studies/{document_id:path}")
    def viewer_study(document_id: str) -> dict[str, Any]:
        try:
            return _detail(service, document_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Study not found in this snapshot.",
            ) from error

    return app
