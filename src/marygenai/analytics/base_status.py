from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from marygenai.initial_load.files import clean_value

DEFAULT_LEGACY_ENGLISH_GLOB = (
    "data/normalized/legacy_identity_validation/*_identity_confirmed_for_triage.jsonl"
)
CONDITION_FIELD = "Condições Médicas"
TITLE_PT_FIELD = "Título"
TITLE_EN_FIELD = "Título do artigo em inglês"
CONCLUSIONS_FIELD = "Principais Conclusões"
STUDY_TYPE_FIELD = "Tipo de Estudo"
RESULT_FIELD = "Resultado do Estudo"
YEAR_FIELD = "Ano de Publicação"
URL_FIELD = "URL do estudo"
CANNABINOID_FIELDS = ("Canabinoides", "Canabinóides", "Canabinóides Estudados")
SAMPLE_SIZE_FIELD = "Tamanho da Amostra do Estudo"

PRIORITY_STUDY_TYPES = (
    "Metanálise",
    "Metanálise Clínica",
    "Ensaio Clínico",
    "Ensaio Clínico Duplo-Cego",
)
OPEN_ACCESS_CLASSES = {
    "open_access_gold",
    "open_access_green",
    "open_access_hybrid",
    "open_access_bronze",
}


@dataclass(frozen=True)
class LegacyStudyRecord:
    document_id: str | None
    legacy_id: str | None
    raw_payload: dict[str, Any]
    title_pt: str | None
    title_en: str | None
    legacy_study_type: str | None
    legacy_result: str | None
    publication_year: int | None
    canonical_url: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None


def build_base_status_report(
    database_path: Path,
    *,
    legacy_csv_path: Path | None = None,
    legacy_english_path: Path | None = None,
    condition: str | None = None,
    top: int = 25,
) -> dict[str, Any]:
    """Build a read-only status report from SQLite plus optional legacy CSV fallback."""
    legacy_csv_path = legacy_csv_path or Path("temp/legacy/cannadocs/Estudos-Grid view.csv")
    with _connect_read_only(database_path) as connection:
        legacy_records = _load_legacy_study_records(connection)
        source = "sqlite.source_record"
        if not legacy_records and legacy_csv_path.exists():
            legacy_records = _load_legacy_study_records_from_csv(legacy_csv_path)
            source = "legacy_csv_fallback"

        legacy_document_ids = {
            record.document_id for record in legacy_records if record.document_id
        }
        overview = _overview(connection, legacy_records, legacy_document_ids)
        bibliography = _bibliographic_identity(legacy_records)
        canonical_urls = _canonical_urls(connection, legacy_records)
        descriptive = _descriptive_evidence(legacy_records)
        study_types = _study_types(legacy_records)
        access = _access_enrichment(connection, legacy_document_ids)
        conditions = _conditions(connection, legacy_records, condition=condition, top=top)
        legacy_english = _legacy_english_reference(
            connection,
            legacy_english_path=legacy_english_path,
            condition=condition,
            top=top,
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "database_path": str(database_path),
        "legacy_study_source": source,
        "notes": [
            "This report is read-only and does not alter SQLite or legacy files.",
            "Legacy rows from source_record/source_table=studies are trusted bootstrap records.",
            "PubMed discovery candidates are candidate evidence until human review.",
            "Access enrichment artifacts currently cover PubMed candidates "
            "and may not cover all legacy records.",
            "Open access inferred from PMCID/PMC is reported separately "
            "from artifact-confirmed access.",
        ],
        "overview": overview,
        "bibliographic_identity": bibliography,
        "canonical_url": canonical_urls,
        "legacy_descriptive_evidence": descriptive,
        "study_type": study_types,
        "access_open_download": access,
        "conditions": conditions,
        "legacy_english_reference": legacy_english,
    }


def write_report_json(report: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def default_output_path(data_dir: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return data_dir / "normalized" / "analytics" / "base_status" / f"{timestamp}_base_status.json"


@contextmanager
def _connect_read_only(database_path: Path) -> Iterator[sqlite3.Connection]:
    if not database_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")
    uri = f"file:{database_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _load_legacy_study_records(
    connection: sqlite3.Connection,
) -> list[LegacyStudyRecord]:
    if not _table_exists(connection, "source_record") or not _table_exists(
        connection, "publication"
    ):
        return []
    rows = connection.execute(
        """
        SELECT
            sr.legacy_id,
            sr.raw_payload_json,
            p.document_id,
            p.title_pt,
            p.title_en,
            p.legacy_study_type,
            p.legacy_result,
            p.legacy_reference_values_json,
            d.publication_year,
            d.canonical_url,
            d.pmid,
            d.pmcid,
            d.doi
        FROM source_record AS sr
        LEFT JOIN publication AS p ON p.legacy_study_id = sr.legacy_id
        LEFT JOIN document AS d ON d.document_id = p.document_id
        WHERE sr.source_table = 'studies'
        ORDER BY sr.row_number
        """
    ).fetchall()
    records: list[LegacyStudyRecord] = []
    for row in rows:
        raw_payload = _loads_object(row["raw_payload_json"])
        reference_values = _loads_object(row["legacy_reference_values_json"])
        merged_payload = {**raw_payload, **reference_values}
        records.append(
            LegacyStudyRecord(
                document_id=row["document_id"],
                legacy_id=row["legacy_id"],
                raw_payload=merged_payload,
                title_pt=_clean(row["title_pt"]) or _payload_value(merged_payload, TITLE_PT_FIELD),
                title_en=_clean(row["title_en"]) or _payload_value(merged_payload, TITLE_EN_FIELD),
                legacy_study_type=_clean(row["legacy_study_type"])
                or _payload_value(merged_payload, STUDY_TYPE_FIELD),
                legacy_result=_clean(row["legacy_result"])
                or _payload_value(merged_payload, RESULT_FIELD),
                publication_year=row["publication_year"]
                or _safe_int(_payload_value(merged_payload, YEAR_FIELD)),
                canonical_url=_clean(row["canonical_url"])
                or _payload_value(merged_payload, URL_FIELD),
                pmid=_clean(row["pmid"]),
                pmcid=_clean(row["pmcid"]),
                doi=_clean(row["doi"]),
            )
        )
    return records


def _load_legacy_study_records_from_csv(path: Path) -> list[LegacyStudyRecord]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    records: list[LegacyStudyRecord] = []
    for index, row in enumerate(rows, start=2):
        legacy_id = _payload_value(row, "ID do Estudo") or str(index)
        records.append(
            LegacyStudyRecord(
                document_id=None,
                legacy_id=legacy_id,
                raw_payload={key: value for key, value in row.items() if value},
                title_pt=_payload_value(row, TITLE_PT_FIELD),
                title_en=_payload_value(row, TITLE_EN_FIELD),
                legacy_study_type=_payload_value(row, STUDY_TYPE_FIELD),
                legacy_result=_payload_value(row, RESULT_FIELD),
                publication_year=_safe_int(_payload_value(row, YEAR_FIELD)),
                canonical_url=_payload_value(row, URL_FIELD),
                pmid=None,
                pmcid=None,
                doi=None,
            )
        )
    return records


def _overview(
    connection: sqlite3.Connection,
    legacy_records: list[LegacyStudyRecord],
    legacy_document_ids: set[str],
) -> dict[str, Any]:
    return {
        "legacy_study_source_rows": _count_source_studies(connection),
        "legacy_unique_documents": len(legacy_document_ids)
        or len({r.legacy_id for r in legacy_records}),
        "sqlite_documents": _count_table(connection, "document"),
        "document_review_state_counts": _count_group(connection, "document", "review_state"),
        "review_queue_counts": _review_queue_counts(connection),
    }


def _bibliographic_identity(records: list[LegacyStudyRecord]) -> dict[str, Any]:
    total = len(records)
    with_pmid = sum(1 for record in records if record.pmid)
    with_pmcid = sum(1 for record in records if record.pmcid)
    with_doi = sum(1 for record in records if record.doi)
    with_strong = sum(1 for record in records if _has_strong_identifier(record))
    return {
        "total_legacy_records": total,
        "with_pmid": _count_percent(with_pmid, total),
        "with_pmcid": _count_percent(with_pmcid, total),
        "with_doi": _count_percent(with_doi, total),
        "with_any_strong_identifier": _count_percent(with_strong, total),
        "without_strong_identifier": _count_percent(total - with_strong, total),
    }


def _canonical_urls(
    connection: sqlite3.Connection,
    records: list[LegacyStudyRecord],
) -> dict[str, Any]:
    urls = [record.canonical_url for record in records if record.canonical_url]
    return {
        "with_canonical_url": len(urls),
        "pubmed_urls": sum(1 for url in urls if "pubmed.ncbi.nlm.nih.gov" in url),
        "pmc_urls": sum(1 for url in urls if "pmc.ncbi.nlm.nih.gov" in url),
        "doi_urls": sum(1 for url in urls if "doi.org/" in url),
        "science_direct_urls": sum(1 for url in urls if "sciencedirect.com" in url),
        "science_direct_with_pii": sum(
            1 for url in urls if "sciencedirect.com" in url and "/pii/" in url
        ),
        "science_direct_abs_pii": sum(
            1 for url in urls if "sciencedirect.com" in url and "/abs/pii/" in url
        ),
        "top_problem_domains_in_legacy_identity_review": _top_problem_domains(connection),
    }


def _descriptive_evidence(records: list[LegacyStudyRecord]) -> dict[str, Any]:
    total = len(records)
    counts = {
        "title_pt": sum(1 for record in records if record.title_pt),
        "title_en": sum(1 for record in records if record.title_en),
        "main_conclusions": sum(
            1 for record in records if _payload_value(record.raw_payload, CONCLUSIONS_FIELD)
        ),
        "study_type": sum(1 for record in records if record.legacy_study_type),
        "result": sum(1 for record in records if record.legacy_result),
        "year": sum(1 for record in records if record.publication_year),
        "url": sum(1 for record in records if record.canonical_url),
        "medical_conditions": sum(1 for record in records if _conditions_for_record(record)),
        "cannabinoids": sum(
            1 for record in records if _first_payload_value(record.raw_payload, CANNABINOID_FIELDS)
        ),
        "sample_size": sum(
            1 for record in records if _payload_value(record.raw_payload, SAMPLE_SIZE_FIELD)
        ),
    }
    strong = sum(
        1
        for record in records
        if record.title_pt or record.title_en
        if _payload_value(record.raw_payload, CONCLUSIONS_FIELD)
        if record.legacy_study_type
        if record.legacy_result
        if record.publication_year
        if record.canonical_url
    )
    return {
        "total_legacy_records": total,
        "field_counts": {key: _count_percent(value, total) for key, value in counts.items()},
        "strong_descriptive_evidence": _count_percent(strong, total),
    }


def _study_types(records: list[LegacyStudyRecord]) -> dict[str, Any]:
    total = len(records)
    type_counts = Counter(record.legacy_study_type or "Unknown" for record in records)
    cross_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        cross_counts[record.legacy_study_type or "Unknown"][record.legacy_result or "Unknown"] += 1
    return {
        "counts": [
            {"study_type": study_type, **_count_percent(count, total)}
            for study_type, count in type_counts.most_common()
        ],
        "study_type_by_result": {
            study_type: dict(result_counts.most_common())
            for study_type, result_counts in sorted(cross_counts.items())
        },
    }


def _access_enrichment(
    connection: sqlite3.Connection,
    legacy_document_ids: set[str],
) -> dict[str, Any]:
    if not _table_exists(connection, "access_enrichment_artifact"):
        return _empty_access_report()
    rows = connection.execute(
        """
        SELECT document_id, artifact_type, access_class, errors_json
        FROM access_enrichment_artifact
        """
    ).fetchall()
    artifact_document_ids = {row["document_id"] for row in rows}
    open_artifact_document_ids = {
        row["document_id"]
        for row in rows
        if row["artifact_type"] in {"pmc_nxml", "europe_pmc_full_text_xml"}
        or row["access_class"] in OPEN_ACCESS_CLASSES
    }
    access_class_counts = Counter(row["access_class"] for row in rows)
    errors = sum(1 for row in rows if _loads_list(row["errors_json"]))
    pmcid_legacy = _count_legacy_pmcid_open_inference(connection, legacy_document_ids)
    return {
        "documents_with_access_enrichment_artifact": len(artifact_document_ids),
        "documents_with_open_access_artifact": len(open_artifact_document_ids),
        "documents_with_open_access_xml": len(
            {
                row["document_id"]
                for row in rows
                if row["artifact_type"] in {"pmc_nxml", "europe_pmc_full_text_xml"}
            }
        ),
        "open_access_gold": access_class_counts.get("open_access_gold", 0),
        "open_access_green": access_class_counts.get("open_access_green", 0),
        "open_access_hybrid": access_class_counts.get("open_access_hybrid", 0),
        "open_access_bronze": access_class_counts.get("open_access_bronze", 0),
        "closed_or_unknown_access": access_class_counts.get("closed_or_unknown_access", 0),
        "artifact_rows_with_errors": errors,
        "legacy_documents_with_pmcid_open_access_inference": pmcid_legacy,
        "scope_note": (
            "Access enrichment artifacts are produced for PubMed candidates and do not necessarily "
            "cover the full trusted legacy bootstrap."
        ),
    }


def _conditions(
    connection: sqlite3.Connection,
    records: list[LegacyStudyRecord],
    *,
    condition: str | None,
    top: int,
) -> dict[str, Any]:
    normalized_filter = _normalize_condition(condition) if condition else None
    access_open_ids = _open_access_artifact_document_ids(connection)
    buckets: dict[str, list[LegacyStudyRecord]] = defaultdict(list)
    for record in records:
        for medical_condition in _conditions_for_record(record):
            if normalized_filter and _normalize_condition(medical_condition) != normalized_filter:
                continue
            buckets[medical_condition].append(record)

    ranked = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0].casefold()))
    if not normalized_filter:
        ranked = ranked[:top]
    return {
        "filter": condition,
        "top": top,
        "total_conditions": len(buckets),
        "items": [
            _condition_summary(name, condition_records, access_open_ids)
            for name, condition_records in ranked
        ],
    }


def _legacy_english_reference(
    connection: sqlite3.Connection,
    *,
    legacy_english_path: Path | None,
    condition: str | None,
    top: int,
) -> dict[str, Any]:
    resolved_path = legacy_english_path or _latest_legacy_english_reference_path()
    if resolved_path is None or not resolved_path.exists():
        return {
            "available": False,
            "path": str(resolved_path) if resolved_path else None,
            "note": "No normalized English legacy reference file was found.",
        }

    records = _load_jsonl_objects(resolved_path)
    access_document_ids = _access_artifact_document_ids(connection)
    open_access_document_ids = _open_access_artifact_document_ids(connection)
    filtered_pathologies = _rank_filename_topics(
        records,
        prefix="medical-condition-thc-cbd-for-",
        suffix="-studies-",
        top=top,
        exact_filter=condition,
    )
    return {
        "available": True,
        "path": str(resolved_path),
        "total_records": len(records),
        "identity_confirmation_status_counts": dict(
            Counter(record.get("identity_confirmation_status") or "unknown" for record in records)
            .most_common()
        ),
        "field_coverage": _legacy_english_field_coverage(records),
        "study_type_counts": dict(
            Counter(record.get("type_of_study") or "missing" for record in records).most_common()
        ),
        "study_result_counts": dict(
            Counter(record.get("study_result") or "missing" for record in records).most_common()
        ),
        "access_progress": _legacy_english_access_progress(
            records,
            access_document_ids=access_document_ids,
            open_access_document_ids=open_access_document_ids,
        ),
        "top_pathologies": filtered_pathologies
        if condition
        else _rank_filename_topics(
            records,
            prefix="medical-condition-thc-cbd-for-",
            suffix="-studies-",
            top=top,
        ),
        "top_organ_systems": _rank_filename_topics(
            records,
            prefix="by-organ-system-thc-cbd-for-",
            suffix="-system-studies-",
            top=top,
            label_suffix=" system",
        ),
        "top_cannabinoids": _rank_list_field(records, "Cannabinoids Studied", top=top),
        "top_terpenes": _rank_list_field(records, "Terpenes Studied", top=top),
        "top_receptors": _rank_list_field(records, "Receptors Studied", top=top),
        "top_locations": _rank_list_field(records, "Study Location(s)", top=top),
        "condition_filter": condition,
    }


def _legacy_english_field_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    direct_fields = {
        "title": lambda record: record.get("title"),
        "publication_year": lambda record: record.get("publication_year"),
        "type_of_study": lambda record: record.get("type_of_study"),
        "study_result": lambda record: record.get("study_result"),
        "study_sample_size": lambda record: record.get("study_sample_size"),
        "key_findings": lambda record: record.get("key_findings"),
        "pmid": lambda record: record.get("pmid"),
        "pmcid": lambda record: record.get("pmcid"),
        "doi": lambda record: record.get("doi"),
        "canonical_url": lambda record: record.get("canonical_url"),
    }
    list_fields = {
        "study_locations": "Study Location(s)",
        "cannabinoids": "Cannabinoids Studied",
        "phytocannabinoid_source": "Phytocannabinoid Source",
        "route_of_administration": "Route of Administration",
        "chemotype": "Chemotype",
        "receptors": "Receptors Studied",
        "ligands": "Ligands Studied",
        "terpenes": "Terpenes Studied",
        "dosing_objective": "Study Dosing Objective",
        "dosing_regimen": "Dosing Regimen",
        "treatment_duration": "Treatment Duration",
        "clinical_relevance": "Clinical Relevance",
        "adverse_events": "Adverse Events",
    }
    text_fields = {
        "dosage": "Dosage",
        "starting_dose": "Starting Dose",
        "maximum_dose": "Maximum Dose",
        "additional_notes": "Additional Notes",
    }
    coverage = {
        name: _count_percent(
            sum(1 for record in records if value_getter(record)),
            total,
        )
        for name, value_getter in direct_fields.items()
    }
    coverage.update(
        {
            name: _count_percent(
                sum(1 for record in records if (record.get("list_fields") or {}).get(field)),
                total,
            )
            for name, field in list_fields.items()
        }
    )
    coverage.update(
        {
            name: _count_percent(
                sum(1 for record in records if (record.get("text_fields") or {}).get(field)),
                total,
            )
            for name, field in text_fields.items()
        }
    )
    return coverage


def _legacy_english_access_progress(
    records: list[dict[str, Any]],
    *,
    access_document_ids: set[str],
    open_access_document_ids: set[str],
) -> dict[str, Any]:
    total = len(records)
    pmcid_records = [record for record in records if record.get("pmcid")]
    doi_without_pmcid = [
        record for record in records if record.get("doi") and not record.get("pmcid")
    ]
    pmid_only = [
        record
        for record in records
        if record.get("pmid") and not record.get("pmcid") and not record.get("doi")
    ]
    return {
        "records_with_any_access_artifact": _count_percent(
            sum(1 for record in records if record.get("document_id") in access_document_ids),
            total,
        ),
        "records_with_open_access_xml_or_artifact": _count_percent(
            sum(1 for record in records if record.get("document_id") in open_access_document_ids),
            total,
        ),
        "pmcid_candidates": _count_percent(len(pmcid_records), total),
        "pmcid_candidates_with_any_access_artifact": _count_percent(
            sum(
                1
                for record in pmcid_records
                if record.get("document_id") in access_document_ids
            ),
            len(pmcid_records),
        ),
        "pmcid_candidates_remaining": len(
            [
                record
                for record in pmcid_records
                if record.get("document_id") not in access_document_ids
            ]
        ),
        "doi_without_pmcid_candidates": _count_percent(len(doi_without_pmcid), total),
        "pmid_only_candidates": _count_percent(len(pmid_only), total),
    }


def _condition_summary(
    condition: str,
    records: list[LegacyStudyRecord],
    access_open_ids: set[str],
) -> dict[str, Any]:
    study_type_counts = Counter(record.legacy_study_type or "Unknown" for record in records)
    return {
        "condition": condition,
        "total_studies": len(records),
        "study_type_counts": dict(study_type_counts.most_common()),
        "meta_analysis": study_type_counts.get("Metanálise", 0),
        "clinical_meta_analysis": study_type_counts.get("Metanálise Clínica", 0),
        "clinical_trial": study_type_counts.get("Ensaio Clínico", 0),
        "double_blind_clinical_trial": study_type_counts.get("Ensaio Clínico Duplo-Cego", 0),
        "with_pmid_pmcid_or_doi": sum(1 for record in records if _has_strong_identifier(record)),
        "with_pmcid": sum(1 for record in records if record.pmcid),
        "with_open_access_artifact": sum(
            1 for record in records if record.document_id and record.document_id in access_open_ids
        ),
    }


def _review_queue_counts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(connection, "review_item"):
        return []
    rows = connection.execute(
        """
        SELECT queue_type, status, COUNT(*) AS count
        FROM review_item
        GROUP BY queue_type, status
        ORDER BY queue_type, status
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _top_problem_domains(connection: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    if not _table_exists(connection, "review_item"):
        return []
    rows = connection.execute(
        """
        SELECT d.canonical_url
        FROM review_item AS ri
        JOIN document AS d ON d.document_id = ri.document_id
        WHERE ri.queue_type = 'legacy_identity_review'
          AND ri.status IN ('open', 'in_review')
          AND d.canonical_url IS NOT NULL
        """
    ).fetchall()
    counter = Counter(
        _domain(row["canonical_url"]) for row in rows if _domain(row["canonical_url"])
    )
    return [{"domain": domain, "count": count} for domain, count in counter.most_common(limit)]


def _open_access_artifact_document_ids(connection: sqlite3.Connection) -> set[str]:
    if not _table_exists(connection, "access_enrichment_artifact"):
        return set()
    rows = connection.execute(
        """
        SELECT DISTINCT document_id
        FROM access_enrichment_artifact
        WHERE artifact_type IN ('pmc_nxml', 'europe_pmc_full_text_xml')
           OR access_class IN (
                'open_access_gold',
                'open_access_green',
                'open_access_hybrid',
                'open_access_bronze'
           )
        """
    ).fetchall()
    return {row["document_id"] for row in rows}


def _access_artifact_document_ids(connection: sqlite3.Connection) -> set[str]:
    if not _table_exists(connection, "access_enrichment_artifact"):
        return set()
    rows = connection.execute(
        "SELECT DISTINCT document_id FROM access_enrichment_artifact"
    ).fetchall()
    return {row["document_id"] for row in rows}


def _count_source_studies(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "source_record"):
        return 0
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM source_record WHERE source_table = 'studies'"
        ).fetchone()[0]
    )


def _count_table(connection: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(connection, table_name):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])


def _count_group(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> dict[str, int]:
    if not _table_exists(connection, table_name):
        return {}
    rows = connection.execute(
        f"""
        SELECT {column_name} AS key, COUNT(*) AS count
        FROM {table_name}
        GROUP BY {column_name}
        ORDER BY {column_name}
        """
    ).fetchall()
    return {row["key"]: row["count"] for row in rows}


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _count_legacy_pmcid_open_inference(
    connection: sqlite3.Connection,
    legacy_document_ids: set[str],
) -> int:
    if not legacy_document_ids:
        return 0
    placeholders = ",".join("?" for _ in legacy_document_ids)
    row = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM document
        WHERE document_id IN ({placeholders})
          AND pmcid IS NOT NULL
          AND TRIM(pmcid) != ''
        """,
        tuple(legacy_document_ids),
    ).fetchone()
    return int(row[0])


def _empty_access_report() -> dict[str, Any]:
    return {
        "documents_with_access_enrichment_artifact": 0,
        "documents_with_open_access_artifact": 0,
        "documents_with_open_access_xml": 0,
        "open_access_gold": 0,
        "open_access_green": 0,
        "open_access_hybrid": 0,
        "open_access_bronze": 0,
        "closed_or_unknown_access": 0,
        "artifact_rows_with_errors": 0,
        "legacy_documents_with_pmcid_open_access_inference": 0,
        "scope_note": "Access enrichment artifact table is not available.",
    }


def _conditions_for_record(record: LegacyStudyRecord) -> list[str]:
    raw_value = _payload_value(record.raw_payload, CONDITION_FIELD)
    if not raw_value:
        return []
    conditions = []
    seen = set()
    for value in raw_value.split(","):
        normalized = " ".join(value.split())
        key = _normalize_condition(normalized)
        if normalized and key not in seen:
            conditions.append(normalized)
            seen.add(key)
    return conditions


def _has_strong_identifier(record: LegacyStudyRecord) -> bool:
    return bool(record.pmid or record.pmcid or record.doi)


def _count_percent(count: int, total: int) -> dict[str, Any]:
    percent = round((count / total * 100), 2) if total else 0.0
    return {"count": count, "percent": percent}


def _payload_value(payload: dict[str, Any], key: str) -> str | None:
    return _clean(payload.get(key))


def _first_payload_value(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _payload_value(payload, key)
        if value:
            return value
    return None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    return clean_value(str(value))


def _safe_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _loads_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def _load_jsonl_objects(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _latest_legacy_english_reference_path() -> Path | None:
    paths = sorted(Path().glob(DEFAULT_LEGACY_ENGLISH_GLOB))
    return paths[-1] if paths else None


def _rank_list_field(
    records: list[dict[str, Any]],
    field: str,
    *,
    top: int,
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        counter.update((record.get("list_fields") or {}).get(field) or [])
    return [{"value": value, "count": count} for value, count in counter.most_common(top)]


def _rank_filename_topics(
    records: list[dict[str, Any]],
    *,
    prefix: str,
    suffix: str,
    top: int,
    exact_filter: str | None = None,
    label_suffix: str = "",
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    normalized_filter = _normalize_condition(exact_filter) if exact_filter else None
    for record in records:
        seen_for_record = set()
        for filename in record.get("source_filenames") or []:
            topic = _topic_from_filename(
                filename,
                prefix=prefix,
                suffix=suffix,
                label_suffix=label_suffix,
            )
            if not topic:
                continue
            topic_key = _normalize_condition(topic)
            if normalized_filter and topic_key != normalized_filter:
                continue
            if topic_key in seen_for_record:
                continue
            counter[topic] += 1
            seen_for_record.add(topic_key)
    return [{"value": value, "count": count} for value, count in counter.most_common(top)]


def _topic_from_filename(
    filename: str,
    *,
    prefix: str,
    suffix: str,
    label_suffix: str,
) -> str | None:
    stem = Path(filename).name
    if not stem.startswith(prefix):
        return None
    remainder = stem.removeprefix(prefix)
    if suffix not in remainder:
        return None
    slug = remainder.split(suffix, 1)[0]
    label = " ".join(part for part in slug.split("-") if part)
    if not label:
        return None
    return f"{label}{label_suffix}".title()


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower().removeprefix("www.")


def _normalize_condition(value: str | None) -> str:
    return " ".join((value or "").casefold().split())
