"""Candidate study classification contracts."""

from marygenai.classification.models import (
    CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION,
    CandidateClassificationLabel,
    CandidateClassificationPromptPacket,
    CandidateStudyClassification,
    ClassificationRunError,
    EvidenceSpan,
    PopulationOrModel,
)

__all__ = [
    "CANDIDATE_STUDY_CLASSIFICATION_SCHEMA_VERSION",
    "CandidateClassificationLabel",
    "CandidateClassificationPromptPacket",
    "CandidateStudyClassification",
    "ClassificationRunError",
    "EvidenceSpan",
    "PopulationOrModel",
]
