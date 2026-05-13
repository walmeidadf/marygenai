"""Classify publication link availability before full-text retrieval.

This POC consumes normalized records from previous POCs and produces access-path
classifications. It intentionally does not fetch remote pages or download PDFs.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

DEFAULT_INPUT_GLOB = "data/normalized/legacy_reconciliation/*_legacy_reconciliation_records.jsonl"
DEFAULT_OUTPUT_SUBDIR = Path("normalized/link_resolver")

console = Console()
app = typer.Typer(help="Classify publication full-text and link availability.")


@app.callback()
def main() -> None:
    """Run link resolver commands."""


@dataclass(frozen=True)
class LinkResolutionRecord:
    source_record_id: str | None
    source_record_type: str
    title: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    canonical_url: str | None
    host: str | None
    access_class: str
    full_text_url: str | None
    landing_url: str | None
    pdf_candidate_url: str | None
    next_resolver_steps: list[str]
    requires_network_resolution: bool
    confidence: str
    notes: list[str]
    provenance: dict[str, Any]


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def latest_input_path(pattern: str = DEFAULT_INPUT_GLOB) -> Path:
    paths = sorted(Path().glob(pattern))
    if not paths:
        msg = f"No input files matched {pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def pmc_article_url(pmcid: str) -> str:
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"


def pmc_pdf_candidate_url(pmcid: str) -> str:
    return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/"


def pubmed_url(pmid: str) -> str:
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


def doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}"


def source_record_id(record: dict[str, Any]) -> str | None:
    return value_or_none(record.get("legacy_study_id") or record.get("pmid"))


def source_record_type(record: dict[str, Any]) -> str:
    if "legacy_study_id" in record:
        return "legacy_study"
    if "pmid" in record:
        return "pubmed_record"
    return "unknown_record"


def title_from_record(record: dict[str, Any]) -> str | None:
    return value_or_none(record.get("title_en") or record.get("title") or record.get("title_pt"))


def resolve_record(
    record: dict[str, Any],
    *,
    input_path: Path,
    fetched_at: str,
) -> LinkResolutionRecord:
    pmid = value_or_none(record.get("pmid"))
    pmcid = value_or_none(record.get("pmcid"))
    doi = value_or_none(record.get("doi"))
    canonical_url = value_or_none(record.get("canonical_url") or record.get("url"))
    host = value_or_none(record.get("host"))

    notes: list[str] = []
    next_steps: list[str] = []
    access_class = "not_automatically_recoverable"
    full_text_url: str | None = None
    landing_url: str | None = None
    pdf_candidate_url: str | None = None
    confidence = "low"
    requires_network_resolution = True

    if pmcid:
        access_class = "pmc_full_text_available"
        full_text_url = pmc_article_url(pmcid)
        landing_url = full_text_url
        pdf_candidate_url = pmc_pdf_candidate_url(pmcid)
        next_steps = ["verify_pmc_license", "sample_pmc_full_text_extraction"]
        confidence = "high"
        requires_network_resolution = False
        notes.append("PMCID is present, so PMC is the first full-text path.")
        if pmid:
            notes.append("PMID is also present and can anchor PubMed metadata.")
        if doi:
            notes.append("DOI is also present and can support Unpaywall enrichment.")
    elif doi:
        access_class = "doi_landing_page_available"
        landing_url = doi_url(doi)
        next_steps = ["query_unpaywall", "query_europe_pmc", "verify_doi_landing_page"]
        confidence = "medium"
        notes.append("DOI is present, but open-access status is not known locally.")
    elif pmid:
        access_class = "pubmed_metadata_only"
        landing_url = pubmed_url(pmid)
        next_steps = ["query_pubmed_for_pmcid_and_doi", "query_europe_pmc_by_pmid"]
        confidence = "medium"
        notes.append("PMID is present, but no PMCID or DOI is known in the input record.")
    elif canonical_url:
        access_class = "publisher_landing_page_only"
        landing_url = canonical_url
        next_steps = [
            "extract_identifier_from_publisher_page",
            "title_search_in_pubmed_or_crossref",
        ]
        confidence = "low"
        notes.append("Only a canonical URL is known locally.")
    else:
        next_steps = ["manual_review"]
        notes.append("No identifier or URL is available.")

    return LinkResolutionRecord(
        source_record_id=source_record_id(record),
        source_record_type=source_record_type(record),
        title=title_from_record(record),
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        canonical_url=canonical_url,
        host=host,
        access_class=access_class,
        full_text_url=full_text_url,
        landing_url=landing_url,
        pdf_candidate_url=pdf_candidate_url,
        next_resolver_steps=next_steps,
        requires_network_resolution=requires_network_resolution,
        confidence=confidence,
        notes=notes,
        provenance={
            "source": "link_resolver",
            "method": "local_identifier_access_classification",
            "input_path": str(input_path),
            "fetched_at": fetched_at,
        },
    )


def write_jsonl(path: Path, records: list[LinkResolutionRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def build_summary(
    records: list[LinkResolutionRecord],
    *,
    input_path: Path,
    records_path: Path,
    fetched_at: str,
) -> dict[str, Any]:
    access_class_counts = Counter(record.access_class for record in records)
    step_counts = Counter(step for record in records for step in record.next_resolver_steps)
    confidence_counts = Counter(record.confidence for record in records)
    host_counts = Counter(record.host or "missing" for record in records)

    return {
        "source": "link_resolver",
        "method": "local_identifier_access_classification",
        "input_path": str(input_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "total_records": len(records),
        "access_class_counts": dict(access_class_counts.most_common()),
        "next_resolver_step_counts": dict(step_counts.most_common()),
        "confidence_counts": dict(confidence_counts.most_common()),
        "records_requiring_network_resolution": sum(
            record.requires_network_resolution for record in records
        ),
        "top_hosts": dict(host_counts.most_common(20)),
        "examples": {
            "pmc_full_text_available": [
                asdict(record)
                for record in records
                if record.access_class == "pmc_full_text_available"
            ][:5],
            "doi_landing_page_available": [
                asdict(record)
                for record in records
                if record.access_class == "doi_landing_page_available"
            ][:5],
            "pubmed_metadata_only": [
                asdict(record)
                for record in records
                if record.access_class == "pubmed_metadata_only"
            ][:5],
            "publisher_landing_page_only": [
                asdict(record)
                for record in records
                if record.access_class == "publisher_landing_page_only"
            ][:5],
        },
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Link resolver summary")
    table.add_column("Access class")
    table.add_column("Records", justify="right")
    for access_class, count in summary["access_class_counts"].items():
        table.add_row(access_class, str(count))
    table.add_row(
        "network_resolution_required",
        str(summary["records_requiring_network_resolution"]),
    )
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input-path",
            help="Input JSONL records. Defaults to latest legacy reconciliation output.",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for link resolver outputs."),
    ] = None,
) -> None:
    """Classify access paths for normalized publication records."""
    resolved_input_path = input_path or latest_input_path()
    settings = get_settings()
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    records_path = resolved_output_dir / f"{run_id}_link_resolver_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_link_resolver_summary.json"

    source_records = read_jsonl(resolved_input_path)
    records = [
        resolve_record(record, input_path=resolved_input_path, fetched_at=fetched_at)
        for record in source_records
    ]
    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        input_path=resolved_input_path,
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
