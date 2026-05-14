"""Run a small PubMed E-utilities validation batch.

The script intentionally stays inside the PubMed POC folder. It is meant to answer
source-validation questions before MaryGenAI commits to a production adapter.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from dotenv import load_dotenv
from lxml import etree
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_QUERY = (
    '("cannabis"[Title/Abstract] OR "cannabinoid"[Title/Abstract] '
    'OR "cannabidiol"[Title/Abstract] OR "THC"[Title/Abstract])'
)
QUERY_BATCHES = {
    "broad_cannabinoids": DEFAULT_QUERY,
    "cannabidiol_epilepsy": (
        '"cannabidiol"[Title/Abstract] AND '
        '("epilepsy"[Title/Abstract] OR "seizure"[Title/Abstract])'
    ),
    "thc_pain": (
        '("THC"[Title/Abstract] OR "tetrahydrocannabinol"[Title/Abstract]) '
        'AND "pain"[Title/Abstract]'
    ),
    "cannabis_adverse_effects": (
        '"cannabis"[Title/Abstract] AND '
        '("adverse effects"[Title/Abstract] OR "adverse events"[Title/Abstract])'
    ),
    "human_cannabinoids": (
        DEFAULT_QUERY + ' AND ("humans"[MeSH Terms] OR "clinical trial"[Publication Type])'
    ),
    "animal_cannabinoids": DEFAULT_QUERY + ' AND "animals"[MeSH Terms]',
    "in_vitro_cannabinoids": DEFAULT_QUERY + ' AND "in vitro"[Title/Abstract]',
    "review_cannabinoids": DEFAULT_QUERY + ' AND "review"[Publication Type]',
}

console = Console()
app = typer.Typer(help="Validate PubMed metadata availability for cannabinoid queries.")


@app.callback()
def main() -> None:
    """Run PubMed POC validation commands."""


@dataclass(frozen=True)
class PubMedRecord:
    pmid: str
    doi: str | None
    pmcid: str | None
    title: str | None
    abstract: str | None
    journal: str | None
    publication_date: str | None
    publication_status: str | None
    publication_types: list[str]
    mesh_terms: list[str]
    authors: list[str]
    languages: list[str]
    chemicals: list[str]
    keywords: list[str]
    article_ids: dict[str, str]
    provenance: dict[str, Any]

    @property
    def has_abstract(self) -> bool:
        return bool(self.abstract)

    @property
    def has_doi(self) -> bool:
        return bool(self.doi)

    @property
    def has_pmcid(self) -> bool:
        return bool(self.pmcid)

    @property
    def has_mesh_terms(self) -> bool:
        return bool(self.mesh_terms)


def text_or_none(node: etree._Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    value = " ".join(node.text.split())
    return value or None


def all_text(node: etree._Element | None) -> str | None:
    if node is None:
        return None
    value = " ".join(" ".join(node.itertext()).split())
    return value or None


def node_texts(root: etree._Element, xpath: str) -> list[str]:
    values: list[str] = []
    for node in root.xpath(xpath):
        value = all_text(node)
        if value:
            values.append(value)
    return values


def parse_author(author: etree._Element) -> str | None:
    collective_name = text_or_none(author.find("CollectiveName"))
    if collective_name:
        return collective_name

    last_name = text_or_none(author.find("LastName"))
    fore_name = text_or_none(author.find("ForeName"))
    initials = text_or_none(author.find("Initials"))

    if last_name and fore_name:
        return f"{fore_name} {last_name}"
    if last_name and initials:
        return f"{initials} {last_name}"
    return last_name


def parse_publication_date(article: etree._Element) -> str | None:
    article_date = article.find(".//ArticleDate")
    if article_date is not None:
        year = text_or_none(article_date.find("Year"))
        month = text_or_none(article_date.find("Month"))
        day = text_or_none(article_date.find("Day"))
        if year and month and day:
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None

    year = text_or_none(pub_date.find("Year"))
    medline_date = text_or_none(pub_date.find("MedlineDate"))
    if not year:
        return medline_date

    month = text_or_none(pub_date.find("Month"))
    day = text_or_none(pub_date.find("Day"))
    parts = [year]
    if month:
        parts.append(month)
    if day:
        parts.append(day)
    return "-".join(parts)


def parse_doi(article: etree._Element) -> str | None:
    for location_id in article.xpath(".//ELocationID[@EIdType='doi']"):
        value = text_or_none(location_id)
        if value:
            return value

    article_ids = parse_article_ids(article)
    doi = article_ids.get("doi")
    if doi:
        return doi

    return None


def parse_article_ids(article: etree._Element) -> dict[str, str]:
    article_ids: dict[str, str] = {}
    for article_id in article.xpath(".//ArticleIdList/ArticleId"):
        id_type = article_id.get("IdType")
        value = text_or_none(article_id)
        if id_type and value:
            article_ids[id_type] = value
    return article_ids


def parse_pubmed_article(article: etree._Element, *, query: str, fetched_at: str) -> PubMedRecord:
    pmid = text_or_none(article.find(".//MedlineCitation/PMID"))
    if not pmid:
        msg = "PubMed article is missing a PMID."
        raise ValueError(msg)

    title = all_text(article.find(".//Article/ArticleTitle"))
    abstract = "\n".join(node_texts(article, ".//Article/Abstract/AbstractText")) or None
    journal = all_text(article.find(".//Article/Journal/Title"))
    authors = [
        author_name
        for author in article.xpath(".//Article/AuthorList/Author")
        if (author_name := parse_author(author))
    ]
    article_ids = parse_article_ids(article)

    return PubMedRecord(
        pmid=pmid,
        doi=parse_doi(article),
        pmcid=article_ids.get("pmc"),
        title=title,
        abstract=abstract,
        journal=journal,
        publication_date=parse_publication_date(article),
        publication_status=all_text(article.find(".//PubmedData/PublicationStatus")),
        publication_types=node_texts(article, ".//Article/PublicationTypeList/PublicationType"),
        mesh_terms=node_texts(
            article,
            ".//MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName",
        ),
        authors=authors,
        languages=node_texts(article, ".//Article/Language"),
        chemicals=node_texts(article, ".//MedlineCitation/ChemicalList/Chemical/NameOfSubstance"),
        keywords=node_texts(article, ".//MedlineCitation/KeywordList/Keyword"),
        article_ids=article_ids,
        provenance={
            "source": "pubmed",
            "method": "ncbi_eutils_esearch_efetch",
            "query": query,
            "fetched_at": fetched_at,
        },
    )


def parse_pubmed_xml(xml_text: str, *, query: str, fetched_at: str) -> list[PubMedRecord]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)
    root = etree.fromstring(xml_text.encode("utf-8"), parser=parser)
    return [
        parse_pubmed_article(article, query=query, fetched_at=fetched_at)
        for article in root.xpath(".//PubmedArticle")
    ]


class PubMedClient:
    def __init__(
        self,
        *,
        api_key: str | None,
        email: str | None,
        tool: str = "marygenai_pubmed_poc",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.email = email
        self.tool = tool
        self.client = httpx.Client(base_url=EUTILS_BASE_URL, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params = {"tool": self.tool, **extra}
        if self.api_key:
            params["api_key"] = self.api_key
        if self.email:
            params["email"] = self.email
        return params

    def search(
        self,
        query: str,
        *,
        retmax: int,
        sort: str,
        datetype: str | None = None,
        mindate: str | None = None,
        maxdate: str | None = None,
    ) -> dict[str, Any]:
        params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": retmax,
            "sort": sort,
        }
        if datetype:
            params["datetype"] = datetype
        if mindate:
            params["mindate"] = mindate
        if maxdate:
            params["maxdate"] = maxdate

        response = self.client.get(
            "/esearch.fcgi",
            params=self.params(params),
        )
        response.raise_for_status()
        return response.json()["esearchresult"]

    def fetch_xml(self, pmids: list[str]) -> str:
        response = self.client.get(
            "/efetch.fcgi",
            params=self.params(
                {
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "retmode": "xml",
                }
            ),
        )
        response.raise_for_status()
        return response.text


def output_paths(
    raw_dir: Path,
    normalized_dir: Path,
    query_slug: str,
    *,
    run_id: str | None = None,
) -> dict[str, Path]:
    timestamp = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{timestamp}_{query_slug}"
    return {
        "search": raw_dir / f"{prefix}_esearch.json",
        "fetch": raw_dir / f"{prefix}_efetch.xml",
        "records": normalized_dir / f"{prefix}_records.jsonl",
        "summary": normalized_dir / f"{prefix}_summary.json",
    }


def slugify_query(query: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "_" for character in query)
    slug = "_".join(part for part in slug.split("_") if part)
    return slug[:80] or "pubmed_query"


def write_jsonl(path: Path, records: list[PubMedRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def build_summary(
    *,
    batch_name: str | None = None,
    query: str,
    search_result: dict[str, Any],
    records: list[PubMedRecord],
    api_key_present: bool,
    fetched_at: str,
) -> dict[str, Any]:
    total = len(records)
    count = int(search_result.get("count", 0))
    return {
        "source": "pubmed",
        "method": "ncbi_eutils_esearch_efetch",
        "batch_name": batch_name,
        "query": query,
        "fetched_at": fetched_at,
        "api_key_present": api_key_present,
        "pubmed_total_count": count,
        "records_fetched": total,
        "availability": {
            "doi": sum(record.has_doi for record in records),
            "pmcid": sum(record.has_pmcid for record in records),
            "abstract": sum(record.has_abstract for record in records),
            "mesh_terms": sum(record.has_mesh_terms for record in records),
            "chemicals": sum(bool(record.chemicals) for record in records),
            "keywords": sum(bool(record.keywords) for record in records),
            "publication_type": sum(bool(record.publication_types) for record in records),
            "publication_status": sum(bool(record.publication_status) for record in records),
            "authors": sum(bool(record.authors) for record in records),
            "journal": sum(bool(record.journal) for record in records),
            "publication_date": sum(bool(record.publication_date) for record in records),
        },
        "pmids": [record.pmid for record in records],
    }


def print_summary(paths: dict[str, Path], summary: dict[str, Any]) -> None:
    title = "PubMed validation summary"
    if summary.get("batch_name"):
        title = f"{title}: {summary['batch_name']}"
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("PubMed total count", str(summary["pubmed_total_count"]))
    table.add_row("Records fetched", str(summary["records_fetched"]))
    for field_name, count in summary["availability"].items():
        table.add_row(field_name, str(count))
    console.print(table)
    console.print({name: str(path) for name, path in paths.items()})


def resolve_output_dirs(
    raw_dir: Path | None,
    normalized_dir: Path | None,
) -> tuple[Path, Path]:
    settings = get_settings()
    resolved_raw_dir = raw_dir or settings.data_dir / "raw" / "pubmed"
    resolved_normalized_dir = normalized_dir or settings.data_dir / "normalized" / "pubmed"
    resolved_raw_dir.mkdir(parents=True, exist_ok=True)
    resolved_normalized_dir.mkdir(parents=True, exist_ok=True)
    return resolved_raw_dir, resolved_normalized_dir


def run_pubmed_query(
    *,
    client: PubMedClient,
    query: str,
    batch_name: str | None,
    retmax: int,
    sort: str,
    raw_dir: Path,
    normalized_dir: Path,
    api_key_present: bool,
    fetched_at: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    search_result = client.search(query, retmax=retmax, sort=sort)
    pmids = [str(pmid) for pmid in search_result.get("idlist", [])]
    delay_seconds = 0.11 if api_key_present else 0.34
    time.sleep(delay_seconds)
    xml_text = client.fetch_xml(pmids) if pmids else "<PubmedArticleSet />"

    query_slug = batch_name or slugify_query(query)
    paths = output_paths(raw_dir, normalized_dir, query_slug, run_id=run_id)
    paths["search"].write_text(
        json.dumps(search_result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths["fetch"].write_text(xml_text, encoding="utf-8")

    records = parse_pubmed_xml(xml_text, query=query, fetched_at=fetched_at)
    write_jsonl(paths["records"], records)

    summary = build_summary(
        batch_name=batch_name,
        query=query,
        search_result=search_result,
        records=records,
        api_key_present=api_key_present,
        fetched_at=fetched_at,
    )
    summary["raw_payloads"] = {
        "esearch": str(paths["search"]),
        "efetch": str(paths["fetch"]),
    }
    paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(paths, summary)
    return summary


def build_batch_summary(
    *,
    run_id: str,
    summaries: list[dict[str, Any]],
    retmax: int,
    sort: str,
    fetched_at: str,
) -> dict[str, Any]:
    availability_totals: dict[str, int] = {}
    for summary in summaries:
        for field_name, count in summary["availability"].items():
            availability_totals[field_name] = availability_totals.get(field_name, 0) + int(count)

    return {
        "source": "pubmed",
        "method": "ncbi_eutils_esearch_efetch_batch",
        "run_id": run_id,
        "fetched_at": fetched_at,
        "retmax_per_query": retmax,
        "sort": sort,
        "query_count": len(summaries),
        "records_fetched": sum(int(summary["records_fetched"]) for summary in summaries),
        "pubmed_total_count": sum(int(summary["pubmed_total_count"]) for summary in summaries),
        "availability": availability_totals,
        "queries": [
            {
                "batch_name": summary["batch_name"],
                "query": summary["query"],
                "pubmed_total_count": summary["pubmed_total_count"],
                "records_fetched": summary["records_fetched"],
                "availability": summary["availability"],
                "raw_payloads": summary["raw_payloads"],
            }
            for summary in summaries
        ],
    }


@app.command()
def run(
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="PubMed query to validate."),
    ] = DEFAULT_QUERY,
    retmax: Annotated[
        int,
        typer.Option("--retmax", min=1, max=200, help="Maximum PubMed records to fetch."),
    ] = 25,
    sort: Annotated[
        str,
        typer.Option("--sort", help="PubMed esearch sort order."),
    ] = "relevance",
    raw_dir: Annotated[
        Path | None,
        typer.Option("--raw-dir", help="Directory for immutable PubMed API payloads."),
    ] = None,
    normalized_dir: Annotated[
        Path | None,
        typer.Option("--normalized-dir", help="Directory for extracted PubMed records."),
    ] = None,
) -> None:
    """Fetch a small PubMed batch and report metadata availability."""
    load_dotenv()

    resolved_raw_dir, resolved_normalized_dir = resolve_output_dirs(raw_dir, normalized_dir)

    pubmed_api_key = os.getenv("PUBMED_API_KEY")
    pubmed_email = os.getenv("PUBMED_EMAIL")
    fetched_at = datetime.now(UTC).isoformat()

    client = PubMedClient(api_key=pubmed_api_key, email=pubmed_email)
    try:
        run_pubmed_query(
            client=client,
            query=query,
            batch_name=None,
            retmax=retmax,
            sort=sort,
            raw_dir=resolved_raw_dir,
            normalized_dir=resolved_normalized_dir,
            api_key_present=bool(pubmed_api_key),
            fetched_at=fetched_at,
        )
    finally:
        client.close()


@app.command()
def batch(
    query_name: Annotated[
        list[str] | None,
        typer.Option(
            "--query-name",
            "-n",
            help="Named query to run. Repeat to run a subset. Defaults to all POC 1 queries.",
        ),
    ] = None,
    retmax: Annotated[
        int,
        typer.Option("--retmax", min=1, max=200, help="Maximum PubMed records per query."),
    ] = 100,
    sort: Annotated[
        str,
        typer.Option("--sort", help="PubMed esearch sort order."),
    ] = "relevance",
    raw_dir: Annotated[
        Path | None,
        typer.Option("--raw-dir", help="Directory for immutable PubMed API payloads."),
    ] = None,
    normalized_dir: Annotated[
        Path | None,
        typer.Option("--normalized-dir", help="Directory for extracted PubMed records."),
    ] = None,
) -> None:
    """Run the expanded PubMed metadata POC query set."""
    load_dotenv()

    selected_names = query_name or list(QUERY_BATCHES)
    unknown_names = sorted(set(selected_names) - set(QUERY_BATCHES))
    if unknown_names:
        allowed = ", ".join(QUERY_BATCHES)
        names = ", ".join(unknown_names)
        msg = f"Unknown query name(s): {names}. Available names: {allowed}."
        raise typer.BadParameter(msg)

    resolved_raw_dir, resolved_normalized_dir = resolve_output_dirs(raw_dir, normalized_dir)

    pubmed_api_key = os.getenv("PUBMED_API_KEY")
    pubmed_email = os.getenv("PUBMED_EMAIL")
    fetched_at = datetime.now(UTC).isoformat()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    client = PubMedClient(api_key=pubmed_api_key, email=pubmed_email)
    summaries: list[dict[str, Any]] = []
    try:
        for name in selected_names:
            summaries.append(
                run_pubmed_query(
                    client=client,
                    query=QUERY_BATCHES[name],
                    batch_name=name,
                    retmax=retmax,
                    sort=sort,
                    raw_dir=resolved_raw_dir,
                    normalized_dir=resolved_normalized_dir,
                    api_key_present=bool(pubmed_api_key),
                    fetched_at=fetched_at,
                    run_id=run_id,
                )
            )
    finally:
        client.close()

    summary = build_batch_summary(
        run_id=run_id,
        summaries=summaries,
        retmax=retmax,
        sort=sort,
        fetched_at=fetched_at,
    )
    summary_path = resolved_normalized_dir / f"{run_id}_expanded_pubmed_batch_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    console.print({"batch_summary": str(summary_path)})


if __name__ == "__main__":
    app()
