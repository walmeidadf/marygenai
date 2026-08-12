from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from marygenai.mcp_server.projection import project_mcp_payload
from marygenai.retrieval.common import DEFAULT_INDEX_RELATIVE_PATH
from marygenai.retrieval.models import SearchRequest
from marygenai.retrieval.service import RetrievalService
from marygenai.settings import get_settings


def create_mcp_server(
    index_path: Path | None = None,
    *,
    stateless_http: bool = False,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastMCP:
    """Create a closed-world MCP server over a read-only candidate index."""
    resolved_path = index_path or (get_settings().data_dir / DEFAULT_INDEX_RELATIVE_PATH)
    service = RetrievalService(resolved_path)
    mcp = FastMCP(
        "MaryGenAI Candidate Evidence Retrieval",
        instructions=(
            "Search a closed local index of cannabinoid scientific candidate evidence. "
            "The indexed sources and candidate metadata are primarily English. Translate "
            "non-English scientific questions into concise English query terms and structured "
            "filter labels before calling search_studies or get_facets; preserve identifiers "
            "and source evidence unchanged, then answer the user in their language. Describe "
            "search results only as AI-classified candidate matches, not validated relevant "
            "studies. A zero-result search means only that the effective query retrieved no "
            "candidate records from the current index; never infer absence from the scientific "
            "literature. Include projected_identity.preferred_access_url whenever citing a "
            "result. Call get_study for shortlisted records before making detailed evidence "
            "claims, and separate direct matches from tangential matches. Never send "
            "patient-identifying information. "
            "Results are not reviewed clinical truth, medical advice, or treatment "
            "recommendations. Preserve uncertainty, provenance, and source links."
        ),
        json_response=True,
        stateless_http=stateless_http,
        streamable_http_path="/mcp",
        transport_security=(
            TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=allowed_hosts,
                allowed_origins=allowed_origins or [],
            )
            if allowed_hosts is not None
            else None
        ),
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(
        title="Search MaryGenAI candidate matches",
        description=(
            "Search AI-classified candidate evidence with explicit filters. Translate "
            "non-English scientific concepts into concise English query terms and filter "
            "labels before calling this tool. The server never silently relaxes filters and "
            "returns the effective query, match explanations, uncertainty, review state, and "
            "source identity. Describe outputs only as candidate matches; zero matches do not "
            "establish absence from the scientific literature. Include each cited result's "
            "projected_identity.preferred_access_url, separate direct from tangential matches, "
            "and call get_study before making detailed evidence claims."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def search_studies(request: SearchRequest) -> dict[str, Any]:
        return project_mcp_payload(service.search(request).model_dump(mode="json"))

    @mcp.tool(
        title="Get MaryGenAI study detail",
        description=(
            "Get one complete candidate record with source path and hash, evidence spans, "
            "grounding-review flags, uncertainty, versions, provenance, preferred physician "
            "access URL, and trust boundary. Use this tool for shortlisted records before "
            "making detailed evidence claims; the returned classification remains candidate "
            "metadata requiring human judgment."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def get_study(document_id: str) -> dict[str, Any]:
        return project_mcp_payload(service.get_study(document_id).model_dump(mode="json"))

    @mcp.tool(
        title="Get MaryGenAI search facets",
        description=(
            "Count canonical retrieval facets over the explicitly filtered result set before "
            "pagination. Use English labels after translating non-English scientific concepts. "
            "Useful for constructing or refining a search query."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def get_facets(request: SearchRequest, top: int = 25) -> dict[str, Any]:
        return service.facets(request, top=top).model_dump(mode="json")

    @mcp.tool(
        title="Get MaryGenAI search capabilities",
        description=(
            "Describe supported filters, question types, pagination, ranking semantics, "
            "language and host-translation requirements, presentation rules, known v3 schema "
            "gaps, index runs, and the candidate-evidence trust boundary."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def get_search_capabilities() -> dict[str, Any]:
        return service.capabilities().model_dump(mode="json")

    @mcp.resource(
        "marygenai://index/manifest",
        title="MaryGenAI retrieval index manifest",
        description=(
            "Build provenance, input hashes, included runs, limitations, and trust boundary."
        ),
        mime_type="application/json",
    )
    def index_manifest() -> str:
        return service.public_manifest().model_dump_json()

    @mcp.resource(
        "marygenai://index/capabilities",
        title="MaryGenAI search capabilities",
        description="Machine-readable filters, limits, schema gaps, and score semantics.",
        mime_type="application/json",
    )
    def index_capabilities() -> str:
        return service.capabilities().model_dump_json()

    @mcp.resource(
        "marygenai://studies/{document_id}",
        title="MaryGenAI candidate study detail",
        description="Complete read-only candidate classification and source provenance.",
        mime_type="application/json",
    )
    def study_resource(document_id: str) -> str:
        detail = service.get_study(document_id).model_dump(mode="json")
        return json.dumps(project_mcp_payload(detail), ensure_ascii=False, sort_keys=True)

    return mcp
