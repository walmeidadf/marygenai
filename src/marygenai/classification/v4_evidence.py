from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from marygenai.classification.retrieval_baseline import clean_source_text
from marygenai.classification.v4_models import V4EvidenceReference

EVIDENCE_LOCATOR_VERSION = "classification_v4_evidence_locator.v1"
MAX_EVIDENCE_PER_FIELD = 4
SENTENCE_PATTERN = re.compile(r"[^.!?]{20,700}[.!?]", re.DOTALL)
OUTCOME_TERMS = re.compile(
    r"\b("
    r"result(?:s|ed)?|conclusion(?:s)?|finding(?:s)?|outcome(?:s)?|"
    r"improv(?:e|ed|ement)|reduc(?:e|ed|tion)|increas(?:e|ed)|"
    r"associated with|no significant|did not|adverse event(?:s)?|"
    r"safety|efficacy|effective|effect(?:s)?|risk|prevalence"
    r")\b",
    re.IGNORECASE,
)
QUESTION_TERMS = re.compile(
    r"\b(objective|aim|purpose|we investigated|we evaluated|we examined)\b",
    re.IGNORECASE,
)
CANNABINOID_ALIASES = {
    "cannabidiol": ("cannabidiol", "cbd"),
    "tetrahydrocannabinol": (
        "tetrahydrocannabinol",
        "delta-9-thc",
        "delta 9 thc",
        "δ-9-tetrahydrocannabinol",
        "thc",
    ),
    "cannabis": ("cannabis", "marijuana"),
    "cannabinoid": ("cannabinoid", "cannabinoids"),
    "palmitoylethanolamide": ("palmitoylethanolamide", "pea"),
    "anandamide": ("anandamide", "aea"),
    "2-arachidonoylglycerol": ("2-arachidonoylglycerol", "2-ag"),
    "endocannabinoid": ("endocannabinoid", "endocannabinoids"),
}


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def label_aliases(label: str) -> list[str]:
    aliases = {normalized_text(label)}
    aliases.update(
        normalized_text(value)
        for value in re.findall(r"\(([^)]+)\)", label)
        if len(normalized_text(value)) >= 3
    )
    without_parentheses = normalized_text(re.sub(r"\([^)]*\)", " ", label))
    aliases.add(without_parentheses)
    aliases.add(normalized_text(label.replace(" - ", " ")))
    words = [word for word in re.split(r"[^A-Za-z0-9]+", label) if len(word) >= 5]
    if len(words) >= 2:
        aliases.add(" ".join(reversed(words[-2:])))
    return sorted((alias for alias in aliases if len(alias) >= 3), key=len, reverse=True)


def sentence_spans(text: str) -> list[tuple[int, int, str]]:
    return [
        (match.start(), match.end(), normalized_text(match.group()))
        for match in SENTENCE_PATTERN.finditer(text)
    ]


def evidence_reference(
    *,
    evidence_id: str,
    field_name: str,
    text: str,
    source_text_path: str,
    char_start: int,
    char_end: int,
    extraction_method: str,
) -> V4EvidenceReference:
    return V4EvidenceReference(
        evidence_id=evidence_id,
        field_name=field_name,
        text=normalized_text(text),
        source_text_path=source_text_path,
        char_start=char_start,
        char_end=char_end,
        extraction_method=extraction_method,
    )


def locate_label_evidence(
    text: str,
    *,
    labels: list[str],
    field_name: str,
    source_text_path: str,
) -> list[V4EvidenceReference]:
    located: list[V4EvidenceReference] = []
    seen_spans: set[tuple[int, int]] = set()
    sentences = sentence_spans(text)
    for label in labels:
        for alias in label_aliases(label):
            pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
            for start, end, sentence in sentences:
                if (start, end) in seen_spans or not pattern.search(sentence):
                    continue
                seen_spans.add((start, end))
                located.append(
                    evidence_reference(
                        evidence_id=f"{field_name}:locator:{len(located) + 1}",
                        field_name=field_name,
                        text=sentence,
                        source_text_path=source_text_path,
                        char_start=start,
                        char_end=end,
                        extraction_method="deterministic_label_evidence_locator",
                    )
                )
                break
            if len(located) >= MAX_EVIDENCE_PER_FIELD:
                return located
    return located


def cannabinoid_search_terms(labels: list[str]) -> list[str]:
    terms = set()
    for label in labels:
        terms.update(label_aliases(label))
    lowered = " ".join(labels).lower()
    for canonical, aliases in CANNABINOID_ALIASES.items():
        if canonical in lowered or any(alias in lowered for alias in aliases):
            terms.update(aliases)
    return sorted((term for term in terms if len(term) >= 3), key=len, reverse=True)


def locate_cannabinoid_evidence(
    text: str,
    *,
    labels: list[str],
    source_text_path: str,
) -> list[V4EvidenceReference]:
    terms = cannabinoid_search_terms(labels)
    if not terms:
        terms = ["cannabidiol", "cannabinoid", "cannabis", "tetrahydrocannabinol"]
    located: list[V4EvidenceReference] = []
    for start, end, sentence in sentence_spans(text):
        if not any(
            re.search(rf"\b{re.escape(term)}\b", sentence, re.IGNORECASE)
            for term in terms
        ):
            continue
        located.append(
            evidence_reference(
                evidence_id=f"cannabinoid_identity:locator:{len(located) + 1}",
                field_name="cannabinoid_identity",
                text=sentence,
                source_text_path=source_text_path,
                char_start=start,
                char_end=end,
                extraction_method="deterministic_cannabinoid_evidence_locator",
            )
        )
        if len(located) >= MAX_EVIDENCE_PER_FIELD:
            break
    return located


def locate_outcome_evidence(
    text: str,
    *,
    source_text_path: str,
) -> list[V4EvidenceReference]:
    candidates: list[tuple[int, int, str, int]] = []
    for start, end, sentence in sentence_spans(text):
        outcome_hits = len(OUTCOME_TERMS.findall(sentence))
        question_hits = len(QUESTION_TERMS.findall(sentence))
        if not outcome_hits and not question_hits:
            continue
        section_bonus = int(
            bool(re.search(r"\b(results?|conclusions?)\b", sentence, re.IGNORECASE))
        )
        candidates.append((start, end, sentence, outcome_hits + question_hits + section_bonus))
    candidates.sort(key=lambda item: (-item[3], item[0]))
    return [
        evidence_reference(
            evidence_id=f"outcomes_direction:locator:{index}",
            field_name="outcomes_direction",
            text=sentence,
            source_text_path=source_text_path,
            char_start=start,
            char_end=end,
            extraction_method="deterministic_outcome_evidence_locator",
        )
        for index, (start, end, sentence, _) in enumerate(
            candidates[:MAX_EVIDENCE_PER_FIELD], start=1
        )
    ]


def locate_title_evidence(
    *,
    title: str | None,
    source_text_path: str,
) -> list[V4EvidenceReference]:
    if not title:
        return []
    return [
        evidence_reference(
            evidence_id="document_title:locator:1",
            field_name="document_title",
            text=title,
            source_text_path=source_text_path,
            char_start=0,
            char_end=len(title),
            extraction_method="canonical_title_metadata",
        )
    ]


def locate_v4_evidence(
    *,
    sample: dict[str, Any],
    source_path: Path,
    stored_source_path: str,
) -> list[V4EvidenceReference]:
    text = clean_source_text(source_path, primary_title=sample.get("primary_title"))
    corpus = sample.get("corpus_metadata_candidates") or {}
    evidence = locate_title_evidence(
        title=sample.get("primary_title"),
        source_text_path=stored_source_path,
    )
    evidence.extend(
        locate_label_evidence(
            text,
            labels=corpus.get("medical_condition_labels") or [],
            field_name="clinical_topic",
            source_text_path=stored_source_path,
        )
    )
    evidence.extend(
        locate_label_evidence(
            text,
            labels=corpus.get("organ_system_labels") or [],
            field_name="anatomy_organ_system",
            source_text_path=stored_source_path,
        )
    )
    evidence.extend(
        locate_cannabinoid_evidence(
            text,
            labels=corpus.get("cannabinoid_labels") or [],
            source_text_path=stored_source_path,
        )
    )
    evidence.extend(
        locate_outcome_evidence(text, source_text_path=stored_source_path)
    )
    counts = Counter(item.evidence_id for item in evidence)
    duplicates = [evidence_id for evidence_id, count in counts.items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate evidence IDs: {', '.join(duplicates)}")
    return evidence
