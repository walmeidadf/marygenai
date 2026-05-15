from __future__ import annotations

from pathlib import Path
from typing import Any

from marygenai.initial_load.files import clean_value, normalize_title, read_csv_rows, stable_hash
from marygenai.initial_load.identity import (
    canonicalize_url,
    extract_doi,
    extract_pmcid,
    extract_pmid,
    stable_document_id,
)
from marygenai.schemas import (
    CanonicalPublicationCandidate,
    LegacySourceRecord,
    Provenance,
    PublicationIdentity,
)

LEGACY_STUDY_ID_FIELD = "ID do Estudo"
TITLE_PT_FIELD = "Título"
TITLE_EN_FIELD = "Título do artigo em inglês"
URL_FIELD = "URL do estudo"
YEAR_FIELD = "Ano de Publicação"
STUDY_TYPE_FIELD = "Tipo de Estudo"
RESULT_FIELD = "Resultado do Estudo"


def parse_year(value: str | None) -> int | None:
    cleaned = clean_value(value)
    if not cleaned:
        return None
    try:
        year = int(cleaned)
    except ValueError:
        return None
    return year if 1500 <= year <= 2100 else None


def build_legacy_source_record(
    *,
    row: dict[str, str],
    row_number: int,
    source_file: Path,
    run_id: str,
) -> LegacySourceRecord:
    legacy_id = clean_value(row.get(LEGACY_STUDY_ID_FIELD))
    payload_hash = stable_hash(row)
    return LegacySourceRecord(
        source_record_id=f"legacy_cannadocs:studies:{legacy_id or row_number}",
        source_table="studies",
        legacy_id=legacy_id,
        row_number=row_number,
        payload_hash=payload_hash,
        raw_payload=row,
        provenance=Provenance(
            source="legacy_cannadocs",
            source_file=str(source_file),
            source_row_number=row_number,
            method="legacy_initial_load",
            run_id=run_id,
        ),
    )


def build_publication_candidate(
    *,
    row: dict[str, str],
    row_number: int,
    source_file: Path,
    run_id: str,
) -> CanonicalPublicationCandidate:
    legacy_study_id = clean_value(row.get(LEGACY_STUDY_ID_FIELD)) or str(row_number)
    title_pt = clean_value(row.get(TITLE_PT_FIELD))
    title_en = clean_value(row.get(TITLE_EN_FIELD))
    primary_title = title_en or title_pt
    normalized_title = normalize_title(primary_title)
    canonical_url = canonicalize_url(clean_value(row.get(URL_FIELD)))
    pmid = extract_pmid(canonical_url)
    pmcid = extract_pmcid(canonical_url)
    doi = extract_doi(canonical_url)
    document_id = stable_document_id(
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        canonical_url=canonical_url,
        title=primary_title,
        legacy_study_id=legacy_study_id,
    )

    identities = build_identities(
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        canonical_url=canonical_url,
        normalized_title=normalized_title,
        legacy_study_id=legacy_study_id,
    )

    return CanonicalPublicationCandidate(
        document_id=document_id,
        primary_title=primary_title,
        title_pt=title_pt,
        title_en=title_en,
        normalized_title=normalized_title,
        publication_year=parse_year(row.get(YEAR_FIELD)),
        canonical_url=canonical_url,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        legacy_study_id=legacy_study_id,
        legacy_study_type=clean_value(row.get(STUDY_TYPE_FIELD)),
        legacy_result=clean_value(row.get(RESULT_FIELD)),
        legacy_reference_values=legacy_reference_values(row),
        identities=identities,
        provenance=Provenance(
            source="legacy_cannadocs",
            source_file=str(source_file),
            source_row_number=row_number,
            method="legacy_initial_load",
            run_id=run_id,
        ),
    )


def build_identities(
    *,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
    canonical_url: str | None,
    normalized_title: str | None,
    legacy_study_id: str,
) -> list[PublicationIdentity]:
    identity_values = [
        ("pmid", pmid, 1.0),
        ("pmcid", pmcid, 0.98),
        ("doi", doi, 0.98),
        ("canonical_url", canonical_url, 0.85),
        ("normalized_title", normalized_title, 0.7),
        ("legacy_id", legacy_study_id, 1.0),
    ]
    return [
        PublicationIdentity(
            identifier_type=identifier_type,
            identifier_value=value,
            confidence=confidence,
            association_state=(
                "trusted_legacy_reference"
                if identifier_type in {"pmid", "pmcid", "doi", "legacy_id"}
                else "needs_manual_identity_review"
            ),
        )
        for identifier_type, value, confidence in identity_values
        if value
    ]


def legacy_reference_values(row: dict[str, str]) -> dict[str, Any]:
    return {
        key: value.strip()
        for key, value in row.items()
        if value is not None and value.strip()
    }


def import_legacy_studies(
    *,
    studies_path: Path,
    run_id: str,
) -> tuple[list[LegacySourceRecord], list[CanonicalPublicationCandidate], dict[str, str]]:
    source_records: list[LegacySourceRecord] = []
    publications: list[CanonicalPublicationCandidate] = []
    legacy_id_to_document_id: dict[str, str] = {}

    for row_number, row in read_csv_rows(studies_path):
        source_records.append(
            build_legacy_source_record(
                row=row,
                row_number=row_number,
                source_file=studies_path,
                run_id=run_id,
            )
        )
        publication = build_publication_candidate(
            row=row,
            row_number=row_number,
            source_file=studies_path,
            run_id=run_id,
        )
        publications.append(publication)
        legacy_id_to_document_id[publication.legacy_study_id] = publication.document_id

    return source_records, publications, legacy_id_to_document_id
