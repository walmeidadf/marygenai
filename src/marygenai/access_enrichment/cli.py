from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.access_enrichment.pipeline import run_access_enrichment
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Enrich prioritized PubMed candidates with access/full-text evidence.")
console = Console()


@app.callback()
def main() -> None:
    """Run access enrichment commands."""


@app.command("run")
def run(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=200, help="Maximum candidates to enrich."),
    ] = 50,
    identity_status: Annotated[
        list[str] | None,
        typer.Option("--identity-status", help="Candidate identity status filter."),
    ] = None,
    cannabinoid_focus: Annotated[
        list[str] | None,
        typer.Option("--cannabinoid-focus", help="Cannabinoid focus filter."),
    ] = None,
    full_text_priority: Annotated[
        list[str] | None,
        typer.Option("--full-text-priority", help="Full-text review priority filter."),
    ] = None,
    study_design: Annotated[
        list[str] | None,
        typer.Option("--study-design", help="Study design filter."),
    ] = None,
    include_manual_identity_review: Annotated[
        bool,
        typer.Option(
            "--include-manual-identity-review",
            help="Allow candidates marked needs_manual_identity_review.",
        ),
    ] = False,
    fetch_pmc_html: Annotated[
        bool,
        typer.Option("--fetch-pmc-html", help="Also retrieve PMC article HTML when PMCID exists."),
    ] = False,
    fetch_pdf: Annotated[
        bool,
        typer.Option(
            "--fetch-pdf",
            help="Reserved narrow PDF fallback flag; PDFs are not downloaded yet.",
        ),
    ] = False,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite database path."),
    ] = None,
) -> None:
    """Run targeted access/full-text enrichment for PubMed candidates."""
    settings = get_settings()
    result = run_access_enrichment(
        storage=LocalStorage(settings.data_dir),
        database_path=database_path or sqlite_database_path(settings.data_dir),
        limit=limit,
        identity_statuses=identity_status,
        cannabinoid_focuses=cannabinoid_focus,
        full_text_priorities=full_text_priority,
        study_designs=study_design,
        include_manual_identity_review=include_manual_identity_review,
        fetch_pmc_html=fetch_pmc_html,
        fetch_pdf=fetch_pdf,
    )
    console.print(result.model_dump(mode="json"))
