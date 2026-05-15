from __future__ import annotations

from typing import Annotated

import typer
import uvicorn

from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review_api.app import create_app
from marygenai.settings import get_settings

app = typer.Typer(help="Serve the local MaryGenAI review API.")


@app.callback()
def main() -> None:
    """Run review API commands."""


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host", help="Host interface to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port to bind.")] = 8000,
) -> None:
    """Serve the local FastAPI review API."""
    database_path = sqlite_database_path(get_settings().data_dir)
    uvicorn.run(create_app(database_path), host=host, port=port)
