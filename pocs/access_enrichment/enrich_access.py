"""Enrich link resolver records with Europe PMC and Unpaywall metadata."""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

DEFAULT_INPUT_GLOB = "data/normalized/link_resolver/*_link_resolver_records.jsonl"
DEFAULT_RAW_SUBDIR = Path("raw/access_enrichment")
DEFAULT_NORMALIZED_SUBDIR = Path("normalized/access_enrichment")
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
UNPAYWALL_BASE_URL = "https://api.unpaywall.org/v2"

console = Console()
app = typer.Typer(help="Enrich access metadata using Europe PMC and Unpaywall.")


@app.callback()
def main() -> None:
    """Run access enrichment commands."""


@dataclass(frozen=True)
class AccessEnrichmentRecord:
    source_record_id: str | None
    title: str | None
    input_access_class: str
    pmid: str | None
    pmcid: str | None
    doi: str | None
    europe_pmc_queried: bool
    europe_pmc_found: bool
    europe_pmc_pmid: str | None
    europe_pmc_pmcid: str | None
    europe_pmc_doi: str | None
    europe_pmc_has_full_text: bool | None
    europe_pmc_is_open_access: bool | None
    europe_pmc_full_text_urls: list[dict[str, Any]]
    unpaywall_queried: bool
    unpaywall_found: bool
    unpaywall_is_oa: bool | None
    unpaywall_oa_status: str | None
    unpaywall_best_landing_url: str | None
    unpaywall_best_pdf_url: str | None
    unpaywall_license: str | None
    resolved_access_class: str
    candidate_full_text_urls: list[str]
    candidate_pdf_urls: list[str]
    errors: list[str]
    provenance: dict[str, Any]


def latest_input_path(pattern: str = DEFAULT_INPUT_GLOB) -> Path:
    paths = sorted(Path().glob(pattern))
    if not paths:
        msg = f"No input files matched {pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, records: list[AccessEnrichmentRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


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


def select_sample(records: list[dict[str, Any]], *, limit_per_class: int) -> list[dict[str, Any]]:
    target_classes = {"pubmed_metadata_only", "doi_landing_page_available"}
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for record in records:
        access_class = value_or_none(record.get("access_class")) or "unknown"
        if access_class not in target_classes:
            continue
        if counts[access_class] >= limit_per_class:
            continue
        selected.append(record)
        counts[access_class] += 1
    return selected


class EuropePmcClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.client = httpx.Client(timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def search_by_pmid_or_doi(self, *, pmid: str | None, doi: str | None) -> dict[str, Any] | None:
        if pmid:
            query = f"EXT_ID:{pmid} AND SRC:MED"
        elif doi:
            query = f'DOI:"{doi}"'
        else:
            return None

        response = self.client.get(
            EUROPE_PMC_SEARCH_URL,
            params={"query": query, "format": "json", "resultType": "core", "pageSize": 1},
        )
        response.raise_for_status()
        return response.json()


class UnpaywallClient:
    def __init__(self, *, email: str, timeout_seconds: float = 30.0) -> None:
        self.email = email
        self.client = httpx.Client(base_url=UNPAYWALL_BASE_URL, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def get_by_doi(self, doi: str) -> dict[str, Any]:
        response = self.client.get(f"/{doi}", params={"email": self.email})
        if response.status_code == 404:
            return {"doi": doi, "not_found": True}
        response.raise_for_status()
        return response.json()


def first_europe_pmc_result(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    results = payload.get("resultList", {}).get("result", [])
    return results[0] if results else None


def doi_from_europe_pmc_payload(payload: dict[str, Any] | None) -> str | None:
    result = first_europe_pmc_result(payload)
    if not result:
        return None
    return value_or_none(result.get("doi"))


def europe_pmc_full_text_urls(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not result:
        return []
    return result.get("fullTextUrlList", {}).get("fullTextUrl", []) or []


def is_free_or_open_access_url(url_record: dict[str, Any]) -> bool:
    availability_code = value_or_none(url_record.get("availabilityCode"))
    return availability_code in {"F", "OA"}


def is_pdf_url(url_record: dict[str, Any]) -> bool:
    document_style = value_or_none(url_record.get("documentStyle"))
    url = value_or_none(url_record.get("url")) or ""
    return document_style == "pdf" or url.lower().endswith(".pdf")


def unpaywall_best_location(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload or payload.get("not_found"):
        return None
    return payload.get("best_oa_location")


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def raw_path(raw_dir: Path, run_id: str, source: str, source_record_id: str | None) -> Path:
    safe_id = source_record_id or "unknown"
    safe_id = "".join(character if character.isalnum() else "_" for character in safe_id)
    return raw_dir / f"{run_id}_{source}_{safe_id}.json"


def write_raw_payload(path: Path, payload: dict[str, Any] | None) -> None:
    path.write_text(
        json.dumps(payload or {}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_enrichment_record(
    source_record: dict[str, Any],
    *,
    europe_pmc_payload: dict[str, Any] | None,
    unpaywall_payload: dict[str, Any] | None,
    europe_pmc_queried: bool,
    unpaywall_queried: bool,
    errors: list[str],
    input_path: Path,
    fetched_at: str,
) -> AccessEnrichmentRecord:
    europe_pmc_result = first_europe_pmc_result(europe_pmc_payload)
    europe_urls = europe_pmc_full_text_urls(europe_pmc_result)
    best_oa_location = unpaywall_best_location(unpaywall_payload)

    europe_free_urls = [
        url
        for url in europe_urls
        if value_or_none(url.get("url")) and is_free_or_open_access_url(url)
    ]
    europe_full_text_candidates = [
        url["url"] for url in europe_free_urls if not is_pdf_url(url)
    ]
    europe_pdf_candidates = [url["url"] for url in europe_free_urls if is_pdf_url(url)]
    unpaywall_landing_url = (
        value_or_none(best_oa_location.get("url_for_landing_page"))
        if best_oa_location
        else None
    )
    unpaywall_pdf_url = (
        value_or_none(best_oa_location.get("url_for_pdf")) if best_oa_location else None
    )

    candidate_full_text_urls = list(europe_full_text_candidates)
    if unpaywall_landing_url:
        candidate_full_text_urls.append(unpaywall_landing_url)
    candidate_full_text_urls = dedupe_preserving_order(candidate_full_text_urls)

    candidate_pdf_urls = list(europe_pdf_candidates)
    if unpaywall_pdf_url:
        candidate_pdf_urls.append(unpaywall_pdf_url)
    candidate_pdf_urls = dedupe_preserving_order(candidate_pdf_urls)

    if candidate_pdf_urls:
        resolved_access_class = "open_access_pdf_candidate"
    elif candidate_full_text_urls:
        resolved_access_class = "open_access_landing_candidate"
    elif europe_pmc_result:
        resolved_access_class = "metadata_enriched_no_full_text"
    elif unpaywall_payload and not unpaywall_payload.get("not_found"):
        resolved_access_class = "unpaywall_metadata_no_oa"
    else:
        resolved_access_class = "not_enriched"

    return AccessEnrichmentRecord(
        source_record_id=value_or_none(source_record.get("source_record_id")),
        title=value_or_none(source_record.get("title")),
        input_access_class=value_or_none(source_record.get("access_class")) or "unknown",
        pmid=value_or_none(source_record.get("pmid")),
        pmcid=value_or_none(source_record.get("pmcid")),
        doi=value_or_none(source_record.get("doi")),
        europe_pmc_queried=europe_pmc_queried,
        europe_pmc_found=bool(europe_pmc_result),
        europe_pmc_pmid=value_or_none(europe_pmc_result.get("pmid")) if europe_pmc_result else None,
        europe_pmc_pmcid=value_or_none(europe_pmc_result.get("pmcid"))
        if europe_pmc_result
        else None,
        europe_pmc_doi=value_or_none(europe_pmc_result.get("doi")) if europe_pmc_result else None,
        europe_pmc_has_full_text=bool_or_none(europe_pmc_result.get("hasFullText"))
        if europe_pmc_result
        else None,
        europe_pmc_is_open_access=bool_or_none(europe_pmc_result.get("isOpenAccess"))
        if europe_pmc_result
        else None,
        europe_pmc_full_text_urls=europe_urls,
        unpaywall_queried=unpaywall_queried,
        unpaywall_found=bool(unpaywall_payload and not unpaywall_payload.get("not_found")),
        unpaywall_is_oa=bool_or_none(unpaywall_payload.get("is_oa"))
        if unpaywall_payload and not unpaywall_payload.get("not_found")
        else None,
        unpaywall_oa_status=value_or_none(unpaywall_payload.get("oa_status"))
        if unpaywall_payload and not unpaywall_payload.get("not_found")
        else None,
        unpaywall_best_landing_url=unpaywall_landing_url,
        unpaywall_best_pdf_url=unpaywall_pdf_url,
        unpaywall_license=value_or_none(best_oa_location.get("license"))
        if best_oa_location
        else None,
        resolved_access_class=resolved_access_class,
        candidate_full_text_urls=candidate_full_text_urls,
        candidate_pdf_urls=candidate_pdf_urls,
        errors=errors,
        provenance={
            "source": "access_enrichment",
            "method": "europe_pmc_unpaywall_sample",
            "input_path": str(input_path),
            "fetched_at": fetched_at,
        },
    )


def build_summary(
    records: list[AccessEnrichmentRecord],
    *,
    input_path: Path,
    records_path: Path,
    fetched_at: str,
    limit_per_class: int,
) -> dict[str, Any]:
    return {
        "source": "access_enrichment",
        "method": "europe_pmc_unpaywall_sample",
        "input_path": str(input_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "limit_per_class": limit_per_class,
        "total_records": len(records),
        "input_access_class_counts": dict(
            Counter(record.input_access_class for record in records).most_common()
        ),
        "resolved_access_class_counts": dict(
            Counter(record.resolved_access_class for record in records).most_common()
        ),
        "europe_pmc": {
            "queried": sum(record.europe_pmc_queried for record in records),
            "found": sum(record.europe_pmc_found for record in records),
            "has_full_text": sum(record.europe_pmc_has_full_text is True for record in records),
            "is_open_access": sum(record.europe_pmc_is_open_access is True for record in records),
        },
        "unpaywall": {
            "queried": sum(record.unpaywall_queried for record in records),
            "found": sum(record.unpaywall_found for record in records),
            "is_oa": sum(record.unpaywall_is_oa is True for record in records),
            "pdf_url": sum(bool(record.unpaywall_best_pdf_url) for record in records),
        },
        "records_with_errors": sum(bool(record.errors) for record in records),
        "examples": {
            "open_access_pdf_candidate": [
                asdict(record)
                for record in records
                if record.resolved_access_class == "open_access_pdf_candidate"
            ][:5],
            "open_access_landing_candidate": [
                asdict(record)
                for record in records
                if record.resolved_access_class == "open_access_landing_candidate"
            ][:5],
            "metadata_enriched_no_full_text": [
                asdict(record)
                for record in records
                if record.resolved_access_class == "metadata_enriched_no_full_text"
            ][:5],
        },
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Access enrichment summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total records", str(summary["total_records"]))
    for access_class, count in summary["resolved_access_class_counts"].items():
        table.add_row(access_class, str(count))
    table.add_row("Europe PMC queried", str(summary["europe_pmc"]["queried"]))
    table.add_row("Europe PMC found", str(summary["europe_pmc"]["found"]))
    table.add_row("Unpaywall queried", str(summary["unpaywall"]["queried"]))
    table.add_row("Unpaywall found", str(summary["unpaywall"]["found"]))
    table.add_row("Records with errors", str(summary["records_with_errors"]))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input-path",
            help="Input link resolver JSONL. Defaults to latest link resolver output.",
        ),
    ] = None,
    limit_per_class: Annotated[
        int,
        typer.Option("--limit-per-class", min=1, max=200, help="Sample size per class."),
    ] = 25,
    raw_dir: Annotated[
        Path | None,
        typer.Option("--raw-dir", help="Directory for raw API payloads."),
    ] = None,
    normalized_dir: Annotated[
        Path | None,
        typer.Option("--normalized-dir", help="Directory for normalized outputs."),
    ] = None,
) -> None:
    """Enrich a resolver sample through Europe PMC and Unpaywall."""
    load_dotenv()

    resolved_input_path = input_path or latest_input_path()
    settings = get_settings()
    resolved_raw_dir = raw_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_normalized_dir = normalized_dir or settings.data_dir / DEFAULT_NORMALIZED_SUBDIR
    resolved_raw_dir.mkdir(parents=True, exist_ok=True)
    resolved_normalized_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    records_path = resolved_normalized_dir / f"{run_id}_access_enrichment_records.jsonl"
    summary_path = resolved_normalized_dir / f"{run_id}_access_enrichment_summary.json"

    source_records = select_sample(read_jsonl(resolved_input_path), limit_per_class=limit_per_class)
    europe_pmc_client = EuropePmcClient()
    unpaywall_email = value_or_none(os.getenv("UNPAYWALL_EMAIL"))
    unpaywall_client = UnpaywallClient(email=unpaywall_email) if unpaywall_email else None

    records: list[AccessEnrichmentRecord] = []
    try:
        for source_record in source_records:
            source_id = value_or_none(source_record.get("source_record_id"))
            pmid = value_or_none(source_record.get("pmid"))
            doi = value_or_none(source_record.get("doi"))
            errors: list[str] = []
            europe_pmc_payload: dict[str, Any] | None = None
            unpaywall_payload: dict[str, Any] | None = None
            europe_pmc_queried = False
            unpaywall_queried = False

            if pmid or doi:
                europe_pmc_queried = True
                try:
                    europe_pmc_payload = europe_pmc_client.search_by_pmid_or_doi(
                        pmid=pmid,
                        doi=doi,
                    )
                    write_raw_payload(
                        raw_path(resolved_raw_dir, run_id, "europe_pmc", source_id),
                        europe_pmc_payload,
                    )
                except httpx.HTTPError as error:
                    errors.append(f"europe_pmc:{error}")

            doi_for_unpaywall = doi or doi_from_europe_pmc_payload(europe_pmc_payload)
            if doi_for_unpaywall:
                if unpaywall_client:
                    unpaywall_queried = True
                    try:
                        unpaywall_payload = unpaywall_client.get_by_doi(doi_for_unpaywall)
                        write_raw_payload(
                            raw_path(resolved_raw_dir, run_id, "unpaywall", source_id),
                            unpaywall_payload,
                        )
                    except httpx.HTTPError as error:
                        errors.append(f"unpaywall:{error}")
                else:
                    errors.append("unpaywall:missing_UNPAYWALL_EMAIL")

            records.append(
                build_enrichment_record(
                    source_record,
                    europe_pmc_payload=europe_pmc_payload,
                    unpaywall_payload=unpaywall_payload,
                    europe_pmc_queried=europe_pmc_queried,
                    unpaywall_queried=unpaywall_queried,
                    errors=errors,
                    input_path=resolved_input_path,
                    fetched_at=fetched_at,
                )
            )
            time.sleep(0.1)
    finally:
        europe_pmc_client.close()
        if unpaywall_client:
            unpaywall_client.close()

    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        input_path=resolved_input_path,
        records_path=records_path,
        fetched_at=fetched_at,
        limit_per_class=limit_per_class,
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


if __name__ == "__main__":
    app()
