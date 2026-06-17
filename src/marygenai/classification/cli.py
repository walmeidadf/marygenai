from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from marygenai.classification.pipeline import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_SOURCE_CHARS,
    build_classification_prompt_packets,
    run_classification_smoke,
)
from marygenai.settings import get_settings
from marygenai.storage import LocalStorage

app = typer.Typer(help="Run candidate classification validation workflows.")
console = Console()


@app.callback()
def main() -> None:
    """Run candidate classification commands."""


@app.command("run-smoke")
def run_smoke(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=30, help="Maximum sample records to validate."),
    ] = 5,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification sample or corpus JSONL path."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--no-dry-run", help="Use deterministic mock outputs."),
    ] = True,
    provider: Annotated[
        str,
        typer.Option("--provider", help="Provider for --no-dry-run. Currently only openai."),
    ] = "openai",
    model: Annotated[
        str,
        typer.Option("--model", help="Model for --no-dry-run."),
    ] = DEFAULT_OPENAI_MODEL,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = 6_000,
    max_completion_tokens: Annotated[
        int,
        typer.Option("--max-completion-tokens", min=500, max=8_000),
    ] = DEFAULT_MAX_COMPLETION_TOKENS,
) -> None:
    """Validate candidate classification schema on a tiny local sample."""
    settings = get_settings()
    result = run_classification_smoke(
        storage=LocalStorage(settings.data_dir),
        limit=limit,
        input_path=input_path,
        dry_run=dry_run,
        provider=provider,
        model=model,
        max_source_chars=max_source_chars,
        max_completion_tokens=max_completion_tokens,
    )
    console.print(result)


@app.command("build-prompt-packets")
def build_prompt_packets(
    limit: Annotated[
        int,
        typer.Option("--limit", min=1, max=30, help="Maximum sample records to packetize."),
    ] = 5,
    input_path: Annotated[
        Path | None,
        typer.Option("--input-path", help="Classification sample or corpus JSONL path."),
    ] = None,
    max_source_chars: Annotated[
        int,
        typer.Option("--max-source-chars", min=1_000, max=80_000),
    ] = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_provider: Annotated[
        str | None,
        typer.Option("--target-model-provider", help="Provider planned for later real run."),
    ] = None,
    target_model_name: Annotated[
        str | None,
        typer.Option("--target-model-name", help="Model planned for later real run."),
    ] = None,
) -> None:
    """Build prompt packets for inspection without calling an LLM."""
    settings = get_settings()
    result = build_classification_prompt_packets(
        storage=LocalStorage(settings.data_dir),
        limit=limit,
        input_path=input_path,
        max_source_chars=max_source_chars,
        target_model_provider=target_model_provider,
        target_model_name=target_model_name,
    )
    console.print(result)
