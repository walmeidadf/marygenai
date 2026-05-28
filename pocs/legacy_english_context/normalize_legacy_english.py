"""Normalize the maintainer-local English legacy study export.

The English export is useful LLM context because it avoids translating curated
fields back from Portuguese. It is page-oriented, so this POC deduplicates by
strong identifiers or URL/title keys and aggregates repeated page rows.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import unquote, urlparse

import typer
from rich.console import Console
from rich.table import Table

from marygenai.initial_load.files import normalize_title, stable_hash
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.repository import connect_initialized_review_database
from marygenai.settings import get_settings

DEFAULT_INPUT_PATH = Path("temp/legacy-en/studies_html_20240425_1030.csv")
DEFAULT_OUTPUT_SUBDIR = Path("normalized/legacy_english_context")
PMID_RE = re.compile(r"(?:pubmed(?:\.ncbi\.nlm\.nih\.gov)?/|/pubmed/)(\d+)", re.IGNORECASE)
PMCID_RE = re.compile(r"/pmc/articles/(PMC\d+)", re.IGNORECASE)
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)

LIST_FIELDS = {
    "Study Location(s)",
    "Cannabinoids Studied",
    "Phytocannabinoid Source",
    "Route of Administration",
    "Chemotype",
    "Sub-Ratio",
    "Receptors Studied",
    "Ligands Studied",
    "Terpenes Studied",
    "Study Dosing Objective",
    "Established Protocol",
    "Dosing Regimen",
    "Treatment Duration",
    "Clinical Relevance",
    "Cannabinoid Ratio",
    "Titration",
    "Dosage Form",
    "Adverse Events",
}
TEXT_FIELDS = {
    "Key Findings",
    "DOSING DETAILS",
    "Additional Notes",
    "Dosage",
    "Starting Dose",
    "Maximum Dose",
}
SCALAR_FIELDS = {"title", "Type of Study", "Study Result", "Year of Pub", "Study Sample Size"}

console = Console()
app = typer.Typer(help="Normalize English legacy context for LLM triage.")


@dataclass(frozen=True)
class LegacyEnglishDocumentMatch:
    document_id: str
    match_type: str
    review_state: str


@dataclass(frozen=True)
class LegacyEnglishContextRecord:
    context_id: str
    dedupe_key: str
    source_row_count: int
    source_filenames: list[str]
    title: str | None
    normalized_title: str | None
    link_to_study: str | None
    canonical_url: str | None
    host: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    publication_year: int | None
    type_of_study: str | None
    study_result: str | None
    study_sample_size: str | None
    key_findings: list[str]
    list_fields: dict[str, list[str]]
    text_fields: dict[str, list[str]]
    document_matches: list[LegacyEnglishDocumentMatch]
    provenance: dict[str, Any]


@app.callback()
def main() -> None:
    """Run legacy English context commands."""


def clean_value(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def normalize_host(host: str | None) -> str | None:
    if not host:
        return None
    normalized = host.lower().strip()
    return normalized[4:] if normalized.startswith("www.") else normalized


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


def extract_doi(url: str | None) -> str | None:
    if not url:
        return None
    decoded = unquote(url)
    parsed = urlparse(decoded)
    if normalize_host(parsed.netloc) in {"doi.org", "dx.doi.org"}:
        path = parsed.path.strip("/")
        if path.startswith("10."):
            return path.rstrip(").,;]").lower()
    match = DOI_RE.search(decoded)
    return match.group(0).rstrip(").,;]").lower() if match else None


def split_values(value: str | None) -> list[str]:
    if not value:
        return []
    parts = []
    for chunk in value.replace("\n", ",").split(","):
        stripped = chunk.strip()
        if stripped:
            parts.append(stripped)
    return parts


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    stripped = value.strip()
    return int(stripped) if stripped.isdigit() else None


def dedupe_key(row: dict[str, str]) -> str:
    url = clean_value(row.get("link_to_study"))
    pmid = extract_pmid(url)
    if pmid:
        return f"pmid:{pmid}"
    pmcid = extract_pmcid(url)
    if pmcid:
        return f"pmcid:{pmcid}"
    doi = extract_doi(url)
    if doi:
        return f"doi:{doi}"
    canonical_url = canonicalize_url(url)
    if canonical_url:
        return f"url:{canonical_url}"
    normalized = normalize_title(row.get("title"))
    year = clean_value(row.get("Year of Pub")) or "unknown"
    return f"title_year:{normalized or stable_hash(row)[:16]}:{year}"


def load_source_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [(index, row) for index, row in enumerate(reader, start=2)]


def normalize_records(
    source_rows: list[tuple[int, dict[str, str]]],
    *,
    input_path: Path,
    document_index: dict[str, list[LegacyEnglishDocumentMatch]] | None = None,
) -> list[LegacyEnglishContextRecord]:
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for index, row in source_rows:
        grouped[dedupe_key(row)].append((index, row))

    records = [
        build_context_record(
            key,
            rows,
            input_path=input_path,
            document_index=document_index or {},
        )
        for key, rows in grouped.items()
    ]
    return sorted(records, key=lambda record: (record.title or "", record.dedupe_key))


def build_context_record(
    key: str,
    source_rows: list[tuple[int, dict[str, str]]],
    *,
    input_path: Path,
    document_index: dict[str, list[LegacyEnglishDocumentMatch]],
) -> LegacyEnglishContextRecord:
    rows = [row for _, row in source_rows]
    representative = rows[0]
    title = most_common_value(rows, "title")
    canonical_url = canonicalize_url(most_common_value(rows, "link_to_study"))
    parsed = urlparse(canonical_url or "")
    host = normalize_host(parsed.netloc)
    pmid = extract_pmid(canonical_url)
    pmcid = extract_pmcid(canonical_url)
    doi = extract_doi(canonical_url)
    list_fields = {
        field: aggregate_list_field(rows, field)
        for field in sorted(LIST_FIELDS)
        if aggregate_list_field(rows, field)
    }
    text_fields = {
        field: aggregate_text_field(rows, field)
        for field in sorted(TEXT_FIELDS)
        if aggregate_text_field(rows, field)
    }
    matches = match_documents(
        key=key,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        canonical_url=canonical_url,
        normalized_title=normalize_title(title),
        publication_year=parse_year(most_common_value(rows, "Year of Pub")),
        document_index=document_index,
    )
    return LegacyEnglishContextRecord(
        context_id=f"legacy_english_context:{stable_hash({'dedupe_key': key})[:24]}",
        dedupe_key=key,
        source_row_count=len(rows),
        source_filenames=sorted(clean_value(row.get("filename")) or "" for row in rows)[:50],
        title=title,
        normalized_title=normalize_title(title),
        link_to_study=most_common_value(rows, "link_to_study"),
        canonical_url=canonical_url,
        host=host,
        pmid=pmid,
        pmcid=pmcid,
        doi=doi,
        publication_year=parse_year(most_common_value(rows, "Year of Pub")),
        type_of_study=most_common_value(rows, "Type of Study"),
        study_result=most_common_value(rows, "Study Result"),
        study_sample_size=most_common_value(rows, "Study Sample Size"),
        key_findings=aggregate_text_field(rows, "Key Findings"),
        list_fields=list_fields,
        text_fields=text_fields,
        document_matches=matches,
        provenance={
            "source": "legacy_english_context",
            "method": "deduplicate_english_legacy_html_export",
            "input_path": str(input_path),
            "source_row_numbers": [index for index, _ in source_rows[:50]],
            "representative_filename": clean_value(representative.get("filename")),
        },
    )


def most_common_value(rows: list[dict[str, str]], field: str) -> str | None:
    values = [value for row in rows if (value := clean_value(row.get(field)))]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def aggregate_list_field(rows: list[dict[str, str]], field: str) -> list[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(split_values(clean_value(row.get(field))))
    return [value for value, _ in counter.most_common()]


def aggregate_text_field(rows: list[dict[str, str]], field: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for row in rows:
        value = clean_value(row.get(field))
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values[:10]


def build_document_index(database_path: Path | None) -> dict[str, list[LegacyEnglishDocumentMatch]]:
    if database_path is None or not database_path.exists():
        return {}
    index: dict[str, list[LegacyEnglishDocumentMatch]] = defaultdict(list)
    with connect_initialized_review_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT
                d.document_id,
                d.canonical_url,
                d.pmid,
                d.pmcid,
                d.doi,
                d.review_state,
                p.normalized_title,
                d.publication_year
            FROM document AS d
            JOIN publication AS p ON p.document_id = d.document_id
            """
        ).fetchall()
    for row in rows:
        match = LegacyEnglishDocumentMatch(
            document_id=row["document_id"],
            match_type="unknown",
            review_state=row["review_state"],
        )
        add_index(index, f"pmid:{row['pmid']}", match, "pmid")
        add_index(index, f"pmcid:{row['pmcid']}", match, "pmcid")
        add_index(index, f"doi:{row['doi']}", match, "doi")
        add_index(index, f"url:{canonicalize_url(row['canonical_url'])}", match, "canonical_url")
        if row["normalized_title"]:
            add_index(
                index,
                f"title_year:{row['normalized_title']}:{row['publication_year'] or 'unknown'}",
                match,
                "normalized_title_year",
            )
    return dict(index)


def add_index(
    index: dict[str, list[LegacyEnglishDocumentMatch]],
    key: str,
    match: LegacyEnglishDocumentMatch,
    match_type: str,
) -> None:
    if key.endswith(":None") or key.endswith(":"):
        return
    index[key].append(
        LegacyEnglishDocumentMatch(
            document_id=match.document_id,
            match_type=match_type,
            review_state=match.review_state,
        )
    )


def match_documents(
    *,
    key: str,
    pmid: str | None,
    pmcid: str | None,
    doi: str | None,
    canonical_url: str | None,
    normalized_title: str | None,
    publication_year: int | None,
    document_index: dict[str, list[LegacyEnglishDocumentMatch]],
) -> list[LegacyEnglishDocumentMatch]:
    candidate_keys = [
        f"pmid:{pmid}" if pmid else None,
        f"pmcid:{pmcid}" if pmcid else None,
        f"doi:{doi}" if doi else None,
        f"url:{canonical_url}" if canonical_url else None,
        key,
        f"title_year:{normalized_title}:{publication_year or 'unknown'}"
        if normalized_title
        else None,
    ]
    matches: dict[tuple[str, str], LegacyEnglishDocumentMatch] = {}
    for candidate_key in candidate_keys:
        if not candidate_key:
            continue
        for match in document_index.get(candidate_key, []):
            matches[(match.document_id, match.match_type)] = match
    return sorted(matches.values(), key=lambda match: (match.document_id, match.match_type))


def write_jsonl(path: Path, records: list[LegacyEnglishContextRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def build_summary(
    records: list[LegacyEnglishContextRecord],
    *,
    source_row_count: int,
    input_path: Path,
    records_path: Path,
    fetched_at: str,
) -> dict[str, Any]:
    host_counts = Counter(record.host or "missing" for record in records)
    type_counts = Counter(record.type_of_study or "missing" for record in records)
    return {
        "source": "legacy_english_context",
        "method": "deduplicate_english_legacy_html_export",
        "input_path": str(input_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "source_rows": source_row_count,
        "deduplicated_records": len(records),
        "records_with_pmid": sum(record.pmid is not None for record in records),
        "records_with_pmcid": sum(record.pmcid is not None for record in records),
        "records_with_doi": sum(record.doi is not None for record in records),
        "records_with_document_match": sum(bool(record.document_matches) for record in records),
        "document_match_count": sum(len(record.document_matches) for record in records),
        "top_hosts": dict(host_counts.most_common(20)),
        "type_of_study_counts": dict(type_counts.most_common()),
        "duplicate_source_row_counts": dict(
            Counter(record.source_row_count for record in records).most_common(20)
        ),
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Legacy English context")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("source_rows", str(summary["source_rows"]))
    table.add_row("deduplicated", str(summary["deduplicated_records"]))
    table.add_row("with_pmid", str(summary["records_with_pmid"]))
    table.add_row("with_pmcid", str(summary["records_with_pmcid"]))
    table.add_row("with_doi", str(summary["records_with_doi"]))
    table.add_row("with_document_match", str(summary["records_with_document_match"]))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    input_path: Annotated[
        Path,
        typer.Option("--input-path", help="English legacy CSV export path."),
    ] = DEFAULT_INPUT_PATH,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for normalized outputs."),
    ] = None,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path for optional matching."),
    ] = None,
) -> None:
    """Deduplicate English legacy export and link it to local SQLite documents."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC).isoformat()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    records_path = resolved_output_dir / f"{run_id}_legacy_english_context_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_legacy_english_context_summary.json"

    source_rows = load_source_rows(input_path)
    document_index = build_document_index(resolved_database_path)
    records = normalize_records(source_rows, input_path=input_path, document_index=document_index)
    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        source_row_count=len(source_rows),
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
