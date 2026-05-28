"""Resolve DOI/PMID/PMCID for legacy identity-review items.

This POC focuses on records already queued for identity review. It extracts
publisher identifiers from known URLs, especially ScienceDirect PII values, then
tries public identifier services before writing auditable JSONL outputs.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from time import sleep
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.repository import connect_initialized_review_database
from marygenai.settings import get_settings

DEFAULT_OUTPUT_SUBDIR = Path("normalized/identity_identifier_resolution")
SCIENCEDIRECT_PII_RE = re.compile(
    r"sciencedirect\.com/science/article/(?:abs/)?pii/([^/?#]+)",
    re.I,
)
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)
CROSSREF_WORKS_URL = "https://api.crossref.org/works"
OPENALEX_WORKS_URL = "https://api.openalex.org/works"
ELSEVIER_ARTICLE_PII_URL = "https://api.elsevier.com/content/article/pii/{pii}"
NCBI_EUTILS_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

console = Console()
app = typer.Typer(help="Evaluate DOI/PMID/PMCID resolution for identity-review items.")


@app.callback()
def main() -> None:
    """Run identity identifier resolution commands."""


@dataclass(frozen=True)
class ReviewIdentifierInput:
    review_item_id: str
    document_id: str
    status: str
    priority_tier: str
    priority_score: float
    title: str | None
    publication_year: int | None
    canonical_url: str | None
    known_pmid: str | None
    known_pmcid: str | None
    known_doi: str | None
    legacy_study_id: str | None
    legacy_study_type: str | None
    identity_urls: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IdentifierCandidate:
    source: str
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    title: str | None = None
    publication_year: int | None = None
    score: float | None = None
    confidence: str = "low"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewIdentifierResolution:
    review_item_id: str
    document_id: str
    title: str | None
    publication_year: int | None
    canonical_url: str | None
    extracted_pii: str | None
    known: dict[str, str | None]
    resolved: dict[str, str | None]
    resolution_status: str
    recommended_review_decision: str
    candidates: list[IdentifierCandidate]
    errors: list[dict[str, str]]
    provenance: dict[str, Any]


class IdentifierResolutionClient:
    def __init__(
        self,
        *,
        ncbi_email: str | None,
        ncbi_api_key: str | None,
        elsevier_api_key: str | None,
        timeout_seconds: float,
    ) -> None:
        headers = {"User-Agent": "marygenai-identity-identifier-resolution/0.1"}
        self.client = httpx.Client(timeout=timeout_seconds, headers=headers)
        self.ncbi_email = ncbi_email
        self.ncbi_api_key = ncbi_api_key
        self.elsevier_api_key = elsevier_api_key

    def close(self) -> None:
        self.client.close()

    def crossref_by_pii(self, pii: str, *, title: str | None) -> list[IdentifierCandidate]:
        query = pii if not title else f"{pii} {title}"
        response = self.client.get(
            CROSSREF_WORKS_URL,
            params={"query.bibliographic": query, "rows": 5},
        )
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
        return [crossref_candidate(item, pii=pii, expected_title=title) for item in items]

    def openalex_by_pii(self, pii: str, *, title: str | None) -> list[IdentifierCandidate]:
        query = pii if not title else f"{pii} {title}"
        response = self.client.get(OPENALEX_WORKS_URL, params={"search": query, "per-page": 5})
        response.raise_for_status()
        return [
            openalex_candidate(item, pii=pii, expected_title=title)
            for item in response.json().get("results", [])
        ]

    def elsevier_by_pii(self, pii: str) -> list[IdentifierCandidate]:
        if not self.elsevier_api_key:
            return []
        response = self.client.get(
            ELSEVIER_ARTICLE_PII_URL.format(pii=pii),
            headers={"X-ELS-APIKey": self.elsevier_api_key, "Accept": "application/json"},
        )
        if response.status_code == 404:
            return []
        response.raise_for_status()
        coredata = response.json().get("full-text-retrieval-response", {}).get("coredata", {})
        doi = value_or_none(coredata.get("prism:doi"))
        return [
            IdentifierCandidate(
                source="elsevier",
                doi=normalize_doi(doi),
                title=value_or_none(coredata.get("dc:title")),
                confidence="high" if doi else "low",
                evidence={"pii": pii},
            )
        ]

    def pubmed_by_doi(self, doi: str) -> list[IdentifierCandidate]:
        pmids = self._pubmed_search(f"{doi}[AID]")
        return self._pubmed_fetch(pmids, query=f"{doi}[AID]")

    def pubmed_by_title(self, title: str) -> list[IdentifierCandidate]:
        pmids = self._pubmed_search(f'"{title}"[Title]', retmax=3)
        return self._pubmed_fetch(pmids, query=f'"{title}"[Title]')

    def _pubmed_search(self, query: str, *, retmax: int = 5) -> list[str]:
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": retmax,
            "tool": "marygenai_identity_identifier_resolution",
        }
        if self.ncbi_email:
            params["email"] = self.ncbi_email
        if self.ncbi_api_key:
            params["api_key"] = self.ncbi_api_key
        response = self.client.get(f"{NCBI_EUTILS_URL}/esearch.fcgi", params=params)
        response.raise_for_status()
        return response.json().get("esearchresult", {}).get("idlist", [])

    def _pubmed_fetch(self, pmids: list[str], *, query: str) -> list[IdentifierCandidate]:
        if not pmids:
            return []
        params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "tool": "marygenai_identity_identifier_resolution",
        }
        if self.ncbi_email:
            params["email"] = self.ncbi_email
        if self.ncbi_api_key:
            params["api_key"] = self.ncbi_api_key
        response = self.client.get(f"{NCBI_EUTILS_URL}/efetch.fcgi", params=params)
        response.raise_for_status()
        return pubmed_candidates_from_xml(response.text, query=query)


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    match = DOI_RE.search(value.strip())
    doi = match.group(0) if match else value.strip()
    return doi.rstrip(".,);]").lower()


def extract_sciencedirect_pii(url: str | None) -> str | None:
    if not url:
        return None
    match = SCIENCEDIRECT_PII_RE.search(url)
    if not match:
        return None
    return match.group(1).strip()


def title_similarity(left: str | None, right: str | None) -> float | None:
    if not left or not right:
        return None
    left_normalized = " ".join(left.lower().split())
    right_normalized = " ".join(right.lower().split())
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def candidate_confidence(
    *,
    source_score: float | None,
    pii_match: bool,
    title_score: float | None,
) -> str:
    if pii_match:
        return "high"
    if title_score is not None and title_score >= 0.92:
        return "medium"
    if source_score is not None and source_score >= 80:
        return "medium"
    return "low"


def crossref_candidate(
    item: dict[str, Any],
    *,
    pii: str,
    expected_title: str | None,
) -> IdentifierCandidate:
    title = first_value(item.get("title"))
    alternatives = [str(value) for value in item.get("alternative-id", [])]
    pii_match = pii in alternatives
    similarity = title_similarity(expected_title, title)
    score = float(item.get("score") or 0.0)
    return IdentifierCandidate(
        source="crossref",
        doi=normalize_doi(item.get("DOI")),
        title=title,
        publication_year=crossref_year(item),
        score=score,
        confidence=candidate_confidence(
            source_score=score,
            pii_match=pii_match,
            title_score=similarity,
        ),
        evidence={"pii": pii, "alternative_ids": alternatives, "title_similarity": similarity},
    )


def openalex_candidate(
    item: dict[str, Any],
    *,
    pii: str,
    expected_title: str | None,
) -> IdentifierCandidate:
    title = value_or_none(item.get("title") or item.get("display_name"))
    doi = normalize_doi(item.get("doi"))
    similarity = title_similarity(expected_title, title)
    return IdentifierCandidate(
        source="openalex",
        doi=doi,
        title=title,
        publication_year=item.get("publication_year"),
        score=item.get("relevance_score"),
        confidence=candidate_confidence(
            source_score=item.get("relevance_score"),
            pii_match=pii.lower() in json.dumps(item).lower(),
            title_score=similarity,
        ),
        evidence={"pii": pii, "title_similarity": similarity, "openalex_id": item.get("id")},
    )


def first_value(values: Any) -> str | None:
    if isinstance(values, list) and values:
        return value_or_none(values[0])
    return value_or_none(values)


def crossref_year(item: dict[str, Any]) -> int | None:
    parts = (
        item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or item.get("published", {}).get("date-parts")
    )
    if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
        year = parts[0][0]
        return int(year) if str(year).isdigit() else None
    return None


def pubmed_candidates_from_xml(xml_text: str, *, query: str) -> list[IdentifierCandidate]:
    from marygenai.pubmed_discovery.pubmed import parse_pubmed_xml

    records = parse_pubmed_xml(xml_text, query=query, fetched_at=datetime.now(UTC).isoformat())
    return [
        IdentifierCandidate(
            source="pubmed",
            doi=normalize_doi(record.doi),
            pmid=record.pmid,
            pmcid=record.pmcid,
            title=record.title,
            publication_year=int(record.publication_date[:4])
            if record.publication_date and record.publication_date[:4].isdigit()
            else None,
            confidence="high",
            evidence={"article_ids": record.article_ids, "query": query},
        )
        for record in records
    ]


def read_review_inputs(
    connection: sqlite3.Connection,
    *,
    queue_type: str,
    status: str,
    limit: int,
    require_sciencedirect_pii: bool,
) -> list[ReviewIdentifierInput]:
    status_clause = "" if status == "all" else "AND ri.status = ?"
    sciencedirect_pii_like_clause = """
        (
            lower(coalesce(d.canonical_url, '')) LIKE '%sciencedirect.com/science/article/pii/%'
            OR lower(coalesce(d.canonical_url, ''))
                LIKE '%sciencedirect.com/science/article/abs/pii/%'
            OR EXISTS (
                SELECT 1
                FROM document_identity AS di_filter
                WHERE di_filter.document_id = d.document_id
                AND di_filter.identifier_type IN ('canonical_url', 'url')
                AND (
                    lower(di_filter.identifier_value)
                        LIKE '%sciencedirect.com/science/article/pii/%'
                    OR lower(di_filter.identifier_value)
                        LIKE '%sciencedirect.com/science/article/abs/pii/%'
                )
            )
        )
    """
    pii_clause = (
        f"AND {sciencedirect_pii_like_clause}"
        if require_sciencedirect_pii
        else ""
    )
    params: list[Any] = [queue_type]
    if status != "all":
        params.append(status)
    params.append(limit)
    rows = connection.execute(
        f"""
        SELECT
            ri.review_item_id,
            ri.document_id,
            ri.status,
            ri.priority_tier,
            ri.priority_score,
            d.primary_title,
            d.publication_year,
            d.canonical_url,
            d.pmid,
            d.pmcid,
            d.doi,
            p.legacy_study_id,
            p.legacy_study_type
        FROM review_item AS ri
        JOIN document AS d ON d.document_id = ri.document_id
        JOIN publication AS p ON p.document_id = d.document_id
        WHERE ri.queue_type = ?
        {status_clause}
        {pii_clause}
        ORDER BY ri.priority_score DESC, ri.created_at ASC, ri.review_item_id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    inputs = []
    for row in rows:
        identity_urls = [
            identity_row["identifier_value"]
            for identity_row in connection.execute(
                """
                SELECT identifier_value
                FROM document_identity
                WHERE document_id = ?
                AND identifier_type IN ('canonical_url', 'url')
                ORDER BY confidence DESC
                """,
                (row["document_id"],),
            ).fetchall()
        ]
        inputs.append(
            ReviewIdentifierInput(
                review_item_id=row["review_item_id"],
                document_id=row["document_id"],
                status=row["status"],
                priority_tier=row["priority_tier"],
                priority_score=float(row["priority_score"]),
                title=row["primary_title"],
                publication_year=row["publication_year"],
                canonical_url=row["canonical_url"],
                known_pmid=row["pmid"],
                known_pmcid=row["pmcid"],
                known_doi=normalize_doi(row["doi"]),
                legacy_study_id=row["legacy_study_id"],
                legacy_study_type=row["legacy_study_type"],
                identity_urls=identity_urls,
            )
        )
    return inputs


def resolve_input(
    item: ReviewIdentifierInput,
    *,
    client: IdentifierResolutionClient,
    fetched_at: str,
    title_fallback: bool,
    request_delay_seconds: float,
) -> ReviewIdentifierResolution:
    urls = [item.canonical_url, *item.identity_urls]
    pii = next((value for url in urls if (value := extract_sciencedirect_pii(url))), None)
    candidates: list[IdentifierCandidate] = []
    errors: list[dict[str, str]] = []

    if item.known_doi:
        candidates.append(
            IdentifierCandidate(source="local", doi=item.known_doi, confidence="high")
        )
    if item.known_pmid or item.known_pmcid:
        candidates.append(
            IdentifierCandidate(
                source="local",
                pmid=item.known_pmid,
                pmcid=item.known_pmcid,
                confidence="high",
            )
        )

    if pii:
        for source_name, resolver in (
            ("crossref", lambda: client.crossref_by_pii(pii, title=item.title)),
            ("openalex", lambda: client.openalex_by_pii(pii, title=item.title)),
            ("elsevier", lambda: client.elsevier_by_pii(pii)),
        ):
            try:
                candidates.extend(resolver())
            except httpx.HTTPError as exc:
                errors.append({"source": source_name, "error": str(exc)})
            if request_delay_seconds:
                sleep(request_delay_seconds)

    doi = best_identifier(candidates, "doi")
    if doi:
        try:
            candidates.extend(client.pubmed_by_doi(doi))
        except httpx.HTTPError as exc:
            errors.append({"source": "pubmed", "error": str(exc)})
    elif title_fallback and item.title:
        try:
            candidates.extend(client.pubmed_by_title(item.title))
        except httpx.HTTPError as exc:
            errors.append({"source": "pubmed_title", "error": str(exc)})

    resolved = {
        "doi": best_identifier(candidates, "doi"),
        "pmid": best_identifier(candidates, "pmid"),
        "pmcid": best_identifier(candidates, "pmcid"),
    }
    status = resolution_status(item, resolved, pii=pii, candidates=candidates, errors=errors)
    return ReviewIdentifierResolution(
        review_item_id=item.review_item_id,
        document_id=item.document_id,
        title=item.title,
        publication_year=item.publication_year,
        canonical_url=item.canonical_url,
        extracted_pii=pii,
        known={"doi": item.known_doi, "pmid": item.known_pmid, "pmcid": item.known_pmcid},
        resolved=resolved,
        resolution_status=status,
        recommended_review_decision=recommended_review_decision(status),
        candidates=candidates,
        errors=errors,
        provenance={
            "source": "identity_identifier_resolution",
            "method": "science_direct_pii_to_doi_pubmed_identifier_resolution",
            "fetched_at": fetched_at,
            "title_fallback": title_fallback,
        },
    )


def best_identifier(candidates: list[IdentifierCandidate], field_name: str) -> str | None:
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    ranked = sorted(
        (
            candidate
            for candidate in candidates
            if getattr(candidate, field_name) and candidate.confidence in confidence_rank
        ),
        key=lambda candidate: (confidence_rank[candidate.confidence], candidate.score or 0),
        reverse=True,
    )
    return getattr(ranked[0], field_name) if ranked else None


def resolution_status(
    item: ReviewIdentifierInput,
    resolved: dict[str, str | None],
    *,
    pii: str | None,
    candidates: list[IdentifierCandidate],
    errors: list[dict[str, str]],
) -> str:
    if any(resolved.values()):
        if item.known_doi or item.known_pmid or item.known_pmcid:
            return "known_identifier_enriched"
        return "identifier_resolved"
    if candidates:
        return "candidate_without_identifier"
    if pii:
        return "pii_extracted_unresolved"
    if errors:
        return "lookup_error"
    return "no_pii_or_identifier"


def recommended_review_decision(status: str) -> str:
    if status in {"identifier_resolved", "known_identifier_enriched"}:
        return "candidate_corrected_identity"
    if status == "candidate_without_identifier":
        return "manual_compare_candidates"
    return "manual_review"


def write_jsonl(path: Path, records: list[ReviewIdentifierResolution]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def build_summary(
    records: list[ReviewIdentifierResolution],
    *,
    database_path: Path,
    records_path: Path,
    fetched_at: str,
) -> dict[str, Any]:
    status_counts = Counter(record.resolution_status for record in records)
    source_counts = Counter(
        candidate.source for record in records for candidate in record.candidates
    )
    sciencedirect_pii_count = sum(record.extracted_pii is not None for record in records)
    resolved_doi_count = sum(record.resolved["doi"] is not None for record in records)
    resolved_pmid_count = sum(record.resolved["pmid"] is not None for record in records)
    resolved_pmcid_count = sum(record.resolved["pmcid"] is not None for record in records)
    return {
        "source": "identity_identifier_resolution",
        "method": "science_direct_pii_to_doi_pubmed_identifier_resolution",
        "database_path": str(database_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "total_records": len(records),
        "records_with_sciencedirect_pii": sciencedirect_pii_count,
        "records_with_resolved_doi": resolved_doi_count,
        "records_with_resolved_pmid": resolved_pmid_count,
        "records_with_resolved_pmcid": resolved_pmcid_count,
        "resolution_status_counts": dict(status_counts.most_common()),
        "candidate_source_counts": dict(source_counts.most_common()),
        "error_count": sum(len(record.errors) for record in records),
        "examples": {
            "identifier_resolved": [
                asdict(record)
                for record in records
                if record.resolution_status == "identifier_resolved"
            ][:5],
            "pii_extracted_unresolved": [
                asdict(record)
                for record in records
                if record.resolution_status == "pii_extracted_unresolved"
            ][:5],
        },
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Identity identifier resolution")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("total", str(summary["total_records"]))
    table.add_row("science_direct_pii", str(summary["records_with_sciencedirect_pii"]))
    table.add_row("resolved_doi", str(summary["records_with_resolved_doi"]))
    table.add_row("resolved_pmid", str(summary["records_with_resolved_pmid"]))
    table.add_row("resolved_pmcid", str(summary["records_with_resolved_pmcid"]))
    for status, count in summary["resolution_status_counts"].items():
        table.add_row(status, str(count))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite review database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for identifier resolution outputs."),
    ] = None,
    queue_type: Annotated[
        str,
        typer.Option("--queue", help="Review queue to evaluate."),
    ] = "legacy_identity_review",
    status: Annotated[
        str,
        typer.Option("--status", help="Review item status to evaluate, or all."),
    ] = "open",
    limit: Annotated[int, typer.Option("--limit", help="Maximum review items to evaluate.")] = 50,
    title_fallback: Annotated[
        bool,
        typer.Option(
            "--title-fallback",
            help="Search PubMed by exact title when DOI is not found.",
        ),
    ] = False,
    require_sciencedirect_pii: Annotated[
        bool,
        typer.Option(
            "--require-sciencedirect-pii",
            help="Only evaluate review items with a ScienceDirect PII URL.",
        ),
    ] = False,
    request_delay_seconds: Annotated[
        float,
        typer.Option("--request-delay-seconds", help="Delay between external service calls."),
    ] = 0.1,
    timeout_seconds: Annotated[
        float,
        typer.Option("--timeout-seconds", help="HTTP timeout for external service calls."),
    ] = 30.0,
) -> None:
    """Resolve identifiers for review-queue items and write JSONL audit outputs."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    records_path = resolved_output_dir / f"{run_id}_identity_identifier_resolution_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_identity_identifier_resolution_summary.json"

    with connect_initialized_review_database(resolved_database_path) as connection:
        inputs = read_review_inputs(
            connection,
            queue_type=queue_type,
            status=status,
            limit=limit,
            require_sciencedirect_pii=require_sciencedirect_pii,
        )

    client = IdentifierResolutionClient(
        ncbi_email=os.getenv("MARYGENAI_NCBI_EMAIL"),
        ncbi_api_key=os.getenv("MARYGENAI_NCBI_API_KEY"),
        elsevier_api_key=os.getenv("MARYGENAI_ELSEVIER_API_KEY"),
        timeout_seconds=timeout_seconds,
    )
    try:
        records = [
            resolve_input(
                item,
                client=client,
                fetched_at=fetched_at,
                title_fallback=title_fallback,
                request_delay_seconds=request_delay_seconds,
            )
            for item in inputs
        ]
    finally:
        client.close()

    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        database_path=resolved_database_path,
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
