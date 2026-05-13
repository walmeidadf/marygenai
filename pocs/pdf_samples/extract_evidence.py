"""Run POC 6b evidence extraction and schema normalization.

This runner uses text artifacts already saved by POC 6. It compares a heuristic
baseline with optional LLM providers, then normalizes all candidates through
strict Pydantic models. All normalized fields remain marked for human review.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
import typer
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from rich.console import Console
from rich.table import Table

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from marygenai.settings import get_settings
from pocs.pdf_samples.sample_full_text import (
    DEFAULT_MANIFEST_PATH,
    DEFAULT_NORMALIZED_SUBDIR,
    DEFAULT_PROCESSED_SUBDIR,
    FIELD_KEYWORDS,
    SampleItem,
    read_manifest,
    score_sentence,
    split_sentences,
)

DEFAULT_OUTPUT_SUBDIR = DEFAULT_NORMALIZED_SUBDIR
DEFAULT_SOURCE_RECORD_IDS = ["340", "164", "43"]
DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"
RATE_LIMIT_HEADERS = [
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
]

console = Console()
app = typer.Typer(help="Run POC 6b LLM evidence extraction and normalization.")


@app.callback()
def main() -> None:
    """Run POC 6b commands."""


class ExtractionProvider(StrEnum):
    HEURISTIC = "heuristic"
    OLLAMA = "ollama"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CandidateEvidenceSnippet(StrictModel):
    field_name: str
    candidate_value: str | None
    evidence_text: str
    source_section: str | None
    confidence: Literal["none", "low", "medium", "high"]
    needs_review: Literal[True] = True
    notes: list[str] = Field(default_factory=list)


class CandidateEvidenceExtraction(StrictModel):
    source_record_id: str
    title: str
    provider: str
    model: str | None
    extraction_stage: Literal["candidate_evidence"] = "candidate_evidence"
    candidates: list[CandidateEvidenceSnippet]
    errors: list[str] = Field(default_factory=list)


class NormalizedEvidenceField(StrictModel):
    field_name: str
    normalized_value: str | None
    evidence_text: str | None
    source_section: str | None
    extraction_provider: str
    extraction_model: str | None
    confidence: Literal["none", "low", "medium", "high"]
    needs_review: Literal[True] = True
    review_state: Literal["needs_review"] = "needs_review"
    normalization_method: Literal["pydantic_strict_candidate_normalization"]
    notes: list[str] = Field(default_factory=list)


class NormalizedEvidenceRecord(StrictModel):
    source_record_id: str
    title: str
    sample_category: str
    text_path: str
    text_character_count: int
    providers_attempted: list[str]
    fields: list[NormalizedEvidenceField]
    errors: list[str] = Field(default_factory=list)
    provenance: dict[str, str]


class ProviderResult(StrictModel):
    provider: str
    model: str | None
    raw_response_path: str | None
    rate_limit_headers: dict[str, str] = Field(default_factory=dict)
    extraction: CandidateEvidenceExtraction | None = None
    errors: list[str] = Field(default_factory=list)


def value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def read_latest_text_path(processed_dir: Path, source_record_id: str) -> Path:
    paths = sorted(processed_dir.glob(f"*_{source_record_id}_text.txt"))
    if not paths:
        msg = f"No processed text found for source_record_id={source_record_id}"
        raise FileNotFoundError(msg)
    return paths[-1]


def text_to_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        heading_match = re.fullmatch(r"\[(.+)]", stripped)
        if heading_match:
            if current_heading and current_lines:
                sections.append((current_heading, " ".join(current_lines)))
            current_heading = heading_match.group(1)
            current_lines = []
        else:
            if current_heading is None:
                current_heading = "document"
            current_lines.append(stripped)
    if current_heading and current_lines:
        sections.append((current_heading, " ".join(current_lines)))
    return sections


def select_prompt_sections(
    sections: list[tuple[str, str]],
    target_fields: list[str],
    *,
    max_chars: int,
) -> str:
    scored: list[tuple[int, str, str]] = []
    keywords = [keyword for field in target_fields for keyword in FIELD_KEYWORDS[field]]
    for heading, text in sections:
        lowered = f"{heading} {text}".lower()
        score = sum(1 for keyword in keywords if keyword in lowered)
        score += 3 if any(term in lowered for term in ["abstract", "methods", "results"]) else 0
        score += 2 if re.search(r"\b\d+(\.\d+)?\s*(mg|mg/kg|week|weeks|day|days)\b", lowered) else 0
        if score:
            scored.append((score, heading, text))
    scored.sort(key=lambda item: item[0], reverse=True)

    chunks: list[str] = []
    used = 0
    for _, heading, text in scored:
        chunk = f"[{heading}]\n{text}"
        if used + len(chunk) > max_chars and chunks:
            continue
        chunks.append(chunk[: max(0, max_chars - used)])
        used += len(chunks[-1])
        if used >= max_chars:
            break
    return "\n\n".join(chunks)


def heuristic_candidates(
    item: SampleItem,
    sections: list[tuple[str, str]],
) -> CandidateEvidenceExtraction:
    candidates: list[CandidateEvidenceSnippet] = []
    for field_name in item.target_fields:
        field_candidates: list[tuple[int, str, str]] = []
        for heading, section_text in sections:
            for sentence in split_sentences(section_text):
                score = score_sentence(sentence, FIELD_KEYWORDS[field_name])
                if score:
                    field_candidates.append((score, heading, sentence))

        if not field_candidates:
            candidates.append(
                CandidateEvidenceSnippet(
                    field_name=field_name,
                    candidate_value=None,
                    evidence_text="",
                    source_section=None,
                    confidence="none",
                    notes=["No heuristic evidence candidate found."],
                )
            )
            continue

        field_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        for score, heading, evidence in field_candidates[:3]:
            candidates.append(
                CandidateEvidenceSnippet(
                    field_name=field_name,
                    candidate_value=evidence[:500],
                    evidence_text=evidence[:900],
                    source_section=heading,
                    confidence="medium" if score >= 3 else "low",
                    notes=["Heuristic candidate; human review required."],
                )
            )

    return CandidateEvidenceExtraction(
        source_record_id=item.source_record_id,
        title=item.title,
        provider=ExtractionProvider.HEURISTIC.value,
        model=None,
        candidates=candidates,
    )


def evidence_prompt(item: SampleItem, section_text: str) -> str:
    fields = ", ".join(item.target_fields)
    return (
        "You extract candidate evidence for a cannabinoid evidence knowledge base. "
        "Return JSON only, with this shape: "
        '{"candidates":[{"field_name":"dosage","candidate_value":"...",'
        '"evidence_text":"verbatim evidence sentence or short passage",'
        '"source_section":"Methods","confidence":"low|medium|high",'
        '"needs_review":true,"notes":["..."]}]}. '
        "Use only the provided article text. Do not infer beyond the text. "
        "Every candidate must have needs_review true. It is acceptable to omit a "
        "field when the evidence is not present. Do not provide medical advice. "
        f"Target fields: {fields}.\n\n"
        f"Title: {item.title}\n\n"
        f"Article text:\n{section_text}"
    )


def call_ollama(model: str, prompt: str) -> tuple[str, dict[str, str]]:
    url = value_or_none(os.getenv("OLLAMA_BASE_URL")) or "http://localhost:11434"
    with httpx.Client(timeout=180.0) as client:
        response = client.post(
            f"{url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return str(response.json().get("response", "")).strip(), {}


def call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    extra_headers: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    with httpx.Client(timeout=180.0) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        rate_headers = {
            header: value
            for header in RATE_LIMIT_HEADERS
            if (value := response.headers.get(header)) is not None
        }
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"]).strip(), rate_headers


def rate_headers_from_response(response: httpx.Response | None) -> dict[str, str]:
    if response is None:
        return {}
    return {
        header: value
        for header in RATE_LIMIT_HEADERS
        if (value := response.headers.get(header)) is not None
    }


def call_groq(model: str, prompt: str) -> tuple[str, dict[str, str]]:
    api_key = value_or_none(os.getenv("GROQ_API_KEY"))
    if not api_key:
        msg = "GROQ_API_KEY is required for groq extraction."
        raise RuntimeError(msg)
    return call_openai_compatible(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=model,
        prompt=prompt,
    )


def call_openrouter(model: str, prompt: str) -> tuple[str, dict[str, str]]:
    api_key = value_or_none(os.getenv("OPENROUTER_API_KEY"))
    if not api_key:
        msg = "OPENROUTER_API_KEY is required for openrouter extraction."
        raise RuntimeError(msg)
    return call_openai_compatible(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
        model=model,
        prompt=prompt,
        extra_headers={
            "HTTP-Referer": "https://github.com/marygenai/marygenai",
            "X-Title": "MaryGenAI POC",
        },
    )


def extract_json_object(raw_text: str) -> dict[str, Any]:
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        msg = "LLM JSON root must be an object."
        raise TypeError(msg)
    return payload


def parse_candidate_extraction(
    *,
    item: SampleItem,
    provider: ExtractionProvider,
    model: str | None,
    raw_text: str,
) -> CandidateEvidenceExtraction:
    payload = extract_json_object(raw_text)
    candidates_payload = payload.get("candidates", payload.get("fields", []))
    if not isinstance(candidates_payload, list):
        msg = "LLM JSON must include a candidates list."
        raise TypeError(msg)

    candidates: list[CandidateEvidenceSnippet] = []
    for candidate in candidates_payload:
        if not isinstance(candidate, dict):
            continue
        field_name = value_or_none(candidate.get("field_name") or candidate.get("field"))
        evidence_text = value_or_none(candidate.get("evidence_text") or candidate.get("evidence"))
        if field_name not in item.target_fields or not evidence_text:
            continue
        candidates.append(
            CandidateEvidenceSnippet(
                field_name=field_name,
                candidate_value=value_or_none(
                    candidate.get("candidate_value") or candidate.get("value")
                ),
                evidence_text=evidence_text[:1200],
                source_section=value_or_none(
                    candidate.get("source_section") or candidate.get("section")
                ),
                confidence=value_or_none(candidate.get("confidence")) or "low",
                needs_review=True,
                notes=[
                    str(note)
                    for note in candidate.get("notes", [])
                    if isinstance(candidate.get("notes", []), list)
                ],
            )
        )

    return CandidateEvidenceExtraction(
        source_record_id=item.source_record_id,
        title=item.title,
        provider=provider.value,
        model=model,
        candidates=candidates,
    )


def run_provider(
    *,
    item: SampleItem,
    provider: ExtractionProvider,
    model: str | None,
    prompt: str,
    output_dir: Path,
    run_id: str,
) -> ProviderResult:
    if provider == ExtractionProvider.HEURISTIC:
        msg = "Heuristic provider should be built from sections, not prompt."
        raise RuntimeError(msg)

    resolved_model = model
    if provider == ExtractionProvider.OLLAMA:
        resolved_model = model or DEFAULT_OLLAMA_MODEL
        call = call_ollama
    elif provider == ExtractionProvider.GROQ:
        resolved_model = model or DEFAULT_GROQ_MODEL
        call = call_groq
    elif provider == ExtractionProvider.OPENROUTER:
        resolved_model = model or DEFAULT_OPENROUTER_MODEL
        call = call_openrouter
    else:
        msg = f"Unsupported provider: {provider}"
        raise RuntimeError(msg)

    raw_path = output_dir / f"{run_id}_{item.source_record_id}_poc6b_{provider.value}_raw.json"
    try:
        raw_text, rate_headers = call(resolved_model, prompt)
        raw_path.write_text(raw_text + "\n", encoding="utf-8")
        extraction = parse_candidate_extraction(
            item=item,
            provider=provider,
            model=resolved_model,
            raw_text=raw_text,
        )
        return ProviderResult(
            provider=provider.value,
            model=resolved_model,
            raw_response_path=str(raw_path),
            rate_limit_headers=rate_headers,
            extraction=extraction,
        )
    except httpx.HTTPStatusError as error:
        return ProviderResult(
            provider=provider.value,
            model=resolved_model,
            raw_response_path=str(raw_path) if raw_path.exists() else None,
            rate_limit_headers=rate_headers_from_response(error.response),
            errors=[str(error)],
        )
    except (
        httpx.HTTPError,
        RuntimeError,
        TypeError,
        ValidationError,
        json.JSONDecodeError,
    ) as error:
        return ProviderResult(
            provider=provider.value,
            model=resolved_model,
            raw_response_path=str(raw_path) if raw_path.exists() else None,
            errors=[str(error)],
        )


def normalize_candidates(
    *,
    extraction: CandidateEvidenceExtraction,
    provider: str,
    model: str | None,
) -> list[NormalizedEvidenceField]:
    by_field: dict[str, CandidateEvidenceSnippet] = {}
    for candidate in extraction.candidates:
        if candidate.field_name in by_field and by_field[candidate.field_name].confidence == "high":
            continue
        if candidate.confidence == "none" and candidate.field_name in by_field:
            continue
        by_field[candidate.field_name] = candidate

    normalized: list[NormalizedEvidenceField] = []
    for candidate in by_field.values():
        value = candidate.candidate_value or candidate.evidence_text or None
        normalized.append(
            NormalizedEvidenceField(
                field_name=candidate.field_name,
                normalized_value=value[:700] if value else None,
                evidence_text=candidate.evidence_text[:1200] if candidate.evidence_text else None,
                source_section=candidate.source_section,
                extraction_provider=provider,
                extraction_model=model,
                confidence=candidate.confidence,
                needs_review=True,
                review_state="needs_review",
                normalization_method="pydantic_strict_candidate_normalization",
                notes=[
                    *candidate.notes,
                    "Normalized value is a candidate prefill, not reviewed truth.",
                ],
            )
        )
    return normalized


def build_record(
    *,
    item: SampleItem,
    text_path: Path,
    text: str,
    provider_results: list[ProviderResult],
    heuristic_extraction: CandidateEvidenceExtraction,
    run_id: str,
    created_at: str,
) -> NormalizedEvidenceRecord:
    fields: list[NormalizedEvidenceField] = []
    errors: list[str] = []
    providers_attempted = [ExtractionProvider.HEURISTIC.value]

    fields.extend(
        normalize_candidates(
            extraction=heuristic_extraction,
            provider=ExtractionProvider.HEURISTIC.value,
            model=None,
        )
    )
    for result in provider_results:
        providers_attempted.append(result.provider)
        errors.extend(f"{result.provider}:{error}" for error in result.errors)
        if result.extraction:
            fields.extend(
                normalize_candidates(
                    extraction=result.extraction,
                    provider=result.provider,
                    model=result.model,
                )
            )

    return NormalizedEvidenceRecord(
        source_record_id=item.source_record_id,
        title=item.title,
        sample_category=item.sample_category,
        text_path=str(text_path),
        text_character_count=len(text),
        providers_attempted=providers_attempted,
        fields=fields,
        errors=errors,
        provenance={
            "source": "pdf_samples_poc6b",
            "method": "candidate_evidence_then_pydantic_normalization",
            "run_id": run_id,
            "created_at": created_at,
        },
    )


def write_jsonl(path: Path, records: list[NormalizedEvidenceRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(record.model_dump_json() + "\n")


def build_summary(
    *,
    records: list[NormalizedEvidenceRecord],
    provider_results: list[ProviderResult],
    records_path: Path,
    summary_path: Path,
    run_id: str,
    created_at: str,
) -> dict[str, Any]:
    field_counts = Counter(field.field_name for record in records for field in record.fields)
    provider_counts = Counter(
        field.extraction_provider for record in records for field in record.fields
    )
    review_counts = Counter(field.review_state for record in records for field in record.fields)
    provider_errors = {
        f"{result.provider}:{result.model or 'default'}": result.errors
        for result in provider_results
        if result.errors
    }
    rate_limit_headers = {
        f"{result.provider}:{result.model or 'default'}:{index}": result.rate_limit_headers
        for index, result in enumerate(provider_results, start=1)
        if result.rate_limit_headers
    }
    return {
        "source": "pdf_samples_poc6b",
        "method": "candidate_evidence_then_pydantic_normalization",
        "run_id": run_id,
        "created_at": created_at,
        "records_path": str(records_path),
        "summary_path": str(summary_path),
        "total_records": len(records),
        "total_normalized_fields": sum(len(record.fields) for record in records),
        "field_counts": dict(field_counts.most_common()),
        "provider_counts": dict(provider_counts.most_common()),
        "review_state_counts": dict(review_counts.most_common()),
        "provider_errors": provider_errors,
        "rate_limit_headers": rate_limit_headers,
        "examples": [
            {
                "source_record_id": record.source_record_id,
                "providers_attempted": record.providers_attempted,
                "field_count": len(record.fields),
                "errors": record.errors[:3],
            }
            for record in records
        ],
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="POC 6b evidence extraction summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Run id", summary["run_id"])
    table.add_row("Records", str(summary["total_records"]))
    table.add_row("Normalized fields", str(summary["total_normalized_fields"]))
    for provider, count in summary["provider_counts"].items():
        table.add_row(f"provider:{provider}", str(count))
    table.add_row("Provider error groups", str(len(summary["provider_errors"])))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


@app.command()
def run(
    processed_dir: Annotated[
        Path | None,
        typer.Option("--processed-dir", help="Directory containing POC 6 extracted text files."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for normalized POC 6b outputs."),
    ] = None,
    manifest_path: Annotated[
        Path,
        typer.Option("--manifest-path", help="POC 6 sample manifest."),
    ] = DEFAULT_MANIFEST_PATH,
    source_record_id: Annotated[
        list[str] | None,
        typer.Option("--source-record-id", help="Source record IDs to process."),
    ] = None,
    provider: Annotated[
        list[ExtractionProvider] | None,
        typer.Option("--provider", help="Optional LLM provider to compare with heuristic."),
    ] = None,
    ollama_model: Annotated[
        str,
        typer.Option("--ollama-model", help="Ollama model name."),
    ] = DEFAULT_OLLAMA_MODEL,
    groq_model: Annotated[
        str,
        typer.Option("--groq-model", help="Groq model name."),
    ] = DEFAULT_GROQ_MODEL,
    openrouter_model: Annotated[
        str,
        typer.Option("--openrouter-model", help="OpenRouter model name."),
    ] = DEFAULT_OPENROUTER_MODEL,
    prompt_max_chars: Annotated[
        int,
        typer.Option("--prompt-max-chars", min=2000, help="Max selected text chars per LLM call."),
    ] = 9000,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0, help="Delay between remote/local LLM calls."),
    ] = 2.5,
) -> None:
    """Normalize POC 6 evidence candidates from saved text samples."""
    load_dotenv()

    settings = get_settings()
    resolved_processed_dir = processed_dir or settings.data_dir / DEFAULT_PROCESSED_SUBDIR
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    requested_ids = source_record_id or DEFAULT_SOURCE_RECORD_IDS
    manifest_items = {item.source_record_id: item for item in read_manifest(manifest_path)}
    missing_manifest_ids = [
        record_id for record_id in requested_ids if record_id not in manifest_items
    ]
    if missing_manifest_ids:
        msg = f"IDs missing from manifest: {', '.join(missing_manifest_ids)}"
        raise typer.BadParameter(msg)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    created_at = datetime.now(UTC).isoformat()
    records_path = resolved_output_dir / f"{run_id}_poc6b_evidence_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_poc6b_evidence_summary.json"

    llm_providers = [item for item in provider or [] if item != ExtractionProvider.HEURISTIC]
    records: list[NormalizedEvidenceRecord] = []
    all_provider_results: list[ProviderResult] = []

    for record_id in requested_ids:
        item = manifest_items[record_id]
        text_path = read_latest_text_path(resolved_processed_dir, record_id)
        text = text_path.read_text(encoding="utf-8")
        sections = text_to_sections(text)
        heuristic_extraction = heuristic_candidates(item, sections)
        prompt_text = select_prompt_sections(
            sections,
            item.target_fields,
            max_chars=prompt_max_chars,
        )
        prompt = evidence_prompt(item, prompt_text)

        provider_results: list[ProviderResult] = []
        for llm_provider in llm_providers:
            model = {
                ExtractionProvider.OLLAMA: ollama_model,
                ExtractionProvider.GROQ: groq_model,
                ExtractionProvider.OPENROUTER: openrouter_model,
            }[llm_provider]
            result = run_provider(
                item=item,
                provider=llm_provider,
                model=model,
                prompt=prompt,
                output_dir=resolved_output_dir,
                run_id=run_id,
            )
            provider_results.append(result)
            all_provider_results.append(result)
            time.sleep(delay_seconds)

        records.append(
            build_record(
                item=item,
                text_path=text_path,
                text=text,
                provider_results=provider_results,
                heuristic_extraction=heuristic_extraction,
                run_id=run_id,
                created_at=created_at,
            )
        )

    write_jsonl(records_path, records)
    summary = build_summary(
        records=records,
        provider_results=all_provider_results,
        records_path=records_path,
        summary_path=summary_path,
        run_id=run_id,
        created_at=created_at,
    )
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


if __name__ == "__main__":
    app()
