from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from marygenai.retrieval.index import DEFAULT_INDEX_RELATIVE_PATH
from marygenai.retrieval.models import SearchRequest
from marygenai.retrieval.service import RetrievalService
from marygenai.settings import get_settings


def create_mcp_server(index_path: Path | None = None) -> FastMCP:
    """Create a closed-world MCP server over a read-only candidate index."""
    resolved_path = index_path or (get_settings().data_dir / DEFAULT_INDEX_RELATIVE_PATH)
    service = RetrievalService(resolved_path)
    mcp = FastMCP(
        "MaryGenAI Candidate Evidence Retrieval",
        instructions=(
            "Search a closed local index of cannabinoid scientific candidate evidence. "
            "Results are not reviewed clinical truth, medical advice, or treatment "
            "recommendations. Preserve uncertainty, provenance, and source links."
        ),
        json_response=True,
    )
    read_only = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )

    @mcp.tool(
        title="Search MaryGenAI studies",
        description=(
            "Search AI-classified candidate evidence with explicit filters. The server never "
            "silently relaxes filters and returns the effective query, match explanations, "
            "uncertainty, review state, and source identity."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def search_studies(request: SearchRequest) -> dict[str, Any]:
        return service.search(request).model_dump(mode="json")

    @mcp.tool(
        title="Get MaryGenAI study detail",
        description=(
            "Get one complete candidate record with source path and hash, evidence spans, "
            "grounding-review flags, uncertainty, versions, provenance, and trust boundary."
        ),
        annotations=read_only,
        structured_output=True,
    )
    def get_study(document_id: str) -> dict[str, Any]:
        return service.get_study(document_id).model_dump(mode="json")

    @mcp.tool(
        title="Get MaryGenAI search facets",
        description=(
            "Count canonical retrieval facets over the explicitly filtered result set before "
            "pagination. Useful for constructing or refining a search query."
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
            "known v3 schema gaps, index runs, and the candidate-evidence trust boundary."
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
        return json.dumps(service.manifest(), ensure_ascii=False, sort_keys=True)

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
        return service.get_study(document_id).model_dump_json()

    return mcp
