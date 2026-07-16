from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

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
) -> None:
    """Materialize an isolated DuckDB index without mutating SQLite or reviewed knowledge."""
    settings = get_settings()
    manifest = build_retrieval_index(
        data_dir=settings.data_dir,
        output_path=output_path,
        records_paths=records_path,
        corpus_path=corpus_path,
        evaluation_report_paths=evaluation_report_path,
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
            "facets": service.facets(empty_request, top=15).model_dump(mode="json"),
        }
    )


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
