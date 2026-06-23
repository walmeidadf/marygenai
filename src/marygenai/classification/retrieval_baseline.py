from __future__ import annotations

import html
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

BASELINE_VERSION = "retrieval_metadata_parser_baseline.v1"
MAX_ANALYSIS_CHARS = 60_000

SampleSizeScope = Literal[
    "participants",
    "patients",
    "animals",
    "included_studies",
    "records_or_charts",
    "cells_or_samples",
    "unknown",
]

COUNTRY_CONTEXT_TERMS = (
    "conducted in",
    "performed in",
    "recruited in",
    "recruited from",
    "participants from",
    "patients from",
    "study sites in",
    "centers in",
    "centres in",
    "nationwide",
    "multicenter",
    "multicentre",
)

COUNTRY_ALIASES = {
    "United States": ("united states", "u.s.", "usa"),
    "United Kingdom": ("united kingdom", "u.k.", "uk"),
    "South Korea": ("south korea", "republic of korea"),
    "Brazil": ("brazil",),
    "Canada": ("canada",),
    "Italy": ("italy",),
    "Sweden": ("sweden",),
    "Argentina": ("argentina",),
    "India": ("india",),
    "Netherlands": ("netherlands", "the netherlands"),
}

ROUTE_PATTERNS = {
    "oral": (
        r"\boral(?:ly)?\b",
        r"\bperoral(?:ly)?\b",
        r"\bby mouth\b",
        r"\bingest(?:ed|ion)\b",
    ),
    "inhaled": (
        r"\binhal(?:ed|ation)\b",
        r"\bvapori[sz]ed\b",
        r"\baerosoli[sz]ed\b",
    ),
    "injection": (
        r"\bintraperitoneal(?:ly)?\b",
        r"\bsubcutaneous(?:ly)?\b",
        r"\bintravenous(?:ly)?\b",
        r"\bintramuscular(?:ly)?\b",
        r"\binjection\b",
        r"\binjected\b",
    ),
    "topical": (r"\btopical(?:ly)?\b", r"\btransdermal(?:ly)?\b"),
    "sublingual_or_oromucosal": (r"\bsublingual(?:ly)?\b", r"\boromucosal\b"),
    "nasal": (r"\bintranasal(?:ly)?\b", r"\bnasal administration\b"),
    "rectal": (r"\brectal(?:ly)?\b",),
    "vaginal": (r"\bvaginal(?:ly)?\b",),
}

DESIGN_PATTERNS = {
    "systematic_review": (r"\bsystematic review\b",),
    "meta_analysis": (r"\bmeta-analysis\b", r"\bmeta analysis\b"),
    "randomized": (r"\brandomi[sz]ed\b",),
    "double_blind": (r"\bdouble[- ]blind(?:ed)?\b", r"\bdouble[- ]masked\b"),
    "placebo_controlled": (r"\bplacebo[- ]controlled\b",),
    "observational": (r"\bobservational study\b", r"\bobservational analysis\b"),
    "retrospective": (r"\bretrospective\b",),
    "prospective": (r"\bprospective\b",),
    "cross_sectional": (r"\bcross[- ]sectional\b",),
    "case_report_or_series": (r"\bcase report\b", r"\bcase series\b"),
    "in_vitro": (r"\bin vitro\b",),
    "in_silico": (r"\bin silico\b",),
}

SPECIES_PATTERNS = {
    "mouse": (r"\bmice\b", r"\bmouse\b", r"\bmurine\b"),
    "rat": (r"\brats?\b", r"\brodent\b"),
    "dog": (r"\bdogs?\b", r"\bcanine\b"),
    "human": (r"\bpatients?\b", r"\bparticipants?\b", r"\bsubjects?\b"),
    "cells": (r"\bcell lines?\b", r"\bcultured cells?\b", r"\bin vitro\b"),
}

SAMPLE_PATTERNS = (
    re.compile(
        r"\b(?P<count>\d{1,3}(?:,\d{3})*|\d{1,8})\s+"
        r"(?P<noun>patients?|participants?|subjects?|individuals?|volunteers?|"
        r"mice|rats?|animals?|articles|studies|records?|charts?|cells?|samples?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<noun>patients?|participants?|subjects?|individuals?|volunteers?|"
        r"mice|rats?|animals?|articles?|studies|records?|charts?|cells?|samples?)"
        r"\s*\(\s*n\s*=\s*(?P<count>\d{1,3}(?:,\d{3})*|\d{1,8})\s*\)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<noun>patients?|participants?|subjects?|mice|rats?|animals?|"
        r"articles?|studies|records?|charts?|cells?|samples?)"
        r"\s+(?:were|was)\s+(?:included|enrolled|randomi[sz]ed|analy[sz]ed)"
        r"\s*[:;,]?\s*(?:n\s*=\s*)?(?P<count>\d{1,3}(?:,\d{3})*|\d{1,8})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:total\s+)?sample\s+(?:size\s+of|consisted\s+of)\s+"
        r"(?P<count>\d{1,3}(?:,\d{3})*|\d{1,8})\b",
        re.IGNORECASE,
    ),
)

NUMBER_WORD_VALUES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
NUMBER_WORD_PATTERN = re.compile(
    r"\b(?P<count_word>"
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?"
    r"|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
    r"\s+(?P<noun>patients?|participants?|subjects?|individuals?|volunteers?|"
    r"mice|rats?|animals?|articles|studies|records?|charts?|cells?|samples?)\b",
    re.IGNORECASE,
)
ARM_SIZE_PATTERN = re.compile(r"\bn\s*=\s*(\d{1,5})\b", re.IGNORECASE)


class BaselineEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    source_text_path: str


class BaselineCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | int
    normalized_value: str | int
    extraction_method: str
    confidence: Literal["high", "medium", "low"]
    evidence: BaselineEvidence
    attributes: dict[str, Any] = Field(default_factory=dict)


class RetrievalMetadataBaselineRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_id: str
    baseline_run_id: str
    baseline_version: Literal["retrieval_metadata_parser_baseline.v1"] = BASELINE_VERSION
    document_id: str
    primary_title: str | None = None
    publication_year: int | None = None
    source_text_path: str
    source_text_sha256: str
    source_strategy: str | None = None
    classification_dataset_split: str
    cannabinoid_focus_group: str
    sample_size_candidates: list[BaselineCandidate] = Field(default_factory=list)
    route_candidates: list[BaselineCandidate] = Field(default_factory=list)
    country_candidates: list[BaselineCandidate] = Field(default_factory=list)
    population_candidates: list[BaselineCandidate] = Field(default_factory=list)
    species_candidates: list[BaselineCandidate] = Field(default_factory=list)
    study_design_signals: list[BaselineCandidate] = Field(default_factory=list)
    guardrail_comparison: dict[str, Any] = Field(default_factory=dict)
    fields_requiring_semantic_resolution: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def write_jsonl(path: Path, records: list[RetrievalMetadataBaselineRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                + "\n"
            )
    return path


def resolve_source_path(data_dir: Path, stored_path: str) -> Path:
    path = Path(stored_path)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == data_dir.name:
        return data_dir.parent / path
    return data_dir / path


def clean_source_text(path: Path, *, primary_title: str | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() in {".html", ".htm"}:
        text = re.sub(
            r"<(?:script|style)\b.*?</(?:script|style)>",
            " ",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if primary_title:
        title_index = text.lower().find(primary_title.lower())
        if title_index >= 0:
            text = text[title_index:]
    for marker in (" references ", " bibliography "):
        marker_index = text.lower().find(marker, 5_000)
        if marker_index >= 0:
            text = text[:marker_index]
            break
    return text[:MAX_ANALYSIS_CHARS]


def evidence_for_match(
    text: str,
    match: re.Match[str],
    *,
    source_text_path: str,
    context_chars: int = 120,
) -> BaselineEvidence:
    start = max(0, match.start() - context_chars)
    end = min(len(text), match.end() + context_chars)
    return BaselineEvidence(
        text=text[start:end],
        char_start=start,
        char_end=end,
        source_text_path=source_text_path,
    )


def sample_scope(noun: str) -> SampleSizeScope:
    normalized = noun.lower()
    if normalized.startswith("patient"):
        return "patients"
    if normalized.startswith(("participant", "subject", "individual", "volunteer")):
        return "participants"
    if normalized.startswith(("mice", "mouse", "rat", "animal")):
        return "animals"
    if normalized.startswith(("article", "stud")):
        return "included_studies"
    if normalized.startswith(("record", "chart")):
        return "records_or_charts"
    if normalized.startswith(("cell", "sample")):
        return "cells_or_samples"
    return "unknown"


def parse_number_word(value: str) -> int:
    parts = re.split(r"[- ]", value.lower())
    return sum(NUMBER_WORD_VALUES[part] for part in parts)


def extract_sample_sizes(text: str, *, source_text_path: str) -> list[BaselineCandidate]:
    candidates: dict[tuple[int, str], BaselineCandidate] = {}
    for pattern in SAMPLE_PATTERNS:
        for match in pattern.finditer(text):
            count = int(match.group("count").replace(",", ""))
            if count <= 0:
                continue
            if 1800 <= count <= 2035:
                continue
            noun = match.groupdict().get("noun") or "total_sample"
            scope = sample_scope(noun)
            key = (count, scope)
            candidates.setdefault(
                key,
                BaselineCandidate(
                    value=count,
                    normalized_value=count,
                    extraction_method="deterministic_source_regex",
                    confidence="high" if scope != "unknown" else "medium",
                    evidence=evidence_for_match(
                        text,
                        match,
                        source_text_path=source_text_path,
                    ),
                    attributes={"scope": scope, "matched_noun": noun},
                ),
            )
    for match in NUMBER_WORD_PATTERN.finditer(text):
        count = parse_number_word(match.group("count_word"))
        scope = sample_scope(match.group("noun"))
        candidates.setdefault(
            (count, scope),
            BaselineCandidate(
                value=count,
                normalized_value=count,
                extraction_method="deterministic_number_word_regex",
                confidence="high",
                evidence=evidence_for_match(
                    text,
                    match,
                    source_text_path=source_text_path,
                ),
                attributes={"scope": scope, "matched_noun": match.group("noun")},
            ),
        )
    for sentence_match in re.finditer(r"[^.!?]{0,250}\brandomi[sz]ed\b[^.!?]{0,350}", text):
        arm_sizes = [
            int(value) for value in ARM_SIZE_PATTERN.findall(sentence_match.group())
        ]
        if len(arm_sizes) < 2:
            continue
        total = sum(arm_sizes)
        candidates.setdefault(
            (total, "participants"),
            BaselineCandidate(
                value=total,
                normalized_value=total,
                extraction_method="deterministic_randomized_arm_sum",
                confidence="medium",
                evidence=BaselineEvidence(
                    text=sentence_match.group(),
                    char_start=sentence_match.start(),
                    char_end=sentence_match.end(),
                    source_text_path=source_text_path,
                ),
                attributes={"scope": "participants", "arm_sizes": arm_sizes},
            ),
        )
    return list(candidates.values())[:20]


def extract_pattern_candidates(
    text: str,
    *,
    source_text_path: str,
    patterns: dict[str, tuple[str, ...]],
    method: str,
) -> list[BaselineCandidate]:
    candidates = []
    for value, value_patterns in patterns.items():
        earliest: re.Match[str] | None = None
        for pattern in value_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match and (earliest is None or match.start() < earliest.start()):
                earliest = match
        if earliest is None:
            continue
        candidates.append(
            BaselineCandidate(
                value=value,
                normalized_value=value,
                extraction_method=method,
                confidence="high",
                evidence=evidence_for_match(
                    text,
                    earliest,
                    source_text_path=source_text_path,
                ),
            )
        )
    return candidates


def extract_population_and_species(
    text: str,
    *,
    source_text_path: str,
) -> tuple[list[BaselineCandidate], list[BaselineCandidate]]:
    species = extract_pattern_candidates(
        text,
        source_text_path=source_text_path,
        patterns=SPECIES_PATTERNS,
        method="deterministic_species_phrase",
    )
    species_values = {candidate.normalized_value for candidate in species}
    population = []
    mapping = (
        ("human", "human"),
        ("animals", "mouse"),
        ("animals", "rat"),
        ("animals", "dog"),
        ("cells", "cells"),
    )
    for population_value, species_value in mapping:
        if species_value not in species_values:
            continue
        species_candidate = next(
            candidate
            for candidate in species
            if candidate.normalized_value == species_value
        )
        if any(
            candidate.normalized_value == population_value for candidate in population
        ):
            continue
        population.append(
            BaselineCandidate(
                value=population_value,
                normalized_value=population_value,
                extraction_method="derived_from_species_phrase",
                confidence="medium",
                evidence=species_candidate.evidence,
                attributes={"derived_from": species_value},
            )
        )
    return population, species


def country_alias_patterns(country: str) -> tuple[str, ...]:
    aliases = COUNTRY_ALIASES.get(country, (country.lower(),))
    return tuple(rf"\b{re.escape(alias)}\b" for alias in aliases)


def extract_countries(
    text: str,
    *,
    source_text_path: str,
    reference_countries: list[str],
) -> list[BaselineCandidate]:
    candidates = []
    for country in reference_countries:
        matches = [
            match
            for pattern in country_alias_patterns(country)
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
        ]
        if not matches:
            continue
        context_match = next(
            (
                match
                for match in matches
                if any(
                    term
                    in text[max(0, match.start() - 160) : match.end() + 160].lower()
                    for term in COUNTRY_CONTEXT_TERMS
                )
            ),
            None,
        )
        selected = context_match or matches[0]
        candidates.append(
            BaselineCandidate(
                value=country,
                normalized_value=country,
                extraction_method="reference_candidate_source_validation",
                confidence="medium" if context_match else "low",
                evidence=evidence_for_match(
                    text,
                    selected,
                    source_text_path=source_text_path,
                ),
                attributes={
                    "support_scope": (
                        "study_context" if context_match else "source_mention_only"
                    )
                },
            )
        )
    return candidates


def normalized_guardrail_route(value: str) -> str:
    normalized = value.lower()
    if "oral" in normalized or "ingestion" in normalized:
        return "oral"
    if "inhal" in normalized:
        return "inhaled"
    if "inject" in normalized:
        return "injection"
    if "topical" in normalized:
        return "topical"
    if "sublingual" in normalized or "oromucosal" in normalized:
        return "sublingual_or_oromucosal"
    return normalized.replace(" ", "_")


def guardrail_comparison(
    *,
    sample_row: dict[str, Any],
    sample_sizes: list[BaselineCandidate],
    routes: list[BaselineCandidate],
    countries: list[BaselineCandidate],
) -> dict[str, Any]:
    guardrails = sample_row.get("legacy_reference_guardrails") or {}
    sample_size = guardrails.get("study_sample_size")
    expected_sample = int(sample_size) if str(sample_size or "").isdigit() else None
    extracted_sample_values = {
        candidate.normalized_value for candidate in sample_sizes
    }
    expected_routes = {
        normalized_guardrail_route(value)
        for value in guardrails.get("route_of_administration") or []
    }
    extracted_routes = {str(candidate.normalized_value) for candidate in routes}
    expected_countries = set(guardrails.get("study_locations") or [])
    supported_countries = {
        str(candidate.normalized_value)
        for candidate in countries
        if candidate.attributes.get("support_scope") == "study_context"
    }
    mentioned_countries = {str(candidate.normalized_value) for candidate in countries}
    return {
        "sample_size": {
            "reference_value": expected_sample,
            "candidate_values": sorted(extracted_sample_values),
            "reference_value_found": (
                expected_sample in extracted_sample_values
                if expected_sample is not None
                else None
            ),
        },
        "route": {
            "reference_values": sorted(expected_routes),
            "candidate_values": sorted(extracted_routes),
            "overlap": sorted(expected_routes & extracted_routes),
        },
        "country": {
            "reference_values": sorted(expected_countries),
            "source_mentions": sorted(mentioned_countries),
            "study_context_support": sorted(supported_countries),
        },
    }


def semantic_resolution_fields(
    *,
    sample_sizes: list[BaselineCandidate],
    countries: list[BaselineCandidate],
    population: list[BaselineCandidate],
    design: list[BaselineCandidate],
) -> list[str]:
    fields = ["medical_conditions", "pathologies_or_disease_families", "organ_systems"]
    if len(sample_sizes) != 1:
        fields.append("sample_size_and_scope")
    if not any(
        candidate.attributes.get("support_scope") == "study_context"
        for candidate in countries
    ):
        fields.append("study_countries")
    if len(population) != 1:
        fields.append("population_category")
    if len(design) != 1:
        fields.append("study_structure")
    fields.extend(
        [
            "cannabinoid_role",
            "outcome_domains",
            "overall_direction",
        ]
    )
    return fields


def build_baseline_record(
    sample_row: dict[str, Any],
    *,
    data_dir: Path,
    run_id: str,
) -> RetrievalMetadataBaselineRecord:
    stored_source_path = str(sample_row["source_text_path"])
    source_path = resolve_source_path(data_dir, stored_source_path)
    text = clean_source_text(
        source_path,
        primary_title=sample_row.get("primary_title"),
    )
    sample_sizes = extract_sample_sizes(text, source_text_path=stored_source_path)
    routes = extract_pattern_candidates(
        text,
        source_text_path=stored_source_path,
        patterns=ROUTE_PATTERNS,
        method="deterministic_route_phrase",
    )
    population, species = extract_population_and_species(
        text,
        source_text_path=stored_source_path,
    )
    design = extract_pattern_candidates(
        text,
        source_text_path=stored_source_path,
        patterns=DESIGN_PATTERNS,
        method="deterministic_design_phrase",
    )
    reference_countries = list(
        (sample_row.get("legacy_reference_guardrails") or {}).get("study_locations")
        or []
    )
    countries = extract_countries(
        text,
        source_text_path=stored_source_path,
        reference_countries=reference_countries,
    )
    comparison = guardrail_comparison(
        sample_row=sample_row,
        sample_sizes=sample_sizes,
        routes=routes,
        countries=countries,
    )
    return RetrievalMetadataBaselineRecord(
        baseline_id=f"retrieval_metadata_baseline:{run_id}:{sample_row['document_id']}",
        baseline_run_id=run_id,
        document_id=sample_row["document_id"],
        primary_title=sample_row.get("primary_title"),
        publication_year=sample_row.get("publication_year"),
        source_text_path=stored_source_path,
        source_text_sha256=file_sha256(source_path),
        source_strategy=sample_row.get("source_strategy"),
        classification_dataset_split=sample_row["classification_dataset_split"],
        cannabinoid_focus_group=sample_row["cannabinoid_focus_group"],
        sample_size_candidates=sample_sizes,
        route_candidates=routes,
        country_candidates=countries,
        population_candidates=population,
        species_candidates=species,
        study_design_signals=design,
        guardrail_comparison=comparison,
        fields_requiring_semantic_resolution=semantic_resolution_fields(
            sample_sizes=sample_sizes,
            countries=countries,
            population=population,
            design=design,
        ),
        provenance={
            "method": "retrieval_metadata_parser_baseline",
            "analysis_chars": len(text),
            "max_analysis_chars": MAX_ANALYSIS_CHARS,
            "does_not_call_llm": True,
            "does_not_mutate_sqlite": True,
            "legacy_is_guardrail_not_ground_truth": True,
            "review_boundary": "candidate_parser_evidence_not_reviewed_knowledge",
        },
    )


def run_retrieval_metadata_baseline(
    *,
    storage: LocalStorage,
    input_path: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    resolved_run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sample_rows = read_jsonl(input_path)
    records = [
        build_baseline_record(row, data_dir=storage.root, run_id=resolved_run_id)
        for row in sample_rows
    ]
    output_dir = storage.path("normalized/classification_evaluations")
    records_path = write_jsonl(
        output_dir / f"{resolved_run_id}_retrieval_metadata_parser_records.jsonl",
        records,
    )
    sample_reference_count = sum(
        record.guardrail_comparison["sample_size"]["reference_value"] is not None
        for record in records
    )
    sample_match_count = sum(
        record.guardrail_comparison["sample_size"]["reference_value_found"] is True
        for record in records
    )
    route_reference_count = sum(
        bool(record.guardrail_comparison["route"]["reference_values"])
        for record in records
    )
    route_overlap_count = sum(
        bool(record.guardrail_comparison["route"]["overlap"]) for record in records
    )
    report = {
        "baseline_version": BASELINE_VERSION,
        "run_id": resolved_run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "input_path": str(input_path),
        "records_path": str(records_path),
        "counts": {
            "input_records": len(sample_rows),
            "valid_baseline_records": len(records),
            "records_with_sample_size_candidates": sum(
                bool(record.sample_size_candidates) for record in records
            ),
            "records_with_route_candidates": sum(
                bool(record.route_candidates) for record in records
            ),
            "records_with_country_source_mentions": sum(
                bool(record.country_candidates) for record in records
            ),
            "records_with_country_study_context_support": sum(
                any(
                    candidate.attributes.get("support_scope") == "study_context"
                    for candidate in record.country_candidates
                )
                for record in records
            ),
            "records_with_population_candidates": sum(
                bool(record.population_candidates) for record in records
            ),
            "records_with_design_signals": sum(
                bool(record.study_design_signals) for record in records
            ),
        },
        "guardrail_comparison": {
            "sample_size_reference_records": sample_reference_count,
            "sample_size_reference_found": sample_match_count,
            "route_reference_records": route_reference_count,
            "route_reference_overlap": route_overlap_count,
        },
        "semantic_resolution_field_counts": dict(
            Counter(
                field
                for record in records
                for field in record.fields_requiring_semantic_resolution
            )
        ),
        "notes": [
            "No LLM was called.",
            "Source regex matches are candidate evidence, not reviewed field truth.",
            "Country extraction validates reference candidates against source text; "
            "affiliation-only mentions remain low-confidence.",
            "Multiple sample-size candidates require semantic scope resolution.",
            "No SQLite or reviewed knowledge was mutated.",
        ],
    }
    report_path = storage.write_json(
        Path("normalized/classification_evaluations")
        / f"{resolved_run_id}_retrieval_metadata_parser_report.json",
        report,
    )
    return {
        "run_id": resolved_run_id,
        "records_path": str(records_path),
        "report_path": str(report_path),
        "counts": report["counts"],
    }
