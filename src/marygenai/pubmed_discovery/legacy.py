from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher

from marygenai.initial_load.files import normalize_title
from marygenai.pubmed_discovery.models import PubMedLegacyIndexRecord


@dataclass(frozen=True)
class LegacyMatch:
    identity_status: str
    match_type: str | None
    match_confidence: float
    legacy_document_ids: list[str]
    legacy_study_ids: list[str]
    review_reasons: list[str]


class PubMedLegacyIndex:
    def __init__(self, records: list[PubMedLegacyIndexRecord]) -> None:
        self.records = records
        self.by_pmid = _build_index(records, "pmid")
        self.by_pmcid = _build_index(records, "pmcid")
        self.by_doi = _build_index(records, "doi")
        self.by_canonical_url = _build_index(records, "canonical_url")
        self.by_normalized_title = _build_index(records, "normalized_title")
        self.max_publication_year = max(
            (record.publication_year for record in records if record.publication_year),
            default=None,
        )


def load_legacy_index_from_sqlite(connection: sqlite3.Connection) -> PubMedLegacyIndex:
    rows = connection.execute(
        """
        SELECT
            d.document_id,
            d.pmid,
            d.pmcid,
            d.doi,
            d.canonical_url,
            d.publication_year,
            p.legacy_study_id,
            p.normalized_title
        FROM document AS d
        JOIN publication AS p ON p.document_id = d.document_id
        WHERE d.review_state = 'trusted_legacy_reference'
        """
    ).fetchall()
    records = [
        PubMedLegacyIndexRecord(
            document_id=row["document_id"],
            legacy_study_id=row["legacy_study_id"],
            pmid=normalize_pmid(row["pmid"]),
            pmcid=normalize_pmcid(row["pmcid"]),
            doi=normalize_doi(row["doi"]),
            canonical_url=canonicalize_url(row["canonical_url"]),
            normalized_title=row["normalized_title"],
            publication_year=row["publication_year"],
        )
        for row in rows
    ]
    return PubMedLegacyIndex(records)


def classify_against_legacy(
    *,
    pmid: str,
    pmcid: str | None,
    doi: str | None,
    canonical_url: str,
    title: str | None,
    publication_year: int | None,
    index: PubMedLegacyIndex,
) -> LegacyMatch:
    normalized_record_title = normalize_title(title)
    exact_sources: list[tuple[str, list[PubMedLegacyIndexRecord]]] = []
    if pmid in index.by_pmid:
        exact_sources.append(("pmid", index.by_pmid[pmid]))
    normalized_pmcid = normalize_pmcid(pmcid)
    if normalized_pmcid and normalized_pmcid in index.by_pmcid:
        exact_sources.append(("pmcid", index.by_pmcid[normalized_pmcid]))
    normalized_doi = normalize_doi(doi)
    if normalized_doi and normalized_doi in index.by_doi:
        exact_sources.append(("doi", index.by_doi[normalized_doi]))
    normalized_url = canonicalize_url(canonical_url)
    if normalized_url and normalized_url in index.by_canonical_url:
        exact_sources.append(("canonical_url", index.by_canonical_url[normalized_url]))
    if normalized_record_title and normalized_record_title in index.by_normalized_title:
        exact_sources.append(
            ("normalized_title", index.by_normalized_title[normalized_record_title])
        )
    if exact_sources:
        records = [record for _, source_records in exact_sources for record in source_records]
        return _match(
            "in_legacy_exact",
            "+".join(source for source, _ in exact_sources),
            1.0,
            records,
        )

    if (
        publication_year
        and index.max_publication_year
        and publication_year > index.max_publication_year + 1
    ):
        return _new_candidate(doi=doi, pmcid=pmcid)

    title_ratio, content_overlap, title_records = _best_title_similarity(
        normalized_record_title,
        index,
    )
    if title_ratio >= 0.96 and content_overlap >= 0.85:
        return _match(
            "possible_legacy_match",
            "fuzzy_title",
            round(title_ratio, 4),
            title_records,
            ["high_title_similarity_without_identifier_match"],
        )
    if title_ratio >= 0.92 and content_overlap >= 0.75:
        return _match(
            "needs_manual_identity_review",
            "weak_fuzzy_title",
            round(title_ratio, 4),
            title_records,
            ["weak_title_similarity_without_identifier_match"],
        )
    return _new_candidate(doi=doi, pmcid=pmcid)


def normalize_doi(value: str | None) -> str | None:
    return value.strip().rstrip(").,;]").lower() if value else None


def normalize_pmcid(value: str | None) -> str | None:
    return value.strip().upper() if value else None


def normalize_pmid(value: str | None) -> str | None:
    return value.strip() if value else None


def canonicalize_url(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().rstrip("/")


def _build_index(
    records: list[PubMedLegacyIndexRecord],
    field_name: str,
) -> dict[str, list[PubMedLegacyIndexRecord]]:
    index: dict[str, list[PubMedLegacyIndexRecord]] = {}
    for record in records:
        value = getattr(record, field_name)
        if value:
            index.setdefault(value, []).append(record)
    return index


def _match(
    status: str,
    match_type: str | None,
    confidence: float,
    records: list[PubMedLegacyIndexRecord],
    reasons: list[str] | None = None,
) -> LegacyMatch:
    return LegacyMatch(
        identity_status=status,
        match_type=match_type,
        match_confidence=confidence,
        legacy_document_ids=sorted({record.document_id for record in records}),
        legacy_study_ids=sorted(
            {record.legacy_study_id for record in records if record.legacy_study_id}
        ),
        review_reasons=reasons or [],
    )


def _new_candidate(*, doi: str | None, pmcid: str | None) -> LegacyMatch:
    reasons = []
    if not doi and not pmcid:
        reasons.append("missing_doi_and_pmcid")
    return LegacyMatch(
        identity_status="new_candidate",
        match_type=None,
        match_confidence=0.0,
        legacy_document_ids=[],
        legacy_study_ids=[],
        review_reasons=reasons,
    )


GENERIC_TITLE_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "analysis",
    "controlled",
    "effect",
    "effects",
    "efficacy",
    "meta",
    "placebo",
    "randomized",
    "review",
    "safety",
    "study",
    "systematic",
    "treatment",
    "trial",
}


def _best_title_similarity(
    normalized_title: str | None,
    index: PubMedLegacyIndex,
) -> tuple[float, float, list[PubMedLegacyIndexRecord]]:
    if not normalized_title:
        return 0.0, 0.0, []
    best_ratio = 0.0
    best_content_overlap = 0.0
    best_records: list[PubMedLegacyIndexRecord] = []
    for legacy_title, records in index.by_normalized_title.items():
        ratio = SequenceMatcher(None, normalized_title, legacy_title).ratio()
        content_overlap = _title_content_overlap(normalized_title, legacy_title)
        if ratio > best_ratio:
            best_ratio = ratio
            best_content_overlap = content_overlap
            best_records = records
    return best_ratio, best_content_overlap, best_records


def _title_content_overlap(left_title: str, right_title: str) -> float:
    left_tokens = _content_title_tokens(left_title)
    right_tokens = _content_title_tokens(right_title)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _content_title_tokens(normalized_title: str) -> set[str]:
    return {
        token
        for token in normalized_title.split()
        if len(token) > 2 and token not in GENERIC_TITLE_TOKENS
    }
