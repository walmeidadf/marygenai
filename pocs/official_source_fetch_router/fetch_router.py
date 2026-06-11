"""Route and probe official-first source acquisition strategies."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlparse

import httpx
import typer
from rich.console import Console
from rich.table import Table

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.settings import get_settings
from pocs.source_availability_ceiling.assess_ceiling import (
    CANNABINOID_TERMS,
    MIN_CLASSIFICATION_TEXT_CHARS,
    SCIENTIFIC_SECTION_TERMS,
    count_term_hits,
    detect_source_format,
    extract_text,
    is_publisher_probe_candidate,
    load_local_candidates,
)

OUTPUT_SUBDIR = Path("normalized/official_source_fetch_router")
PMC_OAI_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"
EUROPE_PMC_REST_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
NCBI_ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
OPENALEX_WORKS_BASE_URL = "https://api.openalex.org/works"

AUGMENTED_LINK_DENY_HOSTS = {
    "medlineplus.gov",
    "ovid.com",
    "scite.ai",
    "assays.cancer.gov",
    "antibodies.cancer.gov",
    "clinicalkey.com",
    "lens.org",
    "clinicaltrials.gov",
    "informatics.jax.org",
    "facultyopinions.com",
    "guidetopharmacology.org",
    "scopus.com",
    "pubmed.ncbi.nlm.nih.gov",
}
AUGMENTED_LINK_ALLOWED_HOST_FRAGMENTS = (
    "frontiersin.org",
    "mdpi.com",
    "plos.org",
    "biomedcentral.com",
    "springeropen.com",
    "nature.com",
    "link.springer.com",
    "tandfonline.com",
    "journals.sagepub.com",
    "onlinelibrary.wiley.com",
    "academic.oup.com",
    "escholarship.org",
    "hdl.handle.net",
    "figshare.com",
    "kclpure.kcl.ac.uk",
    "discovery.ucl.ac.uk",
    "research.birmingham.ac.uk",
    "pure.",
    "doaj.org",
    "europepmc.org",
    "pmc.ncbi.nlm.nih.gov",
)

ROUTE_PRIORITY = (
    "pmc_oai",
    "europe_pmc_fulltextxml",
    "ncbi_elink",
    "unpaywall_pdf",
    "openalex_identity_access",
    "publisher_known_path",
)

console = Console()
app = typer.Typer(help="Official-first source fetch router POC.")


@dataclass(frozen=True)
class RouteRecord:
    document_id: str
    legacy_study_id: str | None
    title: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    source_strategy_bucket: str
    routes: list[dict[str, str]]
    best_strategy: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class FetchRecord:
    document_id: str
    strategy: str
    url: str
    status_code: int | None
    final_url: str | None
    content_type: str | None
    source_format: str
    retrieved_bytes: int
    extracted_text_chars: int
    scientific_section_hit_count: int
    cannabinoid_term_hit_count: int
    classification_ready_text: bool
    likely_needs_ocr: bool
    discovered_pmcid: str | None
    discovered_doi: str | None
    discovered_oa_url: str | None
    failure_reason: str | None
    error: str | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AcquisitionRecord:
    document_id: str
    strategy: str
    pmcid: str | None
    url: str
    status_code: int | None
    final_url: str | None
    content_type: str | None
    raw_xml_path: str | None
    text_path: str | None
    retrieved_bytes: int
    extracted_text_chars: int
    scientific_section_hit_count: int
    cannabinoid_term_hit_count: int
    classification_ready_text: bool
    skipped_existing: bool
    failure_reason: str | None
    error: str | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class AugmentationRecord:
    document_id: str
    strategy: str
    url: str
    status_code: int | None
    final_url: str | None
    content_type: str | None
    raw_json_path: str | None
    retrieved_bytes: int
    discovered_pmcid: str | None
    discovered_doi: str | None
    discovered_oa_url: str | None
    discovered_urls: list[str]
    skipped_existing: bool
    failure_reason: str | None
    error: str | None
    provenance: dict[str, Any]


def write_jsonl(path: Path, records: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            payload = asdict(record) if hasattr(record, "__dataclass_fields__") else record
            file.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def latest_path(data_dir: Path, pattern: str) -> Path:
    paths = sorted((data_dir / OUTPUT_SUBDIR).glob(pattern))
    if not paths:
        msg = f"No files matched {data_dir / OUTPUT_SUBDIR / pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def safe_document_slug(document_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", document_id).strip("_").lower()


def pmcid_digits(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"PMC?(\d+)", value, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    if value.isdigit():
        return value
    return None


def pmcid_from_url(url: str) -> str | None:
    match = re.search(r"/articles/(PMC\d+)/", url, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def doi_url(doi: str | None) -> str | None:
    if not doi:
        return None
    if doi.startswith(("http://", "https://")):
        return doi
    if doi.startswith("10."):
        return f"https://doi.org/{quote(doi, safe='/')}"
    return None


def normalized_external_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    stripped = doi.strip()
    frontiers_match = re.match(r"^(10\.3389/.+?)(?:/full)?$", stripped)
    if frontiers_match:
        return frontiers_match.group(1)
    return stripped


def pmc_oai_url(pmcid: str) -> str:
    digits = pmcid_digits(pmcid)
    if not digits:
        raise ValueError(f"Invalid PMCID: {pmcid}")
    return (
        f"{PMC_OAI_BASE_URL}?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:"
        f"{digits}&metadataPrefix=pmc"
    )


def europe_pmc_fulltextxml_url(*, pmcid: str | None, pmid: str | None) -> str | None:
    if pmcid:
        normalized = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"
        return f"{EUROPE_PMC_REST_BASE_URL}/PMC/{quote(normalized)}/fullTextXML"
    if pmid:
        return f"{EUROPE_PMC_REST_BASE_URL}/MED/{pmid}/fullTextXML"
    return None


def ncbi_elink_url(pmid: str) -> str:
    return f"{NCBI_ELINK_URL}?dbfrom=pubmed&id={quote(pmid)}&cmd=llinks&retmode=json"


def openalex_url(*, doi: str | None, pmid: str | None, pmcid: str | None) -> str | None:
    if doi:
        normalized_doi = normalized_external_doi(doi)
        return f"{OPENALEX_WORKS_BASE_URL}/doi:{quote(normalized_doi or doi, safe='/')}"
    if pmid:
        return f"{OPENALEX_WORKS_BASE_URL}/pmid:{quote(pmid)}"
    if pmcid:
        return f"{OPENALEX_WORKS_BASE_URL}/pmcid:{quote(pmcid)}"
    return None


def build_routes_for_candidate(candidate: Any) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    pmcid_values: list[str] = []
    if candidate.pmcid:
        pmcid_values.append(candidate.pmcid)
    for item in candidate.candidate_urls:
        if item["source_strategy"] in {
            "europe_pmc_discovered_pmc_xml",
            "europe_pmc_discovered_pmc_html",
        }:
            discovered = pmcid_from_url(item["url"])
            if discovered:
                pmcid_values.append(discovered)

    for pmcid in sorted(set(pmcid_values)):
        routes.append({"strategy": "pmc_oai", "url": pmc_oai_url(pmcid), "pmcid": pmcid})
        epmc_url = europe_pmc_fulltextxml_url(pmcid=pmcid, pmid=None)
        if epmc_url:
            routes.append(
                {"strategy": "europe_pmc_fulltextxml", "url": epmc_url, "pmcid": pmcid}
            )

    epmc_by_pmid = europe_pmc_fulltextxml_url(pmcid=None, pmid=candidate.pmid)
    if epmc_by_pmid and candidate.has_europe_pmc_full_text_hint:
        routes.append({"strategy": "europe_pmc_fulltextxml", "url": epmc_by_pmid})
    if candidate.pmid:
        routes.append({"strategy": "ncbi_elink", "url": ncbi_elink_url(candidate.pmid)})

    for item in candidate.candidate_urls:
        if item["source_strategy"] == "unpaywall_pdf":
            routes.append({"strategy": "unpaywall_pdf", "url": item["url"]})
        elif item["source_strategy"] == "doi_or_publisher_landing" and (
            candidate.has_publisher_or_doi_probe_candidate
            and is_publisher_probe_candidate(item["url"])
        ):
            routes.append({"strategy": "publisher_known_path", "url": item["url"]})

    oa_url = openalex_url(doi=candidate.doi, pmid=candidate.pmid, pmcid=candidate.pmcid)
    if oa_url:
        routes.append({"strategy": "openalex_identity_access", "url": oa_url})

    return dedupe_routes(routes)


def dedupe_routes(routes: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for route in routes:
        key = (route["strategy"], route["url"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(route)
    return sorted(deduped, key=lambda route: ROUTE_PRIORITY.index(route["strategy"]))


def build_route_records(
    data_dir: Path,
    database_path: Path,
) -> tuple[list[RouteRecord], dict[str, Any]]:
    candidates, local_summary = load_local_candidates(
        data_dir=data_dir,
        database_path=database_path,
    )
    records: list[RouteRecord] = []
    for candidate in candidates:
        routes = build_routes_for_candidate(candidate)
        best_strategy = routes[0]["strategy"] if routes else "no_route"
        records.append(
            RouteRecord(
                document_id=candidate.document_id,
                legacy_study_id=candidate.legacy_study_id,
                title=candidate.title,
                pmid=candidate.pmid,
                pmcid=candidate.pmcid,
                doi=candidate.doi,
                source_strategy_bucket=candidate.source_strategy_bucket,
                routes=routes,
                best_strategy=best_strategy,
                provenance={
                    "method": "official_source_fetch_route_plan",
                    "does_not_fetch_network": True,
                    "does_not_mutate_sqlite": True,
                    "review_boundary": "operational_source_routing_not_reviewed_knowledge",
                },
            )
        )
    summary = {
        "local_ceiling_summary": local_summary,
        "route_record_count": len(records),
        "best_strategy_counts": dict(Counter(record.best_strategy for record in records)),
        "route_availability_counts": route_availability_counts(records),
    }
    return records, summary


def route_availability_counts(records: list[RouteRecord]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        for strategy in {route["strategy"] for route in record.routes}:
            counts[strategy] += 1
    return dict(counts)


def fetch_bytes(client: httpx.Client, url: str, *, max_bytes: int) -> tuple[httpx.Response, bytes]:
    with client.stream("GET", url, follow_redirects=True) as response:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                remaining = max_bytes - (total - len(chunk))
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                break
            chunks.append(chunk)
        return response, b"".join(chunks)


def route_records_from_path(path: Path) -> list[RouteRecord]:
    return [RouteRecord(**row) for row in read_jsonl(path)]


def first_route_for_strategy(
    route_record: RouteRecord,
    *,
    strategy: str,
) -> dict[str, str] | None:
    for route_item in route_record.routes:
        if route_item["strategy"] == strategy:
            return route_item
    return None


def classify_failure(
    *,
    status_code: int | None,
    source_format: str,
    text_chars: int,
    error: str | None,
) -> str | None:
    if error:
        return "request_error"
    if status_code is None:
        return "missing_status"
    if status_code == 404:
        return "not_found"
    if status_code in {401, 403}:
        return "access_blocked"
    if status_code == 405:
        return "method_not_allowed"
    if not (200 <= status_code < 300):
        return "http_non_success"
    if source_format == "json":
        return None
    if source_format == "pdf" and text_chars < MIN_CLASSIFICATION_TEXT_CHARS:
        return "pdf_likely_needs_ocr_or_bad_text_layer"
    if text_chars < MIN_CLASSIFICATION_TEXT_CHARS:
        return "retrieved_but_not_enough_text"
    return None


def extract_openalex_signals(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    ids = payload.get("ids") or {}
    discovered_pmcid = ids.get("pmcid") or payload.get("pmcid")
    discovered_doi = ids.get("doi") or payload.get("doi")
    oa_url = None
    best = payload.get("best_oa_location") or payload.get("open_access", {}).get("oa_url")
    if isinstance(best, dict):
        oa_url = best.get("pdf_url") or best.get("landing_page_url") or best.get("url")
    elif isinstance(best, str):
        oa_url = best
    if not oa_url:
        oa_url = (payload.get("open_access") or {}).get("oa_url")
    return discovered_pmcid, discovered_doi, oa_url


def extract_elink_signals(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    urls: list[str] = []
    for linkset in payload.get("linksets") or []:
        for id_url_set in linkset.get("idurllist") or []:
            for obj_url in id_url_set.get("objurls") or []:
                url = obj_url.get("url", {}).get("value")
                if url:
                    urls.append(url)
    pmcid = None
    for url in urls:
        match = re.search(r"PMC\d+", url, flags=re.IGNORECASE)
        if match:
            pmcid = match.group(0).upper()
            break
    return pmcid, None, urls[0] if urls else None


def extract_elink_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for linkset in payload.get("linksets") or []:
        for id_url_set in linkset.get("idurllist") or []:
            for obj_url in id_url_set.get("objurls") or []:
                url = obj_url.get("url", {}).get("value")
                if url and url not in urls:
                    urls.append(url)
    return urls


def extract_openalex_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for location in payload.get("locations") or []:
        if not isinstance(location, dict):
            continue
        for key in ("pdf_url", "landing_page_url"):
            value = location.get(key)
            if value and value not in urls:
                urls.append(value)
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        for key in ("pdf_url", "landing_page_url"):
            value = best.get(key)
            if value and value not in urls:
                urls.append(value)
    oa_url = (payload.get("open_access") or {}).get("oa_url")
    if oa_url and oa_url not in urls:
        urls.append(oa_url)
    return urls


def probe_route(
    *,
    client: httpx.Client,
    route_record: RouteRecord,
    route: dict[str, str],
    run_id: str,
    max_bytes: int,
) -> FetchRecord:
    strategy = route["strategy"]
    url = route["url"]
    error = None
    status_code = None
    final_url = None
    content_type = None
    source_format = "unknown"
    body = b""
    text = ""
    discovered_pmcid = None
    discovered_doi = None
    discovered_oa_url = None
    try:
        response, body = fetch_bytes(client, url, max_bytes=max_bytes)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        if strategy in {"ncbi_elink", "openalex_identity_access"}:
            source_format = "json"
            payload = json.loads(body.decode("utf-8")) if body else {}
            if strategy == "openalex_identity_access" and isinstance(payload, dict):
                discovered_pmcid, discovered_doi, discovered_oa_url = extract_openalex_signals(
                    payload
                )
            elif strategy == "ncbi_elink" and isinstance(payload, dict):
                discovered_pmcid, discovered_doi, discovered_oa_url = extract_elink_signals(
                    payload
                )
            text = json.dumps(payload, ensure_ascii=False)
        else:
            source_format = detect_source_format(final_url, content_type, body)
            text = extract_text(source_format, body)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
    cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
    classification_ready = (
        strategy not in {"ncbi_elink", "openalex_identity_access"}
        and len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
        and section_hits >= 2
        and cannabinoid_hits >= 1
    )
    likely_needs_ocr = source_format == "pdf" and len(text) < MIN_CLASSIFICATION_TEXT_CHARS
    failure_reason = classify_failure(
        status_code=status_code,
        source_format=source_format,
        text_chars=len(text),
        error=error,
    )
    return FetchRecord(
        document_id=route_record.document_id,
        strategy=strategy,
        url=url,
        status_code=status_code,
        final_url=final_url,
        content_type=content_type,
        source_format=source_format,
        retrieved_bytes=len(body),
        extracted_text_chars=len(text),
        scientific_section_hit_count=section_hits,
        cannabinoid_term_hit_count=cannabinoid_hits,
        classification_ready_text=classification_ready,
        likely_needs_ocr=likely_needs_ocr,
        discovered_pmcid=discovered_pmcid,
        discovered_doi=discovered_doi,
        discovered_oa_url=discovered_oa_url,
        failure_reason=failure_reason,
        error=error,
        provenance={
            "run_id": run_id,
            "method": "official_source_fetch_probe",
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_source_fetch_not_reviewed_knowledge",
        },
    )


def build_fetch_summary(
    *,
    route_path: Path,
    records_path: Path,
    fetch_records: list[FetchRecord],
    strategy: str,
    run_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    counts = Counter()
    failure_reasons = Counter()
    for record in fetch_records:
        counts["tested_sample_size"] += 1
        if record.status_code and 200 <= record.status_code < 300:
            counts["http_success"] += 1
        if record.classification_ready_text:
            counts["classification_ready_text"] += 1
        if record.likely_needs_ocr:
            counts["likely_needs_ocr"] += 1
        if record.discovered_pmcid:
            counts["discovered_pmcid"] += 1
        if record.discovered_oa_url:
            counts["discovered_oa_url"] += 1
        if record.failure_reason:
            failure_reasons[record.failure_reason] += 1
    return {
        "run_id": run_id,
        "strategy": strategy,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "route_path": str(route_path),
        "records_path": str(records_path),
        "counts": dict(counts),
        "failure_reason_counts": dict(failure_reasons),
        "notes": [
            "classification_ready_text is source-text availability, not LLM classification.",
            "OpenAlex and NCBI ELink are access/identity augmentation strategies, not full text.",
        ],
    }


def select_acquisition_targets(
    route_records: list[RouteRecord],
    *,
    strategy: str,
    limit: int,
    offset: int,
    data_dir: Path,
    skip_existing: bool,
    skip_attempted: bool,
    raw_subdir: str,
    raw_extension: str,
) -> list[tuple[RouteRecord, dict[str, str], Path, Path]]:
    candidates: list[tuple[RouteRecord, dict[str, str], Path, Path]] = []
    attempted_document_ids = (
        acquired_attempted_document_ids(data_dir, strategy=strategy) if skip_attempted else set()
    )
    for route_record in route_records:
        if route_record.document_id in attempted_document_ids:
            continue
        route_item = first_route_for_strategy(route_record, strategy=strategy)
        if route_item is None:
            continue
        slug = safe_document_slug(route_record.document_id)
        raw_path = (
            data_dir
            / "raw/official_source_fetch_router"
            / raw_subdir
            / f"{slug}.{raw_extension}"
        )
        text_path = (
            data_dir / "processed/official_source_fetch_router" / raw_subdir / f"{slug}.txt"
        )
        if skip_existing and raw_path.exists() and text_path.exists():
            continue
        candidates.append((route_record, route_item, raw_path, text_path))
    return candidates[offset : offset + limit]


def acquired_attempted_document_ids(data_dir: Path, *, strategy: str) -> set[str]:
    document_ids: set[str] = set()
    pattern = f"*_official_source_fetch_{strategy}_acquire_records.jsonl"
    for path in (data_dir / OUTPUT_SUBDIR).glob(pattern):
        for row in read_jsonl(path):
            document_id = row.get("document_id")
            if document_id:
                document_ids.add(str(document_id))
    return document_ids


def acquire_pmc_oai_record(
    *,
    client: httpx.Client,
    route_record: RouteRecord,
    route_item: dict[str, str],
    raw_path: Path,
    text_path: Path,
    run_id: str,
    max_bytes: int,
) -> AcquisitionRecord:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists() and text_path.exists():
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
        cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
        classification_ready = (
            len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
            and section_hits >= 2
            and cannabinoid_hits >= 1
        )
        failure_reason = None if classification_ready else "existing_text_not_classification_ready"
        return AcquisitionRecord(
            document_id=route_record.document_id,
            strategy="pmc_oai",
            pmcid=route_item.get("pmcid"),
            url=route_item["url"],
            status_code=None,
            final_url=None,
            content_type=None,
            raw_xml_path=str(raw_path),
            text_path=str(text_path),
            retrieved_bytes=raw_path.stat().st_size,
            extracted_text_chars=len(text),
            scientific_section_hit_count=section_hits,
            cannabinoid_term_hit_count=cannabinoid_hits,
            classification_ready_text=classification_ready,
            skipped_existing=True,
            failure_reason=failure_reason,
            error=None,
            provenance={
                "run_id": run_id,
                "method": "pmc_oai_acquisition",
                "does_not_mutate_sqlite": True,
                "review_boundary": "operational_source_acquisition_not_reviewed_knowledge",
            },
        )

    error = None
    status_code = None
    final_url = None
    content_type = None
    body = b""
    text = ""
    try:
        response, body = fetch_bytes(client, route_item["url"], max_bytes=max_bytes)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        if 200 <= status_code < 300:
            raw_path.write_bytes(body)
            source_format = detect_source_format(final_url, content_type, body)
            text = extract_text(source_format, body)
            text_path.write_text(text + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
    cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
    classification_ready = (
        len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
        and section_hits >= 2
        and cannabinoid_hits >= 1
    )
    failure_reason = classify_failure(
        status_code=status_code,
        source_format="xml",
        text_chars=len(text),
        error=error,
    )
    return AcquisitionRecord(
        document_id=route_record.document_id,
        strategy="pmc_oai",
        pmcid=route_item.get("pmcid"),
        url=route_item["url"],
        status_code=status_code,
        final_url=final_url,
        content_type=content_type,
        raw_xml_path=str(raw_path) if raw_path.exists() else None,
        text_path=str(text_path) if text_path.exists() else None,
        retrieved_bytes=len(body),
        extracted_text_chars=len(text),
        scientific_section_hit_count=section_hits,
        cannabinoid_term_hit_count=cannabinoid_hits,
        classification_ready_text=classification_ready,
        skipped_existing=False,
        failure_reason=failure_reason,
        error=error,
        provenance={
            "run_id": run_id,
            "method": "pmc_oai_acquisition",
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_source_acquisition_not_reviewed_knowledge",
        },
    )


def acquire_unpaywall_pdf_record(
    *,
    client: httpx.Client,
    route_record: RouteRecord,
    route_item: dict[str, str],
    raw_path: Path,
    text_path: Path,
    run_id: str,
    max_bytes: int,
) -> AcquisitionRecord:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists() and text_path.exists():
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
        cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
        classification_ready = (
            len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
            and section_hits >= 2
            and cannabinoid_hits >= 1
        )
        failure_reason = None if classification_ready else "existing_text_not_classification_ready"
        return AcquisitionRecord(
            document_id=route_record.document_id,
            strategy="unpaywall_pdf",
            pmcid=None,
            url=route_item["url"],
            status_code=None,
            final_url=None,
            content_type=None,
            raw_xml_path=str(raw_path),
            text_path=str(text_path),
            retrieved_bytes=raw_path.stat().st_size,
            extracted_text_chars=len(text),
            scientific_section_hit_count=section_hits,
            cannabinoid_term_hit_count=cannabinoid_hits,
            classification_ready_text=classification_ready,
            skipped_existing=True,
            failure_reason=failure_reason,
            error=None,
            provenance={
                "run_id": run_id,
                "method": "unpaywall_pdf_acquisition",
                "does_not_mutate_sqlite": True,
                "review_boundary": "operational_source_acquisition_not_reviewed_knowledge",
            },
        )

    error = None
    status_code = None
    final_url = None
    content_type = None
    body = b""
    text = ""
    source_format = "unknown"
    try:
        response, body = fetch_bytes(client, route_item["url"], max_bytes=max_bytes)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        if 200 <= status_code < 300:
            source_format = detect_source_format(final_url, content_type, body)
            raw_path.write_bytes(body)
            text = extract_text(source_format, body)
            text_path.write_text(text + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
    cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
    classification_ready = (
        len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
        and section_hits >= 2
        and cannabinoid_hits >= 1
    )
    failure_reason = classify_failure(
        status_code=status_code,
        source_format=source_format,
        text_chars=len(text),
        error=error,
    )
    return AcquisitionRecord(
        document_id=route_record.document_id,
        strategy="unpaywall_pdf",
        pmcid=None,
        url=route_item["url"],
        status_code=status_code,
        final_url=final_url,
        content_type=content_type,
        raw_xml_path=str(raw_path) if raw_path.exists() else None,
        text_path=str(text_path) if text_path.exists() else None,
        retrieved_bytes=len(body),
        extracted_text_chars=len(text),
        scientific_section_hit_count=section_hits,
        cannabinoid_term_hit_count=cannabinoid_hits,
        classification_ready_text=classification_ready,
        skipped_existing=False,
        failure_reason=failure_reason,
        error=error,
        provenance={
            "run_id": run_id,
            "method": "unpaywall_pdf_acquisition",
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_source_acquisition_not_reviewed_knowledge",
        },
    )


def build_acquisition_summary(
    *,
    records: list[AcquisitionRecord],
    run_id: str,
    strategy: str,
    route_path: Path,
    records_path: Path,
    raw_output_dir: str,
    processed_output_dir: str,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    counts = Counter()
    failures = Counter()
    for record in records:
        counts["attempted_records"] += 1
        if record.skipped_existing:
            counts["skipped_existing"] += 1
        if record.status_code and 200 <= record.status_code < 300:
            counts["http_success"] += 1
        if record.raw_xml_path:
            counts["raw_source_saved"] += 1
        if record.text_path:
            counts["text_saved"] += 1
        if record.classification_ready_text:
            counts["classification_ready_text"] += 1
        if record.failure_reason == "pdf_likely_needs_ocr_or_bad_text_layer":
            counts["likely_needs_ocr"] += 1
        if record.failure_reason:
            failures[record.failure_reason] += 1
    return {
        "run_id": run_id,
        "strategy": strategy,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "route_path": str(route_path),
        "records_path": str(records_path),
        "counts": dict(counts),
        "failure_reason_counts": dict(failures),
        "raw_output_dir": raw_output_dir,
        "processed_output_dir": processed_output_dir,
        "notes": [
            "This command acquires source text only; it does not classify studies.",
            "Outputs are ignored local artifacts and do not mutate SQLite or review state.",
        ],
    }


def augmentation_attempted_document_ids(data_dir: Path, *, strategy: str) -> set[str]:
    document_ids: set[str] = set()
    pattern = f"*_official_source_fetch_{strategy}_augment_records.jsonl"
    for path in (data_dir / OUTPUT_SUBDIR).glob(pattern):
        for row in read_jsonl(path):
            document_id = row.get("document_id")
            if document_id:
                document_ids.add(str(document_id))
    return document_ids


def select_augmentation_targets(
    route_records: list[RouteRecord],
    *,
    strategy: str,
    limit: int,
    offset: int,
    data_dir: Path,
    skip_existing: bool,
    skip_attempted: bool,
) -> list[tuple[RouteRecord, dict[str, str], Path]]:
    attempted = augmentation_attempted_document_ids(data_dir, strategy=strategy)
    targets: list[tuple[RouteRecord, dict[str, str], Path]] = []
    for route_record in route_records:
        if skip_attempted and route_record.document_id in attempted:
            continue
        route_item = first_route_for_strategy(route_record, strategy=strategy)
        if route_item is None:
            continue
        slug = safe_document_slug(route_record.document_id)
        raw_path = data_dir / "raw/official_source_fetch_router" / strategy / f"{slug}.json"
        if skip_existing and raw_path.exists():
            continue
        targets.append((route_record, route_item, raw_path))
    return targets[offset : offset + limit]


def acquire_augmentation_record(
    *,
    client: httpx.Client,
    route_record: RouteRecord,
    route_item: dict[str, str],
    raw_path: Path,
    strategy: str,
    run_id: str,
    max_bytes: int,
) -> AugmentationRecord:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_path.exists():
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        discovered_pmcid, discovered_doi, discovered_oa_url, discovered_urls = (
            normalize_augmentation_payload(strategy=strategy, payload=payload)
        )
        return AugmentationRecord(
            document_id=route_record.document_id,
            strategy=strategy,
            url=route_item["url"],
            status_code=None,
            final_url=None,
            content_type=None,
            raw_json_path=str(raw_path),
            retrieved_bytes=raw_path.stat().st_size,
            discovered_pmcid=discovered_pmcid,
            discovered_doi=discovered_doi,
            discovered_oa_url=discovered_oa_url,
            discovered_urls=discovered_urls,
            skipped_existing=True,
            failure_reason=None,
            error=None,
            provenance={
                "run_id": run_id,
                "method": f"{strategy}_augmentation",
                "does_not_mutate_sqlite": True,
                "review_boundary": "operational_access_augmentation_not_reviewed_knowledge",
            },
        )

    status_code = None
    final_url = None
    content_type = None
    body = b""
    error = None
    payload: dict[str, Any] = {}
    try:
        response, body = fetch_bytes(client, route_item["url"], max_bytes=max_bytes)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        if 200 <= status_code < 300:
            payload = json.loads(body.decode("utf-8")) if body else {}
            raw_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    discovered_pmcid, discovered_doi, discovered_oa_url, discovered_urls = (
        normalize_augmentation_payload(strategy=strategy, payload=payload)
    )
    failure_reason = classify_augmentation_failure(
        status_code=status_code,
        error=error,
        discovered_urls=discovered_urls,
        discovered_pmcid=discovered_pmcid,
        discovered_oa_url=discovered_oa_url,
    )
    return AugmentationRecord(
        document_id=route_record.document_id,
        strategy=strategy,
        url=route_item["url"],
        status_code=status_code,
        final_url=final_url,
        content_type=content_type,
        raw_json_path=str(raw_path) if raw_path.exists() else None,
        retrieved_bytes=len(body),
        discovered_pmcid=discovered_pmcid,
        discovered_doi=discovered_doi,
        discovered_oa_url=discovered_oa_url,
        discovered_urls=discovered_urls,
        skipped_existing=False,
        failure_reason=failure_reason,
        error=error,
        provenance={
            "run_id": run_id,
            "method": f"{strategy}_augmentation",
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_access_augmentation_not_reviewed_knowledge",
        },
    )


def normalize_augmentation_payload(
    *,
    strategy: str,
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, list[str]]:
    if strategy == "ncbi_elink":
        discovered_pmcid, discovered_doi, discovered_oa_url = extract_elink_signals(payload)
        return discovered_pmcid, discovered_doi, discovered_oa_url, extract_elink_urls(payload)
    discovered_pmcid, discovered_doi, discovered_oa_url = extract_openalex_signals(payload)
    return discovered_pmcid, discovered_doi, discovered_oa_url, extract_openalex_urls(payload)


def classify_augmentation_failure(
    *,
    status_code: int | None,
    error: str | None,
    discovered_urls: list[str],
    discovered_pmcid: str | None,
    discovered_oa_url: str | None,
) -> str | None:
    if error:
        return "request_error"
    if status_code is None:
        return "missing_status"
    if status_code == 404:
        return "not_found"
    if not (200 <= status_code < 300):
        return "http_non_success"
    if discovered_pmcid or discovered_oa_url or discovered_urls:
        return None
    return "metadata_found_no_access_signal"


def build_augmentation_summary(
    *,
    records: list[AugmentationRecord],
    strategy: str,
    run_id: str,
    route_path: Path,
    records_path: Path,
    started_at: datetime,
    completed_at: datetime,
) -> dict[str, Any]:
    counts = Counter()
    failures = Counter()
    for record in records:
        counts["attempted_records"] += 1
        if record.skipped_existing:
            counts["skipped_existing"] += 1
        if record.status_code and 200 <= record.status_code < 300:
            counts["http_success"] += 1
        if record.raw_json_path:
            counts["raw_json_saved"] += 1
        if record.discovered_pmcid:
            counts["discovered_pmcid"] += 1
        if record.discovered_oa_url:
            counts["discovered_oa_url"] += 1
        if record.discovered_urls:
            counts["records_with_discovered_urls"] += 1
            counts["discovered_url_count"] += len(record.discovered_urls)
        if record.failure_reason:
            failures[record.failure_reason] += 1
    return {
        "run_id": run_id,
        "strategy": strategy,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "route_path": str(route_path),
        "records_path": str(records_path),
        "counts": dict(counts),
        "failure_reason_counts": dict(failures),
        "raw_output_dir": f"data/raw/official_source_fetch_router/{strategy}",
        "notes": [
            "This command augments access and identity only; it does not fetch full text.",
            "Outputs are ignored local artifacts and do not mutate SQLite or review state.",
        ],
    }


def source_ready_document_ids_from_acquisitions(data_dir: Path) -> set[str]:
    ready: set[str] = set()
    for path in (data_dir / OUTPUT_SUBDIR).glob("*_official_source_fetch_*_acquire_records.jsonl"):
        for row in read_jsonl(path):
            if (
                (row.get("extracted_text_chars") or 0) >= MIN_CLASSIFICATION_TEXT_CHARS
                and (row.get("scientific_section_hit_count") or 0) >= 2
            ):
                ready.add(str(row["document_id"]))
    return ready


def attempted_augmented_link_keys(data_dir: Path) -> set[str]:
    keys: set[str] = set()
    pattern = "*_official_source_fetch_augmented_links_acquire_records.jsonl"
    for path in (data_dir / OUTPUT_SUBDIR).glob(pattern):
        for row in read_jsonl(path):
            url = row.get("url")
            document_id = row.get("document_id")
            if url and document_id:
                keys.add(augmented_link_key(str(document_id), str(url)))
    return keys


def augmented_link_key(document_id: str, url: str) -> str:
    return hashlib.sha1(f"{document_id}\n{url}".encode()).hexdigest()


def normalize_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def classify_augmented_url(url: str) -> tuple[str, int, str, str] | None:
    parsed = urlparse(url)
    host = normalize_host(url)
    path = parsed.path.lower()
    lowered = url.lower()
    if not host or host in AUGMENTED_LINK_DENY_HOSTS:
        return None
    if "pmc.ncbi.nlm.nih.gov" in host and "/articles/pmc" in path:
        pmcid = pmcid_from_url(url)
        if not pmcid:
            return None
        return "augmented_pmc_oai", 10, pmc_oai_url(pmcid), "xml"
    if lowered.endswith(".pdf") or "pdf" in path or "download" in path or "printable" in lowered:
        return "augmented_pdf", 20, url, "pdf"
    if host in {"doi.org", "dx.doi.org"}:
        return "augmented_doi_landing", 50, url, "html"
    if any(fragment in host for fragment in AUGMENTED_LINK_ALLOWED_HOST_FRAGMENTS):
        return "augmented_allowed_html_or_repo", 30, url, "html"
    return None


def load_augmented_link_targets(
    data_dir: Path,
    *,
    limit: int,
    offset: int,
    skip_attempted: bool,
    skip_source_ready: bool,
) -> list[dict[str, Any]]:
    source_ready = (
        source_ready_document_ids_from_acquisitions(data_dir) if skip_source_ready else set()
    )
    attempted = attempted_augmented_link_keys(data_dir) if skip_attempted else set()
    targets_by_key: dict[str, dict[str, Any]] = {}
    patterns = (
        "*_official_source_fetch_ncbi_elink_augment_records.jsonl",
        "*_official_source_fetch_openalex_identity_access_augment_records.jsonl",
    )
    for pattern in patterns:
        for path in sorted((data_dir / OUTPUT_SUBDIR).glob(pattern)):
            for row in read_jsonl(path):
                document_id = str(row["document_id"])
                if document_id in source_ready:
                    continue
                for discovered_url in row.get("discovered_urls") or []:
                    classified = classify_augmented_url(str(discovered_url))
                    if not classified:
                        continue
                    link_kind, priority, fetch_url, raw_extension = classified
                    key = augmented_link_key(document_id, fetch_url)
                    if key in attempted:
                        continue
                    existing = targets_by_key.get(key)
                    if existing and existing["priority"] <= priority:
                        continue
                    targets_by_key[key] = {
                        "document_id": document_id,
                        "source_augmentation_strategy": row.get("strategy"),
                        "source_url": discovered_url,
                        "fetch_url": fetch_url,
                        "link_kind": link_kind,
                        "priority": priority,
                        "raw_extension": raw_extension,
                    }
    targets = sorted(
        targets_by_key.values(),
        key=lambda item: (item["priority"], item["document_id"], item["fetch_url"]),
    )
    return targets[offset : offset + limit]


def acquire_augmented_link_record(
    *,
    client: httpx.Client,
    target: dict[str, Any],
    data_dir: Path,
    run_id: str,
    max_bytes: int,
) -> AcquisitionRecord:
    key = augmented_link_key(target["document_id"], target["fetch_url"])
    slug = safe_document_slug(target["document_id"])
    raw_path = (
        data_dir
        / "raw/official_source_fetch_router/augmented_links"
        / f"{slug}_{key[:12]}.{target['raw_extension']}"
    )
    text_path = (
        data_dir
        / "processed/official_source_fetch_router/augmented_links"
        / f"{slug}_{key[:12]}.txt"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.parent.mkdir(parents=True, exist_ok=True)

    error = None
    status_code = None
    final_url = None
    content_type = None
    body = b""
    text = ""
    source_format = "unknown"
    try:
        response, body = fetch_bytes(client, target["fetch_url"], max_bytes=max_bytes)
        status_code = response.status_code
        final_url = str(response.url)
        content_type = response.headers.get("content-type")
        if 200 <= status_code < 300:
            source_format = detect_source_format(final_url, content_type, body)
            raw_path.write_bytes(body)
            text = extract_text(source_format, body)
            text_path.write_text(text + "\n", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    section_hits = count_term_hits(text, SCIENTIFIC_SECTION_TERMS)
    cannabinoid_hits = count_term_hits(text, CANNABINOID_TERMS)
    classification_ready = (
        len(text) >= MIN_CLASSIFICATION_TEXT_CHARS
        and section_hits >= 2
        and cannabinoid_hits >= 1
    )
    failure_reason = classify_failure(
        status_code=status_code,
        source_format=source_format,
        text_chars=len(text),
        error=error,
    )
    return AcquisitionRecord(
        document_id=target["document_id"],
        strategy="augmented_links",
        pmcid=pmcid_from_url(target["source_url"]) if "pmc" in target["link_kind"] else None,
        url=target["fetch_url"],
        status_code=status_code,
        final_url=final_url,
        content_type=content_type,
        raw_xml_path=str(raw_path) if raw_path.exists() else None,
        text_path=str(text_path) if text_path.exists() else None,
        retrieved_bytes=len(body),
        extracted_text_chars=len(text),
        scientific_section_hit_count=section_hits,
        cannabinoid_term_hit_count=cannabinoid_hits,
        classification_ready_text=classification_ready,
        skipped_existing=False,
        failure_reason=failure_reason,
        error=error,
        provenance={
            "run_id": run_id,
            "method": "augmented_link_acquisition",
            "link_kind": target["link_kind"],
            "source_augmentation_strategy": target["source_augmentation_strategy"],
            "source_url": target["source_url"],
            "does_not_mutate_sqlite": True,
            "review_boundary": "operational_source_acquisition_not_reviewed_knowledge",
        },
    )


def print_route_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Official Source Fetch Route Plan")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("route_record_count", str(summary["route_record_count"]))
    for key, value in summary["best_strategy_counts"].items():
        table.add_row(f"best: {key}", str(value))
    for key, value in summary["route_availability_counts"].items():
        table.add_row(f"available: {key}", str(value))
    console.print(table)


@app.callback()
def main() -> None:
    """Run official source fetch router commands."""


@app.command("route")
def route(
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Create an official-first route plan without network fetches."""
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_database_path = database_path or sqlite_database_path(data_dir)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    route_records, summary = build_route_records(data_dir, resolved_database_path)
    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_official_source_fetch_route_records.jsonl"
    summary_path = output_dir / f"{run_id}_official_source_fetch_route_summary.json"
    summary.update(
        {
            "run_id": run_id,
            "method": "official_source_fetch_route",
            "does_not_fetch_network": True,
            "does_not_mutate_sqlite": True,
            "records_path": str(records_path),
        }
    )
    write_jsonl(records_path, route_records)
    write_json(summary_path, summary)
    print_route_summary(summary)
    console.print(summary)


@app.command("fetch")
def fetch(
    strategy: Annotated[
        str,
        typer.Option("--strategy", help=f"One of: {', '.join(ROUTE_PRIORITY)}"),
    ],
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 25,
    max_bytes: Annotated[
        int,
        typer.Option("--max-bytes", min=100_000, max=25_000_000),
    ] = 8_000_000,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0),
    ] = 0.4,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0),
    ] = 30.0,
    route_path: Annotated[
        Path | None,
        typer.Option("--route-path", help="Route JSONL path. Defaults to latest route output."),
    ] = None,
) -> None:
    """Fetch a bounded sample for one routed strategy."""
    if strategy not in ROUTE_PRIORITY:
        raise typer.BadParameter(f"Unknown strategy: {strategy}")
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_route_path = route_path or latest_path(
        data_dir, "*_official_source_fetch_route_records.jsonl"
    )
    route_rows = read_jsonl(resolved_route_path)
    route_records = [RouteRecord(**row) for row in route_rows]
    targets: list[tuple[RouteRecord, dict[str, str]]] = []
    for route_record in route_records:
        for route_item in route_record.routes:
            if route_item["strategy"] == strategy:
                targets.append((route_record, route_item))
                break
        if len(targets) >= limit:
            break

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": (
            "application/xml,text/xml,application/json,text/html,"
            "application/pdf;q=0.9,*/*;q=0.1"
        ),
        "Accept-Encoding": "gzip, deflate",
    }
    fetch_records: list[FetchRecord] = []
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for route_record, route_item in targets:
            fetch_records.append(
                probe_route(
                    client=client,
                    route_record=route_record,
                    route=route_item,
                    run_id=run_id,
                    max_bytes=max_bytes,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_official_source_fetch_{strategy}_fetch_records.jsonl"
    summary_path = output_dir / f"{run_id}_official_source_fetch_{strategy}_fetch_summary.json"
    write_jsonl(records_path, fetch_records)
    summary = build_fetch_summary(
        route_path=resolved_route_path,
        records_path=records_path,
        fetch_records=fetch_records,
        strategy=strategy,
        run_id=run_id,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    console.print(summary)


@app.command("acquire-pmc-oai")
def acquire_pmc_oai(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[
        int,
        typer.Option("--offset", min=0, help="Offset after filtering existing outputs."),
    ] = 0,
    max_bytes: Annotated[
        int,
        typer.Option("--max-bytes", min=100_000, max=25_000_000),
    ] = 8_000_000,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.34, help="Keep PMC OAI at or below 3 rps."),
    ] = 0.5,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0),
    ] = 30.0,
    skip_existing: Annotated[
        bool,
        typer.Option("--skip-existing/--no-skip-existing"),
    ] = True,
    skip_attempted: Annotated[
        bool,
        typer.Option("--skip-attempted/--no-skip-attempted"),
    ] = True,
    route_path: Annotated[
        Path | None,
        typer.Option("--route-path", help="Route JSONL path. Defaults to latest route output."),
    ] = None,
) -> None:
    """Acquire PMC OAI XML and extracted text in bounded resumable batches."""
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_route_path = route_path or latest_path(
        data_dir, "*_official_source_fetch_route_records.jsonl"
    )
    route_records = route_records_from_path(resolved_route_path)
    targets = select_acquisition_targets(
        route_records,
        strategy="pmc_oai",
        limit=limit,
        offset=offset,
        data_dir=data_dir,
        skip_existing=skip_existing,
        skip_attempted=skip_attempted,
        raw_subdir="pmc_oai",
        raw_extension="xml",
    )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": "application/xml,text/xml,*/*;q=0.1",
        "Accept-Encoding": "gzip, deflate",
    }
    acquisition_records: list[AcquisitionRecord] = []
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for route_record, route_item, raw_path, text_path in targets:
            acquisition_records.append(
                acquire_pmc_oai_record(
                    client=client,
                    route_record=route_record,
                    route_item=route_item,
                    raw_path=raw_path,
                    text_path=text_path,
                    run_id=run_id,
                    max_bytes=max_bytes,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_official_source_fetch_pmc_oai_acquire_records.jsonl"
    summary_path = output_dir / f"{run_id}_official_source_fetch_pmc_oai_acquire_summary.json"
    write_jsonl(records_path, acquisition_records)
    summary = build_acquisition_summary(
        records=acquisition_records,
        run_id=run_id,
        strategy="pmc_oai",
        route_path=resolved_route_path,
        records_path=records_path,
        raw_output_dir="data/raw/official_source_fetch_router/pmc_oai",
        processed_output_dir="data/processed/official_source_fetch_router/pmc_oai",
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    console.print(summary)


@app.command("acquire-unpaywall-pdf")
def acquire_unpaywall_pdf(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[
        int,
        typer.Option("--offset", min=0, help="Offset after filtering existing outputs."),
    ] = 0,
    max_bytes: Annotated[
        int,
        typer.Option("--max-bytes", min=100_000, max=50_000_000),
    ] = 20_000_000,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0),
    ] = 0.5,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", min=1.0),
    ] = 45.0,
    skip_existing: Annotated[
        bool,
        typer.Option("--skip-existing/--no-skip-existing"),
    ] = True,
    skip_attempted: Annotated[
        bool,
        typer.Option("--skip-attempted/--no-skip-attempted"),
    ] = True,
    route_path: Annotated[
        Path | None,
        typer.Option("--route-path", help="Route JSONL path. Defaults to latest route output."),
    ] = None,
) -> None:
    """Acquire Unpaywall OA PDFs and extracted text in bounded resumable batches."""
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_route_path = route_path or latest_path(
        data_dir, "*_official_source_fetch_route_records.jsonl"
    )
    route_records = route_records_from_path(resolved_route_path)
    targets = select_acquisition_targets(
        route_records,
        strategy="unpaywall_pdf",
        limit=limit,
        offset=offset,
        data_dir=data_dir,
        skip_existing=skip_existing,
        skip_attempted=skip_attempted,
        raw_subdir="unpaywall_pdf",
        raw_extension="pdf",
    )

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": "application/pdf,text/html,*/*;q=0.1",
        "Accept-Encoding": "gzip, deflate",
    }
    acquisition_records: list[AcquisitionRecord] = []
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for route_record, route_item, raw_path, text_path in targets:
            acquisition_records.append(
                acquire_unpaywall_pdf_record(
                    client=client,
                    route_record=route_record,
                    route_item=route_item,
                    raw_path=raw_path,
                    text_path=text_path,
                    run_id=run_id,
                    max_bytes=max_bytes,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = (
        output_dir / f"{run_id}_official_source_fetch_unpaywall_pdf_acquire_records.jsonl"
    )
    summary_path = output_dir / f"{run_id}_official_source_fetch_unpaywall_pdf_acquire_summary.json"
    write_jsonl(records_path, acquisition_records)
    summary = build_acquisition_summary(
        records=acquisition_records,
        run_id=run_id,
        strategy="unpaywall_pdf",
        route_path=resolved_route_path,
        records_path=records_path,
        raw_output_dir="data/raw/official_source_fetch_router/unpaywall_pdf",
        processed_output_dir="data/processed/official_source_fetch_router/unpaywall_pdf",
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    console.print(summary)


def run_augmentation_command(
    *,
    strategy: str,
    limit: int,
    offset: int,
    max_bytes: int,
    delay_seconds: float,
    timeout_seconds: float,
    skip_existing: bool,
    skip_attempted: bool,
    route_path: Path | None,
) -> None:
    settings = get_settings()
    data_dir = settings.data_dir
    resolved_route_path = route_path or latest_path(
        data_dir, "*_official_source_fetch_route_records.jsonl"
    )
    route_records = route_records_from_path(resolved_route_path)
    targets = select_augmentation_targets(
        route_records,
        strategy=strategy,
        limit=limit,
        offset=offset,
        data_dir=data_dir,
        skip_existing=skip_existing,
        skip_attempted=skip_attempted,
    )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": "application/json,*/*;q=0.1",
        "Accept-Encoding": "gzip, deflate",
    }
    records: list[AugmentationRecord] = []
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for route_record, route_item, raw_path in targets:
            records.append(
                acquire_augmentation_record(
                    client=client,
                    route_record=route_record,
                    route_item=route_item,
                    raw_path=raw_path,
                    strategy=strategy,
                    run_id=run_id,
                    max_bytes=max_bytes,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = output_dir / f"{run_id}_official_source_fetch_{strategy}_augment_records.jsonl"
    summary_path = output_dir / f"{run_id}_official_source_fetch_{strategy}_augment_summary.json"
    write_jsonl(records_path, records)
    summary = build_augmentation_summary(
        records=records,
        strategy=strategy,
        run_id=run_id,
        route_path=resolved_route_path,
        records_path=records_path,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    write_json(summary_path, summary)
    console.print(summary)


@app.command("acquire-augmented-links")
def acquire_augmented_links(
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    max_bytes: Annotated[
        int,
        typer.Option("--max-bytes", min=100_000, max=50_000_000),
    ] = 20_000_000,
    delay_seconds: Annotated[float, typer.Option("--delay-seconds", min=0.0)] = 0.5,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 45.0,
    skip_attempted: Annotated[
        bool,
        typer.Option("--skip-attempted/--no-skip-attempted"),
    ] = True,
    skip_source_ready: Annotated[
        bool,
        typer.Option("--skip-source-ready/--no-skip-source-ready"),
    ] = True,
) -> None:
    """Acquire prioritized source text from NCBI ELink/OpenAlex augmentation URLs."""
    settings = get_settings()
    data_dir = settings.data_dir
    targets = load_augmented_link_targets(
        data_dir,
        limit=limit,
        offset=offset,
        skip_attempted=skip_attempted,
        skip_source_ready=skip_source_ready,
    )
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    started_at = datetime.now(UTC)
    headers = {
        "User-Agent": "MaryGenAI source availability POC (mailto:local-maintainer@example.invalid)",
        "Accept": (
            "application/xml,text/xml,text/html,application/pdf,"
            "application/octet-stream;q=0.9,*/*;q=0.1"
        ),
        "Accept-Encoding": "gzip, deflate",
    }
    records: list[AcquisitionRecord] = []
    with httpx.Client(timeout=timeout_seconds, headers=headers) as client:
        for target in targets:
            records.append(
                acquire_augmented_link_record(
                    client=client,
                    target=target,
                    data_dir=data_dir,
                    run_id=run_id,
                    max_bytes=max_bytes,
                )
            )
            time.sleep(delay_seconds)

    output_dir = data_dir / OUTPUT_SUBDIR
    records_path = (
        output_dir / f"{run_id}_official_source_fetch_augmented_links_acquire_records.jsonl"
    )
    summary_path = (
        output_dir / f"{run_id}_official_source_fetch_augmented_links_acquire_summary.json"
    )
    write_jsonl(records_path, records)
    summary = build_acquisition_summary(
        records=records,
        run_id=run_id,
        strategy="augmented_links",
        route_path=Path("data/normalized/official_source_fetch_router/*_augment_records.jsonl"),
        records_path=records_path,
        raw_output_dir="data/raw/official_source_fetch_router/augmented_links",
        processed_output_dir="data/processed/official_source_fetch_router/augmented_links",
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    summary["link_kind_counts"] = dict(
        Counter(record.provenance.get("link_kind") for record in records)
    )
    write_json(summary_path, summary)
    console.print(summary)


@app.command("augment-ncbi-elink")
def augment_ncbi_elink(
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 200,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=100_000, max=10_000_000)] = 2_000_000,
    delay_seconds: Annotated[float, typer.Option("--delay-seconds", min=0.34)] = 0.4,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 30.0,
    skip_existing: Annotated[bool, typer.Option("--skip-existing/--no-skip-existing")] = True,
    skip_attempted: Annotated[bool, typer.Option("--skip-attempted/--no-skip-attempted")] = True,
    route_path: Annotated[Path | None, typer.Option("--route-path")] = None,
) -> None:
    """Acquire NCBI ELink LinkOut/OA metadata in bounded resumable batches."""
    run_augmentation_command(
        strategy="ncbi_elink",
        limit=limit,
        offset=offset,
        max_bytes=max_bytes,
        delay_seconds=delay_seconds,
        timeout_seconds=timeout_seconds,
        skip_existing=skip_existing,
        skip_attempted=skip_attempted,
        route_path=route_path,
    )


@app.command("augment-openalex")
def augment_openalex(
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 200,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=100_000, max=10_000_000)] = 2_000_000,
    delay_seconds: Annotated[float, typer.Option("--delay-seconds", min=0.0)] = 0.2,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 30.0,
    skip_existing: Annotated[bool, typer.Option("--skip-existing/--no-skip-existing")] = True,
    skip_attempted: Annotated[bool, typer.Option("--skip-attempted/--no-skip-attempted")] = True,
    route_path: Annotated[Path | None, typer.Option("--route-path")] = None,
) -> None:
    """Acquire OpenAlex identity and OA-location metadata in bounded resumable batches."""
    run_augmentation_command(
        strategy="openalex_identity_access",
        limit=limit,
        offset=offset,
        max_bytes=max_bytes,
        delay_seconds=delay_seconds,
        timeout_seconds=timeout_seconds,
        skip_existing=skip_existing,
        skip_attempted=skip_attempted,
        route_path=route_path,
    )


@app.command("summarize")
def summarize() -> None:
    """Summarize latest route output and fetch summaries."""
    settings = get_settings()
    data_dir = settings.data_dir
    route_summary_path = latest_path(data_dir, "*_official_source_fetch_route_summary.json")
    route_summary = json.loads(route_summary_path.read_text(encoding="utf-8"))
    fetch_summaries = []
    fetch_summary_paths = sorted(
        (data_dir / OUTPUT_SUBDIR).glob("*_official_source_fetch_*_fetch_summary.json")
    )
    for path in fetch_summary_paths:
        fetch_summaries.append(json.loads(path.read_text(encoding="utf-8")))
    console.print(
        {
            "latest_route_summary": str(route_summary_path),
            "best_strategy_counts": route_summary.get("best_strategy_counts", {}),
            "route_availability_counts": route_summary.get("route_availability_counts", {}),
            "fetch_summaries": [
                {
                    "strategy": item.get("strategy"),
                    "run_id": item.get("run_id"),
                    "counts": item.get("counts"),
                    "failure_reason_counts": item.get("failure_reason_counts"),
                }
                for item in fetch_summaries
            ],
        }
    )


if __name__ == "__main__":
    app()
