"""Run POC 6 evidence extraction, schema normalization, and review export.

This runner uses text artifacts already saved by POC 6. It compares a heuristic
baseline with optional LLM providers, normalizes all candidates through strict
Pydantic models, and writes review-ready field rows. All normalized fields remain
marked for human review.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
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
DEFAULT_ONTOLOGY_VERSION = "poc6"
EXTRACTOR_VERSION = "poc6c_review_export_v1"
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RATE_LIMIT_HEADERS = [
    "retry-after",
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
]

FIELD_SECTION_PROFILES: dict[str, dict[str, list[str]]] = {
    "dosage": {
        "preferred": ["methods", "intervention", "treatment", "procedure", "case"],
        "secondary": ["abstract", "results", "table"],
        "avoid": ["references", "discussion"],
    },
    "treatment_duration": {
        "preferred": ["methods", "intervention", "treatment", "follow-up", "case"],
        "secondary": ["abstract", "results"],
        "avoid": ["references"],
    },
    "adverse_events": {
        "preferred": ["safety", "adverse", "tolerability", "results"],
        "secondary": ["abstract", "case", "discussion"],
        "avoid": ["references", "methods"],
    },
    "route_of_administration": {
        "preferred": ["methods", "intervention", "treatment", "case"],
        "secondary": ["abstract", "results"],
        "avoid": ["references", "discussion"],
    },
    "protocol_intervention_details": {
        "preferred": ["methods", "intervention", "procedure", "protocol", "treatment"],
        "secondary": ["abstract", "results", "case"],
        "avoid": ["references"],
    },
    "arms_comparators_control_groups": {
        "preferred": ["methods", "random", "intervention", "study design", "procedure"],
        "secondary": ["abstract", "results", "table"],
        "avoid": ["references", "discussion"],
    },
    "study_design": {
        "preferred": ["abstract", "methods", "study design"],
        "secondary": ["introduction", "results"],
        "avoid": ["references", "discussion"],
    },
    "population_details": {
        "preferred": ["participants", "patients", "population", "methods", "case"],
        "secondary": ["abstract", "results", "table"],
        "avoid": ["references", "discussion"],
    },
}

console = Console()
app = typer.Typer(help="Run POC 6 evidence extraction, normalization, and review export.")


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


class ReviewExportRow(StrictModel):
    review_row_id: str
    source_record_id: str
    title: str
    sample_category: str
    field_name: str
    candidate_value: str | None
    evidence_text: str | None
    source_section: str | None
    provider: str
    model: str | None
    confidence: Literal["none", "low", "medium", "high"]
    ontology_version: str
    extractor_version: str
    needs_review: Literal[True] = True
    review_state: Literal["needs_review"] = "needs_review"
    reviewer_identity: str | None = None
    reviewed_field: str
    original_value: str | None
    reviewed_value: str | None = None
    review_timestamp: str | None = None
    review_notes: str | None = None
    source_text_path: str
    provenance_run_id: str
    created_at: str


class RetryEvent(StrictModel):
    attempt: int
    status_code: int | None
    wait_seconds: float
    reason: str
    rate_limit_headers: dict[str, str] = Field(default_factory=dict)


class ProviderResult(StrictModel):
    provider: str
    model: str | None
    raw_response_path: str | None
    rate_limit_headers: dict[str, str] = Field(default_factory=dict)
    retry_events: list[RetryEvent] = Field(default_factory=list)
    extraction: CandidateEvidenceExtraction | None = None
    errors: list[str] = Field(default_factory=list)


class ProviderCallError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        response: httpx.Response | None = None,
        retry_events: list[RetryEvent] | None = None,
    ) -> None:
        super().__init__(message)
        self.response = response
        self.retry_events = retry_events or []


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


def score_section_for_field(field_name: str, heading: str, text: str) -> int:
    lowered_heading = heading.lower()
    lowered = f"{heading} {text}".lower()
    score = sum(2 for keyword in FIELD_KEYWORDS[field_name] if keyword in lowered)

    profile = FIELD_SECTION_PROFILES.get(field_name, {})
    score += 6 * sum(1 for hint in profile.get("preferred", []) if hint in lowered_heading)
    score += 3 * sum(1 for hint in profile.get("secondary", []) if hint in lowered_heading)
    score -= 5 * sum(1 for hint in profile.get("avoid", []) if hint in lowered_heading)

    if field_name in {"dosage", "treatment_duration"}:
        has_numeric_measure = re.search(
            r"\b\d+(\.\d+)?\s*(mg|mg/kg|week|weeks|day|days)\b",
            lowered,
        )
        score += 4 if has_numeric_measure else 0
    if field_name == "arms_comparators_control_groups":
        has_arm_term = re.search(
            r"\b(placebo|randomi[sz]ed|double-blind|arm|crossover)\b",
            lowered,
        )
        score += 4 if has_arm_term else 0
    if field_name == "population_details":
        has_population_count = re.search(
            r"\b(n\s*=\s*\d+|\d+\s+(patients|participants|children|adults))\b",
            lowered,
        )
        score += 4 if has_population_count else 0
    return score


def select_prompt_sections(
    sections: list[tuple[str, str]],
    target_fields: list[str],
    *,
    max_chars: int,
) -> str:
    scored: dict[tuple[str, str], tuple[int, set[str]]] = {}
    for heading, text in sections:
        field_scores = {
            field_name: score_section_for_field(field_name, heading, text)
            for field_name in target_fields
        }
        matched_fields = {field_name for field_name, score in field_scores.items() if score > 0}
        if matched_fields:
            total_score = sum(score for score in field_scores.values() if score > 0)
            scored[(heading, text)] = (total_score, matched_fields)

    ranked = sorted(scored.items(), key=lambda item: item[1][0], reverse=True)

    chunks: list[str] = []
    used = 0
    for (heading, text), (_, matched_fields) in ranked:
        fields = ", ".join(sorted(matched_fields))
        chunk = f"[{heading}]\nTarget fields likely here: {fields}.\n{text}"
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
            section_score = score_section_for_field(field_name, heading, section_text)
            for sentence in split_sentences(section_text):
                score = score_sentence(sentence, FIELD_KEYWORDS[field_name])
                if score:
                    field_candidates.append((score + max(section_score, 0), heading, sentence))

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


def call_ollama(
    model: str,
    prompt: str,
    *,
    max_retries: int = 0,
    retry_base_seconds: float = 2.0,
) -> tuple[str, dict[str, str], list[RetryEvent]]:
    del max_retries, retry_base_seconds
    url = value_or_none(os.getenv("OLLAMA_BASE_URL")) or "http://localhost:11434"
    with httpx.Client(timeout=180.0) as client:
        response = client.post(
            f"{url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
        )
        response.raise_for_status()
        return str(response.json().get("response", "")).strip(), {}, []


def parse_wait_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.isdigit():
        return float(stripped)
    duration_match = re.fullmatch(
        r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?(?:(?P<seconds>\d+(?:\.\d+)?)s)?",
        stripped,
    )
    if duration_match and duration_match.group(0):
        minutes = float(duration_match.group("minutes") or 0)
        seconds = float(duration_match.group("seconds") or 0)
        return minutes * 60 + seconds
    try:
        parsed = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return max(0.0, (parsed - current).total_seconds())


def retry_wait_seconds(
    headers: dict[str, str],
    *,
    attempt: int,
    retry_base_seconds: float,
) -> tuple[float, str]:
    retry_after = parse_wait_seconds(headers.get("retry-after"))
    if retry_after is not None:
        return min(retry_after, 120.0), "retry-after"

    reset_values = [
        parse_wait_seconds(headers.get("x-ratelimit-reset-requests")),
        parse_wait_seconds(headers.get("x-ratelimit-reset-tokens")),
    ]
    reset_values = [value for value in reset_values if value is not None]
    if reset_values:
        return min(max(reset_values), 120.0), "rate-limit-reset"

    return min(retry_base_seconds * (2 ** max(attempt - 1, 0)), 60.0), "exponential-backoff"


def call_openai_compatible(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    extra_headers: dict[str, str] | None = None,
    max_retries: int = 2,
    retry_base_seconds: float = 2.0,
) -> tuple[str, dict[str, str], list[RetryEvent]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    retry_events: list[RetryEvent] = []
    with httpx.Client(timeout=180.0) as client:
        for attempt in range(1, max_retries + 2):
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
            rate_headers = rate_headers_from_response(response)
            if response.status_code not in RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return (
                    str(response.json()["choices"][0]["message"]["content"]).strip(),
                    rate_headers,
                    retry_events,
                )
            if attempt > max_retries:
                raise ProviderCallError(
                    "Provider returned retryable status "
                    f"{response.status_code} after {attempt} attempts.",
                    response=response,
                    retry_events=retry_events,
                )
            wait_seconds, reason = retry_wait_seconds(
                rate_headers,
                attempt=attempt,
                retry_base_seconds=retry_base_seconds,
            )
            retry_events.append(
                RetryEvent(
                    attempt=attempt,
                    status_code=response.status_code,
                    wait_seconds=wait_seconds,
                    reason=reason,
                    rate_limit_headers=rate_headers,
                )
            )
            time.sleep(wait_seconds)


def rate_headers_from_response(response: httpx.Response | None) -> dict[str, str]:
    if response is None:
        return {}
    return {
        header: value
        for header in RATE_LIMIT_HEADERS
        if (value := response.headers.get(header)) is not None
    }


def call_groq(
    model: str,
    prompt: str,
    *,
    max_retries: int = 2,
    retry_base_seconds: float = 2.0,
) -> tuple[str, dict[str, str], list[RetryEvent]]:
    api_key = value_or_none(os.getenv("GROQ_API_KEY"))
    if not api_key:
        msg = "GROQ_API_KEY is required for groq extraction."
        raise RuntimeError(msg)
    return call_openai_compatible(
        base_url="https://api.groq.com/openai/v1",
        api_key=api_key,
        model=model,
        prompt=prompt,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
    )


def call_openrouter(
    model: str,
    prompt: str,
    *,
    max_retries: int = 2,
    retry_base_seconds: float = 2.0,
) -> tuple[str, dict[str, str], list[RetryEvent]]:
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
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
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
    max_retries: int,
    retry_base_seconds: float,
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

    raw_path = output_dir / f"{run_id}_{item.source_record_id}_poc6c_{provider.value}_raw.json"
    try:
        raw_text, rate_headers, retry_events = call(
            resolved_model,
            prompt,
            max_retries=max_retries,
            retry_base_seconds=retry_base_seconds,
        )
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
            retry_events=retry_events,
            extraction=extraction,
        )
    except ProviderCallError as error:
        return ProviderResult(
            provider=provider.value,
            model=resolved_model,
            raw_response_path=str(raw_path) if raw_path.exists() else None,
            rate_limit_headers=rate_headers_from_response(error.response),
            retry_events=error.retry_events,
            errors=[str(error)],
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
            "source": "pdf_samples_poc6c",
            "method": "section_ranked_candidate_evidence_then_pydantic_normalization",
            "run_id": run_id,
            "created_at": created_at,
        },
    )


def write_jsonl(path: Path, records: list[NormalizedEvidenceRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(record.model_dump_json() + "\n")


def build_review_export_rows(
    *,
    records: list[NormalizedEvidenceRecord],
    ontology_version: str,
    extractor_version: str,
    created_at: str,
) -> list[ReviewExportRow]:
    rows: list[ReviewExportRow] = []
    for record in records:
        run_id = record.provenance["run_id"]
        for index, field in enumerate(record.fields, start=1):
            row_id_parts = [
                record.source_record_id,
                field.field_name,
                field.extraction_provider,
                field.extraction_model or "none",
                str(index),
            ]
            rows.append(
                ReviewExportRow(
                    review_row_id=":".join(row_id_parts),
                    source_record_id=record.source_record_id,
                    title=record.title,
                    sample_category=record.sample_category,
                    field_name=field.field_name,
                    candidate_value=field.normalized_value,
                    evidence_text=field.evidence_text,
                    source_section=field.source_section,
                    provider=field.extraction_provider,
                    model=field.extraction_model,
                    confidence=field.confidence,
                    ontology_version=ontology_version,
                    extractor_version=extractor_version,
                    needs_review=True,
                    review_state="needs_review",
                    reviewed_field=field.field_name,
                    original_value=field.normalized_value,
                    source_text_path=record.text_path,
                    provenance_run_id=run_id,
                    created_at=created_at,
                )
            )
    return rows


def write_review_jsonl(path: Path, rows: list[ReviewExportRow]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(row.model_dump_json() + "\n")


def build_summary(
    *,
    records: list[NormalizedEvidenceRecord],
    review_rows: list[ReviewExportRow],
    provider_results: list[ProviderResult],
    records_path: Path,
    review_export_path: Path,
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
    retry_events = {
        f"{result.provider}:{result.model or 'default'}:{index}": [
            event.model_dump() for event in result.retry_events
        ]
        for index, result in enumerate(provider_results, start=1)
        if result.retry_events
    }
    return {
        "source": "pdf_samples_poc6c",
        "method": "section_ranked_candidate_evidence_then_pydantic_normalization",
        "run_id": run_id,
        "created_at": created_at,
        "records_path": str(records_path),
        "review_export_path": str(review_export_path),
        "summary_path": str(summary_path),
        "total_records": len(records),
        "total_normalized_fields": sum(len(record.fields) for record in records),
        "total_review_rows": len(review_rows),
        "field_counts": dict(field_counts.most_common()),
        "provider_counts": dict(provider_counts.most_common()),
        "review_state_counts": dict(review_counts.most_common()),
        "provider_errors": provider_errors,
        "rate_limit_headers": rate_limit_headers,
        "retry_events": retry_events,
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
    table = Table(title="POC 6c evidence extraction summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Run id", summary["run_id"])
    table.add_row("Records", str(summary["total_records"]))
    table.add_row("Normalized fields", str(summary["total_normalized_fields"]))
    table.add_row("Review export rows", str(summary["total_review_rows"]))
    for provider, count in summary["provider_counts"].items():
        table.add_row(f"provider:{provider}", str(count))
    table.add_row("Provider error groups", str(len(summary["provider_errors"])))
    console.print(table)
    console.print(
        {
            "summary": summary["summary_path"],
            "records": summary["records_path"],
            "review_export": summary["review_export_path"],
        }
    )


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
    max_retries: Annotated[
        int,
        typer.Option("--max-retries", min=0, help="Retry count for retryable provider failures."),
    ] = 2,
    retry_base_seconds: Annotated[
        float,
        typer.Option("--retry-base-seconds", min=0.1, help="Fallback exponential backoff base."),
    ] = 2.0,
    ontology_version: Annotated[
        str,
        typer.Option("--ontology-version", help="Ontology version recorded in review export rows."),
    ] = DEFAULT_ONTOLOGY_VERSION,
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
    records_path = resolved_output_dir / f"{run_id}_poc6c_evidence_records.jsonl"
    review_export_path = resolved_output_dir / f"{run_id}_poc6c_review_export.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_poc6c_evidence_summary.json"

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
                max_retries=max_retries,
                retry_base_seconds=retry_base_seconds,
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
    review_rows = build_review_export_rows(
        records=records,
        ontology_version=ontology_version,
        extractor_version=EXTRACTOR_VERSION,
        created_at=created_at,
    )
    write_review_jsonl(review_export_path, review_rows)
    summary = build_summary(
        records=records,
        review_rows=review_rows,
        provider_results=all_provider_results,
        records_path=records_path,
        review_export_path=review_export_path,
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
