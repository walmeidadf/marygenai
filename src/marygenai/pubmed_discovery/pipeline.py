from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

from marygenai import __version__
from marygenai.initial_load.files import file_sha256, normalize_title, stable_hash
from marygenai.initial_load.persist import document_identity_id, dump_json, review_item_id
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.pubmed_discovery.legacy import (
    PubMedLegacyIndex,
    classify_against_legacy,
    load_legacy_index_from_sqlite,
    normalize_doi,
    normalize_pmcid,
)
from marygenai.pubmed_discovery.models import (
    PubMedCandidate,
    PubMedDiscoverySummary,
    PubMedDiscoveryWindow,
    default_pubmed_window,
)
from marygenai.pubmed_discovery.pubmed import (
    QUERY_BATCHES,
    PubMedClient,
    PubMedRecord,
    cannabinoid_focus,
    classify_full_text_review_priority,
    infer_study_design,
    parse_pubmed_xml,
    pubmed_canonical_url,
    score_pubmed_record,
)
from marygenai.schemas import OutputArtifact, RunManifest
from marygenai.storage import LocalStorage

PUBMED_CANDIDATE_QUEUE = "publication_candidate_review"


class PubMedDiscoveryResult(BaseModel):
    run_id: str
    manifest_path: Path
    output_paths: dict[str, Path]
    counts: dict[str, int]


def discover_pubmed_candidates(
    *,
    storage: LocalStorage,
    database_path: Path | None = None,
    run_id: str | None = None,
    query_names: list[str] | None = None,
    retmax: int = 100,
    sort: str = "relevance",
    datetype: str = "pdat",
    mindate: str | None = None,
    maxdate: str | None = None,
    overlap_years: int = 1,
    persist: bool = True,
    today: date | None = None,
) -> PubMedDiscoveryResult:
    """Discover PubMed candidates past the legacy boundary and write audit snapshots."""
    load_dotenv()
    storage.ensure_layout()
    resolved_database_path = database_path or sqlite_database_path(storage.root)
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    fetched_at = started_at.isoformat()

    with connect_sqlite(resolved_database_path) as connection:
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
        legacy_index = load_legacy_index_from_sqlite(connection)

    window = resolve_window(
        legacy_index=legacy_index,
        datetype=datetype,
        mindate=mindate,
        maxdate=maxdate,
        overlap_years=overlap_years,
        today=today or date.today(),
    )
    selected_query_names = query_names or ["strong_evidence_all"]
    unknown_query_names = sorted(set(selected_query_names) - set(QUERY_BATCHES))
    if unknown_query_names:
        allowed = ", ".join(sorted(QUERY_BATCHES))
        unknown = ", ".join(unknown_query_names)
        raise ValueError(f"Unknown PubMed query name(s): {unknown}. Available names: {allowed}.")

    api_key = os.getenv("PUBMED_API_KEY")
    client = PubMedClient(api_key=api_key, email=os.getenv("PUBMED_EMAIL"))
    records_by_pmid: dict[str, PubMedRecord] = {}
    query_names_by_pmid: dict[str, set[str]] = {}
    source_records: list[dict[str, Any]] = []
    try:
        for query_name in selected_query_names:
            query = QUERY_BATCHES[query_name]
            search_result = client.search(
                query,
                retmax=retmax,
                sort=sort,
                datetype=window.datetype,
                mindate=window.mindate,
                maxdate=window.maxdate,
            )
            pmids = [str(pmid) for pmid in search_result.get("idlist", [])]
            time.sleep(0.11 if api_key else 0.34)
            xml_text = client.fetch_xml(pmids) if pmids else "<PubmedArticleSet />"
            records = parse_pubmed_xml(xml_text, query=query, fetched_at=fetched_at)
            source_records.append(
                build_source_record(
                    run_id=resolved_run_id,
                    query_name=query_name,
                    query=query,
                    search_result=search_result,
                    pmids=pmids,
                    xml_text=xml_text,
                    fetched_at=fetched_at,
                    window=window,
                )
            )
            for record in records:
                records_by_pmid.setdefault(record.pmid, record)
                query_names_by_pmid.setdefault(record.pmid, set()).add(query_name)
    finally:
        client.close()

    candidates = [
        candidate_from_pubmed_record(
            record,
            index=legacy_index,
            query_names=sorted(query_names_by_pmid[record.pmid]),
            run_id=resolved_run_id,
            fetched_at=fetched_at,
            window=window,
        )
        for record in records_by_pmid.values()
    ]
    candidates.sort(key=lambda candidate: candidate.priority_score, reverse=True)
    review_items = build_review_item_snapshots(candidates, run_id=resolved_run_id, now=fetched_at)

    paths = write_discovery_outputs(
        storage=storage,
        run_id=resolved_run_id,
        source_records=source_records,
        candidates=candidates,
        review_items=review_items,
        window=window,
        fetched_at=fetched_at,
        query_count=len(selected_query_names),
    )
    completed_at = datetime.now(UTC)
    manifest = build_manifest(
        run_id=resolved_run_id,
        started_at=started_at,
        completed_at=completed_at,
        paths=paths,
        counts={
            "source_records": len(source_records),
            "publication_candidates": len(candidates),
            "review_items": len(review_items),
        },
    )
    manifest_path = storage.write_json(
        Path("manifests/runs") / f"{resolved_run_id}_pubmed_discovery_manifest.json",
        manifest,
    )
    paths["manifest"] = manifest_path
    if persist:
        persist_pubmed_candidates(
            storage=storage,
            database_path=resolved_database_path,
            run_id=resolved_run_id,
        )
    return PubMedDiscoveryResult(
        run_id=resolved_run_id,
        manifest_path=manifest_path,
        output_paths=paths,
        counts={
            "source_records": len(source_records),
            "publication_candidates": len(candidates),
            "review_items": len(review_items),
        },
    )


def persist_pubmed_candidates(
    *,
    storage: LocalStorage,
    database_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, int | str]:
    manifest_path = find_pubmed_manifest(storage=storage, run_id=run_id)
    manifest = RunManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidates_path = resolve_manifest_output(storage, manifest, "publication_candidates")
    candidates = read_jsonl(candidates_path, PubMedCandidate)
    resolved_database_path = database_path or sqlite_database_path(storage.root)
    with connect_sqlite(resolved_database_path) as connection:
        initialize_schema(connection)
        persist_pubmed_manifest(connection, manifest=manifest, manifest_path=manifest_path)
        persisted_candidates = persist_candidate_documents(
            connection,
            candidates=candidates,
            run_id=manifest.run_id,
        )
        review_items = persist_publication_candidate_review_queue(
            connection,
            candidates=candidates,
            run_id=manifest.run_id,
        )
    return {
        "database": str(resolved_database_path),
        "run_id": manifest.run_id,
        "publication_candidates": persisted_candidates,
        "review_items": review_items,
    }


def resolve_window(
    *,
    legacy_index: PubMedLegacyIndex,
    datetype: str,
    mindate: str | None,
    maxdate: str | None,
    overlap_years: int,
    today: date,
) -> PubMedDiscoveryWindow:
    if mindate and maxdate:
        return PubMedDiscoveryWindow(
            datetype=datetype,
            mindate=mindate,
            maxdate=maxdate,
            overlap_years=overlap_years,
            legacy_max_publication_year=legacy_index.max_publication_year,
        )
    window = default_pubmed_window(
        legacy_max_publication_year=legacy_index.max_publication_year,
        today=today,
        overlap_years=overlap_years,
    )
    return window.model_copy(update={"datetype": datetype, "maxdate": maxdate or window.maxdate})


def candidate_from_pubmed_record(
    record: PubMedRecord,
    *,
    index: PubMedLegacyIndex,
    query_names: list[str],
    run_id: str,
    fetched_at: str,
    window: PubMedDiscoveryWindow,
) -> PubMedCandidate:
    publication_year = parse_publication_year(record.publication_date)
    canonical_url = pubmed_canonical_url(record.pmid)
    match = classify_against_legacy(
        pmid=record.pmid,
        pmcid=record.pmcid,
        doi=record.doi,
        canonical_url=canonical_url,
        title=record.title,
        publication_year=publication_year,
        index=index,
    )
    priority_score, score_reasons = score_pubmed_record(record)
    study_design, study_design_rank, _ = infer_study_design(record)
    focus = cannabinoid_focus(record)
    return PubMedCandidate(
        document_id=f"publication:pubmed:{record.pmid}",
        pmid=record.pmid,
        doi=normalize_doi(record.doi),
        pmcid=normalize_pmcid(record.pmcid),
        canonical_url=canonical_url,
        title=record.title,
        normalized_title=normalize_title(record.title),
        abstract=record.abstract,
        journal=record.journal,
        publication_date=record.publication_date,
        publication_year=publication_year,
        publication_types=record.publication_types,
        mesh_terms=record.mesh_terms,
        chemicals=record.chemicals,
        keywords=record.keywords,
        authors=record.authors,
        languages=record.languages,
        article_ids=record.article_ids,
        query_names=query_names,
        cannabinoid_focus=focus,
        study_design=study_design,
        study_design_rank=study_design_rank,
        priority_score=priority_score,
        priority_tier=priority_tier(focus),
        score_reasons=score_reasons,
        full_text_review_priority=classify_full_text_review_priority(
            record,
            priority_score=priority_score,
            score_reasons=score_reasons,
        ),
        identity_status=match.identity_status,  # type: ignore[arg-type]
        legacy_match_type=match.match_type,
        legacy_match_confidence=match.match_confidence,
        legacy_document_ids=match.legacy_document_ids,
        legacy_study_ids=match.legacy_study_ids,
        review_reasons=match.review_reasons,
        provenance={
            "source": "pubmed",
            "method": "legacy_anchored_pubmed_discovery",
            "run_id": run_id,
            "fetched_at": fetched_at,
            "window": window.model_dump(mode="json"),
            "query_names": query_names,
            "parser": "marygenai.pubmed_discovery.pubmed.parse_pubmed_xml",
            "scoring": "marygenai.pubmed_discovery.pipeline",
        },
    )


def priority_tier(cannabinoid_focus_value: str) -> str:
    if cannabinoid_focus_value == "direct_title_or_indexed":
        return "direct_title_or_indexed"
    if cannabinoid_focus_value == "abstract_only":
        return "abstract_only"
    return "no_cannabinoid_signal"


def parse_publication_year(value: str | None) -> int | None:
    if not value:
        return None
    year = value[:4]
    return int(year) if year.isdigit() else None


def build_source_record(
    *,
    run_id: str,
    query_name: str,
    query: str,
    search_result: dict[str, Any],
    pmids: list[str],
    xml_text: str,
    fetched_at: str,
    window: PubMedDiscoveryWindow,
) -> dict[str, Any]:
    payload = {
        "query_name": query_name,
        "query": query,
        "search_result": search_result,
        "pmids": pmids,
        "efetch_xml_sha256": stable_hash(xml_text),
        "fetched_at": fetched_at,
        "window": window.model_dump(mode="json"),
    }
    return {
        "source_record_id": f"pubmed:discovery:{run_id}:{query_name}",
        "source": "pubmed",
        "source_table": "esearch_efetch",
        "legacy_id": None,
        "row_number": 1,
        "payload_hash": stable_hash(payload),
        "raw_payload": payload,
        "provenance": {
            "source": "pubmed",
            "source_file": "ncbi_eutils",
            "source_row_number": 1,
            "method": "legacy_anchored_pubmed_discovery",
            "run_id": run_id,
        },
    }


def build_review_item_snapshots(
    candidates: list[PubMedCandidate],
    *,
    run_id: str,
    now: str,
) -> list[dict[str, Any]]:
    items = []
    for candidate in candidates:
        if candidate.identity_status == "in_legacy_exact":
            continue
        metadata = review_item_metadata(candidate)
        items.append(
            {
                "review_item_id": review_item_id(PUBMED_CANDIDATE_QUEUE, candidate.document_id),
                "queue_type": PUBMED_CANDIDATE_QUEUE,
                "document_id": candidate.document_id,
                "priority_tier": candidate.priority_tier,
                "priority_score": candidate.priority_score,
                "assignee": None,
                "status": "open",
                "batch_run_id": run_id,
                "metadata": metadata,
                "created_at": now,
                "updated_at": now,
            }
        )
    return items


def review_item_metadata(candidate: PubMedCandidate) -> dict[str, Any]:
    return {
        "source": "pubmed_discovery",
        "identity_status": candidate.identity_status,
        "legacy_match_type": candidate.legacy_match_type,
        "legacy_match_confidence": candidate.legacy_match_confidence,
        "legacy_document_ids": candidate.legacy_document_ids,
        "legacy_study_ids": candidate.legacy_study_ids,
        "review_reasons": candidate.review_reasons,
        "score_reasons": candidate.score_reasons,
        "query_names": candidate.query_names,
        "cannabinoid_focus": candidate.cannabinoid_focus,
        "full_text_review_priority": candidate.full_text_review_priority,
        "provenance": candidate.provenance,
    }


def write_discovery_outputs(
    *,
    storage: LocalStorage,
    run_id: str,
    source_records: list[dict[str, Any]],
    candidates: list[PubMedCandidate],
    review_items: list[dict[str, Any]],
    window: PubMedDiscoveryWindow,
    fetched_at: str,
    query_count: int,
) -> dict[str, Path]:
    source_records_relative_path = (
        Path("staging/source_records/pubmed") / f"{run_id}_pubmed_source_records.jsonl"
    )
    source_path = write_dict_jsonl(
        storage.path(source_records_relative_path),
        source_records,
    )
    candidates_path = storage.write_jsonl(
        Path("normalized/publication_enrichments/pubmed")
        / f"{run_id}_pubmed_publication_candidates.jsonl",
        candidates,
    )
    review_items_path = write_dict_jsonl(
        storage.path(
            Path("normalized/review_items") / f"{run_id}_publication_candidate_review_items.jsonl"
        ),
        review_items,
    )
    summary = PubMedDiscoverySummary(
        run_id=run_id,
        fetched_at=fetched_at,
        window=window,
        query_count=query_count,
        records_after_dedupe=len(candidates),
        identity_status_counts=dict(Counter(candidate.identity_status for candidate in candidates)),
        cannabinoid_focus_counts=dict(
            Counter(candidate.cannabinoid_focus for candidate in candidates)
        ),
        output_paths={
            "source_records": str(source_path),
            "publication_candidates": str(candidates_path),
            "review_items": str(review_items_path),
        },
    )
    summary_path = storage.write_json(
        Path("manifests/source_windows") / f"{run_id}_pubmed_discovery_summary.json",
        summary,
    )
    return {
        "source_records": source_path,
        "publication_candidates": candidates_path,
        "review_items": review_items_path,
        "summary": summary_path,
    }


def write_dict_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def build_manifest(
    *,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    paths: dict[str, Path],
    counts: dict[str, int],
) -> RunManifest:
    output_artifacts = [
        OutputArtifact(
            path=str(path),
            record_count=record_count_for(name, counts),
            sha256=file_sha256(path),
        )
        for name, path in paths.items()
    ]
    return RunManifest(
        run_id=run_id,
        job_type="pubmed_discovery",
        source="pubmed",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        software_version=__version__,
        input_artifacts=[],
        output_artifacts=output_artifacts,
        counts=counts,
        notes=[
            "PubMed candidates are discovery outputs that require human review "
            "before becoming reviewed knowledge.",
        ],
    )


def record_count_for(name: str, counts: dict[str, int]) -> int:
    if name == "source_records":
        return counts["source_records"]
    if name == "publication_candidates":
        return counts["publication_candidates"]
    if name == "review_items":
        return counts["review_items"]
    return 1


def find_pubmed_manifest(*, storage: LocalStorage, run_id: str | None = None) -> Path:
    manifest_dir = storage.path("manifests/runs")
    if run_id:
        manifest_path = manifest_dir / f"{run_id}_pubmed_discovery_manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing PubMed discovery manifest for run id {run_id}")
        return manifest_path
    candidates = sorted(manifest_dir.glob("*_pubmed_discovery_manifest.json"))
    if not candidates:
        raise FileNotFoundError(f"No PubMed discovery manifests found under {manifest_dir}")
    return candidates[-1]


def resolve_manifest_output(storage: LocalStorage, manifest: RunManifest, name: str) -> Path:
    suffixes = {
        "publication_candidates": "_pubmed_publication_candidates.jsonl",
    }
    suffix = suffixes[name]
    for artifact in manifest.output_artifacts:
        path = Path(artifact.path)
        if path.name.endswith(suffix):
            if path.exists():
                return path
            return storage.path(path)
    raise ValueError(f"Manifest {manifest.run_id} does not include {name}")


def read_jsonl[ModelT: BaseModel](path: Path, model: type[ModelT]) -> list[ModelT]:
    records: list[ModelT] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(model.model_validate_json(line))
    return records


def persist_pubmed_manifest(
    connection: sqlite3.Connection,
    *,
    manifest: RunManifest,
    manifest_path: Path,
) -> None:
    now = datetime.now(UTC).isoformat()
    connection.execute(
        """
        INSERT INTO run_manifest (
            run_id, job_type, source, started_at, completed_at, status, software_version,
            input_artifacts_json, output_artifacts_json, counts_json, errors_json, notes_json,
            manifest_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            job_type = excluded.job_type,
            source = excluded.source,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            status = excluded.status,
            software_version = excluded.software_version,
            input_artifacts_json = excluded.input_artifacts_json,
            output_artifacts_json = excluded.output_artifacts_json,
            counts_json = excluded.counts_json,
            errors_json = excluded.errors_json,
            notes_json = excluded.notes_json,
            manifest_path = excluded.manifest_path,
            imported_at = excluded.imported_at
        """,
        (
            manifest.run_id,
            manifest.job_type,
            manifest.source,
            manifest.started_at.isoformat(),
            manifest.completed_at.isoformat(),
            manifest.status,
            manifest.software_version,
            dump_json([artifact.model_dump(mode="json") for artifact in manifest.input_artifacts]),
            dump_json([artifact.model_dump(mode="json") for artifact in manifest.output_artifacts]),
            dump_json(manifest.counts),
            dump_json(manifest.errors),
            dump_json(manifest.notes),
            str(manifest_path),
            now,
        ),
    )


def persist_candidate_documents(
    connection: sqlite3.Connection,
    *,
    candidates: list[PubMedCandidate],
    run_id: str,
) -> int:
    now = datetime.now(UTC).isoformat()
    rows = [candidate for candidate in candidates if candidate.identity_status != "in_legacy_exact"]
    connection.executemany(
        """
        INSERT INTO document (
            document_id, document_type, primary_title, publication_year, canonical_url,
            pmid, pmcid, doi, lifecycle_state, review_state, provenance_json, run_id
        )
        VALUES (?, 'publication', ?, ?, ?, ?, ?, ?, 'active', 'needs_review', ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            primary_title = excluded.primary_title,
            publication_year = excluded.publication_year,
            canonical_url = excluded.canonical_url,
            pmid = excluded.pmid,
            pmcid = excluded.pmcid,
            doi = excluded.doi,
            review_state = excluded.review_state,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id
        """,
        [
            (
                candidate.document_id,
                candidate.title,
                candidate.publication_year,
                candidate.canonical_url,
                candidate.pmid,
                candidate.pmcid,
                candidate.doi,
                dump_json(candidate.provenance),
                run_id,
            )
            for candidate in rows
        ],
    )
    connection.executemany(
        """
        INSERT INTO publication (
            document_id, title_pt, title_en, normalized_title, legacy_study_id,
            legacy_study_type, legacy_result, legacy_reference_values_json,
            journal, authors_json, publication_types_json, language, abstract
        )
        VALUES (?, NULL, ?, ?, '', NULL, NULL, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            title_en = excluded.title_en,
            normalized_title = excluded.normalized_title,
            legacy_reference_values_json = excluded.legacy_reference_values_json,
            journal = excluded.journal,
            authors_json = excluded.authors_json,
            publication_types_json = excluded.publication_types_json,
            language = excluded.language,
            abstract = excluded.abstract
        """,
        [
            (
                candidate.document_id,
                candidate.title,
                candidate.normalized_title,
                dump_json(
                    {
                        "source": "pubmed",
                        "identity_status": candidate.identity_status,
                        "legacy_document_ids": candidate.legacy_document_ids,
                        "legacy_study_ids": candidate.legacy_study_ids,
                    }
                ),
                candidate.journal,
                dump_json(candidate.authors),
                dump_json(candidate.publication_types),
                candidate.languages[0] if candidate.languages else None,
                candidate.abstract,
            )
            for candidate in rows
        ],
    )
    identity_rows = []
    for candidate in rows:
        for identifier_type, identifier_value in (
            ("pmid", candidate.pmid),
            ("pmcid", candidate.pmcid),
            ("doi", candidate.doi),
            ("canonical_url", candidate.canonical_url),
            ("normalized_title", candidate.normalized_title),
        ):
            if not identifier_value:
                continue
            identity_rows.append(
                (
                    document_identity_id(
                        candidate.document_id,
                        identifier_type,
                        identifier_value,
                    ),
                    candidate.document_id,
                    identifier_type,
                    identifier_value,
                    "pubmed",
                    identity_confidence(identifier_type, candidate.identity_status),
                    candidate.identity_status,
                    run_id,
                )
            )
    connection.executemany(
        """
        INSERT INTO document_identity (
            document_identity_id, document_id, identifier_type, identifier_value, source,
            confidence, association_state, run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id, identifier_type, identifier_value) DO UPDATE SET
            source = excluded.source,
            confidence = excluded.confidence,
            association_state = excluded.association_state,
            run_id = excluded.run_id
        """,
        identity_rows,
    )
    connection.executemany(
        """
        INSERT INTO publication_candidate_discovery (
            document_id, source, source_candidate_id, identity_status, legacy_match_type,
            legacy_match_confidence, legacy_document_ids_json, legacy_study_ids_json,
            cannabinoid_focus, study_design, study_design_rank, priority_tier,
            priority_score, full_text_review_priority, query_names_json, score_reasons_json,
            review_reasons_json, provenance_json, run_id, created_at, updated_at
        )
        VALUES (?, 'pubmed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(document_id) DO UPDATE SET
            identity_status = excluded.identity_status,
            legacy_match_type = excluded.legacy_match_type,
            legacy_match_confidence = excluded.legacy_match_confidence,
            legacy_document_ids_json = excluded.legacy_document_ids_json,
            legacy_study_ids_json = excluded.legacy_study_ids_json,
            cannabinoid_focus = excluded.cannabinoid_focus,
            study_design = excluded.study_design,
            study_design_rank = excluded.study_design_rank,
            priority_tier = excluded.priority_tier,
            priority_score = excluded.priority_score,
            full_text_review_priority = excluded.full_text_review_priority,
            query_names_json = excluded.query_names_json,
            score_reasons_json = excluded.score_reasons_json,
            review_reasons_json = excluded.review_reasons_json,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id,
            updated_at = excluded.updated_at
        """,
        [
            (
                candidate.document_id,
                candidate.pmid,
                candidate.identity_status,
                candidate.legacy_match_type,
                candidate.legacy_match_confidence,
                dump_json(candidate.legacy_document_ids),
                dump_json(candidate.legacy_study_ids),
                candidate.cannabinoid_focus,
                candidate.study_design,
                candidate.study_design_rank,
                candidate.priority_tier,
                candidate.priority_score,
                candidate.full_text_review_priority,
                dump_json(candidate.query_names),
                dump_json(candidate.score_reasons),
                dump_json(candidate.review_reasons),
                dump_json(candidate.provenance),
                run_id,
                now,
                now,
            )
            for candidate in rows
        ],
    )
    return len(rows)


def identity_confidence(identifier_type: str, identity_status: str) -> float:
    if identity_status == "new_candidate" and identifier_type in {"pmid", "doi", "pmcid"}:
        return 0.95
    if identity_status == "possible_legacy_match":
        return 0.75
    if identity_status == "needs_manual_identity_review":
        return 0.5
    return 0.8


def persist_publication_candidate_review_queue(
    connection: sqlite3.Connection,
    *,
    candidates: list[PubMedCandidate],
    run_id: str,
) -> int:
    now = datetime.now(UTC).isoformat()
    rows = []
    for candidate in candidates:
        if candidate.identity_status == "in_legacy_exact":
            continue
        rows.append(
            (
                review_item_id(PUBMED_CANDIDATE_QUEUE, candidate.document_id),
                PUBMED_CANDIDATE_QUEUE,
                candidate.document_id,
                candidate.priority_tier,
                candidate.priority_score,
                None,
                "open",
                run_id,
                dump_json(review_item_metadata(candidate)),
                now,
                now,
            )
        )
    connection.executemany(
        """
        INSERT INTO review_item (
            review_item_id, queue_type, document_id, priority_tier, priority_score,
            assignee, status, batch_run_id, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(queue_type, document_id) DO UPDATE SET
            priority_tier = excluded.priority_tier,
            priority_score = excluded.priority_score,
            batch_run_id = excluded.batch_run_id,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        rows,
    )
    return len(rows)
