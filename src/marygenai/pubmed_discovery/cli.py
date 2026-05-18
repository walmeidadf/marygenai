from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.pubmed_discovery.pipeline import (
    discover_pubmed_candidates,
    persist_pubmed_candidates,
)
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Discover and stage PubMed publication candidates.")
console = Console()


@app.callback()
def main() -> None:
    """Run PubMed discovery commands."""


@app.command("run")
def run(
    query_name: Annotated[
        list[str] | None,
        typer.Option("--query-name", "-n", help="Named PubMed discovery query to run."),
    ] = None,
    retmax: Annotated[
        int,
        typer.Option("--retmax", min=1, max=200, help="Maximum PubMed records per query."),
    ] = 100,
    sort: Annotated[str, typer.Option("--sort", help="PubMed esearch sort order.")] = "relevance",
    datetype: Annotated[str, typer.Option("--datetype", help="PubMed date type.")] = "pdat",
    mindate: Annotated[str | None, typer.Option("--mindate", help="Lower date bound.")] = None,
    maxdate: Annotated[str | None, typer.Option("--maxdate", help="Upper date bound.")] = None,
    overlap_years: Annotated[
        int,
        typer.Option("--overlap-years", min=0, help="Years to overlap before legacy boundary."),
    ] = 1,
    no_persist: Annotated[
        bool,
        typer.Option("--no-persist", help="Write snapshots without loading SQLite."),
    ] = False,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Discover PubMed candidates and optionally load them into local SQLite."""
    settings = get_settings()
    result = discover_pubmed_candidates(
        storage=LocalStorage(settings.data_dir),
        database_path=database_path or sqlite_database_path(settings.data_dir),
        query_names=query_name,
        retmax=retmax,
        sort=sort,
        datetype=datetype,
        mindate=mindate,
        maxdate=maxdate,
        overlap_years=overlap_years,
        persist=not no_persist,
    )
    console.print(
        {
            "run_id": result.run_id,
            "manifest_path": str(result.manifest_path),
            "counts": result.counts,
            "outputs": {name: str(path) for name, path in result.output_paths.items()},
        }
    )


@app.command("persist")
def persist(
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="PubMed discovery run id to persist."),
    ] = None,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Persist a PubMed discovery snapshot into local SQLite review state."""
    settings = get_settings()
    result = persist_pubmed_candidates(
        storage=LocalStorage(settings.data_dir),
        database_path=database_path or sqlite_database_path(settings.data_dir),
        run_id=run_id,
    )
    console.print(result)
