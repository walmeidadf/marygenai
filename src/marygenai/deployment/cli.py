from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from marygenai.deployment.package import build_lambda_package

app = typer.Typer(help="Build local deployment artifacts without creating cloud resources.")


@app.command("build-lambda")
def build_lambda(
    output_path: Annotated[
        Path,
        typer.Option("--output-path", help="Generated Lambda ZIP path."),
    ] = Path("build/lambda/marygenai-mcp.zip"),
    requirements_path: Annotated[
        Path,
        typer.Option("--requirements-path", help="Locked Lambda requirements path."),
    ] = Path("infra/lambda/requirements.txt"),
    source_root: Annotated[
        Path,
        typer.Option("--source-root", help="Python source root containing marygenai."),
    ] = Path("src"),
) -> None:
    """Build the read-only MCP Lambda package for Linux x86_64."""
    result = build_lambda_package(
        output_path=output_path,
        requirements_path=requirements_path,
        source_root=source_root,
    )
    typer.echo(json.dumps(result, indent=2, sort_keys=True))
