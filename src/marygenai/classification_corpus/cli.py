from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.classification.pipeline import DEFAULT_OPENAI_MODEL, DEFAULT_PROMPT_SOURCE_CHARS
from marygenai.classification_corpus.pipeline import write_corpus_rollup
from marygenai.classification_corpus.pubmed_canary import (
    DEFAULT_CORPUS_VERSION,
    DEFAULT_TARGET_SIZE,
    prepare_pubmed_canary,
)
from marygenai.persistence.sqlite import sqlite_database_path
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


@app.command("prepare-pubmed-canary")
def prepare_pubmed_canary_command(
    target_size: Annotated[
        int,
        typer.Option("--target-size", min=1, max=100, help="Maximum canary documents."),
    ] = DEFAULT_TARGET_SIZE,
    corpus_version: Annotated[
        str,
        typer.Option("--corpus-version", help="Immutable canary corpus version."),
    ] = DEFAULT_CORPUS_VERSION,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="Read-only SQLite candidate database path."),
    ] = None,
    prepare_prompt_packets: Annotated[
        bool,
        typer.Option(
            "--prepare-prompt-packets/--no-prepare-prompt-packets",
            help="Build local prompt packets without calling a provider.",
        ),
    ] = True,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_provider: Annotated[
        str,
        typer.Option("--target-model-provider", help="Provider planned for a later paid run."),
    ] = "openai",
    target_model_name: Annotated[
        str,
        typer.Option("--target-model-name", help="Model planned for a later paid run."),
    ] = DEFAULT_OPENAI_MODEL,
) -> None:
    """Audit PubMed candidates and freeze a local provider-free canary."""
    settings = get_settings()
    result = prepare_pubmed_canary(
        storage=LocalStorage(settings.data_dir),
        database_path=database_path or sqlite_database_path(settings.data_dir),
        target_size=target_size,
        corpus_version=corpus_version,
        prepare_prompt_packets=prepare_prompt_packets,
        max_source_chars=max_source_chars,
        target_model_provider=target_model_provider,
        target_model_name=target_model_name,
    )
    console.print(result)
