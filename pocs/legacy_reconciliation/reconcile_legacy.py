"""Reconcile legacy study URLs against stable publication identifiers.

This POC is intentionally local-only. It parses the legacy CSV export, extracts
identifiers that are already visible in URLs, and writes reproducible summary files
under the ignored data directory.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote, urlparse

import typer
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

DEFAULT_LEGACY_STUDIES_PATH = Path("temp/legacy/cannadocs/Estudos-Grid view.csv")
DEFAULT_OUTPUT_SUBDIR = Path("normalized/legacy_reconciliation")

LEGACY_ID_FIELD = "ID do Estudo"
PORTUGUESE_TITLE_FIELD = "Título"
ENGLISH_TITLE_FIELD = "Título do artigo em inglês"
LEGACY_DOMAIN_FIELD = "Domínio onde estudo foi publicado"
LEGACY_URL_FIELD = "URL do estudo"
LEGACY_STUDY_TYPE_FIELD = "Tipo de Estudo"
LEGACY_YEAR_FIELD = "Ano de Publicação"

PMID_RE = re.compile(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|/pubmed/)(\d+)", re.IGNORECASE)
PMCID_RE = re.compile(r"/pmc/articles/(PMC\d+)", re.IGNORECASE)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)

console = Console()
app = typer.Typer(help="Reconcile legacy study records with stable identifiers.")


@app.callback()
def main() -> None:
    """Run legacy reconciliation commands."""


@dataclass(frozen=True)
class LegacyReconciliationRecord:
    legacy_study_id: str | None
    legacy_domain: str | None
    url: str | None
    canonical_url: str | None
    host: str | None
    source_class: str
    pmid: str | None
    pmcid: str | None
    doi: str | None
    stable_identifier: str | None
    stable_identifier_type: str | None
    title_en: str | None
    title_pt: str | None
    normalized_title: str | None
    study_type: str | None
    publication_year: str | None
    needs_manual_review: bool
    review_reasons: list[str]


def value_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    host = host.lower().strip()
    if host.startswith("www."):
        return host[4:]
    return host


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme and not parsed.netloc:
        return url.strip()
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or parsed.path
    return parsed._replace(scheme=scheme, netloc=host, path=path, fragment="").geturl()


def normalize_title(title: str | None) -> str | None:
    if not title:
        return None
    ascii_title = unicodedata.normalize("NFKD", title)
    ascii_title = ascii_title.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", ascii_title.lower()).strip()
    return re.sub(r"\s+", " ", normalized) or None


def extract_pmid(url: str | None) -> str | None:
    if not url:
        return None
    match = PMID_RE.search(unquote(url))
    return match.group(1) if match else None


def extract_pmcid(url: str | None) -> str | None:
    if not url:
        return None
    match = PMCID_RE.search(unquote(url))
    return match.group(1).upper() if match else None


def clean_doi(raw_doi: str) -> str:
    return raw_doi.rstrip(").,;]").lower()


def extract_doi(url: str | None) -> str | None:
    if not url:
        return None
    decoded_url = unquote(url)
    parsed = urlparse(decoded_url)
    if normalize_host(parsed.netloc) in {"doi.org", "dx.doi.org"}:
        path = parsed.path.strip("/")
        if path.startswith("10."):
            return clean_doi(path)

    match = DOI_RE.search(decoded_url)
    return clean_doi(match.group(0)) if match else None


def classify_source(
    host: str | None,
    path: str,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
) -> str:
    normalized_host = normalize_host(host)
    if not normalized_host:
        return "missing_url"
    if pmcid:
        return "pmc_full_text_page"
    if pmid:
        return "pubmed_record_page"
    if doi and normalized_host in {"doi.org", "dx.doi.org"}:
        return "doi_url"
    if normalized_host.endswith("ncbi.nlm.nih.gov") and "/pmc/" in path.lower():
        return "ncbi_pmc_related"
    if normalized_host.endswith("ncbi.nlm.nih.gov"):
        return "ncbi_other"
    return "publisher_or_other_url"


def choose_stable_identifier(
    *,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
    canonical_url: str | None,
) -> tuple[str | None, str | None]:
    if pmid:
        return pmid, "pmid"
    if pmcid:
        return pmcid, "pmcid"
    if doi:
        return doi, "doi"
    if canonical_url:
        return canonical_url, "canonical_url"
    return None, None


def build_record(row: dict[str, str]) -> LegacyReconciliationRecord:
    url = value_or_none(row.get(LEGACY_URL_FIELD))
    canonical_url = canonicalize_url(url)
    parsed = urlparse(canonical_url or "")
    host = normalize_host(parsed.netloc)
    pmid = extract_pmid(canonical_url)
    pmcid = extract_pmcid(canonical_url)
    doi = extract_doi(canonical_url)
    stable_identifier, stable_identifier_type = choose_stable_identifier(
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        canonical_url=canonical_url,
    )
    title_en = value_or_none(row.get(ENGLISH_TITLE_FIELD))
    title_pt = value_or_none(row.get(PORTUGUESE_TITLE_FIELD))
    normalized_title = normalize_title(title_en or title_pt)
    source_class = classify_source(host, parsed.path, pmid, pmcid, doi)

    review_reasons: list[str] = []
    if not url:
        review_reasons.append("missing_url")
    if stable_identifier_type == "canonical_url":
        review_reasons.append("no_stable_publication_identifier")
    if not normalized_title:
        review_reasons.append("missing_title")

    return LegacyReconciliationRecord(
        legacy_study_id=value_or_none(row.get(LEGACY_ID_FIELD)),
        legacy_domain=value_or_none(row.get(LEGACY_DOMAIN_FIELD)),
        url=url,
        canonical_url=canonical_url,
        host=host,
        source_class=source_class,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        stable_identifier=stable_identifier,
        stable_identifier_type=stable_identifier_type,
        title_en=title_en,
        title_pt=title_pt,
        normalized_title=normalized_title,
        study_type=value_or_none(row.get(LEGACY_STUDY_TYPE_FIELD)),
        publication_year=value_or_none(row.get(LEGACY_YEAR_FIELD)),
        needs_manual_review=bool(review_reasons),
        review_reasons=review_reasons,
    )


def read_legacy_records(input_path: Path) -> list[LegacyReconciliationRecord]:
    with input_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [build_record(row) for row in reader]


def duplicate_examples(
    records: list[LegacyReconciliationRecord],
    field_name: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    values: dict[str, list[LegacyReconciliationRecord]] = defaultdict(list)
    for record in records:
        value = getattr(record, field_name)
        if value:
            values[value].append(record)

    examples: list[dict[str, Any]] = []
    for value, matching_records in values.items():
        if len(matching_records) < 2:
            continue
        examples.append(
            {
                "value": value,
                "count": len(matching_records),
                "legacy_study_ids": [record.legacy_study_id for record in matching_records[:10]],
                "titles": [record.title_en or record.title_pt for record in matching_records[:3]],
            }
        )
    return sorted(examples, key=lambda item: item["count"], reverse=True)[:limit]


def count_non_null(records: list[LegacyReconciliationRecord], field_name: str) -> int:
    return sum(bool(getattr(record, field_name)) for record in records)


def build_summary(
    records: list[LegacyReconciliationRecord],
    *,
    input_path: Path,
    records_path: Path,
    fetched_at: str,
) -> dict[str, Any]:
    source_class_counts = Counter(record.source_class for record in records)
    identifier_type_counts = Counter(
        record.stable_identifier_type or "none" for record in records
    )
    host_counts = Counter(record.host or "missing" for record in records)
    review_reason_counts = Counter(
        reason for record in records for reason in record.review_reasons
    )

    return {
        "source": "legacy_cannadocs",
        "method": "local_legacy_url_reconciliation",
        "input_path": str(input_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "total_records": len(records),
        "identifier_availability": {
            "pmid": count_non_null(records, "pmid"),
            "pmcid": count_non_null(records, "pmcid"),
            "doi": count_non_null(records, "doi"),
            "stable_identifier": count_non_null(records, "stable_identifier"),
        },
        "stable_identifier_type_counts": dict(identifier_type_counts.most_common()),
        "source_class_counts": dict(source_class_counts.most_common()),
        "top_hosts": dict(host_counts.most_common(20)),
        "manual_review": {
            "records": sum(record.needs_manual_review for record in records),
            "reason_counts": dict(review_reason_counts.most_common()),
        },
        "duplicates": {
            "pmid": duplicate_examples(records, "pmid"),
            "pmcid": duplicate_examples(records, "pmcid"),
            "doi": duplicate_examples(records, "doi"),
            "normalized_title": duplicate_examples(records, "normalized_title"),
        },
        "examples": {
            "manual_review": [
                asdict(record) for record in records if record.needs_manual_review
            ][:10],
            "pmc_full_text_page": [
                asdict(record) for record in records if record.source_class == "pmc_full_text_page"
            ][:5],
            "publisher_or_other_url": [
                asdict(record)
                for record in records
                if record.source_class == "publisher_or_other_url"
            ][:5],
        },
    }


def write_jsonl(path: Path, records: list[LegacyReconciliationRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Legacy reconciliation summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total records", str(summary["total_records"]))
    for field_name, count in summary["identifier_availability"].items():
        table.add_row(field_name, str(count))
    table.add_row("Manual review records", str(summary["manual_review"]["records"]))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    input_path: Annotated[
        Path,
        typer.Option("--input-path", help="Legacy studies CSV path."),
    ] = DEFAULT_LEGACY_STUDIES_PATH,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for reconciliation outputs."),
    ] = None,
) -> None:
    """Parse legacy study URLs and report identifier coverage."""
    settings = get_settings()
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    records_path = resolved_output_dir / f"{run_id}_legacy_reconciliation_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_legacy_reconciliation_summary.json"

    records = read_legacy_records(input_path)
    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        input_path=input_path,
        records_path=records_path,
        fetched_at=fetched_at,
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


if __name__ == "__main__":
    app()
