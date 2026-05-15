from __future__ import annotations

import typer
from rich.console import Console

from marygenai.persistence.sqlite import connect_sqlite, initialize_schema, sqlite_database_path
from marygenai.settings import get_settings

app = typer.Typer(help="Manage the local MaryGenAI SQLite database.")
console = Console()


@app.callback()
def main() -> None:
    """Run database commands."""


@app.command("init")
def init() -> None:
    """Initialize or upgrade the local SQLite database schema."""
    settings = get_settings()
    database_path = sqlite_database_path(settings.data_dir)
    with connect_sqlite(database_path) as connection:
        schema_version = initialize_schema(connection)
    console.print({"database": str(database_path), "schema_version": schema_version})
