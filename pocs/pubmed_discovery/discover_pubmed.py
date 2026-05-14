"""Discover PubMed records outside the curated legacy dataset.

This POC keeps discovery separate from full-text access. It searches PubMed for
high-evidence cannabinoid records, compares results against the latest legacy
reconciliation output, and writes review-ready candidate files.
"""

from __future__ import annotations

import csv
import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings
from pocs.legacy_reconciliation.reconcile_legacy import canonicalize_url, normalize_title
from pocs.pubmed.validate_pubmed import PubMedClient, PubMedRecord, parse_pubmed_xml

DEFAULT_LEGACY_RECONCILIATION_DIR = Path("normalized/legacy_reconciliation")
DEFAULT_OUTPUT_SUBDIR = Path("normalized/pubmed_discovery")
MANIFEST_FILENAME = "_manifest.json"

CANNABINOID_QUERY = (
    '("cannabis"[Title/Abstract] OR "cannabinoid"[Title/Abstract] OR '
    '"cannabinoids"[Title/Abstract] OR "cannabidiol"[Title/Abstract] OR '
    '"CBD"[Title/Abstract] OR "THC"[Title/Abstract] OR '
    '"tetrahydrocannabinol"[Title/Abstract])'
)
STRONG_EVIDENCE_QUERY = (
    '("systematic review"[Publication Type] OR "meta-analysis"[Publication Type] OR '
    '"randomized controlled trial"[Publication Type] OR '
    '"controlled clinical trial"[Publication Type] '
    'OR randomized[Title/Abstract] OR randomised[Title/Abstract] '
    'OR controlled[Title/Abstract] OR "double-blind"[Title/Abstract] '
    'OR placebo[Title/Abstract])'
)
PRIORITY_AREAS = {
    "pain": '("pain"[Title/Abstract] OR "chronic pain"[Title/Abstract])',
    "epilepsy": '("epilepsy"[Title/Abstract] OR "seizure"[Title/Abstract])',
    "adverse_effects": (
        '("adverse effects"[Title/Abstract] OR "adverse events"[Title/Abstract] '
        'OR safety[Title/Abstract])'
    ),
    "dependence": '("dependence"[Title/Abstract] OR addiction[Title/Abstract])',
    "anxiety": '("anxiety"[Title/Abstract] OR anxiolytic[Title/Abstract])',
    "cancer": '("cancer"[Title/Abstract] OR oncology[Title/Abstract] OR tumor[Title/Abstract])',
    "inflammation": (
        '("inflammation"[Title/Abstract] OR inflammatory[Title/Abstract] '
        'OR anti-inflammatory[Title/Abstract])'
    ),
}
STUDY_DESIGN_RANKS = {
    "case_report": 10,
    "case_series": 20,
    "case_control": 30,
    "cohort_study": 40,
    "controlled_clinical_trial": 50,
    "randomized_controlled_trial": 60,
    "systematic_review": 70,
    "meta_analysis": 80,
}
STUDY_DESIGN_LABELS = {
    "case_report": "Case Report",
    "case_series": "Case Series",
    "case_control": "Case-Control",
    "cohort_study": "Cohort Study",
    "controlled_clinical_trial": "Controlled Clinical Trial",
    "randomized_controlled_trial": "Randomized Controlled Trial",
    "systematic_review": "Systematic Review",
    "meta_analysis": "Meta-Analysis",
}
QUERY_BATCHES = {
    "strong_evidence_all": f"{CANNABINOID_QUERY} AND {STRONG_EVIDENCE_QUERY}",
    **{
        f"strong_evidence_{area}": (
            f"{CANNABINOID_QUERY} AND {STRONG_EVIDENCE_QUERY} AND {area_query}"
        )
        for area, area_query in PRIORITY_AREAS.items()
    },
}

EXACT_MATCH_STATUSES = {"in_legacy_exact"}
LEGACY_MATCH_STATUSES = {
    "in_legacy_exact",
    "possible_legacy_match",
    "needs_manual_identity_review",
}

console = Console()
app = typer.Typer(help="Run legacy-anchored PubMed discovery.")


@app.callback()
def main() -> None:
    """Run PubMed discovery commands."""


@dataclass(frozen=True)
class LegacyIndexEntry:
    legacy_study_id: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    canonical_url: str | None
    normalized_title: str | None
    title_en: str | None
    study_type: str | None
    publication_year: str | None


@dataclass(frozen=True)
class LegacyMatch:
    match_status: str
    match_type: str | None
    match_confidence: float
    legacy_study_ids: list[str]
    review_reasons: list[str]


@dataclass(frozen=True)
class ScoredPubMedRecord:
    pmid: str
    doi: str | None
    pmcid: str | None
    canonical_url: str
    title: str | None
    normalized_title: str | None
    abstract: str | None
    journal: str | None
    publication_date: str | None
    publication_types: list[str]
    mesh_terms: list[str]
    chemicals: list[str]
    keywords: list[str]
    authors: list[str]
    languages: list[str]
    article_ids: dict[str, str]
    query_names: list[str]
    cannabinoid_focus: str
    study_design: str | None
    study_design_rank: int
    priority_score: int
    score_reasons: list[str]
    full_text_review_priority: str
    identity_status: str
    legacy_match_type: str | None
    legacy_match_confidence: float
    legacy_study_ids: list[str]
    review_reasons: list[str]
    provenance: dict[str, Any]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def find_latest_legacy_records_path(base_dir: Path) -> Path:
    paths = sorted(base_dir.glob("*_legacy_reconciliation_records.jsonl"))
    if not paths:
        msg = f"No legacy reconciliation records found in {base_dir}."
        raise FileNotFoundError(msg)
    return paths[-1]


def normalize_doi(doi: str | None) -> str | None:
    return doi.strip().rstrip(").,;]").lower() if doi else None


def normalize_pmcid(pmcid: str | None) -> str | None:
    return pmcid.strip().upper() if pmcid else None


def normalize_pmid(pmid: str | None) -> str | None:
    return pmid.strip() if pmid else None


def parse_year(value: str | None) -> int | None:
    if not value:
        return None
    year = value[:4]
    return int(year) if year.isdigit() else None


class LegacyIdentityIndex:
    def __init__(self, entries: list[LegacyIndexEntry]) -> None:
        self.entries = entries
        self.by_pmid = self._build_map("pmid")
        self.by_pmcid = self._build_map("pmcid")
        self.by_doi = self._build_map("doi")
        self.by_canonical_url = self._build_map("canonical_url")
        self.by_normalized_title = self._build_map("normalized_title")
        self.max_publication_year = max(
            (year for entry in entries if (year := parse_year(entry.publication_year))),
            default=None,
        )

    def _build_map(self, field_name: str) -> dict[str, list[LegacyIndexEntry]]:
        index: dict[str, list[LegacyIndexEntry]] = {}
        for entry in self.entries:
            value = getattr(entry, field_name)
            if value:
                index.setdefault(value, []).append(entry)
        return index


def build_legacy_index(records: list[dict[str, Any]]) -> LegacyIdentityIndex:
    entries = [
        LegacyIndexEntry(
            legacy_study_id=record.get("legacy_study_id"),
            pmid=normalize_pmid(record.get("pmid")),
            pmcid=normalize_pmcid(record.get("pmcid")),
            doi=normalize_doi(record.get("doi")),
            canonical_url=canonicalize_url(record.get("canonical_url")),
            normalized_title=record.get("normalized_title"),
            title_en=record.get("title_en"),
            study_type=record.get("study_type"),
            publication_year=record.get("publication_year"),
        )
        for record in records
    ]
    return LegacyIdentityIndex(entries)


def pubmed_canonical_url(pmid: str) -> str:
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}"


def legacy_ids(entries: list[LegacyIndexEntry]) -> list[str]:
    return sorted({entry.legacy_study_id for entry in entries if entry.legacy_study_id})


GENERIC_TITLE_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "analysis",
    "controlled",
    "effect",
    "effects",
    "efficacy",
    "meta",
    "placebo",
    "randomized",
    "review",
    "safety",
    "study",
    "systematic",
    "treatment",
    "trial",
}


def content_title_tokens(normalized_title: str) -> set[str]:
    return {
        token
        for token in normalized_title.split()
        if len(token) > 2 and token not in GENERIC_TITLE_TOKENS
    }


def title_content_overlap(left_title: str, right_title: str) -> float:
    left_tokens = content_title_tokens(left_title)
    right_tokens = content_title_tokens(right_title)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def best_title_similarity(
    normalized_title: str | None,
    index: LegacyIdentityIndex,
) -> tuple[float, float, list[LegacyIndexEntry]]:
    if not normalized_title:
        return 0.0, 0.0, []

    best_ratio = 0.0
    best_content_overlap = 0.0
    best_entries: list[LegacyIndexEntry] = []
    for legacy_title, entries in index.by_normalized_title.items():
        ratio = SequenceMatcher(None, normalized_title, legacy_title).ratio()
        content_overlap = title_content_overlap(normalized_title, legacy_title)
        if ratio > best_ratio:
            best_ratio = ratio
            best_content_overlap = content_overlap
            best_entries = entries
    return best_ratio, best_content_overlap, best_entries


def classify_against_legacy(record: PubMedRecord, index: LegacyIdentityIndex) -> LegacyMatch:
    normalized_record_title = normalize_title(record.title)
    exact_sources: list[tuple[str, list[LegacyIndexEntry]]] = []

    if record.pmid and record.pmid in index.by_pmid:
        exact_sources.append(("pmid", index.by_pmid[record.pmid]))
    pmcid = normalize_pmcid(record.pmcid)
    if pmcid and pmcid in index.by_pmcid:
        exact_sources.append(("pmcid", index.by_pmcid[pmcid]))
    doi = normalize_doi(record.doi)
    if doi and doi in index.by_doi:
        exact_sources.append(("doi", index.by_doi[doi]))
    canonical_url = pubmed_canonical_url(record.pmid)
    if canonical_url in index.by_canonical_url:
        exact_sources.append(("canonical_url", index.by_canonical_url[canonical_url]))
    if normalized_record_title and normalized_record_title in index.by_normalized_title:
        exact_sources.append(
            ("normalized_title", index.by_normalized_title[normalized_record_title])
        )

    if exact_sources:
        entries = [entry for _, source_entries in exact_sources for entry in source_entries]
        return LegacyMatch(
            match_status="in_legacy_exact",
            match_type="+".join(source for source, _ in exact_sources),
            match_confidence=1.0,
            legacy_study_ids=legacy_ids(entries),
            review_reasons=[],
        )

    record_year = publication_year(record)
    if (
        record_year
        and index.max_publication_year
        and record_year > index.max_publication_year + 1
    ):
        review_reasons = []
        if not record.doi and not record.pmcid:
            review_reasons.append("missing_doi_and_pmcid")
        return LegacyMatch(
            match_status="new_candidate",
            match_type=None,
            match_confidence=0.0,
            legacy_study_ids=[],
            review_reasons=review_reasons,
        )

    title_ratio, content_overlap, title_entries = best_title_similarity(
        normalized_record_title,
        index,
    )
    if title_ratio >= 0.96 and content_overlap >= 0.85:
        return LegacyMatch(
            match_status="possible_legacy_match",
            match_type="fuzzy_title",
            match_confidence=round(title_ratio, 4),
            legacy_study_ids=legacy_ids(title_entries),
            review_reasons=["high_title_similarity_without_identifier_match"],
        )
    if title_ratio >= 0.92 and content_overlap >= 0.75:
        return LegacyMatch(
            match_status="needs_manual_identity_review",
            match_type="weak_fuzzy_title",
            match_confidence=round(title_ratio, 4),
            legacy_study_ids=legacy_ids(title_entries),
            review_reasons=["weak_title_similarity_without_identifier_match"],
        )

    review_reasons = []
    if not record.doi and not record.pmcid:
        review_reasons.append("missing_doi_and_pmcid")
    return LegacyMatch(
        match_status="new_candidate",
        match_type=None,
        match_confidence=0.0,
        legacy_study_ids=[],
        review_reasons=review_reasons,
    )


def searchable_text(record: PubMedRecord) -> str:
    parts = [
        record.title,
        record.abstract,
        " ".join(record.publication_types),
        " ".join(record.mesh_terms),
        " ".join(record.keywords),
    ]
    return " ".join(part for part in parts if part).lower()


def cannabinoid_focus(record: PubMedRecord) -> str:
    terms = (
        "cannabis",
        "cannabinoid",
        "cannabinoids",
        "cannabidiol",
        "tetrahydrocannabinol",
        "marijuana",
        "thc",
        "cbd",
    )
    title = (record.title or "").lower()
    indexed_text = " ".join([*record.mesh_terms, *record.chemicals, *record.keywords]).lower()
    abstract = (record.abstract or "").lower()

    if any(term in title for term in terms) or any(term in indexed_text for term in terms):
        return "direct_title_or_indexed"
    if any(term in abstract for term in terms):
        return "abstract_only"
    return "no_cannabinoid_signal"


def infer_study_design(record: PubMedRecord) -> tuple[str | None, int, list[str]]:
    text = searchable_text(record)
    publication_types = {value.lower() for value in record.publication_types}
    reasons: list[str] = []

    if "meta-analysis" in publication_types or "meta analysis" in text:
        reasons.append("study_design:meta_analysis")
        return "meta_analysis", STUDY_DESIGN_RANKS["meta_analysis"], reasons
    if "systematic review" in publication_types or "systematic review" in text:
        reasons.append("study_design:systematic_review")
        return "systematic_review", STUDY_DESIGN_RANKS["systematic_review"], reasons
    if any("randomized controlled trial" in value for value in publication_types) or any(
        term in text for term in ("randomized", "randomised")
    ):
        reasons.append("study_design:randomized_controlled_trial")
        return (
            "randomized_controlled_trial",
            STUDY_DESIGN_RANKS["randomized_controlled_trial"],
            reasons,
        )
    if any("controlled clinical trial" in value for value in publication_types) or (
        "controlled clinical trial" in text
    ):
        reasons.append("study_design:controlled_clinical_trial")
        return (
            "controlled_clinical_trial",
            STUDY_DESIGN_RANKS["controlled_clinical_trial"],
            reasons,
        )
    if "cohort" in text:
        reasons.append("study_design:cohort_study")
        return "cohort_study", STUDY_DESIGN_RANKS["cohort_study"], reasons
    if "case-control" in text or "case control" in text:
        reasons.append("study_design:case_control")
        return "case_control", STUDY_DESIGN_RANKS["case_control"], reasons
    if "case series" in text:
        reasons.append("study_design:case_series")
        return "case_series", STUDY_DESIGN_RANKS["case_series"], reasons
    if "case reports" in publication_types or "case report" in text:
        reasons.append("study_design:case_report")
        return "case_report", STUDY_DESIGN_RANKS["case_report"], reasons

    reasons.append("study_design:unclassified")
    return None, 0, reasons


def review_design_bonus(record: PubMedRecord, study_design: str | None) -> tuple[int, list[str]]:
    if study_design not in {"systematic_review", "meta_analysis"}:
        return 0, []

    text = searchable_text(record)
    score = 0
    reasons: list[str] = []
    if any(term in text for term in ("randomized controlled trial", "randomised")):
        score += 10
        reasons.append("review_includes_randomized_trials")
    if "placebo" in text:
        score += 5
        reasons.append("review_includes_placebo_comparators")
    return score, reasons


def publication_year(record: PubMedRecord) -> int | None:
    if not record.publication_date:
        return None
    year = record.publication_date[:4]
    return int(year) if year.isdigit() else None


def score_pubmed_record(record: PubMedRecord) -> tuple[int, list[str]]:
    text = searchable_text(record)
    publication_types = {value.lower() for value in record.publication_types}
    focus = cannabinoid_focus(record)
    study_design, study_design_rank, design_reasons = infer_study_design(record)
    score = study_design_rank
    reasons: list[str] = [*design_reasons]

    if focus == "direct_title_or_indexed":
        score += 20
        reasons.append("direct_cannabinoid_focus")
    elif focus == "abstract_only":
        score -= 60
        reasons.append("abstract_only_cannabinoid_signal")
    else:
        score -= 100
        reasons.append("missing_cannabinoid_signal")

    review_bonus, review_reasons = review_design_bonus(record, study_design)
    score += review_bonus
    reasons.extend(review_reasons)
    if study_design not in {"systematic_review", "meta_analysis"}:
        if "double-blind" in text or "double blind" in text:
            score += 15
            reasons.append("double_blind")
        if "placebo" in text:
            score += 15
            reasons.append("placebo_controlled")

    if "humans" in text or any("clinical trial" in value for value in publication_types):
        score += 15
        reasons.append("human_evidence")
    if "animals" in text:
        score -= 8
        reasons.append("animal_signal")
    if "in vitro" in text:
        score -= 12
        reasons.append("in_vitro_signal")

    matched_areas = [
        area
        for area in PRIORITY_AREAS
        if area.replace("_", " ") in text or area.replace("_", "-") in text
    ]
    if matched_areas:
        score += 15
        reasons.append("priority_condition:" + ",".join(sorted(matched_areas)))

    if record.doi:
        score += 5
        reasons.append("has_doi")
    if record.pmcid:
        score += 5
        reasons.append("has_pmcid")
    if record.abstract:
        score += 8
        reasons.append("has_abstract")

    year = publication_year(record)
    if year and year >= 2020:
        score += 10
        reasons.append("recent_2020_or_later")
    elif year and year >= 2015:
        score += 6
        reasons.append("recent_2015_or_later")
    elif year and year >= 2010:
        score += 3
        reasons.append("recent_2010_or_later")

    return score, reasons


def classify_full_text_review_priority(
    record: PubMedRecord,
    *,
    priority_score: int,
    score_reasons: list[str],
) -> str:
    if priority_score < 70:
        return "low"
    high_value_reason = any(
        reason in score_reasons
        for reason in (
            "study_design:meta_analysis",
            "study_design:systematic_review",
            "study_design:randomized_controlled_trial",
            "study_design:controlled_clinical_trial",
            "placebo_controlled",
            "double_blind",
        )
    )
    if record.pmcid and high_value_reason:
        return "high_auto_full_text"
    if high_value_reason:
        return "high_manual_full_text"
    if record.pmcid:
        return "medium_auto_full_text"
    if record.doi:
        return "medium_manual_full_text"
    return "low"


def classify_and_score_record(
    record: PubMedRecord,
    *,
    index: LegacyIdentityIndex,
    query_names: list[str],
    fetched_at: str,
) -> ScoredPubMedRecord:
    match = classify_against_legacy(record, index)
    priority_score, score_reasons = score_pubmed_record(record)
    focus = cannabinoid_focus(record)
    study_design, study_design_rank, _ = infer_study_design(record)
    full_text_review_priority = classify_full_text_review_priority(
        record,
        priority_score=priority_score,
        score_reasons=score_reasons,
    )
    return ScoredPubMedRecord(
        pmid=record.pmid,
        doi=normalize_doi(record.doi),
        pmcid=normalize_pmcid(record.pmcid),
        canonical_url=pubmed_canonical_url(record.pmid),
        title=record.title,
        normalized_title=normalize_title(record.title),
        abstract=record.abstract,
        journal=record.journal,
        publication_date=record.publication_date,
        publication_types=record.publication_types,
        mesh_terms=record.mesh_terms,
        chemicals=record.chemicals,
        keywords=record.keywords,
        authors=record.authors,
        languages=record.languages,
        article_ids=record.article_ids,
        query_names=query_names,
        cannabinoid_focus=focus,
        study_design=STUDY_DESIGN_LABELS.get(study_design) if study_design else None,
        study_design_rank=study_design_rank,
        priority_score=priority_score,
        score_reasons=score_reasons,
        full_text_review_priority=full_text_review_priority,
        identity_status=match.match_status,
        legacy_match_type=match.match_type,
        legacy_match_confidence=match.match_confidence,
        legacy_study_ids=match.legacy_study_ids,
        review_reasons=match.review_reasons,
        provenance={
            "source": "pubmed",
            "method": "legacy_anchored_pubmed_discovery",
            "query_names": query_names,
            "fetched_at": fetched_at,
        },
    )


def write_jsonl(path: Path, records: list[ScoredPubMedRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def write_review_export(path: Path, records: list[ScoredPubMedRecord]) -> None:
    fieldnames = [
        "identity_status",
        "priority_score",
        "full_text_review_priority",
        "cannabinoid_focus",
        "study_design",
        "study_design_rank",
        "pmid",
        "doi",
        "pmcid",
        "canonical_url",
        "title",
        "publication_date",
        "journal",
        "publication_types",
        "query_names",
        "legacy_study_ids",
        "legacy_match_type",
        "legacy_match_confidence",
        "review_reasons",
        "score_reasons",
        "reviewer",
        "reviewed_identity_status",
        "include_candidate",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in sorted(records, key=lambda item: item.priority_score, reverse=True):
            writer.writerow(
                {
                    "identity_status": record.identity_status,
                    "priority_score": record.priority_score,
                    "full_text_review_priority": record.full_text_review_priority,
                    "cannabinoid_focus": record.cannabinoid_focus,
                    "study_design": record.study_design,
                    "study_design_rank": record.study_design_rank,
                    "pmid": record.pmid,
                    "doi": record.doi,
                    "pmcid": record.pmcid,
                    "canonical_url": record.canonical_url,
                    "title": record.title,
                    "publication_date": record.publication_date,
                    "journal": record.journal,
                    "publication_types": "; ".join(record.publication_types),
                    "query_names": "; ".join(record.query_names),
                    "legacy_study_ids": "; ".join(record.legacy_study_ids),
                    "legacy_match_type": record.legacy_match_type,
                    "legacy_match_confidence": record.legacy_match_confidence,
                    "review_reasons": "; ".join(record.review_reasons),
                    "score_reasons": "; ".join(record.score_reasons),
                    "reviewer": "",
                    "reviewed_identity_status": "",
                    "include_candidate": "",
                    "review_notes": "",
                }
            )


def build_summary(
    *,
    run_id: str,
    fetched_at: str,
    legacy_records_path: Path,
    records: list[ScoredPubMedRecord],
    query_results: list[dict[str, Any]],
    retmax: int,
    sort: str,
    datetype: str | None,
    mindate: str | None,
    maxdate: str | None,
) -> dict[str, Any]:
    status_counts = Counter(record.identity_status for record in records)
    query_counts = Counter(query_name for record in records for query_name in record.query_names)
    return {
        "source": "pubmed",
        "method": "legacy_anchored_pubmed_discovery",
        "run_id": run_id,
        "fetched_at": fetched_at,
        "legacy_records_path": str(legacy_records_path),
        "retmax_per_query": retmax,
        "sort": sort,
        "date_window": {
            "datetype": datetype,
            "mindate": mindate,
            "maxdate": maxdate,
        },
        "query_count": len(query_results),
        "pubmed_total_count_sum": sum(
            int(result["pubmed_total_count"]) for result in query_results
        ),
        "records_fetched_before_dedupe": sum(
            int(result["records_fetched"]) for result in query_results
        ),
        "records_after_dedupe": len(records),
        "identity_status_counts": dict(status_counts.most_common()),
        "query_result_counts": dict(query_counts.most_common()),
        "top_new_candidates": [
            {
                "pmid": record.pmid,
                "title": record.title,
                "priority_score": record.priority_score,
                "score_reasons": record.score_reasons,
            }
            for record in sorted(
                [record for record in records if record.identity_status == "new_candidate"],
                key=lambda item: item.priority_score,
                reverse=True,
            )[:20]
        ],
        "queries": query_results,
    }


def output_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    prefix = f"{run_id}_pubmed_discovery"
    return {
        "records": output_dir / f"{prefix}_records.jsonl",
        "legacy_matches": output_dir / f"{prefix}_legacy_matches.jsonl",
        "new_candidates": output_dir / f"{prefix}_new_candidates.jsonl",
        "review_export": output_dir / f"{prefix}_review_export.csv",
        "summary": output_dir / f"{prefix}_summary.json",
    }


def date_part(value: str | None) -> str | None:
    return value.replace("/", "-") if value else None


def date_window_output_dir(base_dir: Path, datetype: str | None, mindate: str | None) -> Path:
    if datetype and mindate:
        parts = mindate.split("/")
        if len(parts) >= 2:
            return base_dir / datetype.lower() / f"{parts[0]}-{parts[1].zfill(2)}"
        return base_dir / datetype.lower() / date_part(mindate)
    return base_dir / "undated"


def run_signature(
    *,
    query_names: list[str],
    retmax: int,
    sort: str,
    datetype: str | None,
    mindate: str | None,
    maxdate: str | None,
) -> dict[str, Any]:
    return {
        "query_names": sorted(query_names),
        "retmax": retmax,
        "sort": sort,
        "datetype": datetype,
        "mindate": mindate,
        "maxdate": maxdate,
    }


def summary_matches_signature(summary: dict[str, Any], signature: dict[str, Any]) -> bool:
    date_window = summary.get("date_window") or {}
    query_names = sorted(query["query_name"] for query in summary.get("queries", []))
    return {
        "query_names": query_names,
        "retmax": summary.get("retmax_per_query"),
        "sort": summary.get("sort"),
        "datetype": date_window.get("datetype"),
        "mindate": date_window.get("mindate"),
        "maxdate": date_window.get("maxdate"),
    } == signature


def find_existing_summary(base_dir: Path, signature: dict[str, Any]) -> Path | None:
    for summary_path in sorted(base_dir.glob("**/*_pubmed_discovery_summary.json")):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if summary_matches_signature(summary, signature):
            return summary_path
    return None


def paths_from_summary_path(summary_path: Path) -> dict[str, Path]:
    prefix = summary_path.name.removesuffix("_summary.json")
    output_dir = summary_path.parent
    return {
        "records": output_dir / f"{prefix}_records.jsonl",
        "legacy_matches": output_dir / f"{prefix}_legacy_matches.jsonl",
        "new_candidates": output_dir / f"{prefix}_new_candidates.jsonl",
        "review_export": output_dir / f"{prefix}_review_export.csv",
        "summary": summary_path,
    }


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"runs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def update_manifest(manifest_path: Path, summary: dict[str, Any], paths: dict[str, Path]) -> None:
    manifest = read_manifest(manifest_path)
    runs = [
        run
        for run in manifest.get("runs", [])
        if run.get("run_id") != summary["run_id"]
    ]
    runs.append(
        {
            "run_id": summary["run_id"],
            "fetched_at": summary["fetched_at"],
            "date_window": summary["date_window"],
            "query_count": summary["query_count"],
            "records_after_dedupe": summary["records_after_dedupe"],
            "identity_status_counts": summary["identity_status_counts"],
            "paths": {name: str(path) for name, path in paths.items()},
        }
    )
    manifest["runs"] = sorted(runs, key=lambda run: run["fetched_at"])
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_summary(summary: dict[str, Any], paths: dict[str, Path]) -> None:
    table = Table(title="PubMed discovery summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Records after dedupe", str(summary["records_after_dedupe"]))
    for status, count in summary["identity_status_counts"].items():
        table.add_row(status, str(count))
    console.print(table)
    console.print({name: str(path) for name, path in paths.items()})


def fetch_query_records(
    *,
    client: PubMedClient,
    query_name: str,
    query: str,
    retmax: int,
    sort: str,
    fetched_at: str,
    api_key_present: bool,
    datetype: str | None,
    mindate: str | None,
    maxdate: str | None,
) -> tuple[list[PubMedRecord], dict[str, Any]]:
    search_result = client.search(
        query,
        retmax=retmax,
        sort=sort,
        datetype=datetype,
        mindate=mindate,
        maxdate=maxdate,
    )
    pmids = [str(pmid) for pmid in search_result.get("idlist", [])]
    time.sleep(0.11 if api_key_present else 0.34)
    xml_text = client.fetch_xml(pmids) if pmids else "<PubmedArticleSet />"
    records = parse_pubmed_xml(xml_text, query=query, fetched_at=fetched_at)
    return records, {
        "query_name": query_name,
        "query": query,
        "datetype": datetype,
        "mindate": mindate,
        "maxdate": maxdate,
        "pubmed_total_count": int(search_result.get("count", 0)),
        "records_fetched": len(records),
        "pmids": [record.pmid for record in records],
    }


@app.command()
def run(
    query_name: Annotated[
        list[str] | None,
        typer.Option(
            "--query-name",
            "-n",
            help="Named discovery query to run. Repeat to run a subset.",
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
    datetype: Annotated[
        str,
        typer.Option("--datetype", help="PubMed date type for mindate/maxdate."),
    ] = "pdat",
    mindate: Annotated[
        str | None,
        typer.Option("--mindate", help="Lower PubMed date bound, e.g. 2026/04/01."),
    ] = None,
    maxdate: Annotated[
        str | None,
        typer.Option("--maxdate", help="Upper PubMed date bound, e.g. 2026/04/30."),
    ] = None,
    legacy_records_path: Annotated[
        Path | None,
        typer.Option("--legacy-records-path", help="Legacy reconciliation JSONL to index."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for normalized discovery outputs."),
    ] = None,
    skip_existing: Annotated[
        bool,
        typer.Option(
            "--skip-existing/--no-skip-existing",
            help="Skip network calls when a matching date-window run already exists.",
        ),
    ] = True,
) -> None:
    """Search PubMed, compare results with legacy identities, and export candidates."""
    load_dotenv()
    settings = get_settings()
    output_root = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir = date_window_output_dir(output_root, datetype, mindate)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    resolved_legacy_path = legacy_records_path or find_latest_legacy_records_path(
        settings.data_dir / DEFAULT_LEGACY_RECONCILIATION_DIR
    )
    index = build_legacy_index(load_jsonl(resolved_legacy_path))

    selected_names = query_name or list(QUERY_BATCHES)
    unknown_names = sorted(set(selected_names) - set(QUERY_BATCHES))
    if unknown_names:
        allowed = ", ".join(QUERY_BATCHES)
        names = ", ".join(unknown_names)
        msg = f"Unknown query name(s): {names}. Available names: {allowed}."
        raise typer.BadParameter(msg)

    signature = run_signature(
        query_names=selected_names,
        retmax=retmax,
        sort=sort,
        datetype=datetype,
        mindate=mindate,
        maxdate=maxdate,
    )
    if skip_existing and (existing_summary := find_existing_summary(output_root, signature)):
        paths = paths_from_summary_path(existing_summary)
        summary = json.loads(existing_summary.read_text(encoding="utf-8"))
        update_manifest(output_root / MANIFEST_FILENAME, summary, paths)
        console.print("Matching PubMed discovery run already exists; skipping network calls.")
        console.print({name: str(path) for name, path in paths.items()})
        return

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    fetched_at = datetime.now(UTC).isoformat()
    api_key_present = bool(os.getenv("PUBMED_API_KEY"))
    client = PubMedClient(api_key=os.getenv("PUBMED_API_KEY"), email=os.getenv("PUBMED_EMAIL"))
    records_by_pmid: dict[str, PubMedRecord] = {}
    query_names_by_pmid: dict[str, set[str]] = {}
    query_results: list[dict[str, Any]] = []
    try:
        for name in selected_names:
            fetched_records, query_result = fetch_query_records(
                client=client,
                query_name=name,
                query=QUERY_BATCHES[name],
                retmax=retmax,
                sort=sort,
                fetched_at=fetched_at,
                api_key_present=api_key_present,
                datetype=datetype,
                mindate=mindate,
                maxdate=maxdate,
            )
            query_results.append(query_result)
            for record in fetched_records:
                records_by_pmid.setdefault(record.pmid, record)
                query_names_by_pmid.setdefault(record.pmid, set()).add(name)
    finally:
        client.close()

    scored_records = [
        classify_and_score_record(
            record,
            index=index,
            query_names=sorted(query_names_by_pmid[pmid]),
            fetched_at=fetched_at,
        )
        for pmid, record in sorted(records_by_pmid.items())
    ]
    scored_records.sort(key=lambda item: item.priority_score, reverse=True)

    paths = output_paths(resolved_output_dir, run_id)
    write_jsonl(paths["records"], scored_records)
    write_jsonl(
        paths["legacy_matches"],
        [record for record in scored_records if record.identity_status in LEGACY_MATCH_STATUSES],
    )
    write_jsonl(
        paths["new_candidates"],
        [record for record in scored_records if record.identity_status == "new_candidate"],
    )
    write_review_export(paths["review_export"], scored_records)

    summary = build_summary(
        run_id=run_id,
        fetched_at=fetched_at,
        legacy_records_path=resolved_legacy_path,
        records=scored_records,
        query_results=query_results,
        retmax=retmax,
        sort=sort,
        datetype=datetype,
        mindate=mindate,
        maxdate=maxdate,
    )
    paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    update_manifest(output_root / MANIFEST_FILENAME, summary, paths)
    print_summary(summary, paths)


if __name__ == "__main__":
    app()
