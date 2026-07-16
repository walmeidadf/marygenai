"""Read-only candidate-evidence retrieval index."""

from marygenai.retrieval.index import build_retrieval_index
from marygenai.retrieval.service import RetrievalService

__all__ = ["RetrievalService", "build_retrieval_index"]
