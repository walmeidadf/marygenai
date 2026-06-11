"""Estimate and probe full-text availability for legacy core-ID publications.

This POC reads local SQLite and access-artifact audit outputs, then writes
ignored JSONL/JSON artifacts. It does not mutate SQLite, review state, review
items, review decisions, or reviewed knowledge.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import httpx
import pymupdf
import typer
from lxml import etree, html
from rich.console import Console
from rich.table import Table

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.settings import get_settings

OUTPUT_SUBDIR = Path("normalized/source_availability_ceiling")
AUDIT_ROLLUP_GLOB = (
    "normalized/publication_enrichments/access_artifact_quality/"
    "*_access_artifact_document_rollup.jsonl"
)

MIN_CLASSIFICATION_TEXT_CHARS = 4_000
SCIENTIFIC_SECTION_TERMS = {
    "abstract",
    "introduction",
    "background",
    "methods",
    "materials",
    "participants",
    "patients",
    "intervention",
    "results",
    "discussion",
    "conclusion",
    "adverse",
    "safety",
}
CANNABINOID_TERMS = {
    "cannabinoid",
    "cannabis",
    "cannabidiol",
    "cbd",
    "thc",
    "tetrahydrocannabinol",
    "endocannabinoid",
}
OPEN_PUBLISHER_HOST_HINTS = (
    "frontiersin.org",
    "mdpi.com",
    "plos.org",
    "biomedcentral.com",
    "springeropen.com",
    "nature.com",
    "sciencedirect.com",
    "tandfonline.com",
    "liebertpub.com",
    "wiley.com",
    "sagepub.com",
)

console = Console()
app = typer.Typer(help="Estimate the source availability ceiling for legacy core-ID records.")


@dataclass(frozen=True)
class LocalCandidateRecord:
    document_id: str
    legacy_study_id: str | None
    title: str | None
    publication_year: int | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    canonical_url: str | None
    audit_status: str
    has_pmcid_route: bool
    has_persisted_invalid_pmc_artifact: bool
    has_europe_pmc_pmcid_discovered: bool
    has_europe_pmc_full_text_hint: bool
    has_europe_pmc_open_access_hint: bool
    has_unpaywall_oa_location: bool
    has_unpaywall_pdf_url: bool
    has_unpaywall_landing_url: bool
    has_publisher_or_doi_probe_candidate: bool
    source_strategy_bucket: str
    candidate_urls: list[dict[str, str]]
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ProbeRecord:
    document_id: str
    source_strategy: str
    url: str
    status_code: int | None
    final_url: str | None
    content_type: str | None
    retrieved_bytes: int
    source_format: str
    extracted_text_chars: int
    scientific_section_hit_count: int
    cannabinoid_term_hit_count: int
    classification_ready_text: bool
    pdf_retrieved_without_text_extraction: bool
    likely_needs_ocr: bool
    error: str | None
    provenance: dict[str, Any]


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def latest_rollup_path(data_dir: Path) -> Path:
    paths = sorted(data_dir.glob(AUDIT_ROLLUP_GLOB))
    if not paths:
        msg = f"No audit rollup found under {data_dir / AUDIT_ROLLUP_GLOB}."
        raise FileNotFoundError(msg)
    return paths[-1]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            payload = asdict(record) if hasattr(record, "__dataclass_fields__") else record
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def connect_readonly(database_path: Path) -> sqlite3.Connection:
    uri = f"file:{database_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def load_legacy_documents(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT d.document_id, d.pmid, d.pmcid, d.doi, d.canonical_url,
               d.primary_title, d.publication_year, d.review_state,
               p.legacy_study_id, p.legacy_study_type, p.journal
        FROM document d
        JOIN publication p ON p.document_id = d.document_id
        WHERE p.legacy_study_id IS NOT NULL AND p.legacy_study_id != ''
        """
    ).fetchall()
    return {str(row["document_id"]): dict(row) for row in rows}


def load_artifacts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT document_id, artifact_type, access_class, raw_payload_json, url
        FROM access_enrichment_artifact
        """
    ).fetchall()
    return [dict(row) for row in rows]


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def europe_pmc_urls(payload: dict[str, Any]) -> list[dict[str, str]]:
    results = ((payload.get("resultList") or {}).get("result") or [])
    urls: list[dict[str, str]] = []
    for result in results:
        full_text_urls = ((result.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        pmcid = value_or_none(result.get("pmcid"))
        if pmcid:
            urls.append(
                {
                    "source_strategy": "europe_pmc_discovered_pmc_xml",
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/?report=xml",
                    "style": "xml",
                }
            )
            urls.append(
                {
                    "source_strategy": "europe_pmc_discovered_pmc_html",
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                    "style": "html",
                }
            )
        for url_record in full_text_urls:
            url = value_or_none(url_record.get("url"))
            availability_code = value_or_none(url_record.get("availabilityCode"))
            if not url or availability_code not in {"F", "OA"}:
                continue
            style = value_or_none(url_record.get("documentStyle")) or "unknown"
            urls.append({"source_strategy": "europe_pmc_full_text_url", "url": url, "style": style})
    return urls


def unpaywall_locations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    for location in payload.get("oa_locations") or []:
        if isinstance(location, dict):
            locations.append(location)
    return locations


def unpaywall_urls(payload: dict[str, Any]) -> list[dict[str, str]]:
    urls: list[dict[str, str]] = []
    for location in unpaywall_locations(payload):
        pdf_url = value_or_none(location.get("url_for_pdf"))
        landing_url = value_or_none(location.get("url_for_landing_page")) or value_or_none(
            location.get("url")
        )
        if pdf_url:
            urls.append(
                {
                    "source_strategy": "unpaywall_pdf",
                    "url": pdf_url,
                    "host_type": value_or_none(location.get("host_type")) or "unknown",
                }
            )
        if landing_url:
            urls.append(
                {
                    "source_strategy": "unpaywall_landing",
                    "url": landing_url,
                    "host_type": value_or_none(location.get("host_type")) or "unknown",
                }
            )
    return dedupe_url_records(urls)


def dedupe_url_records(urls: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for item in urls:
        key = (item.get("source_strategy", ""), item.get("url", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def doi_probe_url(doi: str | None) -> str | None:
    doi = value_or_none(doi)
    if not doi:
        return None
    frontiers_match = re.match(r"^(10\.3389/[^/]+/\d+\.\d+|10\.3389/[^/]+\.\d+)(?:/full)?$", doi)
    if frontiers_match:
        return f"https://www.frontiersin.org/articles/{frontiers_match.group(1)}/full"
    if doi.startswith(("http://", "https://")):
        return doi
    if doi.lower().startswith("doi.org/"):
        return f"https://{doi}"
    if doi.startswith("10."):
        return f"https://doi.org/{quote(doi, safe='/')}"
    return None


def is_publisher_probe_candidate(url: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return any(host in lowered for host in OPEN_PUBLISHER_HOST_HINTS) or lowered.startswith(
        "https://doi.org/"
    )


def build_candidate_records(
    *,
    documents: dict[str, dict[str, Any]],
    rollups: dict[str, dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> tuple[list[LocalCandidateRecord], dict[str, Any]]:
    legacy_core_ids = {
        document_id
        for document_id, document in documents.items()
        if document.get("pmid") or document.get("pmcid") or document.get("doi")
    }
    usable_ids = {
        document_id
        for document_id, rollup in rollups.items()
        if rollup.get("usable_for_llm_classification") and document_id in documents
    }
    target_ids = sorted(legacy_core_ids - usable_ids)

    by_document_id: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for artifact in artifacts:
        by_document_id[str(artifact["document_id"])].append(artifact)

    records: list[LocalCandidateRecord] = []
    for document_id in target_ids:
        document = documents[document_id]
        document_artifacts = by_document_id.get(document_id, [])
        candidate_urls: list[dict[str, str]] = []
        has_europe_pmc_full_text_hint = False
        has_europe_pmc_pmcid_discovered = False
        has_europe_pmc_open_access_hint = False
        has_unpaywall_oa_location = False
        has_unpaywall_pdf_url = False
        has_unpaywall_landing_url = False

        for artifact in document_artifacts:
            payload = parse_json_object(artifact.get("raw_payload_json"))
            artifact_type = artifact.get("artifact_type")
            if artifact_type == "europe_pmc_metadata":
                for result in ((payload.get("resultList") or {}).get("result") or []):
                    if value_or_none(result.get("pmcid")):
                        has_europe_pmc_pmcid_discovered = True
                    if (
                        str(result.get("hasFullText", "")).upper() == "Y"
                        or str(result.get("hasPDF", "")).upper() == "Y"
                    ):
                        has_europe_pmc_full_text_hint = True
                    if str(result.get("isOpenAccess", "")).upper() == "Y":
                        has_europe_pmc_open_access_hint = True
                candidate_urls.extend(europe_pmc_urls(payload))
            elif artifact_type == "unpaywall_metadata":
                if (
                    payload.get("is_oa")
                    or str(artifact.get("access_class", "")).startswith("open_access")
                    or payload.get("best_oa_location")
                ):
                    has_unpaywall_oa_location = True
                urls = unpaywall_urls(payload)
                has_unpaywall_pdf_url = any(
                    item["source_strategy"] == "unpaywall_pdf" for item in urls
                )
                has_unpaywall_landing_url = any(
                    item["source_strategy"] == "unpaywall_landing" for item in urls
                )
                candidate_urls.extend(urls)

        pmcid = value_or_none(document.get("pmcid"))
        if pmcid:
            candidate_urls.append(
                {
                    "source_strategy": "pmcid_pmc_xml",
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/?report=xml",
                }
            )
            candidate_urls.append(
                {
                    "source_strategy": "pmcid_pmc_html",
                    "url": f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                }
            )

        doi_url = doi_probe_url(value_or_none(document.get("doi")))
        canonical_url = value_or_none(document.get("canonical_url"))
        if doi_url:
            candidate_urls.append({"source_strategy": "doi_or_publisher_landing", "url": doi_url})
        if canonical_url and canonical_url != doi_url:
            candidate_urls.append(
                {"source_strategy": "doi_or_publisher_landing", "url": canonical_url}
            )
        candidate_urls = dedupe_url_records(candidate_urls)

        has_persisted_invalid_pmc_artifact = any(
            artifact.get("artifact_type") in {"pmc_nxml", "pmc_html"}
            and artifact.get("access_class") in {"open_access_xml", "open_access_html"}
            for artifact in document_artifacts
        )
        has_pmcid_route = bool(pmcid)
        has_publisher_or_doi_probe_candidate = any(
            item["source_strategy"] == "doi_or_publisher_landing"
            and is_publisher_probe_candidate(item["url"])
            for item in candidate_urls
        )
        source_strategy_bucket = source_strategy_bucket_for(
            has_pmcid_route=has_pmcid_route,
            has_europe_pmc_full_text_hint=has_europe_pmc_full_text_hint,
            has_unpaywall_oa_location=has_unpaywall_oa_location,
            has_publisher_or_doi_probe_candidate=has_publisher_or_doi_probe_candidate,
        )
        rollup = rollups.get(document_id, {})
        records.append(
            LocalCandidateRecord(
                document_id=document_id,
                legacy_study_id=value_or_none(document.get("legacy_study_id")),
                title=value_or_none(document.get("primary_title")),
                publication_year=document.get("publication_year"),
                pmid=value_or_none(document.get("pmid")),
                pmcid=pmcid,
                doi=value_or_none(document.get("doi")),
                canonical_url=canonical_url,
                audit_status=value_or_none(rollup.get("document_enrichment_status"))
                or "no_rollup",
                has_pmcid_route=has_pmcid_route,
                has_persisted_invalid_pmc_artifact=has_persisted_invalid_pmc_artifact,
                has_europe_pmc_pmcid_discovered=has_europe_pmc_pmcid_discovered,
                has_europe_pmc_full_text_hint=has_europe_pmc_full_text_hint,
                has_europe_pmc_open_access_hint=has_europe_pmc_open_access_hint,
                has_unpaywall_oa_location=has_unpaywall_oa_location,
                has_unpaywall_pdf_url=has_unpaywall_pdf_url,
                has_unpaywall_landing_url=has_unpaywall_landing_url,
                has_publisher_or_doi_probe_candidate=has_publisher_or_doi_probe_candidate,
                source_strategy_bucket=source_strategy_bucket,
                candidate_urls=candidate_urls,
                provenance={
                    "method": "local_source_availability_ceiling_candidate_build",
                    "does_not_fetch_network": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "operational_source_availability_not_reviewed_knowledge",
                },
            )
        )

    summary = build_local_summary(records, legacy_core_ids=legacy_core_ids, usable_ids=usable_ids)
    return records, summary


def source_strategy_bucket_for(
    *,
    has_pmcid_route: bool,
    has_europe_pmc_full_text_hint: bool,
    has_unpaywall_oa_location: bool,
    has_publisher_or_doi_probe_candidate: bool,
) -> str:
    if has_pmcid_route:
        return "pmcid_route"
    if has_europe_pmc_full_text_hint:
        return "europe_pmc_full_text_hint"
    if has_unpaywall_oa_location:
        return "unpaywall_oa_location"
    if has_publisher_or_doi_probe_candidate:
        return "publisher_or_doi_probe_only"
    return "no_open_full_text_signal_yet"


def count_where(records: list[LocalCandidateRecord], attribute: str) -> int:
    return sum(bool(getattr(record, attribute)) for record in records)


def build_local_summary(
    records: list[LocalCandidateRecord],
    *,
    legacy_core_ids: set[str],
    usable_ids: set[str],
) -> dict[str, Any]:
    pmcid_ids = {record.document_id for record in records if record.has_pmcid_route}
    epmc_ids = {
        record.document_id for record in records if record.has_europe_pmc_full_text_hint
    }
    epmc_pmcid_ids = {
        record.document_id for record in records if record.has_europe_pmc_pmcid_discovered
    }
    unpaywall_oa_ids = {
        record.document_id for record in records if record.has_unpaywall_oa_location
    }
    unpaywall_pdf_ids = {record.document_id for record in records if record.has_unpaywall_pdf_url}
    publisher_probe_ids = {
        record.document_id for record in records if record.has_publisher_or_doi_probe_candidate
    }
    any_pmc_ids = pmcid_ids | epmc_pmcid_ids
    optimistic_ids = any_pmc_ids | epmc_ids | unpaywall_oa_ids
    conservative_ids = any_pmc_ids | epmc_ids | unpaywall_pdf_ids
    expanded_probe_ids = optimistic_ids | publisher_probe_ids
    no_signal_ids = {
        record.document_id
        for record in records
        if not (
            record.has_pmcid_route
            or record.has_europe_pmc_full_text_hint
            or record.has_unpaywall_oa_location
            or record.has_publisher_or_doi_probe_candidate
        )
    }
    return {
        "legacy_core_document_count": len(legacy_core_ids),
        "already_usable_legacy_core_count": len(usable_ids & legacy_core_ids),
        "nonusable_legacy_core_count": len(records),
        "local_candidate_counts": {
            "pmcid_route": len(pmcid_ids),
            "persisted_invalid_pmc_artifact": count_where(
                records, "has_persisted_invalid_pmc_artifact"
            ),
            "europe_pmc_full_text_hint": len(epmc_ids),
            "europe_pmc_pmcid_discovered": len(epmc_pmcid_ids),
            "europe_pmc_open_access_hint": count_where(
                records, "has_europe_pmc_open_access_hint"
            ),
            "unpaywall_oa_location": len(unpaywall_oa_ids),
            "unpaywall_pdf_url": len(unpaywall_pdf_ids),
            "unpaywall_landing_url": count_where(records, "has_unpaywall_landing_url"),
            "publisher_or_doi_probe_candidate": len(publisher_probe_ids),
            "no_open_full_text_signal_yet_after_publisher_probe_candidates": len(
                no_signal_ids
            ),
        },
        "strategy_bucket_counts": dict(
            Counter(record.source_strategy_bucket for record in records)
        ),
        "estimated_unique_candidate_counts": {
            "pmcid_local_or_europe_pmc_discovered": len(any_pmc_ids),
            "conservative_pmcid_epmc_fulltext_unpaywall_pdf": len(conservative_ids),
            "optimistic_pmcid_epmc_fulltext_unpaywall_oa": len(optimistic_ids),
            "expanded_with_publisher_or_doi_probe_candidates": len(expanded_probe_ids),
        },
        "estimated_total_with_existing_usable": {
            "pmcid_local_or_europe_pmc_discovered": len(usable_ids & legacy_core_ids)
            + len(any_pmc_ids),
            "conservative_pmcid_epmc_fulltext_unpaywall_pdf": len(usable_ids & legacy_core_ids)
            + len(conservative_ids),
            "optimistic_pmcid_epmc_fulltext_unpaywall_oa": len(usable_ids & legacy_core_ids)
            + len(optimistic_ids),
            "expanded_with_publisher_or_doi_probe_candidates": len(usable_ids & legacy_core_ids)
            + len(expanded_probe_ids),
        },
    }


def load_local_candidates(
    *,
    data_dir: Path,
    database_path: Path,
) -> tuple[list[LocalCandidateRecord], dict[str, Any]]:
    rollup_path = latest_rollup_path(data_dir)
    rollups = {record["document_id"]: record for record in load_jsonl(rollup_path)}
    with connect_readonly(database_path) as connection:
        documents = load_legacy_documents(connection)
        artifacts = load_artifacts(connection)
    records, summary = build_candidate_records(
        documents=documents,
        rollups=rollups,
        artifacts=artifacts,
    )
    summary["input_paths"] = {
        "database_path": str(database_path),
        "audit_rollup_path": str(rollup_path),
    }
    return records, summary


def fetch_limited(
    client: httpx.Client,
    url: str,
    *,
    max_bytes: int,
) -> tuple[httpx.Response, bytes]:
    with client.stream("GET", url, follow_redirects=True) as response:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                remaining = max_bytes - (size - len(chunk))
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                break
            chunks.append(chunk)
        return response, b"".join(chunks)


def detect_source_format(url: str, content_type: str | None, body: bytes) -> str:
    lowered_content_type = (content_type or "").lower()
    lowered_url = url.lower()
    stripped = body[:200].lstrip()
    if (
        "pdf" in lowered_content_type
        or lowered_url.endswith(".pdf")
        or stripped.startswith(b"%PDF")
    ):
        return "pdf"
    if "xml" in lowered_content_type or stripped.startswith(b"<?xml") or b"<article" in body[:1000]:
        return "xml"
    if "html" in lowered_content_type or b"<html" in body[:1000].lower():
        return "html"
    return "unknown"


def extract_text(source_format: str, body: bytes) -> str:
    if source_format == "pdf":
        return extract_pdf_text_if_possible(body)
    if source_format == "xml":
        return extract_xml_text(body)
    if source_format == "html":
        return extract_html_text(body)
    return ""


def extract_html_text(body: bytes) -> str:
    try:
        document = html.fromstring(body)
    except (etree.ParserError, ValueError):
        return ""
    etree.strip_elements(document, "script", "style", "noscript", with_tail=False)
    text = document.text_content()
    return normalize_text(text)


def extract_xml_text(body: bytes) -> str:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    try:
        document = etree.fromstring(body, parser=parser)
    except (etree.ParserError, ValueError):
        return ""
    text = " ".join(document.itertext())
    return normalize_text(text)


def extract_pdf_text_if_possible(body: bytes) -> str:
    try:
        document = pymupdf.open(stream=body, filetype="pdf")
    except Exception:  # noqa: BLE001
        document = None
    if document is not None:
        try:
            page_texts = [page.get_text("text", sort=True) for page in document]
            return normalize_text("\n".join(page_texts))
        finally:
            document.close()

    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "source.pdf"
        text_path = Path(tmpdir) / "source.txt"
        pdf_path.write_bytes(body)
        import subprocess

        result = subprocess.run(
            [pdftotext, "-layout", str(pdf_path), str(text_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or not text_path.exists():
            return ""
        return normalize_text(text_path.read_text(encoding="utf-8", errors="ignore"))


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def count_term_hits(text: str, terms: set[str]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if term in lowered)


def probe_url(
    *,
    client: httpx.Client,
    document_id: str,
    source_strategy: str,
    url: str,
    max_bytes: int,
    run_id: str,
) -> ProbeRecord:
    try:
        response, body = fetch_limited(client, url, max_bytes=max_bytes)
        content_type = response.headers.get("content-type")
        source_format = detect_source_format(str(response.url), content_type, body)
        text = extract_text(source_format, body)
        section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
        cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
        classification_ready = (
            len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
            and section_hits >= 2
            and cannabinoid_hits >= 1
        )
        likely_needs_ocr = source_format == "pdf" and len(text) < MIN_CLASSIFICATION_TEXT_CHARS
        return ProbeRecord(
            document_id=document_id,
            source_strategy=source_strategy,
            url=url,
            status_code=response.status_code,
            final_url=str(response.url),
            content_type=content_type,
            retrieved_bytes=len(body),
            source_format=source_format,
            extracted_text_chars=len(text),
            scientific_section_hit_count=section_hits,
            cannabinoid_term_hit_count=cannabinoid_hits,
            classification_ready_text=classification_ready,
            pdf_retrieved_without_text_extraction=source_format == "pdf" and not text,
            likely_needs_ocr=likely_needs_ocr,
            error=None,
            provenance={
                "run_id": run_id,
                "method": "bounded_source_availability_probe",
                "max_bytes": max_bytes,
                "does_not_mutate_sqlite": True,
                "review_boundary": "operational_source_availability_not_reviewed_knowledge",
            },
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeRecord(
            document_id=document_id,
            source_strategy=source_strategy,
            url=url,
            status_code=None,
            final_url=None,
            content_type=None,
            retrieved_bytes=0,
            source_format="error",
            extracted_text_chars=0,
            scientific_section_hit_count=0,
            cannabinoid_term_hit_count=0,
            classification_ready_text=False,
            pdf_retrieved_without_text_extraction=False,
            likely_needs_ocr=False,
            error=f"{type(exc).__name__}: {exc}",
            provenance={
                "run_id": run_id,
                "method": "bounded_source_availability_probe",
                "max_bytes": max_bytes,
                "does_not_mutate_sqlite": True,
                "review_boundary": "operational_source_availability_not_reviewed_knowledge",
            },
        )


def selected_probe_urls(
    records: list[LocalCandidateRecord],
    *,
    limit_per_strategy: int,
) -> list[tuple[str, str, str]]:
    selected: list[tuple[str, str, str]] = []
    counts: Counter[str] = Counter()
    priority = [
        "pmcid_pmc_xml",
        "pmcid_pmc_html",
        "europe_pmc_discovered_pmc_xml",
        "europe_pmc_discovered_pmc_html",
        "europe_pmc_full_text_url",
        "unpaywall_pdf",
        "unpaywall_landing",
        "doi_or_publisher_landing",
    ]
    for strategy in priority:
        for record in records:
            if counts[strategy] >= limit_per_strategy:
                break
            for candidate in record.candidate_urls:
                if candidate["source_strategy"] != strategy:
                    continue
                if strategy == "doi_or_publisher_landing" and not is_publisher_probe_candidate(
                    candidate["url"]
                ):
                    continue
                selected.append((record.document_id, strategy, candidate["url"]))
                counts[strategy] += 1
                break
    return selected


def build_probe_summary(
    *,
    local_summary: dict[str, Any],
    probe_records: list[ProbeRecord],
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
    records_path: Path,
) -> dict[str, Any]:
    by_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    for record in probe_records:
        counter = by_strategy[record.source_strategy]
        counter["tested_sample_size"] += 1
        if record.status_code and 200 <= record.status_code < 300:
            counter["http_success"] += 1
        if record.classification_ready_text:
            counter["classification_ready_text"] += 1
        if record.pdf_retrieved_without_text_extraction:
            counter["pdf_retrieved_without_text_extraction"] += 1
        if record.likely_needs_ocr:
            counter["likely_needs_ocr"] += 1
        if record.error:
            counter["errors"] += 1
    return {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "records_path": str(records_path),
        "local_ceiling_summary": local_summary,
        "probe_counts_by_strategy": {key: dict(value) for key, value in by_strategy.items()},
        "notes": [
            "classification_ready_text is a source-text heuristic, not LLM classification.",
            "PDF bytes are not counted as classification-ready unless text extraction succeeds.",
            "This probe is bounded and should be used to estimate conversion rates, "
            "not as a full acquisition run.",
        ],
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Legacy Core Source Availability Ceiling")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("legacy_core_document_count", str(summary["legacy_core_document_count"]))
    table.add_row(
        "already_usable_legacy_core_count",
        str(summary["already_usable_legacy_core_count"]),
    )
    table.add_row("nonusable_legacy_core_count", str(summary["nonusable_legacy_core_count"]))
    for key, value in summary["local_candidate_counts"].items():
        table.add_row(key, str(value))
    for key, value in summary["estimated_total_with_existing_usable"].items():
        table.add_row(f"total: {key}", str(value))
    console.print(table)


@app.callback()
def main() -> None:
    """Run source availability ceiling commands."""


@app.command("summarize")
def summarize(
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Build the local-only source availability ceiling summary."""
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_database_path = database_path or sqlite_database_path(data_dir)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    records, summary = load_local_candidates(
        data_dir=data_dir,
        database_path=resolved_database_path,
    )
    summary.update(
        {
            "run_id": run_id,
            "method": "local_source_availability_ceiling_summary",
            "does_not_fetch_network": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_source_availability_not_reviewed_knowledge",
        }
    )
    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_source_availability_ceiling_records.jsonl"
    summary_path = output_dir / f"{run_id}_source_availability_ceiling_summary.json"
    write_jsonl(records_path, records)
    summary["records_path"] = str(records_path)
    write_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    print_summary(summary)
    console.print(summary)


@app.command("probe")
def probe(
    limit_per_strategy: Annotated[
        int,
        typer.Option(
            "--limit-per-strategy",
            min=1,
            max=50,
            help="Bounded sample per URL strategy.",
        ),
    ] = 10,
    max_bytes: Annotated[
        int,
        typer.Option("--max-bytes", min=100_000, max=25_000_000, help="Maximum bytes per URL."),
    ] = 8_000_000,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0, help="Delay between fetches."),
    ] = 0.5,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0, help="HTTP timeout."),
    ] = 30.0,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Fetch a bounded sample to validate text availability conversion."""
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_database_path = database_path or sqlite_database_path(data_dir)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    records, local_summary = load_local_candidates(
        data_dir=data_dir,
        database_path=resolved_database_path,
    )
    targets = selected_probe_urls(records, limit_per_strategy=limit_per_strategy)
    probe_records: list[ProbeRecord] = []
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": "text/html,application/xml,text/xml,application/pdf;q=0.9,*/*;q=0.1",
    }
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for document_id, strategy, url in targets:
            probe_records.append(
                probe_url(
                    client=client,
                    document_id=document_id,
                    source_strategy=strategy,
                    url=url,
                    max_bytes=max_bytes,
                    run_id=run_id,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_source_availability_ceiling_probe_records.jsonl"
    summary_path = output_dir / f"{run_id}_source_availability_ceiling_probe_summary.json"
    write_jsonl(records_path, probe_records)
    summary = build_probe_summary(
        local_summary=local_summary,
        probe_records=probe_records,
        run_id=run_id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        records_path=records_path,
    )
    write_json(summary_path, summary)
    console.print(summary)


if __name__ == "__main__":
    app()
