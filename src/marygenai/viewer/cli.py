from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from marygenai.retrieval.common import DEFAULT_INDEX_RELATIVE_PATH
from marygenai.settings import get_settings
from marygenai.viewer.app import create_app

app = typer.Typer(help="Serve the read-only MaryGenAI Dataset Viewer API.")
DEFAULT_INDEX_PATH = get_settings().data_dir / DEFAULT_INDEX_RELATIVE_PATH


@app.command("serve-api")
def serve_api(
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
    host: Annotated[str, typer.Option("--host", help="HTTP bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8010,
) -> None:
    """Serve a web-safe projection of the immutable candidate index."""
    uvicorn.run(create_app(index_path), host=host, port=port)
