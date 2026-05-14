"""Enrich PubMed discovery candidates with NIH iCite citation metrics.

This POC keeps citation and influence metrics separate from evidence quality.
It preserves the PubMed discovery score and adds iCite fields plus a simple
citation-priority score for review queue experiments.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from marygenai.settings import get_settings

DEFAULT_INPUT_GLOB = "data/normalized/pubmed_discovery/**/*_pubmed_discovery_records.jsonl"
DEFAULT_OUTPUT_SUBDIR = Path("normalized/icite_enrichment")
ICITE_BASE_URL = "https://icite.od.nih.gov/api"
ICITE_BATCH_SIZE = 200
MANIFEST_FILENAME = "_manifest.json"
ICITE_FIELDS = [
    "pmid",
    "year",
    "title",
    "doi",
    "citation_count",
    "relative_citation_ratio",
    "nih_percentile",
    "citations_per_year",
    "expected_citations_per_year",
    "human",
    "animal",
    "molecular_cellular",
    "apt",
    "is_clinical",
    "is_research_article",
    "cited_by_clin",
    "citedByClinicalArticle",
    "provisional",
]

console = Console()
app = typer.Typer(help="Enrich PubMed discovery outputs with NIH iCite metrics.")


@app.callback()
def main() -> None:
    """Run NIH iCite enrichment commands."""


@dataclass(frozen=True)
class IciteMetrics:
    pmid: str
    year: int | None
    title: str | None
    doi: str | None
    citation_count: int | None
    relative_citation_ratio: float | None
    nih_percentile: float | None
    citations_per_year: float | None
    expected_citations_per_year: float | None
    human: float | None
    animal: float | None
    molecular_cellular: float | None
    apt: float | None
    is_clinical: bool | None
    is_research_article: bool | None
    cited_by_clinical_article: bool | None
    cited_by_clinical_count: int
    rcr_is_provisional: bool | None
    raw_available: bool


@dataclass(frozen=True)
class EnrichedCitationRecord:
    source_record: dict[str, Any]
    pmid: str
    priority_score: int | None
    study_design_rank: int | None
    cannabinoid_focus: str | None
    full_text_review_priority: str | None
    icite_found: bool
    icite_year: int | None
    icite_title: str | None
    icite_doi: str | None
    icite_citation_count: int | None
    icite_relative_citation_ratio: float | None
    icite_nih_percentile: float | None
    icite_citations_per_year: float | None
    icite_expected_citations_per_year: float | None
    icite_human: float | None
    icite_animal: float | None
    icite_molecular_cellular: float | None
    icite_apt: float | None
    icite_is_clinical: bool | None
    icite_is_research_article: bool | None
    icite_cited_by_clinical_article: bool | None
    icite_cited_by_clinical_count: int
    icite_rcr_is_provisional: bool | None
    citation_priority_score: int
    citation_score_reasons: list[str]
    citation_review_notes: list[str]
    icite_provenance: dict[str, Any]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def read_source_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return read_csv_records(path)
    return read_jsonl(path)


def write_jsonl(path: Path, records: list[EnrichedCitationRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            merged = {**record.source_record, **asdict(record)}
            merged.pop("source_record")
            file.write(json.dumps(merged, ensure_ascii=False, sort_keys=True) + "\n")


def latest_input_path(pattern: str = DEFAULT_INPUT_GLOB) -> Path:
    paths = sorted(Path().glob(pattern))
    if not paths:
        msg = f"No PubMed discovery records matched {pattern}."
        raise FileNotFoundError(msg)
    return paths[-1]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_pmid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text.isdigit() else None


def source_pmids(records: list[dict[str, Any]]) -> list[str]:
    pmids: list[str] = []
    seen: set[str] = set()
    for record in records:
        pmid = normalize_pmid(record.get("pmid"))
        if pmid and pmid not in seen:
            pmids.append(pmid)
            seen.add(pmid)
    return pmids


def batched(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def numeric_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def int_or_none(value: Any) -> int | None:
    numeric = numeric_or_none(value)
    return int(numeric) if numeric is not None else None


def bool_or_none(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    lowered = str(value).strip().lower()
    if lowered in {"true", "t", "yes", "y", "1"}:
        return True
    if lowered in {"false", "f", "no", "n", "0"}:
        return False
    return None


def list_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if value in (None, ""):
        return 0
    return 1


def get_any(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    return None


def parse_icite_publication(payload: dict[str, Any]) -> IciteMetrics:
    pmid = normalize_pmid(get_any(payload, "pmid", "_id"))
    if not pmid:
        msg = f"iCite publication missing PMID: {payload!r}"
        raise ValueError(msg)

    cited_by_clinical = get_any(payload, "cited_by_clin", "citingClinicalPmids")
    return IciteMetrics(
        pmid=pmid,
        year=int_or_none(get_any(payload, "year", "pubYear")),
        title=get_any(payload, "title"),
        doi=get_any(payload, "doi"),
        citation_count=int_or_none(get_any(payload, "citation_count", "citedByPmidCount")),
        relative_citation_ratio=numeric_or_none(
            get_any(payload, "relative_citation_ratio", "rcr")
        ),
        nih_percentile=numeric_or_none(get_any(payload, "nih_percentile", "nihRcrPercentile")),
        citations_per_year=numeric_or_none(get_any(payload, "citations_per_year", "acr")),
        expected_citations_per_year=numeric_or_none(
            get_any(payload, "expected_citations_per_year", "ecr")
        ),
        human=numeric_or_none(get_any(payload, "human")),
        animal=numeric_or_none(get_any(payload, "animal")),
        molecular_cellular=numeric_or_none(
            get_any(payload, "molecular_cellular", "molCell")
        ),
        apt=numeric_or_none(get_any(payload, "apt")),
        is_clinical=bool_or_none(get_any(payload, "is_clinical", "isClinicalArticle")),
        is_research_article=bool_or_none(
            get_any(payload, "is_research_article", "iCiteArticle")
        ),
        cited_by_clinical_article=bool_or_none(
            get_any(payload, "citedByClinicalArticle")
        ),
        cited_by_clinical_count=list_count(cited_by_clinical),
        rcr_is_provisional=bool_or_none(get_any(payload, "provisional", "rcrIsProvisional")),
        raw_available=True,
    )


def parse_icite_response(payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, IciteMetrics]:
    if isinstance(payload, list):
        publications = payload
    elif "data" in payload and isinstance(payload["data"], list):
        publications = payload["data"]
    elif "pmid" in payload or "_id" in payload:
        publications = [payload]
    else:
        publications = []
    return {metrics.pmid: metrics for metrics in map(parse_icite_publication, publications)}


class IciteClient:
    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        self.client = httpx.Client(base_url=ICITE_BASE_URL, timeout=timeout_seconds)

    def close(self) -> None:
        self.client.close()

    def fetch_pmids(self, pmids: list[str]) -> dict[str, IciteMetrics]:
        response = self.client.get(
            "/pubs",
            params={
                "pmids": ",".join(pmids),
                "fl": ",".join(ICITE_FIELDS),
            },
        )
        response.raise_for_status()
        return parse_icite_response(response.json())


def publication_year_from_source(record: dict[str, Any]) -> int | None:
    value = record.get("publication_date") or record.get("year")
    if not value:
        return None
    text = str(value)
    year = text[:4]
    return int(year) if year.isdigit() else None


def score_citation_priority(
    *,
    metrics: IciteMetrics | None,
    source_record: dict[str, Any],
    current_year: int | None = None,
) -> tuple[int, list[str], list[str]]:
    current_year = current_year or datetime.now(UTC).year
    reasons: list[str] = []
    notes: list[str] = []
    if not metrics:
        return 0, ["icite_metrics_absent"], ["missing_iCite_metrics_not_evidence_quality"]

    score = 0
    if metrics.citation_count is not None:
        citation_points = min(35, int(math.log10(metrics.citation_count + 1) * 18))
        score += citation_points
        reasons.append(f"citation_count:{metrics.citation_count}")
    else:
        notes.append("missing_citation_count")

    if metrics.relative_citation_ratio is not None:
        if metrics.relative_citation_ratio >= 5:
            score += 30
            reasons.append("rcr_5_or_higher")
        elif metrics.relative_citation_ratio >= 2:
            score += 22
            reasons.append("rcr_2_or_higher")
        elif metrics.relative_citation_ratio >= 1:
            score += 12
            reasons.append("rcr_1_or_higher")
        else:
            score += 4
            reasons.append("rcr_below_1")
    else:
        notes.append("missing_relative_citation_ratio")

    if metrics.nih_percentile is not None and metrics.nih_percentile >= 90:
        score += 12
        reasons.append("nih_percentile_90_or_higher")
    elif metrics.nih_percentile is not None and metrics.nih_percentile >= 75:
        score += 8
        reasons.append("nih_percentile_75_or_higher")

    if metrics.cited_by_clinical_count:
        score += min(18, 6 + metrics.cited_by_clinical_count * 2)
        reasons.append(f"clinical_citation_count:{metrics.cited_by_clinical_count}")
    elif metrics.cited_by_clinical_article:
        score += 6
        reasons.append("cited_by_clinical_article")

    if metrics.is_clinical:
        score += 8
        reasons.append("icite_clinical_article")
    if metrics.human is not None and metrics.human >= 0.75:
        score += 8
        reasons.append("human_orientation_high")
    if metrics.animal is not None and metrics.animal >= 0.75:
        score += 3
        reasons.append("animal_orientation_high")
    if metrics.molecular_cellular is not None and metrics.molecular_cellular >= 0.75:
        score += 2
        reasons.append("molecular_cellular_orientation_high")
    if metrics.apt is not None and metrics.apt >= 0.75:
        score += 12
        reasons.append("apt_0_75_or_higher")
    elif metrics.apt is not None and metrics.apt >= 0.5:
        score += 7
        reasons.append("apt_0_5_or_higher")

    source_year = publication_year_from_source(source_record) or metrics.year
    if source_year and current_year - source_year <= 2:
        notes.append("recent_publication_citation_bias_possible")
        if (metrics.citation_count or 0) < 5:
            score += 5
            reasons.append("recent_low_citation_floor")

    if metrics.rcr_is_provisional:
        notes.append("provisional_rcr")
    notes.append("citation_metrics_are_prioritization_not_evidence_quality")
    return score, reasons, notes


def build_enriched_record(
    source_record: dict[str, Any],
    *,
    metrics: IciteMetrics | None,
    input_path: Path,
    fetched_at: str,
) -> EnrichedCitationRecord:
    pmid = normalize_pmid(source_record.get("pmid"))
    if not pmid:
        msg = f"Source record missing PMID: {source_record!r}"
        raise ValueError(msg)
    citation_score, citation_reasons, citation_notes = score_citation_priority(
        metrics=metrics,
        source_record=source_record,
    )
    return EnrichedCitationRecord(
        source_record=source_record,
        pmid=pmid,
        priority_score=int_or_none(source_record.get("priority_score")),
        study_design_rank=int_or_none(source_record.get("study_design_rank")),
        cannabinoid_focus=source_record.get("cannabinoid_focus"),
        full_text_review_priority=source_record.get("full_text_review_priority"),
        icite_found=metrics is not None,
        icite_year=metrics.year if metrics else None,
        icite_title=metrics.title if metrics else None,
        icite_doi=metrics.doi if metrics else None,
        icite_citation_count=metrics.citation_count if metrics else None,
        icite_relative_citation_ratio=metrics.relative_citation_ratio if metrics else None,
        icite_nih_percentile=metrics.nih_percentile if metrics else None,
        icite_citations_per_year=metrics.citations_per_year if metrics else None,
        icite_expected_citations_per_year=metrics.expected_citations_per_year
        if metrics
        else None,
        icite_human=metrics.human if metrics else None,
        icite_animal=metrics.animal if metrics else None,
        icite_molecular_cellular=metrics.molecular_cellular if metrics else None,
        icite_apt=metrics.apt if metrics else None,
        icite_is_clinical=metrics.is_clinical if metrics else None,
        icite_is_research_article=metrics.is_research_article if metrics else None,
        icite_cited_by_clinical_article=metrics.cited_by_clinical_article
        if metrics
        else None,
        icite_cited_by_clinical_count=metrics.cited_by_clinical_count if metrics else 0,
        icite_rcr_is_provisional=metrics.rcr_is_provisional if metrics else None,
        citation_priority_score=citation_score,
        citation_score_reasons=citation_reasons,
        citation_review_notes=citation_notes,
        icite_provenance={
            "source": "nih_icite",
            "method": "pubmed_discovery_citation_enrichment",
            "input_path": str(input_path),
            "fetched_at": fetched_at,
        },
    )


def review_export_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def write_review_export(path: Path, records: list[EnrichedCitationRecord]) -> None:
    fieldnames = [
        "citation_priority_score",
        "priority_score",
        "full_text_review_priority",
        "cannabinoid_focus",
        "study_design",
        "study_design_rank",
        "pmid",
        "doi",
        "pmcid",
        "title",
        "publication_date",
        "journal",
        "identity_status",
        "icite_found",
        "icite_citation_count",
        "icite_relative_citation_ratio",
        "icite_nih_percentile",
        "icite_citations_per_year",
        "icite_expected_citations_per_year",
        "icite_cited_by_clinical_count",
        "icite_cited_by_clinical_article",
        "icite_is_clinical",
        "icite_human",
        "icite_animal",
        "icite_molecular_cellular",
        "icite_apt",
        "icite_rcr_is_provisional",
        "citation_score_reasons",
        "citation_review_notes",
        "score_reasons",
        "reviewer",
        "reviewed_citation_priority",
        "review_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for record in sorted(
            records,
            key=lambda item: (item.citation_priority_score, item.priority_score or 0),
            reverse=True,
        ):
            source = record.source_record
            writer.writerow(
                {
                    "citation_priority_score": record.citation_priority_score,
                    "priority_score": source.get("priority_score"),
                    "full_text_review_priority": source.get("full_text_review_priority"),
                    "cannabinoid_focus": source.get("cannabinoid_focus"),
                    "study_design": source.get("study_design"),
                    "study_design_rank": source.get("study_design_rank"),
                    "pmid": source.get("pmid"),
                    "doi": source.get("doi"),
                    "pmcid": source.get("pmcid"),
                    "title": source.get("title"),
                    "publication_date": source.get("publication_date"),
                    "journal": source.get("journal"),
                    "identity_status": source.get("identity_status"),
                    "icite_found": record.icite_found,
                    "icite_citation_count": record.icite_citation_count,
                    "icite_relative_citation_ratio": record.icite_relative_citation_ratio,
                    "icite_nih_percentile": record.icite_nih_percentile,
                    "icite_citations_per_year": record.icite_citations_per_year,
                    "icite_expected_citations_per_year": (
                        record.icite_expected_citations_per_year
                    ),
                    "icite_cited_by_clinical_count": record.icite_cited_by_clinical_count,
                    "icite_cited_by_clinical_article": (
                        record.icite_cited_by_clinical_article
                    ),
                    "icite_is_clinical": record.icite_is_clinical,
                    "icite_human": record.icite_human,
                    "icite_animal": record.icite_animal,
                    "icite_molecular_cellular": record.icite_molecular_cellular,
                    "icite_apt": record.icite_apt,
                    "icite_rcr_is_provisional": record.icite_rcr_is_provisional,
                    "citation_score_reasons": review_export_value(
                        record.citation_score_reasons
                    ),
                    "citation_review_notes": review_export_value(record.citation_review_notes),
                    "score_reasons": review_export_value(source.get("score_reasons")),
                    "reviewer": "",
                    "reviewed_citation_priority": "",
                    "review_notes": "",
                }
            )


def output_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    prefix = f"{run_id}_icite_enrichment"
    return {
        "records": output_dir / f"{prefix}_records.jsonl",
        "review_export": output_dir / f"{prefix}_review_export.csv",
        "summary": output_dir / f"{prefix}_summary.json",
    }


def build_summary(
    *,
    run_id: str,
    fetched_at: str,
    input_path: Path,
    input_sha256: str,
    records: list[EnrichedCitationRecord],
    batches_queried: int,
) -> dict[str, Any]:
    return {
        "source": "nih_icite",
        "method": "pubmed_discovery_citation_enrichment",
        "run_id": run_id,
        "fetched_at": fetched_at,
        "input_path": str(input_path),
        "input_sha256": input_sha256,
        "total_records": len(records),
        "icite_found": sum(record.icite_found for record in records),
        "icite_missing": sum(not record.icite_found for record in records),
        "batches_queried": batches_queried,
        "citation_priority_score": {
            "min": min((record.citation_priority_score for record in records), default=0),
            "max": max((record.citation_priority_score for record in records), default=0),
        },
        "study_design_rank_counts": dict(
            Counter(
                str(record.study_design_rank)
                for record in records
                if record.study_design_rank is not None
            ).most_common()
        ),
        "top_citation_priority_records": [
            {
                "pmid": record.pmid,
                "title": record.source_record.get("title"),
                "priority_score": record.priority_score,
                "study_design_rank": record.study_design_rank,
                "citation_priority_score": record.citation_priority_score,
                "icite_citation_count": record.icite_citation_count,
                "icite_relative_citation_ratio": record.icite_relative_citation_ratio,
                "citation_review_notes": record.citation_review_notes,
            }
            for record in sorted(
                records,
                key=lambda item: (item.citation_priority_score, item.priority_score or 0),
                reverse=True,
            )[:20]
        ],
        "guardrails": [
            "citation_metrics_are_prioritization_not_evidence_quality",
            "priority_score_and_study_design_rank_preserved_from_pubmed_discovery",
            "recent_publications_may_have_low_citation_counts",
        ],
    }


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"runs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def find_manifest_run(
    manifest: dict[str, Any],
    *,
    input_path: Path,
    input_sha256: str,
) -> dict[str, Any] | None:
    for run in manifest.get("runs", []):
        if run.get("input_path") == str(input_path) and run.get("input_sha256") == input_sha256:
            return run
    return None


def update_manifest(manifest_path: Path, summary: dict[str, Any], paths: dict[str, Path]) -> None:
    manifest = read_manifest(manifest_path)
    runs = [
        run
        for run in manifest.get("runs", [])
        if run.get("run_id") != summary["run_id"]
        and not (
            run.get("input_path") == summary["input_path"]
            and run.get("input_sha256") == summary["input_sha256"]
        )
    ]
    runs.append(
        {
            "run_id": summary["run_id"],
            "fetched_at": summary["fetched_at"],
            "input_path": summary["input_path"],
            "input_sha256": summary["input_sha256"],
            "total_records": summary["total_records"],
            "icite_found": summary["icite_found"],
            "paths": {name: str(path) for name, path in paths.items()},
        }
    )
    manifest["runs"] = sorted(runs, key=lambda run: run["fetched_at"])
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def print_summary(summary: dict[str, Any], paths: dict[str, Path]) -> None:
    table = Table(title="NIH iCite enrichment summary")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Total records", str(summary["total_records"]))
    table.add_row("iCite found", str(summary["icite_found"]))
    table.add_row("iCite missing", str(summary["icite_missing"]))
    table.add_row("Batches queried", str(summary["batches_queried"]))
    console.print(table)
    console.print({name: str(path) for name, path in paths.items()})


@app.command()
def run(
    input_path: Annotated[
        Path | None,
        typer.Option(
            "--input-path",
            help="POC 7 PubMed discovery records JSONL/CSV. Defaults to latest JSONL.",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for normalized iCite outputs."),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", min=1, max=ICITE_BATCH_SIZE, help="PMIDs per API call."),
    ] = ICITE_BATCH_SIZE,
    skip_existing: Annotated[
        bool,
        typer.Option(
            "--skip-existing/--no-skip-existing",
            help="Skip iCite calls when this exact input was already enriched.",
        ),
    ] = True,
) -> None:
    """Query NIH iCite for PubMed discovery PMIDs and export enriched records."""
    load_dotenv()
    settings = get_settings()
    resolved_input_path = input_path or latest_input_path()
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = resolved_output_dir / MANIFEST_FILENAME
    input_sha256 = file_sha256(resolved_input_path)

    manifest = read_manifest(manifest_path)
    if skip_existing and (
        existing_run := find_manifest_run(
            manifest,
            input_path=resolved_input_path,
            input_sha256=input_sha256,
        )
    ):
        console.print("Matching iCite enrichment already exists; skipping API calls.")
        console.print(existing_run.get("paths", {}))
        return

    source_records = read_source_records(resolved_input_path)
    pmids = source_pmids(source_records)
    fetched_at = datetime.now(UTC).isoformat()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    metrics_by_pmid: dict[str, IciteMetrics] = {}
    client = IciteClient()
    batches = batched(pmids, batch_size)
    try:
        for batch in batches:
            metrics_by_pmid.update(client.fetch_pmids(batch))
            time.sleep(0.1)
    finally:
        client.close()

    enriched_records = [
        build_enriched_record(
            record,
            metrics=metrics_by_pmid.get(normalize_pmid(record.get("pmid")) or ""),
            input_path=resolved_input_path,
            fetched_at=fetched_at,
        )
        for record in source_records
        if normalize_pmid(record.get("pmid"))
    ]
    enriched_records.sort(
        key=lambda item: (item.citation_priority_score, item.priority_score or 0),
        reverse=True,
    )

    paths = output_paths(resolved_output_dir, run_id)
    write_jsonl(paths["records"], enriched_records)
    write_review_export(paths["review_export"], enriched_records)
    summary = build_summary(
        run_id=run_id,
        fetched_at=fetched_at,
        input_path=resolved_input_path,
        input_sha256=input_sha256,
        records=enriched_records,
        batches_queried=len(batches),
    )
    paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    update_manifest(manifest_path, summary, paths)
    print_summary(summary, paths)


if __name__ == "__main__":
    app()
