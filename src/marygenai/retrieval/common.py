from __future__ import annotations

import re
import unicodedata
from pathlib import Path

DEFAULT_INDEX_RELATIVE_PATH = Path(
    "normalized/retrieval_indexes/marygenai_candidate_retrieval_v1.duckdb"
)

_TRAILING_ABBREVIATION = re.compile(r"\s*\(([^()]*)\)\s*$")
_MATCH_KEY_PUNCTUATION = re.compile(r"[^a-z0-9]+")


def normalize_match_key(value: str) -> str:
    """Return a stable, conservative key for case-insensitive facet matching."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    abbreviation = _TRAILING_ABBREVIATION.search(normalized)
    if abbreviation:
        token = abbreviation.group(1).strip()
        if token.lower() != "unspecified" and len(token) <= 10:
            normalized = normalized[: abbreviation.start()]
    return _MATCH_KEY_PUNCTUATION.sub(" ", normalized.casefold()).strip()
