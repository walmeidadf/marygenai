"""Run a small full-text and PDF extraction sample.

This POC intentionally fetches only the records listed in sample_manifest.json.
It prefers HTML over PDF, stores raw local samples under data/, and records
field-level evidence with human review state. LLM extraction is optional and is
used only as an exploratory layer.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from dotenv import load_dotenv
from lxml import etree, html
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

DEFAULT_MANIFEST_PATH = Path("pocs/pdf_samples/sample_manifest.json")
DEFAULT_RAW_SUBDIR = Path("raw/pdf_samples")
DEFAULT_PROCESSED_SUBDIR = Path("processed/pdf_samples")
DEFAULT_NORMALIZED_SUBDIR = Path("normalized/pdf_samples")

FIELD_KEYWORDS: dict[str, list[str]] = {
    "dosage": [
        "dose",
        "dosage",
        "mg",
        "mg/kg",
        "administered",
        "titrated",
        "cannabidiol",
        "thc",
    ],
    "treatment_duration": [
        "duration",
        "week",
        "weeks",
        "month",
        "months",
        "day",
        "days",
        "follow-up",
        "follow up",
        "treatment period",
    ],
    "adverse_events": [
        "adverse",
        "safety",
        "tolerability",
        "side effect",
        "side-effect",
        "toxicity",
        "rash",
        "withdrawal",
    ],
    "route_of_administration": [
        "oral",
        "sublingual",
        "intranasal",
        "inhaled",
        "vapor",
        "smok",
        "capsule",
        "oil",
        "spray",
    ],
    "protocol_intervention_details": [
        "intervention",
        "protocol",
        "administered",
        "treatment",
        "randomized",
        "randomised",
        "placebo",
        "assessment",
        "procedure",
    ],
    "arms_comparators_control_groups": [
        "arm",
        "arms",
        "comparator",
        "control",
        "placebo",
        "randomized",
        "randomised",
        "double-blind",
        "crossover",
    ],
    "study_design": [
        "study design",
        "randomized",
        "randomised",
        "controlled",
        "trial",
        "systematic review",
        "case report",
        "qualitative",
        "cohort",
        "cross-sectional",
    ],
    "population_details": [
        "participants",
        "patients",
        "children",
        "adults",
        "age",
        "male",
        "female",
        "population",
        "inclusion",
        "exclusion",
        "sample",
    ],
}

SECTION_HINTS = {
    "abstract",
    "methods",
    "materials",
    "results",
    "discussion",
    "case",
    "patients",
    "participants",
    "intervention",
    "safety",
    "adverse",
    "treatment",
}

MIN_USEFUL_TEXT_CHARS = 1_000

console = Console()
app = typer.Typer(help="Run the small full-text and PDF sample POC.")


@app.callback()
def main() -> None:
    """Run PDF sample commands."""


@dataclass(frozen=True)
class SampleItem:
    source_record_id: str
    sample_category: str
    title: str
    preferred_url: str
    fallback_pdf_url: str | None
    target_fields: list[str]
    selection_reason: str


@dataclass
class FieldExtraction:
    field_name: str
    value: str | None
    evidence_text: str | None
    source_section: str | None
    source_url: str | None
    extraction_method: str
    confidence: str
    review_state: str = "needs_review"
    notes: list[str] = field(default_factory=list)


@dataclass
class SampleExtractionRecord:
    source_record_id: str
    title: str
    sample_category: str
    attempted_urls: list[str]
    selected_source_url: str | None
    selected_source_format: str
    raw_path: str | None
    text_path: str | None
    supplemental_pdf_url: str | None
    supplemental_pdf_path: str | None
    text_character_count: int
    field_extractions: list[FieldExtraction]
    llm_provider: str | None
    llm_output_path: str | None
    errors: list[str]
    provenance: dict[str, Any]


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def read_manifest(path: Path) -> list[SampleItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [SampleItem(**item) for item in payload]


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    return slug[:80] or "sample"


def write_jsonl(path: Path, records: list[SampleExtractionRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def fetch_bytes(client: httpx.Client, url: str) -> tuple[bytes, str]:
    response = client.get(url, follow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    return response.content, content_type


def pmcid_from_url(url: str) -> str | None:
    match = re.search(r"\b(PMC\d+)\b", url, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def candidate_urls_for_item(item: SampleItem) -> list[str]:
    urls = [item.preferred_url]
    pmcid = pmcid_from_url(item.preferred_url) or pmcid_from_url(item.fallback_pdf_url or "")
    if pmcid and "europepmc.org" in item.preferred_url:
        urls.append(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")
        urls.append(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/")
    if item.fallback_pdf_url:
        urls.append(item.fallback_pdf_url)
    return dedupe_preserving_order(urls)


def looks_like_pdf(content: bytes, content_type: str, url: str) -> bool:
    return (
        content.startswith(b"%PDF")
        or "application/pdf" in content_type.lower()
        or url.lower().endswith(".pdf")
        or "pdf=render" in url.lower()
    )


def looks_like_xml(content: bytes, content_type: str, url: str) -> bool:
    stripped = content.lstrip()[:200].lower()
    return (
        "xml" in content_type.lower()
        or "fulltextxml" in url.lower()
        or stripped.startswith(b"<?xml")
        or b"<!doctype article" in stripped
    )


def html_to_sections(content: bytes) -> list[tuple[str, str]]:
    document = html.fromstring(content)
    for bad_node in document.xpath("//script|//style|//nav|//footer|//header"):
        parent = bad_node.getparent()
        if parent is not None:
            parent.remove(bad_node)

    sections: list[tuple[str, str]] = []
    current_heading = "document"
    for node in document.xpath("//h1|//h2|//h3|//h4|//p|//li|//td|//th"):
        tag = node.tag.lower()
        text = normalize_text(" ".join(node.itertext()))
        if not text:
            continue
        if tag in {"h1", "h2", "h3", "h4"}:
            current_heading = text[:160]
            continue
        if should_keep_section(current_heading, text):
            sections.append((current_heading, text))
    return sections


def xml_to_sections(content: bytes) -> list[tuple[str, str]]:
    parser = etree.XMLParser(recover=True, resolve_entities=False)
    document = etree.fromstring(content, parser=parser)
    sections: list[tuple[str, str]] = []

    for abstract in document.xpath("//*[local-name()='abstract']"):
        text = normalize_text(" ".join(abstract.itertext()))
        if text:
            sections.append(("Abstract", text))

    for section in document.xpath("//*[local-name()='sec']"):
        titles = section.xpath("./*[local-name()='title']")
        heading = normalize_text(" ".join(titles[0].itertext())) if titles else "Section"
        for paragraph in section.xpath(".//*[local-name()='p']"):
            text = normalize_text(" ".join(paragraph.itertext()))
            if should_keep_section(heading, text):
                sections.append((heading or "Section", text))

    return sections


def should_keep_section(heading: str, text: str) -> bool:
    combined = f"{heading} {text}".lower()
    if len(text) < 30:
        return False
    return any(hint in combined for hint in SECTION_HINTS) or any(
        keyword in combined for keywords in FIELD_KEYWORDS.values() for keyword in keywords
    )


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sections_to_text(sections: list[tuple[str, str]], *, max_chars: int = 180_000) -> str:
    chunks = [f"[{heading}]\n{text}" for heading, text in sections]
    return "\n\n".join(chunks)[:max_chars]


def split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]


def score_sentence(sentence: str, keywords: list[str]) -> int:
    lowered = sentence.lower()
    score = sum(1 for keyword in keywords if keyword in lowered)
    if re.search(r"\b\d+(\.\d+)?\s*(mg|mg/kg|mcg|g|ml|%)\b", lowered):
        score += 3
    if re.search(r"\b\d+\s*(day|days|week|weeks|month|months|year|years)\b", lowered):
        score += 2
    return score


def extract_field_from_text(
    *,
    field_name: str,
    sections: list[tuple[str, str]],
    source_url: str,
) -> FieldExtraction:
    keywords = FIELD_KEYWORDS[field_name]
    candidates: list[tuple[int, str, str]] = []
    for heading, text in sections:
        for sentence in split_sentences(text):
            score = score_sentence(sentence, keywords)
            if score:
                candidates.append((score, heading, sentence))

    if not candidates:
        return FieldExtraction(
            field_name=field_name,
            value=None,
            evidence_text=None,
            source_section=None,
            source_url=source_url,
            extraction_method="keyword_section_sample",
            confidence="none",
            notes=["No matching evidence found in sampled text."],
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    score, heading, evidence = candidates[0]
    confidence = "medium" if score >= 3 else "low"
    return FieldExtraction(
        field_name=field_name,
        value=evidence[:500],
        evidence_text=evidence[:900],
        source_section=heading,
        source_url=source_url,
        extraction_method="keyword_section_sample",
        confidence=confidence,
        notes=["Heuristic candidate only; human review is required."],
    )


def extract_fields(
    *,
    item: SampleItem,
    sections: list[tuple[str, str]],
    source_url: str,
) -> list[FieldExtraction]:
    return [
        extract_field_from_text(field_name=field_name, sections=sections, source_url=source_url)
        for field_name in item.target_fields
    ]


def llm_prompt(item: SampleItem, text: str) -> str:
    fields = ", ".join(item.target_fields)
    return (
        "Extract cannabinoid evidence fields from the article text. "
        "Return compact JSON only. Every field must include value, evidence_text, "
        "confidence, and needs_human_review. Always set needs_human_review to true. "
        "Do not provide medical advice. "
        f"Target fields: {fields}.\n\n"
        f"Title: {item.title}\n\n"
        f"Text:\n{text[:18000]}"
    )


def call_ollama(model: str, prompt: str) -> str:
    url = value_or_none(os.getenv("OLLAMA_BASE_URL")) or "http://localhost:11434"
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return str(response.json().get("response", "")).strip()


def call_groq(model: str, prompt: str) -> str:
    api_key = value_or_none(os.getenv("GROQ_API_KEY"))
    if not api_key:
        msg = "GROQ_API_KEY is required for groq extraction."
        raise RuntimeError(msg)
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip()


def run_llm_if_requested(
    *,
    provider: str | None,
    model: str | None,
    item: SampleItem,
    text: str,
    raw_dir: Path,
    run_id: str,
) -> str | None:
    if not provider:
        return None
    resolved_model = model or ("llama3.1:8b" if provider == "ollama" else "llama-3.1-8b-instant")
    prompt = llm_prompt(item, text)
    if provider == "ollama":
        result = call_ollama(resolved_model, prompt)
    elif provider == "groq":
        result = call_groq(resolved_model, prompt)
    else:
        msg = f"Unsupported LLM provider: {provider}"
        raise RuntimeError(msg)
    llm_path = raw_dir / f"{run_id}_{item.source_record_id}_llm_{provider}.json"
    llm_path.write_text(result + "\n", encoding="utf-8")
    return str(llm_path)


def process_item(
    *,
    client: httpx.Client,
    item: SampleItem,
    raw_dir: Path,
    processed_dir: Path,
    run_id: str,
    fetched_at: str,
    llm_provider: str | None,
    llm_model: str | None,
    download_pdfs: bool,
) -> SampleExtractionRecord:
    errors: list[str] = []
    attempted_urls: list[str] = []
    selected_source_url: str | None = None
    selected_source_format = "none"
    raw_path: Path | None = None
    text_path: Path | None = None
    supplemental_pdf_url: str | None = None
    supplemental_pdf_path: Path | None = None
    text = ""
    sections: list[tuple[str, str]] = []

    candidate_urls = candidate_urls_for_item(item)

    for url in candidate_urls:
        if url == item.fallback_pdf_url and not download_pdfs:
            errors.append(f"pdf_skipped:{url}")
            continue
        attempted_urls.append(url)
        try:
            content, content_type = fetch_bytes(client, url)
        except httpx.HTTPError as error:
            errors.append(f"fetch:{url}:{error}")
            continue

        if looks_like_pdf(content, content_type, url):
            suffix = ".pdf"
        elif looks_like_xml(content, content_type, url):
            suffix = ".xml"
        else:
            suffix = ".html"
        raw_filename = f"{run_id}_{item.source_record_id}_{safe_slug(item.sample_category)}{suffix}"
        raw_path = raw_dir / raw_filename
        raw_path.write_bytes(content)

        if suffix == ".pdf":
            selected_source_url = url
            selected_source_format = "pdf"
            errors.append("pdf_text_extraction_not_available_without_optional_pdf_parser")
            break

        sections = xml_to_sections(content) if suffix == ".xml" else html_to_sections(content)
        text = sections_to_text(sections)
        if len(text) < MIN_USEFUL_TEXT_CHARS:
            errors.append(f"insufficient_text:{url}:{len(text)}")
            continue
        text_path = processed_dir / f"{run_id}_{item.source_record_id}_text.txt"
        text_path.write_text(text + "\n", encoding="utf-8")
        selected_source_url = url
        selected_source_format = "xml" if suffix == ".xml" else "html"
        break

    if (
        download_pdfs
        and item.sample_category == "unpaywall_pdf"
        and item.fallback_pdf_url
        and selected_source_format != "pdf"
    ):
        attempted_urls.append(item.fallback_pdf_url)
        try:
            pdf_content, pdf_content_type = fetch_bytes(client, item.fallback_pdf_url)
            if looks_like_pdf(pdf_content, pdf_content_type, item.fallback_pdf_url):
                supplemental_pdf_url = item.fallback_pdf_url
                supplemental_pdf_path = raw_dir / (
                    f"{run_id}_{item.source_record_id}_{safe_slug(item.sample_category)}"
                    "_supplemental.pdf"
                )
                supplemental_pdf_path.write_bytes(pdf_content)
            else:
                errors.append(f"supplemental_pdf_not_pdf:{item.fallback_pdf_url}")
        except httpx.HTTPError as error:
            errors.append(f"supplemental_pdf_fetch:{item.fallback_pdf_url}:{error}")

    field_extractions = (
        extract_fields(item=item, sections=sections, source_url=selected_source_url or "")
        if sections and selected_source_url
        else [
            FieldExtraction(
                field_name=field_name,
                value=None,
                evidence_text=None,
                source_section=None,
                source_url=selected_source_url,
                extraction_method="not_extracted",
                confidence="none",
                notes=["No HTML text was available for heuristic extraction."],
            )
            for field_name in item.target_fields
        ]
    )

    llm_output_path = None
    if text and llm_provider:
        try:
            llm_path = run_llm_if_requested(
                provider=llm_provider,
                model=llm_model,
                item=item,
                text=text,
                raw_dir=raw_dir,
                run_id=run_id,
            )
            llm_output_path = llm_path
        except (httpx.HTTPError, RuntimeError) as error:
            errors.append(f"llm:{error}")

    return SampleExtractionRecord(
        source_record_id=item.source_record_id,
        title=item.title,
        sample_category=item.sample_category,
        attempted_urls=attempted_urls,
        selected_source_url=selected_source_url,
        selected_source_format=selected_source_format,
        raw_path=str(raw_path) if raw_path else None,
        text_path=str(text_path) if text_path else None,
        supplemental_pdf_url=supplemental_pdf_url,
        supplemental_pdf_path=str(supplemental_pdf_path) if supplemental_pdf_path else None,
        text_character_count=len(text),
        field_extractions=field_extractions,
        llm_provider=llm_provider,
        llm_output_path=llm_output_path,
        errors=errors,
        provenance={
            "source": "pdf_samples",
            "method": "small_html_first_full_text_sample",
            "manifest_path": str(DEFAULT_MANIFEST_PATH),
            "fetched_at": fetched_at,
        },
    )


def build_summary(
    records: list[SampleExtractionRecord],
    *,
    manifest_path: Path,
    records_path: Path,
    fetched_at: str,
    llm_provider: str | None,
    download_pdfs: bool,
) -> dict[str, Any]:
    field_counts = Counter(
        extraction.field_name
        for record in records
        for extraction in record.field_extractions
        if extraction.evidence_text
    )
    review_counts = Counter(
        extraction.review_state for record in records for extraction in record.field_extractions
    )
    format_counts = Counter(record.selected_source_format for record in records)
    category_counts = Counter(record.sample_category for record in records)

    return {
        "source": "pdf_samples",
        "method": "small_html_first_full_text_sample",
        "manifest_path": str(manifest_path),
        "records_path": str(records_path),
        "fetched_at": fetched_at,
        "total_records": len(records),
        "llm_provider": llm_provider,
        "download_pdfs": download_pdfs,
        "selected_source_format_counts": dict(format_counts.most_common()),
        "sample_category_counts": dict(category_counts.most_common()),
        "fields_with_evidence_counts": dict(field_counts.most_common()),
        "review_state_counts": dict(review_counts.most_common()),
        "records_with_errors": sum(bool(record.errors) for record in records),
        "supplemental_pdf_downloaded": sum(
            bool(record.supplemental_pdf_path) for record in records
        ),
        "examples": [
            {
                "source_record_id": record.source_record_id,
                "title": record.title,
                "format": record.selected_source_format,
                "text_character_count": record.text_character_count,
                "fields_with_evidence": [
                    extraction.field_name
                    for extraction in record.field_extractions
                    if extraction.evidence_text
                ],
                "errors": record.errors[:3],
            }
            for record in records[:10]
        ],
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="PDF sample POC summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total records", str(summary["total_records"]))
    for source_format, count in summary["selected_source_format_counts"].items():
        table.add_row(f"format:{source_format}", str(count))
    table.add_row("Supplemental PDFs", str(summary["supplemental_pdf_downloaded"]))
    table.add_row("Records with errors", str(summary["records_with_errors"]))
    table.add_row("LLM provider", str(summary["llm_provider"] or "disabled"))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    manifest_path: Annotated[
        Path,
        typer.Option("--manifest-path", help="Sample manifest JSON file."),
    ] = DEFAULT_MANIFEST_PATH,
    raw_dir: Annotated[
        Path | None,
        typer.Option("--raw-dir", help="Directory for raw fetched samples."),
    ] = None,
    processed_dir: Annotated[
        Path | None,
        typer.Option("--processed-dir", help="Directory for extracted text samples."),
    ] = None,
    normalized_dir: Annotated[
        Path | None,
        typer.Option("--normalized-dir", help="Directory for normalized extraction outputs."),
    ] = None,
    llm_provider: Annotated[
        str | None,
        typer.Option("--llm-provider", help="Optional LLM provider: ollama or groq."),
    ] = None,
    llm_model: Annotated[
        str | None,
        typer.Option("--llm-model", help="Optional LLM model name."),
    ] = None,
    llm_delay_seconds: Annotated[
        float,
        typer.Option("--llm-delay-seconds", min=0.0, help="Delay between LLM records."),
    ] = 0.2,
    download_pdfs: Annotated[
        bool,
        typer.Option(
            "--download-pdfs/--no-download-pdfs",
            help="Allow selected PDF fallback fetches.",
        ),
    ] = True,
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Only process the first N manifest records."),
    ] = None,
    source_record_id: Annotated[
        list[str] | None,
        typer.Option("--source-record-id", help="Only process selected source record IDs."),
    ] = None,
) -> None:
    """Fetch and extract the fixed 10-record full-text/PDF sample."""
    load_dotenv()

    settings = get_settings()
    resolved_raw_dir = raw_dir or settings.data_dir / DEFAULT_RAW_SUBDIR
    resolved_processed_dir = processed_dir or settings.data_dir / DEFAULT_PROCESSED_SUBDIR
    resolved_normalized_dir = normalized_dir or settings.data_dir / DEFAULT_NORMALIZED_SUBDIR
    resolved_raw_dir.mkdir(parents=True, exist_ok=True)
    resolved_processed_dir.mkdir(parents=True, exist_ok=True)
    resolved_normalized_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    records_path = resolved_normalized_dir / f"{run_id}_pdf_sample_records.jsonl"
    summary_path = resolved_normalized_dir / f"{run_id}_pdf_sample_summary.json"

    items = read_manifest(manifest_path)
    if source_record_id:
        selected_ids = set(source_record_id)
        items = [item for item in items if item.source_record_id in selected_ids]
    if limit:
        items = items[:limit]
    records: list[SampleExtractionRecord] = []
    with httpx.Client(timeout=60.0, headers={"User-Agent": "MaryGenAI POC/0.1"}) as client:
        for item in items:
            records.append(
                process_item(
                    client=client,
                    item=item,
                    raw_dir=resolved_raw_dir,
                    processed_dir=resolved_processed_dir,
                    run_id=run_id,
                    fetched_at=fetched_at,
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                    download_pdfs=download_pdfs,
                )
            )
            time.sleep(llm_delay_seconds if llm_provider else 0.2)

    write_jsonl(records_path, records)
    summary = build_summary(
        records,
        manifest_path=manifest_path,
        records_path=records_path,
        fetched_at=fetched_at,
        llm_provider=llm_provider,
        download_pdfs=download_pdfs,
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


if __name__ == "__main__":
    app()
