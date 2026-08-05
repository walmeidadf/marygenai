from __future__ import annotations

import hashlib
import html as stdlib_html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from lxml import etree, html
from pydantic import BaseModel

from marygenai.classification.pipeline import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_SOURCE_CHARS,
    build_classification_prompt_packets,
)
from marygenai.classification_corpus.models import (
    ClassificationCorpusRecord,
    PubMedArtifactQualityAssessment,
    PubMedCanaryIdentity,
    PubMedCanaryManifestRecord,
    PubMedCanaryOrigin,
    PubMedSourceQualityRecord,
)
from marygenai.classification_corpus.pipeline import (
    CANNABINOID_TERMS,
    MIN_CLASSIFICATION_TEXT_CHARS,
    SCIENTIFIC_SECTION_TERMS,
    count_term_hits,
    new_run_id,
    normalize_text,
    resolve_data_path,
)
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

DEFAULT_CORPUS_VERSION = "pubmed_2024plus_canary.v1"
DEFAULT_TARGET_SIZE = 100
OPEN_ARTIFACT_TYPES = {"pmc_nxml", "pmc_html", "europe_pmc_full_text_xml"}
OPEN_ACCESS_CLASSES = {"open_access_xml", "open_access_html"}
CHALLENGE_MARKERS = {
    "recaptchachallengepageui",
    "recaptcha/challengepage",
    "boq-recaptcha",
    "window['ppconfig']",
    'window["ppconfig"]',
}
SELECTION_CRITERIA = [
    "publication_year_at_least_2024",
    "direct_title_or_indexed_cannabinoid_focus",
    "identity_status_not_manual_review",
    "review_state_needs_review",
    "local_open_xml_or_html_artifact",
    "stored_artifact_sha256_matches_file",
    "artifact_title_matches_candidate_title",
    "artifact_pmid_or_doi_matches_candidate_identity",
    f"extracted_text_at_least_{MIN_CLASSIFICATION_TEXT_CHARS}_characters",
    "at_least_two_scientific_section_signals",
    "at_least_one_cannabinoid_term_signal",
]


def read_only_connection(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def protected_state_snapshot(database_path: Path) -> dict[str, Any]:
    with read_only_connection(database_path) as connection:
        return {
            "database_sha256": file_sha256(database_path),
            "document_review_state_counts": dict(
                connection.execute(
                    "SELECT review_state, COUNT(*) FROM document GROUP BY review_state"
                ).fetchall()
            ),
            "review_item_count": connection.execute(
                "SELECT COUNT(*) FROM review_item"
            ).fetchone()[0],
            "review_item_status_counts": dict(
                connection.execute(
                    "SELECT status, COUNT(*) FROM review_item GROUP BY status"
                ).fetchall()
            ),
            "review_decision_count": connection.execute(
                "SELECT COUNT(*) FROM review_decision"
            ).fetchone()[0],
        }


def load_candidate_artifact_rows(database_path: Path) -> list[sqlite3.Row]:
    with read_only_connection(database_path) as connection:
        return connection.execute(
            """
            SELECT
                discovery.document_id,
                document.primary_title,
                document.publication_year,
                document.pmid,
                document.pmcid,
                document.doi,
                document.canonical_url,
                document.review_state,
                discovery.identity_status,
                discovery.cannabinoid_focus,
                discovery.study_design,
                discovery.study_design_rank,
                discovery.priority_score,
                artifact.artifact_id,
                artifact.source AS artifact_source,
                artifact.artifact_type,
                artifact.access_class,
                artifact.url AS artifact_url,
                artifact.payload_path,
                artifact.payload_sha256,
                artifact.payload_size_bytes,
                artifact.run_id AS artifact_run_id,
                artifact.created_at AS artifact_created_at
            FROM publication_candidate_discovery AS discovery
            JOIN document ON document.document_id = discovery.document_id
            LEFT JOIN access_enrichment_artifact AS artifact
                ON artifact.document_id = discovery.document_id
                AND artifact.artifact_type IN (
                    'pmc_nxml', 'pmc_html', 'europe_pmc_full_text_xml'
                )
                AND artifact.access_class IN ('open_access_xml', 'open_access_html')
                AND artifact.payload_path IS NOT NULL
            ORDER BY discovery.document_id, artifact.artifact_id
            """
        ).fetchall()


def normalized_identity_text(value: str | None) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        stdlib_html.unescape(value or "").casefold(),
    ).strip()


def normalized_doi(value: str | None) -> str:
    return (value or "").casefold().removeprefix("https://doi.org/").strip()


def local_name(element: etree._Element) -> str:
    return etree.QName(element).localname.casefold()


def detect_format(body: bytes) -> str:
    preview = body[:8_000].decode("utf-8", errors="ignore").lstrip().casefold()
    if preview.startswith("<!doctype html") or re.search(r"<html\b", preview):
        return "html"
    parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(body, parser=parser)
    except (etree.ParserError, ValueError):
        return "unknown"
    return "html" if local_name(root) == "html" else "xml"


def html_meta(document: etree._Element, name: str) -> str | None:
    values = document.xpath(
        "//meta[translate(@name, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz')=$name]/@content",
        name=name.casefold(),
    )
    if not values:
        return None
    value = normalize_text(str(values[0]))
    return value or None


def first_xpath_text(document: etree._Element, xpath: str) -> str | None:
    values = document.xpath(xpath)
    if not values:
        return None
    value = values[0]
    if isinstance(value, etree._Element):
        text = " ".join(value.itertext())
    else:
        text = str(value)
    normalized = normalize_text(text)
    return normalized or None


def parse_artifact(body: bytes, detected_format: str) -> dict[str, str | None]:
    if detected_format == "html":
        try:
            document = html.fromstring(body)
        except (etree.ParserError, ValueError):
            return {"title": None, "pmid": None, "doi": None, "text": None}
        etree.strip_elements(
            document,
            "script",
            "style",
            "noscript",
            "svg",
            with_tail=False,
        )
        return {
            "title": html_meta(document, "citation_title"),
            "pmid": html_meta(document, "citation_pmid"),
            "doi": html_meta(document, "citation_doi"),
            "text": normalize_text(document.text_content()),
        }
    if detected_format == "xml":
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
        try:
            document = etree.fromstring(body, parser=parser)
        except (etree.ParserError, ValueError):
            return {"title": None, "pmid": None, "doi": None, "text": None}
        return {
            "title": first_xpath_text(
                document,
                "(//*[local-name()='article-title'])[1]",
            ),
            "pmid": first_xpath_text(
                document,
                "(//*[local-name()='article-id'][@pub-id-type='pmid'])[1]",
            ),
            "doi": first_xpath_text(
                document,
                "(//*[local-name()='article-id'][@pub-id-type='doi'])[1]",
            ),
            "text": normalize_text(" ".join(document.itertext())),
        }
    return {"title": None, "pmid": None, "doi": None, "text": None}


def portable_data_path(path: Path, data_dir: Path) -> str:
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def assess_artifact(
    row: sqlite3.Row,
    *,
    data_dir: Path,
) -> tuple[PubMedArtifactQualityAssessment, str]:
    stored_path = str(row["payload_path"])
    path = resolve_data_path(data_dir, stored_path)
    failure_reasons: list[str] = []
    if path is None or not path.exists():
        failure_reasons.append("artifact_file_missing")
        assessment = PubMedArtifactQualityAssessment(
            artifact_id=str(row["artifact_id"]),
            source=str(row["artifact_source"]),
            artifact_type=str(row["artifact_type"]),
            source_url=row["artifact_url"],
            payload_path=stored_path,
            stored_sha256=row["payload_sha256"],
            failure_reasons=failure_reasons,
            provenance=artifact_provenance(row),
        )
        return assessment, ""

    body = path.read_bytes()
    computed_sha256 = hashlib.sha256(body).hexdigest()
    stored_sha256 = str(row["payload_sha256"] or "") or None
    hash_matches = stored_sha256 is not None and stored_sha256 == computed_sha256
    detected_format = detect_format(body)
    parsed = parse_artifact(body, detected_format)
    artifact_title = parsed["title"]
    artifact_pmid = parsed["pmid"]
    artifact_doi = parsed["doi"]
    extracted_text = parsed["text"] or ""
    title_matches = bool(artifact_title) and normalized_identity_text(
        artifact_title
    ) == normalized_identity_text(row["primary_title"])
    pmid_matches = bool(artifact_pmid and row["pmid"]) and str(artifact_pmid) == str(
        row["pmid"]
    )
    doi_matches = bool(artifact_doi and row["doi"]) and normalized_doi(
        artifact_doi
    ) == normalized_doi(str(row["doi"]))
    identifier_matches = pmid_matches or doi_matches
    identity_verified = title_matches and identifier_matches
    scientific_hits = count_term_hits(extracted_text, SCIENTIFIC_SECTION_TERMS)
    cannabinoid_hits = count_term_hits(extracted_text, CANNABINOID_TERMS)
    preview = body[:8_000].decode("utf-8", errors="ignore").casefold()

    if not stored_sha256:
        failure_reasons.append("artifact_sha256_missing")
    elif not hash_matches:
        failure_reasons.append("artifact_sha256_mismatch")
    if detected_format == "unknown":
        failure_reasons.append("artifact_format_not_xml_or_html")
    if any(marker in preview for marker in CHALLENGE_MARKERS):
        failure_reasons.append("challenge_or_javascript_payload")
    if not artifact_title:
        failure_reasons.append("artifact_title_missing")
    elif not title_matches:
        failure_reasons.append("artifact_title_mismatch")
    if not identifier_matches:
        failure_reasons.append("artifact_identifier_mismatch")
    if not identity_verified:
        failure_reasons.append("artifact_identity_mismatch")
    if len(extracted_text) < MIN_CLASSIFICATION_TEXT_CHARS:
        failure_reasons.append("insufficient_extracted_text")
    if scientific_hits < 2:
        failure_reasons.append("insufficient_scientific_section_signal")
    if cannabinoid_hits < 1:
        failure_reasons.append("missing_cannabinoid_term_signal")

    declared_format = "html" if row["artifact_type"] == "pmc_html" else "xml"
    assessment = PubMedArtifactQualityAssessment(
        artifact_id=str(row["artifact_id"]),
        source=str(row["artifact_source"]),
        artifact_type=str(row["artifact_type"]),
        source_url=row["artifact_url"],
        payload_path=portable_data_path(path, data_dir),
        stored_sha256=stored_sha256,
        computed_sha256=computed_sha256,
        hash_matches=hash_matches,
        detected_format=detected_format,  # type: ignore[arg-type]
        declared_format_matches=declared_format == detected_format,
        artifact_title=artifact_title,
        artifact_pmid=artifact_pmid,
        artifact_doi=artifact_doi,
        title_matches=title_matches,
        identifier_matches=identifier_matches,
        identity_verified=identity_verified,
        extracted_text_chars=len(extracted_text),
        scientific_section_hit_count=scientific_hits,
        cannabinoid_term_hit_count=cannabinoid_hits,
        quality_pass=not failure_reasons,
        failure_reasons=sorted(set(failure_reasons)),
        provenance=artifact_provenance(row),
    )
    return assessment, extracted_text


def artifact_provenance(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "method": "pubmed_canary_local_artifact_quality_gate.v1",
        "source_run_id": row["artifact_run_id"],
        "source_created_at": row["artifact_created_at"],
        "does_not_fetch_network": True,
        "does_not_call_provider": True,
        "does_not_mutate_sqlite": True,
        "review_boundary": "candidate_source_quality_not_reviewed_knowledge",
    }


def candidate_base_exclusions(row: sqlite3.Row) -> list[str]:
    reasons: list[str] = []
    if row["publication_year"] is None:
        reasons.append("publication_year_missing")
    elif int(row["publication_year"]) < 2024:
        reasons.append("publication_year_before_2024")
    if row["cannabinoid_focus"] != "direct_title_or_indexed":
        reasons.append("not_direct_title_or_indexed_cannabinoid_focus")
    if row["identity_status"] == "needs_manual_identity_review":
        reasons.append("identity_requires_manual_review")
    if row["review_state"] != "needs_review":
        reasons.append("review_state_not_needs_review")
    if not row["primary_title"] or not row["pmid"] or not row["canonical_url"]:
        reasons.append("incomplete_candidate_identity")
    return reasons


def preferred_artifact(
    assessments: list[tuple[PubMedArtifactQualityAssessment, str]],
) -> tuple[PubMedArtifactQualityAssessment, str] | None:
    passing = [item for item in assessments if item[0].quality_pass]
    if not passing:
        return None
    return sorted(
        passing,
        key=lambda item: (
            not item[0].declared_format_matches,
            -item[0].extracted_text_chars,
            item[0].artifact_id,
        ),
    )[0]


def build_quality_records(
    rows: list[sqlite3.Row],
    *,
    data_dir: Path,
) -> tuple[list[PubMedSourceQualityRecord], dict[str, str]]:
    by_document: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_document[str(row["document_id"])].append(row)

    records: list[PubMedSourceQualityRecord] = []
    selected_text: dict[str, str] = {}
    for document_id, document_rows in sorted(by_document.items()):
        base_row = document_rows[0]
        artifact_rows = [row for row in document_rows if row["artifact_id"] is not None]
        assessments = [
            assess_artifact(row, data_dir=data_dir)
            for row in artifact_rows
        ]
        preferred = preferred_artifact(assessments)
        exclusion_reasons = candidate_base_exclusions(base_row)
        if not artifact_rows:
            exclusion_reasons.append("no_local_open_xml_html_artifact")
        elif preferred is None:
            exclusion_reasons.extend(
                sorted(
                    {
                        reason
                        for assessment, _ in assessments
                        for reason in assessment.failure_reasons
                    }
                )
            )
            exclusion_reasons.append("no_artifact_passed_source_quality_gate")
        if preferred is not None and not exclusion_reasons:
            selected_text[document_id] = preferred[1]
        records.append(
            PubMedSourceQualityRecord(
                document_id=document_id,
                primary_title=base_row["primary_title"],
                publication_year=base_row["publication_year"],
                pmid=base_row["pmid"],
                pmcid=base_row["pmcid"],
                doi=base_row["doi"],
                canonical_url=base_row["canonical_url"],
                identity_status=str(base_row["identity_status"]),
                cannabinoid_focus=str(base_row["cannabinoid_focus"]),
                study_design=base_row["study_design"],
                study_design_rank=int(base_row["study_design_rank"] or 0),
                priority_score=float(base_row["priority_score"] or 0),
                review_state=str(base_row["review_state"]),
                artifact_count=len(artifact_rows),
                artifact_assessments=[assessment for assessment, _ in assessments],
                selected_artifact_id=preferred[0].artifact_id if preferred else None,
                source_quality_gate_pass=preferred is not None and not exclusion_reasons,
                exclusion_reasons=sorted(set(exclusion_reasons)),
                provenance={
                    "method": "pubmed_2024plus_source_quality_rollup.v1",
                    "does_not_fetch_network": True,
                    "does_not_call_provider": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "candidate_source_quality_not_reviewed_knowledge",
                },
            )
        )
    return records, selected_text


def canary_sort_key(record: PubMedSourceQualityRecord) -> tuple[Any, ...]:
    return (
        -record.priority_score,
        -record.study_design_rank,
        -(record.publication_year or 0),
        record.document_id,
    )


def safe_version_fragment(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def safe_document_fragment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").casefold()


def write_source_text(
    *,
    storage: LocalStorage,
    corpus_version: str,
    document_id: str,
    text: str,
) -> Path:
    relative_path = (
        Path("processed/pubmed_canary")
        / safe_version_fragment(corpus_version)
        / f"{safe_document_fragment(document_id)}.txt"
    )
    path = storage.path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_text(text) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != normalized:
        msg = f"Frozen canary source text changed for {document_id}: {path}"
        raise ValueError(msg)
    path.write_text(normalized, encoding="utf-8")
    return path


def serialized_jsonl(records: Iterable[BaseModel]) -> str:
    return "".join(
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for record in records
    )


def write_frozen_jsonl(path: Path, records: Iterable[BaseModel]) -> Path:
    content = serialized_jsonl(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != content:
            msg = f"Frozen artifact already exists with different content: {path}"
            raise ValueError(msg)
        return path
    path.write_text(content, encoding="utf-8")
    return path


def selected_assessment(record: PubMedSourceQualityRecord) -> PubMedArtifactQualityAssessment:
    for assessment in record.artifact_assessments:
        if assessment.artifact_id == record.selected_artifact_id:
            return assessment
    msg = f"Selected artifact missing from quality record {record.document_id}."
    raise ValueError(msg)


def build_manifest_and_corpus(
    *,
    storage: LocalStorage,
    selected: list[PubMedSourceQualityRecord],
    selected_text: dict[str, str],
    corpus_version: str,
) -> tuple[list[PubMedCanaryManifestRecord], list[ClassificationCorpusRecord]]:
    manifest: list[PubMedCanaryManifestRecord] = []
    corpus: list[ClassificationCorpusRecord] = []
    for rank, record in enumerate(selected, start=1):
        assessment = selected_assessment(record)
        source_text_path = write_source_text(
            storage=storage,
            corpus_version=corpus_version,
            document_id=record.document_id,
            text=selected_text[record.document_id],
        )
        source_text_relative = portable_data_path(source_text_path, storage.root)
        source_text_sha256 = file_sha256(source_text_path)
        source_text_chars = len(source_text_path.read_text(encoding="utf-8"))
        source_text_bytes = source_text_path.stat().st_size
        assert record.primary_title is not None
        assert record.publication_year is not None
        assert record.pmid is not None
        assert record.canonical_url is not None
        assert assessment.payload_path is not None
        assert assessment.computed_sha256 is not None
        assert assessment.detected_format in {"html", "xml"}
        manifest.append(
            PubMedCanaryManifestRecord(
                corpus_version=corpus_version,
                selection_rank=rank,
                document_id=record.document_id,
                identity=PubMedCanaryIdentity(
                    primary_title=record.primary_title,
                    publication_year=record.publication_year,
                    pmid=record.pmid,
                    pmcid=record.pmcid,
                    doi=record.doi,
                    canonical_url=record.canonical_url,
                ),
                origin=PubMedCanaryOrigin(
                    source=assessment.source,
                    artifact_id=assessment.artifact_id,
                    artifact_type=assessment.artifact_type,
                    detected_format=assessment.detected_format,
                    source_url=assessment.source_url,
                    raw_artifact_path=assessment.payload_path,
                    raw_artifact_sha256=assessment.computed_sha256,
                    extracted_text_path=source_text_relative,
                    extracted_text_sha256=source_text_sha256,
                    extracted_text_chars=source_text_chars,
                    extracted_text_bytes=source_text_bytes,
                    scientific_section_hit_count=assessment.scientific_section_hit_count,
                    cannabinoid_term_hit_count=assessment.cannabinoid_term_hit_count,
                ),
                selection_criteria=SELECTION_CRITERIA,
                provenance={
                    "method": "pubmed_2024plus_deterministic_canary_selection.v1",
                    "source_quality_gate": "pubmed_canary_source_quality_gate.v1",
                    "selection_sort": (
                        "priority_score_desc,study_design_rank_desc,"
                        "publication_year_desc,document_id_asc"
                    ),
                    "does_not_fetch_network": True,
                    "does_not_call_provider": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "classification_input_not_reviewed_knowledge",
                },
            )
        )
        corpus.append(
            ClassificationCorpusRecord(
                document_id=record.document_id,
                primary_title=record.primary_title,
                publication_year=record.publication_year,
                pmid=record.pmid,
                pmcid=record.pmcid,
                doi=record.doi,
                canonical_url=record.canonical_url,
                source_strategy=f"pubmed_open_{assessment.detected_format}",
                source_url=assessment.source_url,
                source_text_path=source_text_relative,
                raw_payload_path=assessment.payload_path,
                extracted_text_chars=source_text_chars,
                scientific_section_hit_count=assessment.scientific_section_hit_count,
                cannabinoid_term_hit_count=assessment.cannabinoid_term_hit_count,
                source_ready=True,
                classification_ready=True,
                classification_dataset_split="strict_classification_ready",
                trust_level="source_text_available",
                provenance={
                    "corpus_version": corpus_version,
                    "manifest_rank": rank,
                    "raw_artifact_sha256": assessment.computed_sha256,
                    "source_text_sha256": source_text_sha256,
                    "method": "pubmed_canary_classification_corpus.v1",
                    "classification_output_trust_level": "ai_classified_candidate",
                    "review_state": "needs_review",
                    "requires_human_review": True,
                    "does_not_call_provider": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "source_text_available_not_reviewed_knowledge",
                },
            )
        )
    return manifest, corpus


def write_dict_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return path


def quality_summary(
    *,
    run_id: str,
    corpus_version: str,
    target_size: int,
    quality_records: list[PubMedSourceQualityRecord],
    selected: list[PubMedSourceQualityRecord],
    records_path: Path,
    exclusions_path: Path,
    manifest_path: Path,
    corpus_path: Path,
    prompt_packet_result: dict[str, Any] | None,
    protected_before: dict[str, Any],
    protected_after: dict[str, Any],
) -> dict[str, Any]:
    all_assessments = [
        assessment
        for record in quality_records
        for assessment in record.artifact_assessments
    ]
    exclusion_counts = Counter(
        reason for record in quality_records for reason in record.exclusion_reasons
    )
    return {
        "run_id": run_id,
        "corpus_version": corpus_version,
        "target_size": target_size,
        "counts": {
            "candidate_records": len(quality_records),
            "unique_document_ids": len({record.document_id for record in quality_records}),
            "new_candidates": sum(
                record.identity_status == "new_candidate" for record in quality_records
            ),
            "direct_title_or_indexed_focus": sum(
                record.cannabinoid_focus == "direct_title_or_indexed"
                for record in quality_records
            ),
            "candidate_documents_with_open_xml_html_artifact": sum(
                record.artifact_count > 0 for record in quality_records
            ),
            "direct_focus_documents_with_open_xml_html_artifact": sum(
                record.artifact_count > 0
                and record.cannabinoid_focus == "direct_title_or_indexed"
                for record in quality_records
            ),
            "open_xml_html_artifacts": len(all_assessments),
            "declared_format_mismatches": sum(
                not assessment.declared_format_matches for assessment in all_assessments
            ),
            "identity_verified_artifacts": sum(
                assessment.identity_verified for assessment in all_assessments
            ),
            "source_quality_gate_pass": sum(
                record.source_quality_gate_pass for record in quality_records
            ),
            "selected_canary_documents": len(selected),
            "selection_shortfall": max(0, target_size - len(selected)),
            "excluded_documents": sum(
                not record.source_quality_gate_pass for record in quality_records
            ),
            "duplicate_open_artifacts_discarded": sum(
                max(0, record.artifact_count - 1) for record in quality_records
            ),
        },
        "candidate_focus_counts": dict(
            Counter(record.cannabinoid_focus for record in quality_records)
        ),
        "identity_status_counts": dict(
            Counter(record.identity_status for record in quality_records)
        ),
        "artifact_type_counts": dict(
            Counter(assessment.artifact_type for assessment in all_assessments)
        ),
        "detected_format_counts": dict(
            Counter(assessment.detected_format for assessment in all_assessments)
        ),
        "artifact_failure_reason_counts": dict(
            Counter(
                reason
                for assessment in all_assessments
                for reason in assessment.failure_reasons
            )
        ),
        "document_exclusion_reason_counts": dict(exclusion_counts),
        "selected_document_ids": [record.document_id for record in selected],
        "output_paths": {
            "source_quality_records": str(records_path),
            "exclusions": str(exclusions_path),
            "frozen_manifest": str(manifest_path),
            "frozen_corpus_records": str(corpus_path),
            "prompt_packets": prompt_packet_result or {},
        },
        "protected_state_before": protected_before,
        "protected_state_after": protected_after,
        "protected_state_unchanged": protected_before == protected_after,
        "notes": [
            "All inputs and outputs are local ignored artifacts.",
            "No network, model, or provider call was made.",
            "The source-quality gate requires artifact-level identity verification.",
            "Selected records are source_text_available inputs; any future model output must "
            "remain ai_classified_candidate and needs_review.",
            "No SQLite, review queue, review decision, or reviewed knowledge state was mutated.",
        ],
    }


def prepare_pubmed_canary(
    *,
    storage: LocalStorage,
    database_path: Path,
    target_size: int = DEFAULT_TARGET_SIZE,
    corpus_version: str = DEFAULT_CORPUS_VERSION,
    run_id: str | None = None,
    prepare_prompt_packets: bool = True,
    max_source_chars: int = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_provider: str = "openai",
    target_model_name: str = DEFAULT_OPENAI_MODEL,
) -> dict[str, Any]:
    if target_size < 1:
        raise ValueError("target_size must be at least 1.")
    resolved_run_id = run_id or new_run_id()
    protected_before = protected_state_snapshot(database_path)
    rows = load_candidate_artifact_rows(database_path)
    quality_records, selected_text = build_quality_records(rows, data_dir=storage.root)
    eligible = sorted(
        [record for record in quality_records if record.source_quality_gate_pass],
        key=canary_sort_key,
    )
    selected = eligible[:target_size]
    manifest, corpus = build_manifest_and_corpus(
        storage=storage,
        selected=selected,
        selected_text=selected_text,
        corpus_version=corpus_version,
    )

    version_fragment = safe_version_fragment(corpus_version)
    output_dir = storage.path("normalized/pubmed_canary")
    manifest_path = write_frozen_jsonl(
        output_dir / f"{version_fragment}_manifest.jsonl",
        manifest,
    )
    corpus_path = write_frozen_jsonl(
        output_dir / f"{version_fragment}_corpus_records.jsonl",
        corpus,
    )
    records_path = storage.write_jsonl(
        Path("normalized/pubmed_canary")
        / f"{resolved_run_id}_source_quality_records.jsonl",
        quality_records,
    )
    exclusions_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_source_quality_exclusions.jsonl",
        [
            {
                "document_id": record.document_id,
                "primary_title": record.primary_title,
                "publication_year": record.publication_year,
                "pmid": record.pmid,
                "pmcid": record.pmcid,
                "doi": record.doi,
                "cannabinoid_focus": record.cannabinoid_focus,
                "identity_status": record.identity_status,
                "review_state": record.review_state,
                "artifact_count": record.artifact_count,
                "exclusion_reasons": record.exclusion_reasons,
                "provenance": record.provenance,
            }
            for record in quality_records
            if record.exclusion_reasons
        ],
    )

    prompt_packet_result = None
    if prepare_prompt_packets and corpus:
        prompt_packet_result = build_classification_prompt_packets(
            storage=storage,
            limit=len(corpus),
            input_path=corpus_path,
            run_id=f"{resolved_run_id}_pubmed_canary",
            max_source_chars=max_source_chars,
            target_model_provider=target_model_provider,
            target_model_name=target_model_name,
            dataset_split="strict_classification_ready",
        )

    protected_after = protected_state_snapshot(database_path)
    if protected_before != protected_after:
        raise RuntimeError("Protected SQLite or review state changed during canary preparation.")
    summary = quality_summary(
        run_id=resolved_run_id,
        corpus_version=corpus_version,
        target_size=target_size,
        quality_records=quality_records,
        selected=selected,
        records_path=records_path,
        exclusions_path=exclusions_path,
        manifest_path=manifest_path,
        corpus_path=corpus_path,
        prompt_packet_result=prompt_packet_result,
        protected_before=protected_before,
        protected_after=protected_after,
    )
    summary_path = storage.write_json(
        Path("normalized/pubmed_canary") / f"{resolved_run_id}_source_quality_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "corpus_version": corpus_version,
        "summary_path": str(summary_path),
        "manifest_path": str(manifest_path),
        "corpus_path": str(corpus_path),
        "prompt_packet_result": prompt_packet_result,
        "counts": summary["counts"],
        "selected_document_ids": summary["selected_document_ids"],
        "protected_state_unchanged": True,
    }
