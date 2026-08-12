from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.retrieval.identity_review import export_identity_conflicts
from marygenai.retrieval.index import DEFAULT_INDEX_RELATIVE_PATH, build_retrieval_index
from marygenai.retrieval.models import FilterGroup, SearchFilters, SearchRequest
from marygenai.retrieval.service import RetrievalService
from marygenai.settings import get_settings

app = typer.Typer(help="Build and inspect the read-only candidate-evidence retrieval index.")
console = Console()
DEFAULT_INDEX_PATH = get_settings().data_dir / DEFAULT_INDEX_RELATIVE_PATH


def _group(values: list[str] | None) -> FilterGroup | None:
    return FilterGroup(values=values) if values else None


def _print_json(payload: object) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))


@app.command("build-index")
def build_index(
    output_path: Annotated[
        Path | None,
        typer.Option("--output-path", help="Output DuckDB path. Defaults under data/normalized."),
    ] = None,
    records_path: Annotated[
        list[Path] | None,
        typer.Option("--records-path", help="Candidate records JSONL. Repeat for multiple runs."),
    ] = None,
    corpus_path: Annotated[
        Path | None,
        typer.Option("--corpus-path", help="Classification corpus records JSONL."),
    ] = None,
    evaluation_report_path: Annotated[
        list[Path] | None,
        typer.Option(
            "--evaluation-report-path",
            help="Classification evaluation report JSON. Repeat for multiple runs.",
        ),
    ] = None,
    require_cannabinoid_exposure: Annotated[
        bool,
        typer.Option(
            "--require-cannabinoid-exposure/--allow-missing-cannabinoid-exposure",
            help=(
                "Exclude classifications with no structured cannabinoid or exposure "
                "label and write a provenance report."
            ),
        ),
    ] = False,
    require_cannabinoid_exposure_run_id: Annotated[
        list[str] | None,
        typer.Option(
            "--require-cannabinoid-exposure-run-id",
            help=(
                "Apply the structured cannabinoid/exposure gate only to this "
                "classification run. Repeat for multiple runs."
            ),
        ),
    ] = None,
) -> None:
    """Materialize an isolated DuckDB index without mutating SQLite or reviewed knowledge."""
    settings = get_settings()
    manifest = build_retrieval_index(
        data_dir=settings.data_dir,
        output_path=output_path,
        records_paths=records_path,
        corpus_path=corpus_path,
        evaluation_report_paths=evaluation_report_path,
        require_cannabinoid_exposure=require_cannabinoid_exposure,
        require_cannabinoid_exposure_run_ids=require_cannabinoid_exposure_run_id,
    )
    _print_json(manifest.model_dump(mode="json"))


@app.command("inspect-index")
def inspect_index(
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
) -> None:
    """Inspect index provenance, limitations, capabilities, and facet coverage."""
    service = RetrievalService(index_path)
    empty_request = SearchRequest(limit=1)
    _print_json(
        {
            "manifest": service.manifest(),
            "capabilities": service.capabilities().model_dump(mode="json"),
            "identity_coverage": service.identity_coverage(),
            "facets": service.facets(empty_request, top=15).model_dump(mode="json"),
        }
    )


@app.command("export-identity-conflicts")
def export_identity_conflicts_command(
    classification_run_id: Annotated[
        str | None,
        typer.Option(
            "--classification-run-id",
            help="Optional classification run filter.",
        ),
    ] = None,
    output_path: Annotated[
        Path | None,
        typer.Option("--output-path", help="Human-adjudication CSV output path."),
    ] = None,
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
) -> None:
    """Export explicit identity conflicts without applying decisions."""
    settings = get_settings()
    if output_path is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        scope = classification_run_id or "all_runs"
        output_path = (
            settings.data_dir
            / "normalized/retrieval_identity_reviews"
            / f"{timestamp}_{scope}_identity_conflicts.csv"
        )
    result = export_identity_conflicts(
        index_path=index_path,
        output_path=output_path,
        classification_run_id=classification_run_id,
    )
    _print_json(result)


@app.command("search")
def search(
    query: Annotated[
        str | None,
        typer.Option("--query", help="Optional local keyword query."),
    ] = None,
    condition: Annotated[
        list[str] | None,
        typer.Option("--condition", help="Medical-condition filter. Repeat for OR matching."),
    ] = None,
    cannabinoid: Annotated[
        list[str] | None,
        typer.Option("--cannabinoid", help="Cannabinoid or exposure filter. Repeat for OR."),
    ] = None,
    study_design: Annotated[
        list[str] | None,
        typer.Option("--study-design", help="Study-design category. Repeat for OR."),
    ] = None,
    evidence_context: Annotated[
        list[str] | None,
        typer.Option("--evidence-context", help="Evidence-context filter. Repeat for OR."),
    ] = None,
    population: Annotated[
        list[str] | None,
        typer.Option("--population", help="Population-category filter. Repeat for OR."),
    ] = None,
    outcome_domain: Annotated[
        list[str] | None,
        typer.Option("--outcome-domain", help="Outcome-domain filter. Repeat for OR."),
    ] = None,
    direction: Annotated[
        list[str] | None,
        typer.Option("--direction", help="Overall-direction filter. Repeat for OR."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    cursor: Annotated[
        str | None,
        typer.Option("--cursor", help="Opaque pagination cursor."),
    ] = None,
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
) -> None:
    """Run a local read-only search using the same contract exposed through MCP."""
    request = SearchRequest(
        query=query,
        filters=SearchFilters(
            medical_conditions=_group(condition),
            cannabinoids_or_exposures=_group(cannabinoid),
            study_design_categories=_group(study_design),
            evidence_contexts=_group(evidence_context),
            population_categories=_group(population),
            outcome_domains=_group(outcome_domain),
            overall_directions=_group(direction),
        ),
        limit=limit,
        cursor=cursor,
    )
    response = RetrievalService(index_path).search(request)
    _print_json(response.model_dump(mode="json"))
