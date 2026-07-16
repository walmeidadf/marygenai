from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from marygenai.mcp_server.server import create_mcp_server
from marygenai.retrieval.index import DEFAULT_INDEX_RELATIVE_PATH
from marygenai.settings import get_settings

app = typer.Typer(help="Serve the read-only MaryGenAI candidate-evidence MCP interface.")
DEFAULT_INDEX_PATH = get_settings().data_dir / DEFAULT_INDEX_RELATIVE_PATH


@app.command("serve")
def serve(
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
) -> None:
    """Serve the closed local candidate index over MCP stdio."""
    create_mcp_server(index_path).run(transport="stdio")
