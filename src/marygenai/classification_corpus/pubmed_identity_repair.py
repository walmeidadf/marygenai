from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from marygenai.classification_corpus.models import (
    PubMedIdentityRepairRecord,
    PubMedIdentitySet,
    PubMedSourceQualityRecord,
)
from marygenai.classification_corpus.pubmed_canary import (
    build_quality_records,
    canary_sort_key,
    load_candidate_artifact_rows,
    normalized_identity_text,
    protected_state_snapshot,
)
from marygenai.initial_load.files import file_sha256
from marygenai.pubmed_discovery.pubmed import (
    PubMedClient,
    PubMedRecord,
    parse_pubmed_xml,
    pubmed_canonical_url,
)
from marygenai.storage import LocalStorage

DEFAULT_REPAIR_TARGET_SIZE = 150
DEFAULT_EFETCH_CHUNK_SIZE = 150
REPAIR_OUTPUT_SUBDIR = Path("normalized/pubmed_canary/identity_repairs")
REPAIR_RAW_SUBDIR = Path("raw/pubmed/efetch")


class PubMedFetchClient(Protocol):
    def fetch_xml(self, pmids: list[str]) -> str: ...


def new_repair_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def repair_target_records(
    quality_records: list[PubMedSourceQualityRecord],
    *,
    target_size: int,
) -> list[PubMedSourceQualityRecord]:
    eligible = [
        record
        for record in quality_records
        if record.publication_year is not None
        and record.publication_year >= 2024
        and record.cannabinoid_focus == "direct_title_or_indexed"
        and record.identity_status != "needs_manual_identity_review"
        and record.review_state == "needs_review"
        and record.artifact_count > 0
        and record.pmid
        and any(
            "artifact_identity_mismatch" in assessment.failure_reasons
            for assessment in record.artifact_assessments
        )
    ]
    return sorted(eligible, key=canary_sort_key)[:target_size]


def chunks(
    values: list[PubMedSourceQualityRecord],
    size: int,
) -> list[list[PubMedSourceQualityRecord]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def normalized_doi(value: str | None) -> str:
    return (value or "").casefold().removeprefix("https://doi.org/").strip()


def identity_from_quality(record: PubMedSourceQualityRecord) -> PubMedIdentitySet:
    assert record.pmid is not None
    return PubMedIdentitySet(
        primary_title=record.primary_title,
        publication_year=record.publication_year,
        pmid=record.pmid,
        pmcid=record.pmcid,
        doi=record.doi,
        canonical_url=record.canonical_url,
    )


def publication_year(record: PubMedRecord) -> int | None:
    value = record.publication_date or ""
    if len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def identity_from_pubmed(record: PubMedRecord) -> PubMedIdentitySet:
    return PubMedIdentitySet(
        primary_title=record.title,
        publication_year=publication_year(record),
        pmid=record.pmid,
        pmcid=record.pmcid,
        doi=record.doi,
        canonical_url=pubmed_canonical_url(record.pmid),
    )


def changed_identity_fields(
    current: PubMedIdentitySet,
    resolved: PubMedIdentitySet,
) -> list[str]:
    changed: list[str] = []
    if normalized_identity_text(current.primary_title) != normalized_identity_text(
        resolved.primary_title
    ):
        changed.append("primary_title")
    if current.publication_year != resolved.publication_year and resolved.publication_year:
        changed.append("publication_year")
    if (current.pmcid or "").casefold() != (resolved.pmcid or "").casefold():
        changed.append("pmcid")
    if normalized_doi(current.doi) != normalized_doi(resolved.doi):
        changed.append("doi")
    if current.canonical_url != resolved.canonical_url:
        changed.append("canonical_url")
    return changed


def recommended_action(
    current: PubMedIdentitySet,
    resolved: PubMedIdentitySet | None,
) -> str:
    if resolved is None:
        return "manual_identity_investigation"
    if resolved.pmcid:
        if (current.pmcid or "").casefold() != resolved.pmcid.casefold():
            return "reenrich_from_resolved_pmcid"
        return "refetch_existing_pmc_route"
    return "try_europe_pmc_or_unpaywall"


def quality_failure_reasons(record: PubMedSourceQualityRecord) -> list[str]:
    return sorted(
        {
            reason
            for assessment in record.artifact_assessments
            for reason in assessment.failure_reasons
        }
    )


def write_raw_chunk(
    *,
    storage: LocalStorage,
    run_id: str,
    chunk_number: int,
    xml_text: str,
) -> Path:
    path = storage.path(
        REPAIR_RAW_SUBDIR
        / f"{run_id}_pubmed_identity_repair_chunk_{chunk_number:03d}.xml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml_text, encoding="utf-8")
    return path


def portable_path(path: Path, data_dir: Path) -> str:
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return str(path)


def build_resolved_record(
    *,
    run_id: str,
    selection_rank: int,
    target: PubMedSourceQualityRecord,
    resolved: PubMedRecord | None,
    raw_path: Path | None,
    raw_sha256: str | None,
    fetched_at: str,
    data_dir: Path,
    fetch_error: str | None = None,
) -> PubMedIdentityRepairRecord:
    current_identity = identity_from_quality(target)
    resolved_identity = identity_from_pubmed(resolved) if resolved else None
    if fetch_error:
        resolution_status = "fetch_error"
    elif resolved is None:
        resolution_status = "pubmed_record_missing"
    else:
        resolution_status = "resolved"
    return PubMedIdentityRepairRecord(
        repair_run_id=run_id,
        selection_rank=selection_rank,
        document_id=target.document_id,
        current_identity=current_identity,
        resolved_identity=resolved_identity,
        resolution_status=resolution_status,
        changed_fields=(
            changed_identity_fields(current_identity, resolved_identity)
            if resolved_identity
            else []
        ),
        source_quality_failure_reasons=quality_failure_reasons(target),
        recommended_action=recommended_action(current_identity, resolved_identity),  # type: ignore[arg-type]
        provenance={
            "method": "pubmed_source_identity_repair_overlay.v1",
            "selection_method": (
                "direct_2024plus_open_artifact_identity_failures_sorted_by_"
                "priority_design_year_document"
            ),
            "pubmed_query_key": "pmid",
            "fetched_at": fetched_at,
            "raw_pubmed_path": (
                portable_path(raw_path, data_dir) if raw_path else None
            ),
            "raw_pubmed_sha256": raw_sha256,
            "fetch_error": fetch_error,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "does_not_apply_identity_changes": True,
            "review_boundary": "identity_repair_candidate_not_reviewed_knowledge",
        },
    )


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


def build_summary(
    *,
    run_id: str,
    target_size: int,
    records: list[PubMedIdentityRepairRecord],
    records_path: Path,
    worklist_path: Path,
    errors_path: Path,
    protected_before: dict[str, Any],
    protected_after: dict[str, Any],
) -> dict[str, Any]:
    resolved = [record for record in records if record.resolved_identity]
    return {
        "run_id": run_id,
        "schema_version": "pubmed_source_identity_repair.v1",
        "target_size": target_size,
        "counts": {
            "selected_candidates": len(records),
            "resolved_pubmed_records": len(resolved),
            "missing_pubmed_records": sum(
                record.resolution_status == "pubmed_record_missing" for record in records
            ),
            "fetch_errors": sum(
                record.resolution_status == "fetch_error" for record in records
            ),
            "records_with_identity_changes": sum(bool(record.changed_fields) for record in records),
            "pmcid_changes": sum("pmcid" in record.changed_fields for record in records),
            "doi_changes": sum("doi" in record.changed_fields for record in records),
            "title_changes": sum(
                "primary_title" in record.changed_fields for record in records
            ),
            "resolved_with_pmcid": sum(
                bool(record.resolved_identity and record.resolved_identity.pmcid)
                for record in records
            ),
            "reenrichment_worklist": sum(
                record.recommended_action
                in {"reenrich_from_resolved_pmcid", "refetch_existing_pmc_route"}
                for record in records
            ),
        },
        "changed_field_counts": dict(
            Counter(field for record in records for field in record.changed_fields)
        ),
        "recommended_action_counts": dict(
            Counter(record.recommended_action for record in records)
        ),
        "resolution_status_counts": dict(
            Counter(record.resolution_status for record in records)
        ),
        "output_paths": {
            "repair_records": str(records_path),
            "reenrichment_worklist": str(worklist_path),
            "errors": str(errors_path),
        },
        "protected_state_before": protected_before,
        "protected_state_after": protected_after,
        "protected_state_unchanged": protected_before == protected_after,
        "notes": [
            "PubMed was queried by the existing candidate PMID only.",
            "Resolved identities are a local candidate overlay and were not applied.",
            "No LLM or paid model provider was called.",
            "SQLite, review queues, review decisions, and reviewed knowledge were not mutated.",
        ],
    }


def repair_pubmed_source_identities(
    *,
    storage: LocalStorage,
    database_path: Path,
    target_size: int = DEFAULT_REPAIR_TARGET_SIZE,
    run_id: str | None = None,
    apply: bool = False,
    client: PubMedFetchClient | None = None,
    chunk_size: int = DEFAULT_EFETCH_CHUNK_SIZE,
) -> dict[str, Any]:
    if apply:
        raise ValueError(
            "Applying identity changes is not supported. Use --no-apply and review the overlay."
        )
    if target_size < 1:
        raise ValueError("target_size must be at least 1.")
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1.")

    load_dotenv()
    resolved_run_id = run_id or new_repair_run_id()
    fetched_at = datetime.now(UTC).isoformat()
    protected_before = protected_state_snapshot(database_path)
    rows = load_candidate_artifact_rows(database_path)
    quality_records, _ = build_quality_records(rows, data_dir=storage.root)
    targets = repair_target_records(quality_records, target_size=target_size)

    fetch_client = client or PubMedClient(
        api_key=os.getenv("PUBMED_API_KEY"),
        email=os.getenv("PUBMED_EMAIL"),
    )
    owns_client = client is None
    records: list[PubMedIdentityRepairRecord] = []
    errors: list[dict[str, Any]] = []
    selection_rank = {target.document_id: rank for rank, target in enumerate(targets, start=1)}
    try:
        for chunk_number, target_chunk in enumerate(chunks(targets, chunk_size), start=1):
            pmids = [str(target.pmid) for target in target_chunk if target.pmid]
            raw_path: Path | None = None
            raw_sha256: str | None = None
            try:
                xml_text = fetch_client.fetch_xml(pmids)
                raw_path = write_raw_chunk(
                    storage=storage,
                    run_id=resolved_run_id,
                    chunk_number=chunk_number,
                    xml_text=xml_text,
                )
                raw_sha256 = file_sha256(raw_path)
                resolved_by_pmid = {
                    record.pmid: record
                    for record in parse_pubmed_xml(
                        xml_text,
                        query="identity_repair_by_existing_pmid",
                        fetched_at=fetched_at,
                    )
                }
                for target in target_chunk:
                    records.append(
                        build_resolved_record(
                            run_id=resolved_run_id,
                            selection_rank=selection_rank[target.document_id],
                            target=target,
                            resolved=resolved_by_pmid.get(str(target.pmid)),
                            raw_path=raw_path,
                            raw_sha256=raw_sha256,
                            fetched_at=fetched_at,
                            data_dir=storage.root,
                        )
                    )
            except (httpx.HTTPError, ValueError) as exc:
                for target in target_chunk:
                    records.append(
                        build_resolved_record(
                            run_id=resolved_run_id,
                            selection_rank=selection_rank[target.document_id],
                            target=target,
                            resolved=None,
                            raw_path=raw_path,
                            raw_sha256=raw_sha256,
                            fetched_at=fetched_at,
                            data_dir=storage.root,
                            fetch_error=str(exc),
                        )
                    )
                    errors.append(
                        {
                            "document_id": target.document_id,
                            "pmid": target.pmid,
                            "error_type": type(exc).__name__,
                            "message": str(exc),
                            "does_not_mutate_sqlite": True,
                        }
                    )
    finally:
        if owns_client and isinstance(fetch_client, PubMedClient):
            fetch_client.close()

    records.sort(key=lambda record: record.selection_rank)
    output_dir = storage.path(REPAIR_OUTPUT_SUBDIR)
    records_path = storage.write_jsonl(
        REPAIR_OUTPUT_SUBDIR / f"{resolved_run_id}_pubmed_identity_repair_records.jsonl",
        records,
    )
    worklist_path = storage.write_jsonl(
        REPAIR_OUTPUT_SUBDIR
        / f"{resolved_run_id}_pubmed_identity_reenrichment_worklist.jsonl",
        [
            record
            for record in records
            if record.recommended_action
            in {"reenrich_from_resolved_pmcid", "refetch_existing_pmc_route"}
        ],
    )
    errors_path = write_dict_jsonl(
        output_dir / f"{resolved_run_id}_pubmed_identity_repair_errors.jsonl",
        errors,
    )
    protected_after = protected_state_snapshot(database_path)
    if protected_before != protected_after:
        raise RuntimeError("Protected SQLite or review state changed during identity repair.")
    summary = build_summary(
        run_id=resolved_run_id,
        target_size=target_size,
        records=records,
        records_path=records_path,
        worklist_path=worklist_path,
        errors_path=errors_path,
        protected_before=protected_before,
        protected_after=protected_after,
    )
    summary_path = storage.write_json(
        REPAIR_OUTPUT_SUBDIR / f"{resolved_run_id}_pubmed_identity_repair_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "records_path": str(records_path),
        "worklist_path": str(worklist_path),
        "summary_path": str(summary_path),
        "errors_path": str(errors_path),
        "counts": summary["counts"],
        "protected_state_unchanged": True,
    }
