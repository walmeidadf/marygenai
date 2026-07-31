from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from marygenai.mcp_server.http import create_http_app, validate_token_sha256
from marygenai.mcp_server.server import create_mcp_server
from marygenai.retrieval.common import DEFAULT_INDEX_RELATIVE_PATH
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


@app.command("serve-http")
def serve_http(
    index_path: Annotated[
        Path,
        typer.Option("--index-path", help="Read-only candidate retrieval DuckDB path."),
    ] = DEFAULT_INDEX_PATH,
    host: Annotated[str, typer.Option("--host", help="HTTP bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
    require_auth: Annotated[
        bool,
        typer.Option("--require-auth/--no-auth", help="Require the configured bearer token."),
    ] = True,
    allow_query_token: Annotated[
        bool,
        typer.Option(
            "--allow-query-token/--no-query-token",
            help="Allow the explicit dev-only ?key= compatibility credential.",
        ),
    ] = False,
) -> None:
    """Serve the closed candidate index over stateless MCP Streamable HTTP."""
    token_sha256 = get_settings().mcp_bearer_token_sha256 if require_auth else None
    if require_auth:
        if token_sha256 is None:
            raise typer.BadParameter(
                "MARYGENAI_MCP_BEARER_TOKEN_SHA256 is required unless --no-auth is used."
            )
        token_sha256 = validate_token_sha256(token_sha256)
    app_instance = create_http_app(
        index_path,
        bearer_token_sha256=token_sha256,
        allow_query_token=allow_query_token,
    )
    uvicorn.run(app_instance, host=host, port=port)


@app.command("generate-access-token")
def generate_access_token(
    output_path: Annotated[
        Path | None,
        typer.Option(
            "--output-path",
            help="Optional ignored file for the plaintext token and its SHA-256 digest.",
        ),
    ] = None,
) -> None:
    """Generate one high-entropy pilot token and its storable SHA-256 digest."""
    token = f"mary_{secrets.token_urlsafe(32)}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record = {
        "token": token,
        "sha256": digest,
        "notice": "Store the token securely. Only its SHA-256 digest belongs in config.",
    }
    if output_path is not None:
        resolved_path = output_path.resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                resolved_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError as error:
            raise typer.BadParameter(
                f"Refusing to overwrite existing token file: {resolved_path}"
            ) from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(record, file, indent=2, sort_keys=True)
            file.write("\n")
        typer.echo(
            json.dumps(
                {
                    "output_path": str(resolved_path),
                    "sha256": digest,
                    "notice": "The plaintext token was written once with mode 0600.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    typer.echo(
        json.dumps(
            record,
            indent=2,
            sort_keys=True,
        )
    )
