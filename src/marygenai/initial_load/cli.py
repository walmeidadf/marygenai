from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from marygenai.initial_load.persist import persist_initial_load
from marygenai.initial_load.pipeline import run_initial_load
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Run the MaryGenAI MVP initial load.")
console = Console()


@app.callback()
def main() -> None:
    """Run initial load commands."""


@app.command("setup-data")
def setup_data() -> None:
    """Create the ignored local data directory layout."""
    settings = get_settings()
    storage = LocalStorage(settings.data_dir)
    paths = storage.ensure_layout()
    console.print({"data_dir": str(settings.data_dir), "directories": len(paths)})


@app.command("run")
def run(
    legacy_dir: Annotated[
        Path | None,
        typer.Option("--legacy-dir", help="Directory containing legacy Cannadocs CSV exports."),
    ] = None,
) -> None:
    """Import legacy studies and ontology CSVs into audited JSONL snapshots."""
    settings = get_settings()
    result = run_initial_load(
        legacy_dir=legacy_dir or settings.temp_dir / "legacy/cannadocs",
        storage=LocalStorage(settings.data_dir),
    )
    table = Table(title="Initial load completed")
    table.add_column("Output")
    table.add_column("Records", justify="right")
    for name, count in result.counts.items():
        table.add_row(name, str(count))
    console.print(table)
    console.print({"run_id": result.run_id, "manifest": str(result.manifest_path)})


@app.command("persist")
def persist(
    run_id: Annotated[
        str | None,
        typer.Option("--run-id", help="Initial Load run id to persist. Defaults to latest run."),
    ] = None,
) -> None:
    """Load Initial Load JSONL snapshots into the local SQLite review database."""
    settings = get_settings()
    result = persist_initial_load(
        storage=LocalStorage(settings.data_dir),
        run_id=run_id,
    )
    table = Table(title="Initial load persisted")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    for name in (
        "source_records",
        "publication_candidates",
        "ontology_entities",
        "document_ontology_links",
        "review_items",
    ):
        table.add_row(name, str(result[name]))
    console.print(table)
    console.print({"run_id": result["run_id"], "database": result["database"]})
