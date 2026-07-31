from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Collection
from pathlib import Path
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from marygenai.mcp_server.server import create_mcp_server

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_QUERY_TOKEN_FIELDS = frozenset({"access_token", "api_key", "key", "token"})
_PILOT_QUERY_TOKEN_FIELD = "key"


def hash_access_token(token: str) -> str:
    """Hash a high-entropy access token for storage and comparison."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_token_sha256(value: str) -> str:
    """Validate a lowercase SHA-256 digest supplied through configuration."""
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ValueError("MCP bearer token SHA-256 must contain 64 lowercase hexadecimal digits.")
    return normalized


class BearerTokenMiddleware:
    """Require a pre-shared bearer token without logging or persisting it."""

    def __init__(
        self,
        app: ASGIApp,
        token_sha256: str,
        *,
        public_paths: Collection[str] = ("/health",),
        allow_query_token: bool = False,
    ) -> None:
        self.app = app
        self.token_sha256 = validate_token_sha256(token_sha256)
        self.public_paths = frozenset(public_paths)
        self.allow_query_token = allow_query_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.public_paths:
            await self.app(scope, receive, send)
            return

        query = parse_qs(
            scope.get("query_string", b"").decode("utf-8", errors="replace"),
            keep_blank_values=True,
        )
        query_token_fields = _QUERY_TOKEN_FIELDS.intersection(query)
        disallowed_query_fields = query_token_fields - {_PILOT_QUERY_TOKEN_FIELD}
        if disallowed_query_fields or (
            _PILOT_QUERY_TOKEN_FIELD in query and not self.allow_query_token
        ):
            await JSONResponse(
                {"error": "Access tokens are not accepted in the request URI."},
                status_code=400,
            )(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "")
        scheme, separator, header_token = authorization.partition(" ")
        valid_header_shape = (
            separator == " "
            and scheme.casefold() == "bearer"
            and bool(header_token)
        )
        query_tokens = query.get(_PILOT_QUERY_TOKEN_FIELD, [])
        if len(query_tokens) > 1 or (authorization and query_tokens):
            await JSONResponse(
                {"error": "Provide exactly one access credential."},
                status_code=400,
            )(scope, receive, send)
            return
        query_token = query_tokens[0] if query_tokens else ""
        token = header_token if valid_header_shape else query_token
        authorized = bool(token) and hmac.compare_digest(
            hash_access_token(token), self.token_sha256
        )
        if not authorized:
            await JSONResponse(
                {"error": "A valid bearer token is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)


def create_http_app(
    index_path: Path,
    *,
    bearer_token_sha256: str | None,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
    allow_query_token: bool = False,
) -> ASGIApp:
    """Create the stateless Streamable HTTP application for local or Lambda use."""
    mcp = create_mcp_server(
        index_path,
        stateless_http=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )

    @mcp.custom_route("/health", methods=["GET"], name="health")
    async def health(_request: object) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "marygenai-candidate-retrieval",
                "trust_level": "ai_classified_candidate",
                "medical_advice": False,
            }
        )

    app = mcp.streamable_http_app()
    if bearer_token_sha256 is None:
        return app
    return BearerTokenMiddleware(
        app,
        bearer_token_sha256,
        allow_query_token=allow_query_token,
    )
