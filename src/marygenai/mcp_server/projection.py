from __future__ import annotations

import hashlib
from typing import Any

_PATH_FIELDS = frozenset(
    {
        "evaluation_report_paths",
        "exclusions_path",
        "index_path",
        "path",
        "source_artifact_path",
        "source_corpus_path",
        "source_text_path",
    }
)
_ARTIFACT_REFERENCE_PREFIX = "artifact-ref://sha256/"


def _artifact_reference(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{_ARTIFACT_REFERENCE_PREFIX}{digest}"


def _project_path_value(value: Any) -> Any:
    if isinstance(value, str):
        return _artifact_reference(value) if value else value
    if isinstance(value, list):
        return [_project_path_value(item) for item in value]
    return value


def project_mcp_payload(value: Any) -> Any:
    """Replace stored filesystem paths with stable, non-resolvable references."""
    if isinstance(value, dict):
        return {
            key: (
                _project_path_value(item)
                if key in _PATH_FIELDS
                else project_mcp_payload(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [project_mcp_payload(item) for item in value]
    return value
