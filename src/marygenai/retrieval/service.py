from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import duckdb

from marygenai.retrieval.common import normalize_match_key
from marygenai.retrieval.models import (
    INDEX_LIMITATIONS,
    FacetsResponse,
    FacetValue,
    MatchExplanation,
    MatchReason,
    ProjectedIdentity,
    PublicIndexManifest,
    SearchAccessLink,
    SearchCapabilities,
    SearchEvidencePreview,
    SearchIdentifiers,
    SearchRequest,
    SearchResponse,
    SearchRetrievalConfidence,
    SearchTrace,
    SourceIdentity,
    StudyDetailResponse,
    StudySearchResult,
    TrustBoundary,
)

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "for",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_CURSOR_VERSION = 1
_EVIDENCE_PREVIEW_MAX_CHARS = 320
_CORE_MATCH_FIELDS = frozenset(
    {"title", "medical_conditions", "cannabinoids_or_exposures"}
)

FILTER_FAMILIES = {
    "medical_conditions": "medical_conditions",
    "cannabinoids_or_exposures": "cannabinoids_or_exposures",
    "study_design_categories": "study_design_categories",
    "study_design_subtypes": "study_design_subtypes",
    "evidence_contexts": "evidence_contexts",
    "population_categories": "population_categories",
    "intervention_or_exposure_roles": "intervention_or_exposure_roles",
    "outcome_domains": "outcome_domains",
    "overall_directions": "overall_directions",
    "classification_confidences": "classification_confidences",
    "review_states": "review_states",
}

_FILTER_MATCH_FIELDS = {
    "medical_conditions": "medical_conditions",
    "cannabinoids_or_exposures": "cannabinoids_or_exposures",
    "study_design_categories": "study_design_category",
    "study_design_subtypes": "study_design_subtype",
    "evidence_contexts": "evidence_context",
    "population_categories": "population_category",
    "intervention_or_exposure_roles": "intervention_or_exposure_role",
    "outcome_domains": "outcome_domains",
    "overall_directions": "overall_direction",
    "classification_confidences": "classification_confidence",
    "review_states": "review_state",
}


def _encode_cursor(offset: int, build_id: str) -> str:
    payload = json.dumps(
        {"v": _CURSOR_VERSION, "offset": offset, "build_id": build_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None, build_id: str) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid retrieval cursor.") from exc
    if (
        payload.get("v") != _CURSOR_VERSION
        or payload.get("build_id") != build_id
        or not isinstance(payload.get("offset"), int)
        or payload["offset"] < 0
    ):
        raise ValueError("Retrieval cursor does not belong to this index build.")
    return payload["offset"]


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    words = re.findall(r"[\w-]+", query.casefold(), flags=re.UNICODE)
    return list(dict.fromkeys(word for word in words if len(word) >= 2 and word not in _STOP_WORDS))


class RetrievalService:
    """Query an isolated DuckDB candidate index using read-only connections."""

    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path.resolve()
        if not self.index_path.exists():
            raise FileNotFoundError(f"Retrieval index not found: {self.index_path}")
        connection = self._connect()
        try:
            self._metadata = dict(
                connection.execute("SELECT key, value FROM index_metadata").fetchall()
            )
        finally:
            connection.close()
        self.build_id = self._metadata["build_id"]

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.index_path), read_only=True)

    def cursor_for_offset(self, offset: int) -> str | None:
        """Create an index-bound cursor for a non-negative presentation offset."""
        if offset < 0:
            raise ValueError("Retrieval offset must not be negative.")
        return _encode_cursor(offset, self.build_id) if offset else None

    def _where_clause(
        self,
        request: SearchRequest,
    ) -> tuple[str, list[Any], SearchTrace]:
        clauses: list[str] = []
        parameters: list[Any] = []
        query_terms = _query_terms(request.query)
        for term in query_terms:
            clauses.append("d.search_text LIKE ?")
            parameters.append(f"%{term}%")

        requested_filters = request.filters.model_dump(mode="json", exclude_none=True)
        applied_filters: dict[str, Any] = {}
        for field_name, family in FILTER_FAMILIES.items():
            group = getattr(request.filters, field_name)
            if group is None:
                continue
            keys = list(dict.fromkeys(normalize_match_key(value) for value in group.values))
            keys = [key for key in keys if key]
            if not keys:
                continue
            placeholders = ", ".join("?" for _ in keys)
            if group.match == "any":
                clauses.append(
                    "EXISTS (SELECT 1 FROM facets f "
                    "WHERE f.document_id = d.document_id AND f.family = ? "
                    f"AND f.value_key IN ({placeholders}))"
                )
                parameters.extend([family, *keys])
            else:
                clauses.append(
                    "(SELECT COUNT(DISTINCT f.value_key) FROM facets f "
                    "WHERE f.document_id = d.document_id AND f.family = ? "
                    f"AND f.value_key IN ({placeholders})) = ?"
                )
                parameters.extend([family, *keys, len(keys)])
            applied_filters[field_name] = group.model_dump(mode="json")

        if request.filters.publication_year_from is not None:
            clauses.append("d.publication_year >= ?")
            parameters.append(request.filters.publication_year_from)
            applied_filters["publication_year_from"] = request.filters.publication_year_from
        if request.filters.publication_year_to is not None:
            clauses.append("d.publication_year <= ?")
            parameters.append(request.filters.publication_year_to)
            applied_filters["publication_year_to"] = request.filters.publication_year_to
        if request.filters.has_uncertainty is not None:
            clauses.append("d.has_uncertainty = ?")
            parameters.append(request.filters.has_uncertainty)
            applied_filters["has_uncertainty"] = request.filters.has_uncertainty

        trace = SearchTrace(
            question_type=request.question_type,
            query=request.query,
            query_terms=query_terms,
            requested_filters=requested_filters,
            applied_filters=applied_filters,
            unsupported_dimensions=request.unsupported_dimensions,
            relaxations=[],
        )
        return (" AND ".join(clauses) if clauses else "TRUE"), parameters, trace

    @staticmethod
    def _source_identity(row: dict[str, Any]) -> SourceIdentity:
        return SourceIdentity(
            document_id=row["document_id"],
            title=row.get("title"),
            doi=row.get("doi"),
            pmid=row.get("pmid"),
            pmcid=row.get("pmcid"),
            canonical_url=row.get("canonical_url"),
            source_url=row.get("source_url"),
            publication_year=row.get("publication_year"),
        )

    @staticmethod
    def _identity_contract(row: dict[str, Any]) -> tuple[SourceIdentity, ProjectedIdentity]:
        original = SourceIdentity.model_validate(json.loads(row["original_corpus_identity_json"]))
        projected = ProjectedIdentity.model_validate(json.loads(row["projected_identity_json"]))
        return original, projected

    @staticmethod
    def _candidate_labels(values: list[dict[str, Any]]) -> list[str]:
        labels: list[str] = []
        for value in values:
            label = value.get("normalized_label") or value.get("free_text_label")
            if label and label not in labels:
                labels.append(str(label))
        return labels

    @classmethod
    def _search_field_values(
        cls,
        row: dict[str, Any],
        classification: dict[str, Any],
    ) -> dict[str, list[str]]:
        population = classification["population_or_model"]
        return {
            "title": [str(row["title"])] if row.get("title") else [],
            "medical_conditions": cls._candidate_labels(
                classification["medical_conditions"]
            ),
            "cannabinoids_or_exposures": cls._candidate_labels(
                classification["cannabinoids_or_exposures"]
            ),
            "study_design_category": [classification["study_design_category"]],
            "study_design_subtype": [classification["study_design_subtype"]],
            "evidence_context": [classification["evidence_context"]],
            "population_category": [population["category"]],
            "population_description": (
                [str(population["description"])] if population.get("description") else []
            ),
            "intervention_or_exposure_role": [
                classification["intervention_or_exposure_role"]
            ],
            "outcome_domains": [str(value) for value in classification["outcome_domains"]],
            "overall_direction": [classification["overall_direction"]],
            "classification_confidence": [row["classification_confidence"]],
            "review_state": [row["review_state"]],
            "publication_year": (
                [str(row["publication_year"])]
                if row.get("publication_year") is not None
                else []
            ),
            "has_uncertainty": [str(bool(row["has_uncertainty"])).lower()],
        }

    @staticmethod
    def _first_matching_value(term: str, values: list[str]) -> str | None:
        folded = term.casefold()
        return next((value for value in values if folded in value.casefold()), None)

    @classmethod
    def _match_explanation(
        cls,
        request: SearchRequest,
        field_values: dict[str, list[str]],
    ) -> MatchExplanation:
        reasons: list[MatchReason] = []
        query_terms = _query_terms(request.query)
        query_match_fields: list[str] = []
        filter_match_fields: list[str] = []
        for term in query_terms:
            for field_name, values in field_values.items():
                matched_value = cls._first_matching_value(term, values)
                if matched_value is None:
                    continue
                reasons.append(
                    MatchReason(
                        criterion=term,
                        criterion_type="query_term",
                        matched_field=field_name,
                        matched_value=matched_value,
                    )
                )
                query_match_fields.append(field_name)
                break

        for filter_name in FILTER_FAMILIES:
            group = getattr(request.filters, filter_name)
            if group is None:
                continue
            matched_field = _FILTER_MATCH_FIELDS[filter_name]
            values = field_values[matched_field]
            normalized_values = {
                normalize_match_key(value): value for value in values if normalize_match_key(value)
            }
            for requested_value in group.values:
                matched_value = normalized_values.get(normalize_match_key(requested_value))
                if matched_value is None:
                    continue
                reasons.append(
                    MatchReason(
                        criterion=f"{filter_name}:{requested_value}",
                        criterion_type="filter",
                        matched_field=matched_field,
                        matched_value=matched_value,
                    )
                )
                filter_match_fields.append(matched_field)

        publication_year = field_values["publication_year"]
        if request.filters.publication_year_from is not None and publication_year:
            reasons.append(
                MatchReason(
                    criterion=f"publication_year_from:{request.filters.publication_year_from}",
                    criterion_type="filter",
                    matched_field="publication_year",
                    matched_value=publication_year[0],
                )
            )
            filter_match_fields.append("publication_year")
        if request.filters.publication_year_to is not None and publication_year:
            reasons.append(
                MatchReason(
                    criterion=f"publication_year_to:{request.filters.publication_year_to}",
                    criterion_type="filter",
                    matched_field="publication_year",
                    matched_value=publication_year[0],
                )
            )
            filter_match_fields.append("publication_year")
        if request.filters.has_uncertainty is not None:
            reasons.append(
                MatchReason(
                    criterion=f"has_uncertainty:{str(request.filters.has_uncertainty).lower()}",
                    criterion_type="filter",
                    matched_field="has_uncertainty",
                    matched_value=field_values["has_uncertainty"][0],
                )
            )
            filter_match_fields.append("has_uncertainty")

        if query_terms:
            is_direct = (
                len(query_match_fields) == len(query_terms)
                and all(field_name in _CORE_MATCH_FIELDS for field_name in query_match_fields)
            )
        elif filter_match_fields:
            is_direct = any(
                field_name in _CORE_MATCH_FIELDS for field_name in filter_match_fields
            )
        else:
            is_direct = True
        kind = "direct" if is_direct else "tangential"
        return MatchExplanation(kind=kind, reasons=reasons)

    @staticmethod
    def _evidence_preview(
        classification: dict[str, Any],
        request: SearchRequest,
    ) -> SearchEvidencePreview | None:
        candidates: list[tuple[str, str | None, str]] = []
        for span in classification.get("evidence_spans", []):
            text = str(span.get("text") or "").strip()
            if text:
                candidates.append(("evidence_spans", span.get("section"), text))
        for source_field in ("medical_conditions", "cannabinoids_or_exposures"):
            for value in classification.get(source_field, []):
                text = str(value.get("evidence_text") or "").strip()
                if text:
                    candidates.append((source_field, "Candidate field evidence", text))
        if not candidates:
            return None

        target_terms = _query_terms(request.query)
        for filter_name in FILTER_FAMILIES:
            group = getattr(request.filters, filter_name)
            if group is None:
                continue
            for value in group.values:
                target_terms.extend(_query_terms(value))
                normalized = normalize_match_key(value)
                if normalized:
                    target_terms.append(normalized)
        target_terms = list(dict.fromkeys(target_terms))

        def evidence_score(candidate: tuple[str, str | None, str]) -> int:
            text = candidate[2].casefold()
            return sum(term.casefold() in text for term in target_terms)

        source_field, section, text = max(candidates, key=evidence_score)
        truncated = len(text) > _EVIDENCE_PREVIEW_MAX_CHARS
        if truncated:
            clipped = text[:_EVIDENCE_PREVIEW_MAX_CHARS]
            text = clipped.rsplit(" ", 1)[0] or clipped
        return SearchEvidencePreview(
            text=text,
            section=section,
            source_field=source_field,
            truncated=truncated,
        )

    def search(self, request: SearchRequest) -> SearchResponse:
        where_clause, parameters, trace = self._where_clause(request)
        offset = _decode_cursor(request.cursor, self.build_id)
        connection = self._connect()
        try:
            total = connection.execute(
                f"SELECT COUNT(*) FROM documents d WHERE {where_clause}",
                parameters,
            ).fetchone()[0]
            cursor = connection.execute(
                f"""
                SELECT
                    d.document_id, d.title, d.publication_year,
                    d.classification_confidence, d.retrieval_confidence_score,
                    d.retrieval_confidence_band,
                    d.has_uncertainty, d.review_state, d.classification_json,
                    d.projected_identity_json
                FROM documents d
                WHERE {where_clause}
                ORDER BY d.retrieval_confidence_score DESC NULLS LAST,
                         d.publication_year DESC NULLS LAST,
                         d.document_id
                LIMIT ? OFFSET ?
                """,
                [*parameters, request.limit, offset],
            )
            columns = [description[0] for description in cursor.description]
            rows = [dict(zip(columns, values, strict=True)) for values in cursor.fetchall()]
        finally:
            connection.close()

        results: list[StudySearchResult] = []
        for row in rows:
            classification = json.loads(row.pop("classification_json"))
            projected_identity = ProjectedIdentity.model_validate(
                json.loads(row["projected_identity_json"])
            )
            preferred_access = projected_identity.preferred_access_url
            field_values = self._search_field_values(row, classification)
            results.append(
                StudySearchResult(
                    document_id=row["document_id"],
                    title=row.get("title"),
                    publication_year=row.get("publication_year"),
                    identifiers=SearchIdentifiers(
                        pmid=projected_identity.pmid,
                        pmcid=projected_identity.pmcid,
                        doi=projected_identity.doi,
                        status=projected_identity.status,
                    ),
                    preferred_access_url=(
                        SearchAccessLink(
                            label=preferred_access.label,
                            url=preferred_access.url,
                            url_kind=preferred_access.url_kind,
                        )
                        if preferred_access
                        else None
                    ),
                    medical_conditions=field_values["medical_conditions"],
                    cannabinoids_or_exposures=field_values[
                        "cannabinoids_or_exposures"
                    ],
                    study_design_category=classification["study_design_category"],
                    study_design_subtype=classification["study_design_subtype"],
                    evidence_context=classification["evidence_context"],
                    population_category=classification["population_or_model"]["category"],
                    intervention_or_exposure_role=classification[
                        "intervention_or_exposure_role"
                    ],
                    outcome_domains=classification["outcome_domains"],
                    overall_direction=classification["overall_direction"],
                    classification_confidence=row["classification_confidence"],
                    retrieval_confidence=SearchRetrievalConfidence(
                        score=row["retrieval_confidence_score"],
                        band=row["retrieval_confidence_band"],
                    ),
                    has_uncertainty=row["has_uncertainty"],
                    uncertain_fields=classification["missing_or_uncertain_fields"],
                    review_state=row["review_state"],
                    evidence_preview=self._evidence_preview(classification, request),
                    match=self._match_explanation(request, field_values),
                    detail_uri=f"marygenai://studies/{row['document_id']}",
                )
            )
        next_cursor = None
        if offset + len(results) < total:
            next_cursor = _encode_cursor(offset + len(results), self.build_id)
        return SearchResponse(
            total=total,
            returned=len(results),
            next_cursor=next_cursor,
            search_trace=trace,
            results=results,
        )

    def facets(self, request: SearchRequest, *, top: int = 25) -> FacetsResponse:
        if not 1 <= top <= 100:
            raise ValueError("Facet top must be between 1 and 100.")
        where_clause, parameters, trace = self._where_clause(request)
        connection = self._connect()
        try:
            total = connection.execute(
                f"SELECT COUNT(*) FROM documents d WHERE {where_clause}",
                parameters,
            ).fetchone()[0]
            cursor = connection.execute(
                f"""
                SELECT f.family, f.value_key, MIN(f.display_value) AS display_value,
                       COUNT(DISTINCT f.document_id) AS document_count
                FROM facets f
                JOIN documents d ON d.document_id = f.document_id
                WHERE f.is_canonical AND {where_clause}
                GROUP BY f.family, f.value_key
                ORDER BY f.family, document_count DESC, display_value
                """,
                parameters,
            )
            grouped: dict[str, list[FacetValue]] = {}
            for family, value_key, display_value, count in cursor.fetchall():
                values = grouped.setdefault(family, [])
                if len(values) < top:
                    values.append(FacetValue(value=display_value, match_key=value_key, count=count))
        finally:
            connection.close()
        return FacetsResponse(total=total, facets=grouped, search_trace=trace)

    def get_study(self, document_id: str) -> StudyDetailResponse:
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                SELECT d.* FROM documents d WHERE d.document_id = ?
                """,
                [document_id],
            )
            values = cursor.fetchone()
            if values is None:
                raise KeyError(f"Study not found: {document_id}")
            columns = [description[0] for description in cursor.description]
            row = dict(zip(columns, values, strict=True))
        finally:
            connection.close()

        classification = json.loads(row["classification_json"])
        confidence = (
            json.loads(row["retrieval_confidence_json"])
            if row["retrieval_confidence_json"]
            else None
        )
        review_rows = json.loads(row["grounding_review_json"])
        original_identity, projected_identity = self._identity_contract(row)
        return StudyDetailResponse(
            document_id=document_id,
            source_identity=self._source_identity(row),
            original_corpus_identity=original_identity,
            projected_identity=projected_identity,
            source_text_path=row["source_text_path"],
            source_text_sha256=row["source_text_sha256"],
            source_trust_level=row["source_trust_level"],
            candidate_classification=classification,
            retrieval_confidence=confidence,
            grounding_review={
                "status": "requires_review" if review_rows else "not_flagged_for_review",
                "semantics": (
                    "Evaluation worklist status; absence from the worklist is not a claim that "
                    "the evidence span was human reviewed."
                ),
                "flagged_span_count": len(review_rows),
                "flagged_spans": review_rows,
            },
            provenance={
                "classification": classification["provenance"],
                "classification_run_id": classification["classification_run_id"],
                "model_provider": classification["model_provider"],
                "model_name": classification["model_name"],
                "prompt_version": classification["prompt_version"],
                "schema_version": classification["schema_version"],
                "extractor_name": classification["extractor_name"],
                "extractor_version": classification["extractor_version"],
                "index_build_id": self.build_id,
                "index_schema_version": self._metadata["index_schema_version"],
            },
            review_state=row["review_state"],
        )

    def manifest(self) -> dict[str, Any]:
        manifest_path = self.index_path.with_suffix(".manifest.json")
        if manifest_path.exists():
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        return dict(self._metadata)

    def public_manifest(self) -> PublicIndexManifest:
        """Return a typed, path-free manifest for external read-only interfaces."""
        manifest = self.manifest()

        def decode_list(name: str) -> list[str]:
            value = manifest.get(name, [])
            if isinstance(value, str):
                decoded = json.loads(value or "[]")
                return [str(item) for item in decoded]
            return [str(item) for item in value]

        return PublicIndexManifest(
            index_schema_version=str(manifest["index_schema_version"]),
            build_id=str(manifest["build_id"]),
            built_at=str(manifest["built_at"]),
            document_count=int(manifest["document_count"]),
            classification_run_ids=decode_list("classification_run_ids"),
            inclusion_criteria=decode_list("inclusion_criteria"),
            excluded_document_count=int(manifest.get("excluded_document_count", 0)),
            trust_boundary=manifest.get("trust_boundary") or TrustBoundary(),
            limitations=(
                decode_list("limitations")
                if manifest.get("limitations")
                else list(INDEX_LIMITATIONS)
            ),
        )

    def identity_coverage(self) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS document_count,
                    COUNT(pmid) AS pmid_count,
                    COUNT(pmcid) AS pmcid_count,
                    COUNT(doi) AS doi_count,
                    SUM(
                        CASE WHEN identity_status = 'conflict' THEN 1 ELSE 0 END
                    ) AS conflict_documents,
                    SUM(identity_conflict_count) AS identifier_conflicts,
                    SUM(
                        CASE WHEN pmid IS NOT NULL AND pmcid IS NOT NULL
                            AND doi IS NOT NULL THEN 1 ELSE 0 END
                    ) AS all_three,
                    SUM(
                        CASE WHEN ((pmid IS NOT NULL)::INTEGER
                            + (pmcid IS NOT NULL)::INTEGER
                            + (doi IS NOT NULL)::INTEGER) = 2 THEN 1 ELSE 0 END
                    ) AS two_identifiers,
                    SUM(
                        CASE WHEN ((pmid IS NOT NULL)::INTEGER
                            + (pmcid IS NOT NULL)::INTEGER
                            + (doi IS NOT NULL)::INTEGER) = 1 THEN 1 ELSE 0 END
                    ) AS one_identifier
                FROM documents
                """
            ).fetchone()
        finally:
            connection.close()
        names = (
            "document_count",
            "pmid",
            "pmcid",
            "doi",
            "conflict_documents",
            "identifier_conflicts",
            "all_three_identifiers",
            "two_identifiers",
            "one_identifier",
        )
        return dict(zip(names, row, strict=True))

    def capabilities(self) -> SearchCapabilities:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT family, COUNT(DISTINCT value_key)
                FROM facets WHERE is_canonical GROUP BY family ORDER BY family
                """
            ).fetchall()
        finally:
            connection.close()
        counts = dict(rows)
        filter_fields = {
            name: {
                "match_modes": ["any", "all"],
                "distinct_values": counts.get(family, 0),
            }
            for name, family in FILTER_FAMILIES.items()
        }
        filter_fields.update(
            {
                "publication_year_from": {"type": "integer"},
                "publication_year_to": {"type": "integer"},
                "has_uncertainty": {"type": "boolean"},
            }
        )
        return SearchCapabilities(
            index_schema_version=self._metadata["index_schema_version"],
            document_count=int(self._metadata["document_count"]),
            classification_run_ids=json.loads(self._metadata["classification_run_ids"]),
            language_contract={
                "corpus_primary_language": "English",
                "query_and_filter_language": "English",
                "host_translation_required_for_non_english_questions": True,
                "preserve_identifiers_without_translation": True,
                "answer_in_user_language": True,
                "translation_boundary": (
                    "Translate the user's non-English scientific concepts into concise "
                    "English retrieval terms and structured filters before calling search. "
                    "Do not translate identifiers, source evidence, or quoted spans."
                ),
            },
            filter_fields=filter_fields,
            question_types=[
                "background",
                "therapy",
                "harm_or_etiology",
                "diagnosis",
                "prognosis",
                "prevention",
                "prevalence",
                "mechanism",
                "patient_experience",
            ],
            unsupported_v3_dimensions=[
                "adverse_event_entities",
                "age_groups",
                "blinding",
                "comorbidities",
                "comparator",
                "dose",
                "duration",
                "formulation",
                "outcome_entities",
                "randomization",
                "route_of_administration",
                "sample_size",
                "sex_or_gender",
                "study_countries",
                "study_period",
            ],
            pagination={"cursor": "opaque", "default_limit": 10, "maximum_limit": 50},
            ranking={
                "order": [
                    "retrieval_confidence descending",
                    "publication_year descending",
                    "document_id ascending",
                ],
                "retrieval_confidence_semantics": (
                    "Deterministic heuristic ranking signal; not a calibrated probability "
                    "and not clinical evidence strength."
                ),
                "question_type_affects_ranking": False,
                "silent_filter_relaxation": False,
            },
        )
