from __future__ import annotations

from typing import Annotated

import typer
from rich.console import Console

from marygenai.classification_corpus.pipeline import write_corpus_rollup
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Build classification-ready corpus rollups from local artifacts.")
console = Console()


@app.callback()
def main() -> None:
    """Run classification corpus commands."""


@app.command("rollup")
def rollup(
    sample_size: Annotated[
        int,
        typer.Option("--sample-size", min=1, help="Smoke-test sample size to write."),
    ] = 30,
    write_sample: Annotated[
        bool,
        typer.Option("--write-sample/--no-write-sample", help="Write a stratified sample packet."),
    ] = True,
) -> None:
    """Build a deduplicated local classification corpus rollup."""
    settings = get_settings()
    result = write_corpus_rollup(
        storage=LocalStorage(settings.data_dir),
        sample_size=sample_size,
        write_sample=write_sample,
    )
    console.print(result)
