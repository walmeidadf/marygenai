from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import duckdb

from marygenai.retrieval.common import normalize_match_key
from marygenai.retrieval.models import (
    FacetsResponse,
    FacetValue,
    MatchExplanation,
    ProjectedIdentity,
    RetrievalConfidence,
    SearchCapabilities,
    SearchRequest,
    SearchResponse,
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
    def _matched_filters(request: SearchRequest) -> list[str]:
        matched: list[str] = []
        for field_name in FILTER_FAMILIES:
            group = getattr(request.filters, field_name)
            if group:
                matched.append(f"{field_name} ({group.match}): {', '.join(group.values)}")
        if request.filters.publication_year_from is not None:
            matched.append(f"publication_year >= {request.filters.publication_year_from}")
        if request.filters.publication_year_to is not None:
            matched.append(f"publication_year <= {request.filters.publication_year_to}")
        if request.filters.has_uncertainty is not None:
            matched.append(f"has_uncertainty = {request.filters.has_uncertainty}")
        return matched

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
                    d.document_id, d.classification_id, d.title, d.doi, d.pmid, d.pmcid,
                    d.canonical_url, d.source_url, d.publication_year,
                    d.classification_confidence, d.retrieval_confidence_score,
                    d.retrieval_confidence_band, d.retrieval_confidence_version,
                    d.has_uncertainty, d.review_state, d.classification_json,
                    d.original_corpus_identity_json, d.projected_identity_json
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
        matched = self._matched_filters(request)
        for row in rows:
            classification = json.loads(row.pop("classification_json"))
            original_identity, projected_identity = self._identity_contract(row)
            results.append(
                StudySearchResult(
                    document_id=row["document_id"],
                    classification_id=row["classification_id"],
                    source_identity=self._source_identity(row),
                    original_corpus_identity=original_identity,
                    projected_identity=projected_identity,
                    retrieval_metadata={
                        "medical_conditions": classification["medical_conditions"],
                        "cannabinoids_or_exposures": classification["cannabinoids_or_exposures"],
                        "study_design_category": classification["study_design_category"],
                        "study_design_subtype": classification["study_design_subtype"],
                        "evidence_context": classification["evidence_context"],
                        "population_or_model": classification["population_or_model"],
                        "intervention_or_exposure_role": classification[
                            "intervention_or_exposure_role"
                        ],
                        "outcome_domains": classification["outcome_domains"],
                        "overall_direction": classification["overall_direction"],
                    },
                    classification_confidence=row["classification_confidence"],
                    retrieval_confidence=RetrievalConfidence(
                        score=row["retrieval_confidence_score"],
                        band=row["retrieval_confidence_band"],
                        version=row["retrieval_confidence_version"],
                    ),
                    has_uncertainty=row["has_uncertainty"],
                    review_state=row["review_state"],
                    trust_boundary=TrustBoundary(),
                    match=MatchExplanation(
                        matched=matched,
                        uncertain_fields=classification["missing_or_uncertain_fields"],
                        not_represented=request.unsupported_dimensions,
                    ),
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
