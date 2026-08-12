from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mangum import Mangum
from starlette.types import ASGIApp, Receive, Scope, Send

from marygenai.mcp_server.http import (
    BearerTokenMiddleware,
    create_http_app,
    validate_token_sha256,
)
from marygenai.viewer.app import create_app as create_viewer_app


@dataclass(frozen=True)
class IndexArtifactConfig:
    bucket: str
    key: str
    sha256: str
    local_path: Path = Path("/tmp/marygenai_candidate_retrieval_v1.duckdb")


class ReadOnlyGatewayApp:
    """Route Viewer HTTP requests separately from the MCP ASGI lifecycle."""

    def __init__(self, *, mcp_app: ASGIApp, viewer_app: ASGIApp) -> None:
        self.mcp_app = mcp_app
        self.viewer_app = viewer_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/api/viewer/"):
            await self.viewer_app(scope, receive, send)
            return
        await self.mcp_app(scope, receive, send)


def _environment_flag(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_index(
    config: IndexArtifactConfig,
    *,
    s3_client: Any | None = None,
) -> Path:
    """Copy an immutable DuckDB snapshot from S3 and verify its content hash."""
    expected_sha256 = validate_token_sha256(config.sha256)
    if config.local_path.exists() and _sha256_file(config.local_path) == expected_sha256:
        return config.local_path

    config.local_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = config.local_path.with_suffix(".download")
    if temporary_path.exists():
        temporary_path.unlink()

    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")
    s3_client.download_file(config.bucket, config.key, str(temporary_path))

    actual_sha256 = _sha256_file(temporary_path)
    if actual_sha256 != expected_sha256:
        temporary_path.unlink(missing_ok=True)
        raise ValueError(
            f"Downloaded retrieval index SHA-256 mismatch: expected "
            f"{expected_sha256}, received {actual_sha256}."
        )
    temporary_path.replace(config.local_path)
    return config.local_path


def create_gateway_app(
    index_path: Path,
    *,
    mcp_token_sha256: str,
    viewer_token_sha256: str,
    allowed_hosts: list[str],
    allow_mcp_query_token: bool = False,
) -> ASGIApp:
    """Create isolated authenticated MCP and Viewer routes over one snapshot."""
    mcp_app = create_http_app(
        index_path,
        bearer_token_sha256=mcp_token_sha256,
        allowed_hosts=allowed_hosts,
        allow_query_token=allow_mcp_query_token,
    )
    viewer_app = BearerTokenMiddleware(
        create_viewer_app(index_path, allowed_hosts=allowed_hosts),
        viewer_token_sha256,
        public_paths=(),
        allow_query_token=False,
    )
    return ReadOnlyGatewayApp(mcp_app=mcp_app, viewer_app=viewer_app)


def create_lambda_adapter(*, s3_client: Any | None = None) -> Mangum:
    """Create the API Gateway adapter from Lambda environment configuration."""
    config = IndexArtifactConfig(
        bucket=os.environ["MARYGENAI_INDEX_S3_BUCKET"],
        key=os.environ["MARYGENAI_INDEX_S3_KEY"],
        sha256=os.environ["MARYGENAI_INDEX_SHA256"],
        local_path=Path(
            os.environ.get(
                "MARYGENAI_INDEX_LOCAL_PATH",
                "/tmp/marygenai_candidate_retrieval_v1.duckdb",
            )
        ),
    )
    mcp_token_sha256 = validate_token_sha256(
        os.environ["MARYGENAI_MCP_BEARER_TOKEN_SHA256"]
    )
    viewer_token_sha256 = validate_token_sha256(
        os.environ["MARYGENAI_VIEWER_BEARER_TOKEN_SHA256"]
    )
    allowed_hosts = [
        value.strip()
        for value in os.environ["MARYGENAI_MCP_ALLOWED_HOSTS"].split(",")
        if value.strip()
    ]
    if not allowed_hosts:
        raise ValueError("MARYGENAI_MCP_ALLOWED_HOSTS must contain at least one host.")
    index_path = materialize_index(config, s3_client=s3_client)
    app = create_gateway_app(
        index_path,
        mcp_token_sha256=mcp_token_sha256,
        viewer_token_sha256=viewer_token_sha256,
        allowed_hosts=allowed_hosts,
        allow_mcp_query_token=_environment_flag("MARYGENAI_MCP_ALLOW_QUERY_TOKEN"),
    )
    return Mangum(
        app,
        lifespan="auto",
        api_gateway_base_path="/",
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle one request with a fresh stateless read-only gateway lifecycle."""
    return create_lambda_adapter()(event, context)
