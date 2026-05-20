from __future__ import annotations

import os
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from dotenv import load_dotenv

from marygenai import __version__
from marygenai.access_enrichment.clients import EuropePmcClient, PmcClient, UnpaywallClient
from marygenai.access_enrichment.models import (
    AccessArtifact,
    AccessEnrichmentCandidate,
    AccessEnrichmentRecord,
    AccessEnrichmentResult,
)
from marygenai.initial_load.files import file_sha256, stable_hash
from marygenai.initial_load.persist import dump_json
from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.schemas import OutputArtifact, RunManifest
from marygenai.storage import LocalStorage

DEFAULT_CANNABINOID_FOCUS = ("direct_title_or_indexed",)
DEFAULT_FULL_TEXT_PRIORITY = ("high_auto_full_text",)
DEFAULT_EXCLUDED_IDENTITY_STATUS = "needs_manual_identity_review"


class AccessClientBundle(Protocol):
    pmc: PmcClient
    europe_pmc: EuropePmcClient
    unpaywall: UnpaywallClient | None


class DefaultAccessClientBundle:
    def __init__(self, *, unpaywall_email: str | None) -> None:
        self.pmc = PmcClient()
        self.europe_pmc = EuropePmcClient()
        self.unpaywall = UnpaywallClient(email=unpaywall_email) if unpaywall_email else None

    def close(self) -> None:
        self.pmc.close()
        self.europe_pmc.close()
        if self.unpaywall:
            self.unpaywall.close()


def run_access_enrichment(
    *,
    storage: LocalStorage,
    database_path: Path | None = None,
    run_id: str | None = None,
    limit: int = 50,
    identity_statuses: list[str] | None = None,
    cannabinoid_focuses: list[str] | None = None,
    full_text_priorities: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_manual_identity_review: bool = False,
    fetch_pmc_html: bool = False,
    fetch_pdf: bool = False,
    clients: AccessClientBundle | None = None,
    sleep_seconds: float = 0.1,
) -> AccessEnrichmentResult:
    """Enrich prioritized PubMed candidates with access and full-text candidate evidence."""
    load_dotenv()
    storage.ensure_layout()
    resolved_database_path = database_path or sqlite_database_path(storage.root)
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    fetched_at = started_at.isoformat()

    with connect_sqlite(resolved_database_path) as connection:
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
        candidates = select_access_enrichment_candidates(
            connection,
            limit=limit,
            identity_statuses=identity_statuses,
            cannabinoid_focuses=cannabinoid_focuses or list(DEFAULT_CANNABINOID_FOCUS),
            full_text_priorities=full_text_priorities or list(DEFAULT_FULL_TEXT_PRIORITY),
            study_designs=study_designs,
            include_manual_identity_review=include_manual_identity_review,
        )

    client_bundle = clients or DefaultAccessClientBundle(
        unpaywall_email=value_or_none(os.getenv("UNPAYWALL_EMAIL"))
    )
    owns_clients = clients is None
    records: list[AccessEnrichmentRecord] = []
    try:
        for candidate in candidates:
            records.append(
                enrich_candidate(
                    candidate,
                    storage=storage,
                    run_id=resolved_run_id,
                    fetched_at=fetched_at,
                    clients=client_bundle,
                    fetch_pmc_html=fetch_pmc_html,
                    fetch_pdf=fetch_pdf,
                )
            )
            time.sleep(sleep_seconds)
    finally:
        if owns_clients and hasattr(client_bundle, "close"):
            client_bundle.close()

    output_paths = write_access_outputs(
        storage=storage,
        run_id=resolved_run_id,
        records=records,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        fetched_at=fetched_at,
    )
    with connect_sqlite(resolved_database_path) as connection:
        initialize_schema(connection)
        manifest = RunManifest.model_validate_json(
            output_paths["manifest"].read_text(encoding="utf-8")
        )
        persist_access_manifest(
            connection,
            manifest=manifest,
            manifest_path=output_paths["manifest"],
        )
        artifact_count = persist_access_artifacts(
            connection,
            records=records,
            run_id=resolved_run_id,
        )

    counts = {
        "selected_candidates": len(candidates),
        "enriched_records": len(records),
        "access_artifacts": artifact_count,
        "records_with_errors": sum(bool(record.errors) for record in records),
    }
    return AccessEnrichmentResult(
        run_id=resolved_run_id,
        manifest_path=str(output_paths["manifest"]),
        output_paths={name: str(path) for name, path in output_paths.items()},
        counts=counts,
    )


def select_access_enrichment_candidates(
    connection: sqlite3.Connection,
    *,
    limit: int,
    identity_statuses: list[str] | None = None,
    cannabinoid_focuses: list[str] | None = None,
    full_text_priorities: list[str] | None = None,
    study_designs: list[str] | None = None,
    include_manual_identity_review: bool = False,
) -> list[AccessEnrichmentCandidate]:
    clauses = ["ri.queue_type = 'publication_candidate_review'"]
    params: list[Any] = []
    if identity_statuses:
        clauses.append(in_clause("discovery.identity_status", identity_statuses, params))
    elif not include_manual_identity_review:
        clauses.append("discovery.identity_status != ?")
        params.append(DEFAULT_EXCLUDED_IDENTITY_STATUS)
    if cannabinoid_focuses:
        clauses.append(in_clause("discovery.cannabinoid_focus", cannabinoid_focuses, params))
    if full_text_priorities:
        clauses.append(
            in_clause("discovery.full_text_review_priority", full_text_priorities, params)
        )
    if study_designs:
        clauses.append(in_clause("discovery.study_design", study_designs, params))
    params.append(limit)
    rows = connection.execute(
        f"""
        SELECT
            discovery.document_id,
            document.primary_title AS title,
            document.pmid,
            document.pmcid,
            document.doi,
            discovery.identity_status,
            discovery.cannabinoid_focus,
            discovery.study_design,
            discovery.priority_score,
            discovery.full_text_review_priority
        FROM publication_candidate_discovery AS discovery
        JOIN document ON document.document_id = discovery.document_id
        JOIN review_item AS ri
            ON ri.document_id = discovery.document_id
            AND ri.queue_type = 'publication_candidate_review'
        WHERE {" AND ".join(clauses)}
        ORDER BY discovery.priority_score DESC, ri.created_at ASC, discovery.document_id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [AccessEnrichmentCandidate.model_validate(dict(row)) for row in rows]


def in_clause(column: str, values: list[str], params: list[Any]) -> str:
    placeholders = ", ".join("?" for _ in values)
    params.extend(values)
    return f"{column} IN ({placeholders})"


def enrich_candidate(
    candidate: AccessEnrichmentCandidate,
    *,
    storage: LocalStorage,
    run_id: str,
    fetched_at: str,
    clients: AccessClientBundle,
    fetch_pmc_html: bool,
    fetch_pdf: bool,
) -> AccessEnrichmentRecord:
    errors: list[str] = []
    artifacts: list[AccessArtifact] = []
    europe_pmc_payload: dict[str, Any] | None = None
    unpaywall_payload: dict[str, Any] | None = None

    if candidate.pmcid:
        artifacts.extend(
            fetch_pmc_artifacts(
                candidate,
                storage=storage,
                run_id=run_id,
                fetched_at=fetched_at,
                clients=clients,
                fetch_pmc_html=fetch_pmc_html,
            )
        )

    if candidate.pmid or candidate.doi:
        try:
            europe_pmc_payload = clients.europe_pmc.search_by_pmid_or_doi(
                pmid=candidate.pmid,
                doi=candidate.doi,
            )
            artifacts.append(
                write_json_artifact(
                    storage=storage,
                    run_id=run_id,
                    candidate=candidate,
                    source="europe_pmc",
                    artifact_type="europe_pmc_metadata",
                    relative_dir=Path("raw/europe_pmc/metadata"),
                    payload=europe_pmc_payload or {},
                    url="https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    fetched_at=fetched_at,
                    access_class=europe_pmc_access_class(europe_pmc_payload),
                    license=europe_pmc_license(europe_pmc_payload),
                )
            )
        except httpx.HTTPError as error:
            errors.append(f"europe_pmc_metadata:{error}")

    europe_pmc_result = first_europe_pmc_result(europe_pmc_payload)
    if should_fetch_europe_pmc_xml(europe_pmc_result):
        try:
            source = str(europe_pmc_result["source"])
            identifier = str(europe_pmc_result["id"])
            content = clients.europe_pmc.fetch_full_text_xml(source=source, identifier=identifier)
            artifacts.append(
                write_bytes_artifact(
                    storage=storage,
                    run_id=run_id,
                    candidate=candidate,
                    source="europe_pmc",
                    artifact_type="europe_pmc_full_text_xml",
                    relative_dir=Path("raw/europe_pmc/full_text_xml"),
                    content=content,
                    suffix=".xml",
                    url=f"https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{identifier}/fullTextXML",
                    fetched_at=fetched_at,
                    access_class="open_access_xml",
                    license=europe_pmc_license(europe_pmc_payload),
                )
            )
        except httpx.HTTPError as error:
            errors.append(f"europe_pmc_full_text_xml:{error}")

    doi_for_unpaywall = candidate.doi or doi_from_europe_pmc_payload(europe_pmc_payload)
    if doi_for_unpaywall:
        if clients.unpaywall:
            try:
                unpaywall_payload = clients.unpaywall.get_by_doi(doi_for_unpaywall)
                artifacts.append(
                    write_json_artifact(
                        storage=storage,
                        run_id=run_id,
                        candidate=candidate,
                        source="unpaywall",
                        artifact_type="unpaywall_metadata",
                        relative_dir=Path("raw/unpaywall/doi"),
                        payload=unpaywall_payload,
                        url=f"https://api.unpaywall.org/v2/{doi_for_unpaywall}",
                        fetched_at=fetched_at,
                        access_class=unpaywall_access_class(unpaywall_payload),
                        license=unpaywall_license(unpaywall_payload),
                    )
                )
            except httpx.HTTPError as error:
                errors.append(f"unpaywall_metadata:{error}")
        else:
            errors.append("unpaywall_metadata:missing_UNPAYWALL_EMAIL")

    full_text_urls = dedupe_preserving_order(
        pmc_full_text_urls(candidate)
        + europe_pmc_full_text_urls(europe_pmc_result)
        + unpaywall_landing_urls(unpaywall_payload)
    )
    pdf_urls = dedupe_preserving_order(
        europe_pmc_pdf_urls(europe_pmc_result) + unpaywall_pdf_urls(unpaywall_payload)
    )
    if not fetch_pdf:
        pdf_urls = pdf_urls[:3]

    artifact_errors = [error for artifact in artifacts for error in artifact.errors]
    all_errors = errors + artifact_errors
    return AccessEnrichmentRecord(
        run_id=run_id,
        document_id=candidate.document_id,
        title=candidate.title,
        pmid=candidate.pmid,
        pmcid=candidate.pmcid,
        doi=candidate.doi,
        identity_status=candidate.identity_status,
        cannabinoid_focus=candidate.cannabinoid_focus,
        study_design=candidate.study_design,
        full_text_review_priority=candidate.full_text_review_priority,
        resolved_access_class=resolved_access_class(
            artifacts,
            full_text_urls,
            pdf_urls,
            all_errors,
        ),
        candidate_full_text_urls=full_text_urls,
        candidate_pdf_urls=pdf_urls,
        artifacts=artifacts,
        errors=all_errors,
        provenance={
            "source": "access_enrichment",
            "method": "pubmed_candidate_access_enrichment",
            "fetched_at": fetched_at,
            "review_boundary": "candidate_evidence_not_reviewed_knowledge",
        },
    )


def fetch_pmc_artifacts(
    candidate: AccessEnrichmentCandidate,
    *,
    storage: LocalStorage,
    run_id: str,
    fetched_at: str,
    clients: AccessClientBundle,
    fetch_pmc_html: bool,
) -> list[AccessArtifact]:
    artifacts: list[AccessArtifact] = []
    assert candidate.pmcid is not None
    try:
        nxml = clients.pmc.fetch_nxml(candidate.pmcid)
        artifacts.append(
            write_bytes_artifact(
                storage=storage,
                run_id=run_id,
                candidate=candidate,
                source="pmc",
                artifact_type="pmc_nxml",
                relative_dir=Path("raw/pmc/xml"),
                content=nxml,
                suffix=".nxml",
                url=f"https://pmc.ncbi.nlm.nih.gov/articles/{candidate.pmcid}/?report=xml",
                fetched_at=fetched_at,
                access_class="open_access_xml",
                license=None,
            )
        )
    except httpx.HTTPError as error:
        artifacts.append(
            error_artifact(
                candidate,
                run_id,
                "pmc",
                "pmc_nxml",
                f"pmc_nxml:{error}",
                fetched_at,
            )
        )
    if fetch_pmc_html:
        try:
            html = clients.pmc.fetch_html(candidate.pmcid)
            artifacts.append(
                write_bytes_artifact(
                    storage=storage,
                    run_id=run_id,
                    candidate=candidate,
                    source="pmc",
                    artifact_type="pmc_html",
                    relative_dir=Path("raw/pmc/html"),
                    content=html,
                    suffix=".html",
                    url=f"https://pmc.ncbi.nlm.nih.gov/articles/{candidate.pmcid}/",
                    fetched_at=fetched_at,
                    access_class="open_access_html",
                    license=None,
                )
            )
        except httpx.HTTPError as error:
            artifacts.append(
                error_artifact(
                    candidate,
                    run_id,
                    "pmc",
                    "pmc_html",
                    f"pmc_html:{error}",
                    fetched_at,
                )
            )
    return artifacts


def write_json_artifact(
    *,
    storage: LocalStorage,
    run_id: str,
    candidate: AccessEnrichmentCandidate,
    source: str,
    artifact_type: str,
    relative_dir: Path,
    payload: dict[str, Any],
    url: str,
    fetched_at: str,
    access_class: str,
    license: str | None,
) -> AccessArtifact:
    filename = f"{run_id}_{safe_document_id(candidate.document_id)}_{artifact_type}.json"
    relative_path = relative_dir / filename
    output_path = storage.write_json(relative_path, payload)
    return AccessArtifact(
        artifact_id=access_artifact_id(run_id, candidate.document_id, artifact_type, url),
        document_id=candidate.document_id,
        source=source,  # type: ignore[arg-type]
        artifact_type=artifact_type,  # type: ignore[arg-type]
        url=url,
        access_class=access_class,
        license=license,
        payload_path=str(output_path),
        payload_sha256=file_sha256(output_path),
        payload_size_bytes=output_path.stat().st_size,
        raw_payload=payload,
        provenance=artifact_provenance(run_id, fetched_at),
    )


def write_bytes_artifact(
    *,
    storage: LocalStorage,
    run_id: str,
    candidate: AccessEnrichmentCandidate,
    source: str,
    artifact_type: str,
    relative_dir: Path,
    content: bytes,
    suffix: str,
    url: str,
    fetched_at: str,
    access_class: str,
    license: str | None,
) -> AccessArtifact:
    filename = f"{run_id}_{safe_document_id(candidate.document_id)}_{artifact_type}{suffix}"
    output_path = storage.path(relative_dir / filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    return AccessArtifact(
        artifact_id=access_artifact_id(run_id, candidate.document_id, artifact_type, url),
        document_id=candidate.document_id,
        source=source,  # type: ignore[arg-type]
        artifact_type=artifact_type,  # type: ignore[arg-type]
        url=url,
        access_class=access_class,
        license=license,
        payload_path=str(output_path),
        payload_sha256=file_sha256(output_path),
        payload_size_bytes=output_path.stat().st_size,
        provenance=artifact_provenance(run_id, fetched_at),
    )


def error_artifact(
    candidate: AccessEnrichmentCandidate,
    run_id: str,
    source: str,
    artifact_type: str,
    error: str,
    fetched_at: str,
) -> AccessArtifact:
    return AccessArtifact(
        artifact_id=access_artifact_id(run_id, candidate.document_id, artifact_type, error),
        document_id=candidate.document_id,
        source=source,  # type: ignore[arg-type]
        artifact_type=artifact_type,  # type: ignore[arg-type]
        access_class="error",
        errors=[error],
        provenance=artifact_provenance(run_id, fetched_at),
    )


def write_access_outputs(
    *,
    storage: LocalStorage,
    run_id: str,
    records: list[AccessEnrichmentRecord],
    started_at: datetime,
    completed_at: datetime,
    fetched_at: str,
) -> dict[str, Path]:
    records_path = storage.write_jsonl(
        Path("normalized/publication_enrichments/access_enrichment")
        / f"{run_id}_access_enrichment_records.jsonl",
        records,
    )
    summary = {
        "run_id": run_id,
        "source": "access_enrichment",
        "method": "pubmed_candidate_access_enrichment",
        "fetched_at": fetched_at,
        "total_records": len(records),
        "resolved_access_class_counts": dict(
            Counter(record.resolved_access_class for record in records).most_common()
        ),
        "records_with_errors": sum(bool(record.errors) for record in records),
        "artifact_count": sum(len(record.artifacts) for record in records),
    }
    summary_path = storage.write_json(
        Path("normalized/publication_enrichments/access_enrichment")
        / f"{run_id}_access_enrichment_summary.json",
        summary,
    )
    manifest = RunManifest(
        run_id=run_id,
        job_type="access_enrichment",
        source="pubmed_candidate_access_enrichment",
        started_at=started_at,
        completed_at=completed_at,
        status="succeeded",
        software_version=__version__,
        input_artifacts=[],
        output_artifacts=[
            OutputArtifact(
                path=str(records_path),
                record_count=len(records),
                sha256=file_sha256(records_path),
            ),
            OutputArtifact(
                path=str(summary_path),
                record_count=1,
                sha256=file_sha256(summary_path),
            ),
        ],
        counts={
            "enriched_records": len(records),
            "access_artifacts": sum(len(record.artifacts) for record in records),
        },
        notes=[
            "Access enrichment outputs are candidate evidence and are not reviewed knowledge.",
            "PDF URLs are classified but PDF files are not downloaded by the default command.",
        ],
    )
    manifest_path = storage.write_json(
        Path("manifests/runs") / f"{run_id}_access_enrichment_manifest.json",
        manifest,
    )
    return {"records": records_path, "summary": summary_path, "manifest": manifest_path}


def persist_access_manifest(
    connection: sqlite3.Connection,
    *,
    manifest: RunManifest,
    manifest_path: Path,
) -> None:
    imported_at = datetime.now(UTC).isoformat()
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
            completed_at = excluded.completed_at,
            status = excluded.status,
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
            imported_at,
        ),
    )


def persist_access_artifacts(
    connection: sqlite3.Connection,
    *,
    records: list[AccessEnrichmentRecord],
    run_id: str,
) -> int:
    now = datetime.now(UTC).isoformat()
    rows = []
    for record in records:
        for artifact in record.artifacts:
            rows.append(
                (
                    artifact.artifact_id,
                    artifact.document_id,
                    artifact.source,
                    artifact.artifact_type,
                    artifact.access_class,
                    artifact.url,
                    artifact.license,
                    artifact.payload_path,
                    artifact.payload_sha256,
                    artifact.payload_size_bytes,
                    dump_json(artifact.raw_payload or {}),
                    dump_json(artifact.errors),
                    dump_json(artifact.provenance),
                    run_id,
                    now,
                )
            )
    connection.executemany(
        """
        INSERT INTO access_enrichment_artifact (
            artifact_id, document_id, source, artifact_type, access_class, url, license,
            payload_path, payload_sha256, payload_size_bytes, raw_payload_json, errors_json,
            provenance_json, run_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(artifact_id) DO UPDATE SET
            access_class = excluded.access_class,
            url = excluded.url,
            license = excluded.license,
            payload_path = excluded.payload_path,
            payload_sha256 = excluded.payload_sha256,
            payload_size_bytes = excluded.payload_size_bytes,
            raw_payload_json = excluded.raw_payload_json,
            errors_json = excluded.errors_json,
            provenance_json = excluded.provenance_json,
            run_id = excluded.run_id
        """,
        rows,
    )
    return len(rows)


def first_europe_pmc_result(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    results = payload.get("resultList", {}).get("result", [])
    return results[0] if results else None


def europe_pmc_full_text_urls(result: dict[str, Any] | None) -> list[str]:
    urls = europe_pmc_url_records(result)
    return [
        url_record["url"]
        for url_record in urls
        if value_or_none(url_record.get("url"))
        and is_free_or_open_access_url(url_record)
        and not is_pdf_url(url_record)
    ]


def europe_pmc_pdf_urls(result: dict[str, Any] | None) -> list[str]:
    urls = europe_pmc_url_records(result)
    return [
        url_record["url"]
        for url_record in urls
        if value_or_none(url_record.get("url"))
        and is_free_or_open_access_url(url_record)
        and is_pdf_url(url_record)
    ]


def europe_pmc_url_records(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result:
        return []
    return result.get("fullTextUrlList", {}).get("fullTextUrl", []) or []


def should_fetch_europe_pmc_xml(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    return (
        bool_or_none(result.get("hasFullText")) is True
        and bool_or_none(result.get("isOpenAccess")) is True
    )


def doi_from_europe_pmc_payload(payload: dict[str, Any] | None) -> str | None:
    result = first_europe_pmc_result(payload)
    if not result:
        return None
    return value_or_none(result.get("doi"))


def europe_pmc_access_class(payload: dict[str, Any] | None) -> str:
    result = first_europe_pmc_result(payload)
    if not result:
        return "metadata_not_found"
    if (
        bool_or_none(result.get("hasFullText")) is True
        and bool_or_none(result.get("isOpenAccess")) is True
    ):
        return "open_access_full_text_available"
    if bool_or_none(result.get("hasFullText")) is True:
        return "full_text_metadata_available"
    return "metadata_only"


def europe_pmc_license(payload: dict[str, Any] | None) -> str | None:
    result = first_europe_pmc_result(payload)
    if not result:
        return None
    return value_or_none(result.get("license"))


def unpaywall_access_class(payload: dict[str, Any] | None) -> str:
    if not payload or payload.get("not_found"):
        return "metadata_not_found"
    if bool_or_none(payload.get("is_oa")) is True:
        return f"open_access_{value_or_none(payload.get('oa_status')) or 'unknown'}"
    return "closed_or_unknown_access"


def unpaywall_license(payload: dict[str, Any] | None) -> str | None:
    location = unpaywall_best_location(payload)
    if not location:
        return None
    return value_or_none(location.get("license"))


def unpaywall_best_location(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload or payload.get("not_found"):
        return None
    return payload.get("best_oa_location")


def unpaywall_landing_urls(payload: dict[str, Any] | None) -> list[str]:
    location = unpaywall_best_location(payload)
    if not location:
        return []
    url = value_or_none(location.get("url_for_landing_page"))
    return [url] if url else []


def unpaywall_pdf_urls(payload: dict[str, Any] | None) -> list[str]:
    location = unpaywall_best_location(payload)
    if not location:
        return []
    url = value_or_none(location.get("url_for_pdf"))
    return [url] if url else []


def pmc_full_text_urls(candidate: AccessEnrichmentCandidate) -> list[str]:
    if not candidate.pmcid:
        return []
    return [
        f"https://pmc.ncbi.nlm.nih.gov/articles/{candidate.pmcid}/?report=xml",
        f"https://pmc.ncbi.nlm.nih.gov/articles/{candidate.pmcid}/",
    ]


def resolved_access_class(
    artifacts: list[AccessArtifact],
    full_text_urls: list[str],
    pdf_urls: list[str],
    errors: list[str],
) -> str:
    if any(
        artifact.payload_path
        and artifact.artifact_type in {"pmc_nxml", "europe_pmc_full_text_xml"}
        for artifact in artifacts
    ):
        return "retrieved_open_access_xml"
    if any(
        artifact.payload_path and artifact.artifact_type == "pmc_html"
        for artifact in artifacts
    ):
        return "retrieved_open_access_html"
    if full_text_urls:
        return "open_access_full_text_candidate"
    if pdf_urls:
        return "open_access_pdf_candidate"
    if artifacts:
        return "metadata_enriched_no_full_text"
    if errors:
        return "not_enriched_with_errors"
    return "not_enriched"


def is_free_or_open_access_url(url_record: dict[str, Any]) -> bool:
    availability_code = value_or_none(url_record.get("availabilityCode"))
    return availability_code in {"F", "OA"}


def is_pdf_url(url_record: dict[str, Any]) -> bool:
    document_style = value_or_none(url_record.get("documentStyle"))
    url = value_or_none(url_record.get("url")) or ""
    return document_style == "pdf" or url.lower().endswith(".pdf")


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if lowered in {"y", "yes", "true", "1"}:
            return True
        if lowered in {"n", "no", "false", "0"}:
            return False
    return bool(value)


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def safe_document_id(document_id: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in document_id)


def access_artifact_id(run_id: str, document_id: str, artifact_type: str, url_or_error: str) -> str:
    digest = stable_hash(
        {
            "run_id": run_id,
            "document_id": document_id,
            "artifact_type": artifact_type,
            "url": url_or_error,
        }
    )
    return f"access_artifact:{digest[:24]}"


def artifact_provenance(run_id: str, fetched_at: str) -> dict[str, Any]:
    return {
        "source": "access_enrichment",
        "method": "pubmed_candidate_access_enrichment",
        "run_id": run_id,
        "fetched_at": fetched_at,
        "review_state": "needs_review",
    }

