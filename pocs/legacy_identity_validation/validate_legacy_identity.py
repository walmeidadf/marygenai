"""Validate English legacy context identity against local SQLite.

This POC is intentionally audit-only. It writes bucketed JSONL artifacts but
does not update review state, review items, or structured identity decisions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.table import Table

from marygenai.initial_load.files import normalize_title
from marygenai.persistence.sqlite import sqlite_database_path
from marygenai.review.repository import connect_initialized_review_database
from marygenai.settings import get_settings

DEFAULT_INPUT_PATH = Path(
    "data/normalized/legacy_english_context/20260525T235818Z_legacy_english_context_records.jsonl"
)
DEFAULT_OUTPUT_SUBDIR = Path("normalized/legacy_identity_validation")
BUCKETS = (
    "exact_identifier_match",
    "strong_title_embedding_match",
    "ambiguous_identity",
    "no_local_match",
)
IDENTIFIER_FIELDS = ("pmid", "pmcid", "doi", "canonical_url")
EMBEDDING_DIMENSIONS = 384
TOKEN_RE = re.compile(r"[a-z0-9]+")

console = Console()
app = typer.Typer(help="Validate legacy English context identity locally.")


@dataclass(frozen=True)
class BaselineDocument:
    document_id: str
    title: str | None
    normalized_title: str | None
    publication_year: int | None
    canonical_url: str | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    review_state: str


@dataclass(frozen=True)
class IdentityCandidate:
    document_id: str
    match_method: str
    review_state: str
    title: str | None
    publication_year: int | None
    matched_identifiers: dict[str, str]
    title_similarity: float | None
    embedding_similarity: float | None
    score: float
    evidence: dict[str, Any]


@dataclass(frozen=True)
class IdentityValidationRecord:
    context_id: str
    bucket: str
    title: str | None
    normalized_title: str | None
    publication_year: int | None
    pmid: str | None
    pmcid: str | None
    doi: str | None
    canonical_url: str | None
    selected_document_id: str | None
    candidates: list[IdentityCandidate]
    provenance: dict[str, Any]


@app.callback()
def main() -> None:
    """Run local identity-validation commands."""


@app.command()
def run(
    input_path: Annotated[
        Path,
        typer.Option("--input-path", help="Normalized legacy English context JSONL."),
    ] = DEFAULT_INPUT_PATH,
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite review database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for validation outputs."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Limit input records for smoke runs."),
    ] = None,
    strong_embedding_threshold: Annotated[
        float,
        typer.Option(
            "--strong-embedding-threshold",
            help="Minimum embedding score for strong title matches.",
        ),
    ] = 0.86,
    strong_title_threshold: Annotated[
        float,
        typer.Option(
            "--strong-title-threshold",
            help="Minimum fuzzy title score for strong title matches.",
        ),
    ] = 0.78,
    ambiguity_margin: Annotated[
        float,
        typer.Option(
            "--ambiguity-margin",
            help="Score gap below which close candidates are ambiguous.",
        ),
    ] = 0.03,
) -> None:
    """Bucket each English legacy context by local identity evidence."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_started_at = datetime.now(UTC)
    run_id = run_started_at.strftime("%Y%m%dT%H%M%SZ")

    contexts = load_context_records(input_path, limit=limit)
    documents = load_baseline_documents(resolved_database_path)
    validator = LocalIdentityValidator(
        documents,
        strong_embedding_threshold=strong_embedding_threshold,
        strong_title_threshold=strong_title_threshold,
        ambiguity_margin=ambiguity_margin,
    )
    records = [validator.validate(context) for context in contexts]

    records_path = resolved_output_dir / f"{run_id}_legacy_identity_validation_records.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_legacy_identity_validation_summary.json"
    write_jsonl(records_path, records)
    bucket_paths = write_bucket_jsonl(resolved_output_dir, run_id, records)
    summary = build_summary(
        records,
        input_path=input_path,
        database_path=resolved_database_path,
        records_path=records_path,
        bucket_paths=bucket_paths,
        run_started_at=run_started_at,
        thresholds={
            "strong_embedding_threshold": strong_embedding_threshold,
            "strong_title_threshold": strong_title_threshold,
            "ambiguity_margin": ambiguity_margin,
        },
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_summary(summary)


@app.command("export-confirmed")
def export_confirmed(
    context_path: Annotated[
        Path,
        typer.Option("--context-path", help="Normalized legacy English context JSONL."),
    ] = DEFAULT_INPUT_PATH,
    validation_path: Annotated[
        Path,
        typer.Option("--validation-path", help="Legacy identity validation records JSONL."),
    ] = Path(
        "data/normalized/legacy_identity_validation/"
        "20260526T110937Z_legacy_identity_validation_records.jsonl"
    ),
    database_path: Annotated[
        Path | None,
        typer.Option("--database-path", help="SQLite review database path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Directory for confirmed identity outputs."),
    ] = None,
) -> None:
    """Export identity-confirmed English contexts for downstream scientific triage."""
    settings = get_settings()
    resolved_database_path = database_path or sqlite_database_path(settings.data_dir)
    resolved_output_dir = output_dir or settings.data_dir / DEFAULT_OUTPUT_SUBDIR
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    contexts_by_id = {record["context_id"]: record for record in load_context_records(context_path)}
    validation_records = load_context_records(validation_path)
    with connect_initialized_review_database(resolved_database_path) as connection:
        confirmed_records = build_confirmed_identity_records(
            validation_records,
            contexts_by_id=contexts_by_id,
            connection=connection,
        )

    records_path = resolved_output_dir / f"{run_id}_identity_confirmed_for_triage.jsonl"
    summary_path = resolved_output_dir / f"{run_id}_identity_confirmed_for_triage_summary.json"
    with records_path.open("w", encoding="utf-8") as file:
        for record in confirmed_records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    summary = build_confirmed_identity_summary(
        confirmed_records,
        context_path=context_path,
        validation_path=validation_path,
        database_path=resolved_database_path,
        records_path=records_path,
    )
    summary["summary_path"] = str(summary_path)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print_confirmed_summary(summary)


class LocalIdentityValidator:
    def __init__(
        self,
        documents: list[BaselineDocument],
        *,
        strong_embedding_threshold: float,
        strong_title_threshold: float,
        ambiguity_margin: float,
    ) -> None:
        self.documents_by_id = {document.document_id: document for document in documents}
        self.identifier_index = build_identifier_index(documents)
        self.year_index = build_year_index(documents)
        self.token_index = build_token_index(documents)
        self.embeddings = {
            document.document_id: title_embedding(document.normalized_title or "")
            for document in documents
            if document.normalized_title
        }
        self.strong_embedding_threshold = strong_embedding_threshold
        self.strong_title_threshold = strong_title_threshold
        self.ambiguity_margin = ambiguity_margin

    def validate(self, context: dict[str, Any]) -> IdentityValidationRecord:
        identifier_candidates = self.identifier_candidates(context)
        if identifier_candidates:
            bucket = (
                "exact_identifier_match"
                if count_candidate_documents(identifier_candidates) == 1
                else "ambiguous_identity"
            )
            return build_validation_record(context, bucket, identifier_candidates)
        if has_strong_identifier(context):
            return build_validation_record(context, "no_local_match", [])

        title_candidates = self.title_embedding_candidates(context)
        if not title_candidates:
            return build_validation_record(context, "no_local_match", [])

        top = title_candidates[0]
        close_candidates = [
            candidate
            for candidate in title_candidates[1:4]
            if top.score - candidate.score <= self.ambiguity_margin
        ]
        if close_candidates:
            return build_validation_record(
                context,
                "ambiguous_identity",
                title_candidates[: 1 + len(close_candidates)],
            )
        if (
            top.embedding_similarity is not None
            and top.title_similarity is not None
            and top.embedding_similarity >= self.strong_embedding_threshold
            and top.title_similarity >= self.strong_title_threshold
            and top.evidence["year_compatible"]
        ):
            return build_validation_record(context, "strong_title_embedding_match", [top])
        return build_validation_record(context, "no_local_match", title_candidates[:3])

    def identifier_candidates(self, context: dict[str, Any]) -> list[IdentityCandidate]:
        matches: dict[str, IdentityCandidate] = {}
        matched_by_document: dict[str, dict[str, str]] = defaultdict(dict)
        for field in IDENTIFIER_FIELDS:
            value = normalize_identifier(field, context.get(field))
            if not value:
                continue
            for document_id in self.identifier_index.get((field, value), []):
                matched_by_document[document_id][field] = value

        for document_id, identifiers in matched_by_document.items():
            document = self.documents_by_id[document_id]
            matches[document_id] = IdentityCandidate(
                document_id=document.document_id,
                match_method="strong_identifier",
                review_state=document.review_state,
                title=document.title,
                publication_year=document.publication_year,
                matched_identifiers=dict(sorted(identifiers.items())),
                title_similarity=compare_titles(
                    context.get("normalized_title"),
                    document.normalized_title,
                ),
                embedding_similarity=None,
                score=1.0 + (0.05 * len(identifiers)),
                evidence={
                    "matched_identifier_fields": sorted(identifiers),
                    "year_compatible": years_compatible(
                        context.get("publication_year"),
                        document.publication_year,
                    ),
                },
            )
        return sorted(
            matches.values(),
            key=lambda candidate: (-candidate.score, candidate.document_id),
        )

    def title_embedding_candidates(self, context: dict[str, Any]) -> list[IdentityCandidate]:
        normalized_title = context.get("normalized_title") or normalize_title(context.get("title"))
        if not normalized_title:
            return []
        context_year = context.get("publication_year")
        candidate_ids = self.candidate_document_ids(normalized_title, context_year)
        if not candidate_ids:
            return []

        context_embedding = title_embedding(normalized_title)
        scored: list[IdentityCandidate] = []
        for document_id in candidate_ids:
            document = self.documents_by_id[document_id]
            document_embedding = self.embeddings.get(document_id)
            if document_embedding is None:
                continue
            title_similarity = compare_titles(normalized_title, document.normalized_title)
            embedding_similarity = cosine_similarity(context_embedding, document_embedding)
            year_compatible = years_compatible(context_year, document.publication_year)
            year_score = 0.08 if year_compatible else -0.12
            score = (0.68 * embedding_similarity) + (0.32 * (title_similarity or 0.0)) + year_score
            scored.append(
                IdentityCandidate(
                    document_id=document.document_id,
                    match_method="title_year_local_embedding",
                    review_state=document.review_state,
                    title=document.title,
                    publication_year=document.publication_year,
                    matched_identifiers={},
                    title_similarity=round(title_similarity or 0.0, 6),
                    embedding_similarity=round(embedding_similarity, 6),
                    score=round(score, 6),
                    evidence={
                        "year_compatible": year_compatible,
                        "context_publication_year": context_year,
                        "candidate_publication_year": document.publication_year,
                        "embedding_backend": "local_hashing_384d",
                    },
                )
            )
        return sorted(scored, key=lambda candidate: (-candidate.score, candidate.document_id))[:10]

    def candidate_document_ids(self, normalized_title: str, year: int | None) -> set[str]:
        tokens = title_tokens(normalized_title)
        if not tokens:
            return set()
        token_counts: Counter[str] = Counter()
        for token in tokens:
            token_counts.update(self.token_index.get(token, set()))
        if not token_counts:
            return set()

        candidate_ids = {
            document_id
            for document_id, overlap in token_counts.most_common(120)
            if overlap >= max(1, min(3, len(tokens) // 4))
        }
        if year is not None:
            compatible_year_ids = set().union(
                self.year_index.get(year - 1, set()),
                self.year_index.get(year, set()),
                self.year_index.get(year + 1, set()),
                self.year_index.get(None, set()),
            )
            candidate_ids &= compatible_year_ids
        return candidate_ids


def load_context_records(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if limit is not None and len(records) >= limit:
                break
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                msg = f"Invalid JSON on {path}:{line_number}: {exc}"
                raise ValueError(msg) from exc
    return records


def load_baseline_documents(database_path: Path) -> list[BaselineDocument]:
    with connect_initialized_review_database(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
                d.document_id,
                d.primary_title,
                d.publication_year,
                d.canonical_url,
                d.pmid,
                d.pmcid,
                d.doi,
                d.review_state,
                p.normalized_title
            FROM document AS d
            LEFT JOIN publication AS p ON p.document_id = d.document_id
            WHERE d.lifecycle_state = 'active'
            """
        ).fetchall()
    return [
        BaselineDocument(
            document_id=row["document_id"],
            title=row["primary_title"],
            normalized_title=row["normalized_title"] or normalize_title(row["primary_title"]),
            publication_year=row["publication_year"],
            canonical_url=canonicalize_url(row["canonical_url"]),
            pmid=normalize_identifier("pmid", row["pmid"]),
            pmcid=normalize_identifier("pmcid", row["pmcid"]),
            doi=normalize_identifier("doi", row["doi"]),
            review_state=row["review_state"],
        )
        for row in rows
    ]


def build_confirmed_identity_records(
    validation_records: list[dict[str, Any]],
    *,
    contexts_by_id: dict[str, dict[str, Any]],
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for validation in validation_records:
        document_id = validation.get("selected_document_id")
        if not document_id or validation.get("bucket") not in {
            "exact_identifier_match",
            "strong_title_embedding_match",
        }:
            continue
        workflow = identity_workflow_state(connection, document_id)
        if workflow["confirmation_status"] not in {
            "trusted_legacy_reference_no_identity_queue",
            "workflow_resolved_identity_review",
        }:
            continue
        context = contexts_by_id.get(validation["context_id"])
        if context is None:
            continue
        records.append(
            {
                "context_id": validation["context_id"],
                "document_id": document_id,
                "identity_confirmation_status": workflow["confirmation_status"],
                "identity_validation_bucket": validation["bucket"],
                "review_item_id": workflow["review_item_id"],
                "review_item_status": workflow["review_item_status"],
                "latest_identity_decision": workflow["latest_identity_decision"],
                "title": context.get("title"),
                "normalized_title": context.get("normalized_title"),
                "publication_year": context.get("publication_year"),
                "pmid": context.get("pmid"),
                "pmcid": context.get("pmcid"),
                "doi": context.get("doi"),
                "canonical_url": context.get("canonical_url"),
                "type_of_study": context.get("type_of_study"),
                "study_result": context.get("study_result"),
                "study_sample_size": context.get("study_sample_size"),
                "key_findings": context.get("key_findings") or [],
                "list_fields": context.get("list_fields") or {},
                "text_fields": context.get("text_fields") or {},
                "source_filenames": context.get("source_filenames") or [],
                "identity_validation": {
                    "selected_document_id": document_id,
                    "candidates": validation.get("candidates") or [],
                },
                "provenance": {
                    "source": "legacy_identity_validation",
                    "method": "export_identity_confirmed_legacy_english_context_for_triage",
                    "no_hosted_llm": True,
                    "does_not_mutate_sqlite_review_state": True,
                    "context_provenance": context.get("provenance") or {},
                    "validation_provenance": validation.get("provenance") or {},
                },
            }
        )
    return sorted(
        records,
        key=lambda record: (
            record["identity_confirmation_status"],
            record.get("title") or "",
            record["context_id"],
        ),
    )


def identity_workflow_state(
    connection: sqlite3.Connection,
    document_id: str,
) -> dict[str, Any]:
    review_item = connection.execute(
        """
        SELECT review_item_id, status
        FROM review_item
        WHERE queue_type = 'legacy_identity_review'
        AND document_id = ?
        """,
        (document_id,),
    ).fetchone()
    if review_item is None:
        return {
            "confirmation_status": "trusted_legacy_reference_no_identity_queue",
            "review_item_id": None,
            "review_item_status": None,
            "latest_identity_decision": None,
        }

    latest_decision = connection.execute(
        """
        SELECT decision, review_decision_id, reviewer, created_at
        FROM review_decision
        WHERE review_item_id = ?
        ORDER BY created_at DESC, review_decision_id DESC
        LIMIT 1
        """,
        (review_item["review_item_id"],),
    ).fetchone()
    decision = dict(latest_decision) if latest_decision is not None else None
    confirmation_status = (
        "workflow_resolved_identity_review"
        if review_item["status"] == "resolved"
        and decision is not None
        and decision["decision"] in {"confirmed_identity", "corrected_identity"}
        else "identity_review_still_pending"
    )
    return {
        "confirmation_status": confirmation_status,
        "review_item_id": review_item["review_item_id"],
        "review_item_status": review_item["status"],
        "latest_identity_decision": decision,
    }


def build_identifier_index(documents: list[BaselineDocument]) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for document in documents:
        values = {
            "pmid": document.pmid,
            "pmcid": document.pmcid,
            "doi": document.doi,
            "canonical_url": canonicalize_url(document.canonical_url),
        }
        for field, value in values.items():
            normalized = normalize_identifier(field, value)
            if normalized:
                index[(field, normalized)].append(document.document_id)
    return dict(index)


def build_year_index(documents: list[BaselineDocument]) -> dict[int | None, set[str]]:
    index: dict[int | None, set[str]] = defaultdict(set)
    for document in documents:
        index[document.publication_year].add(document.document_id)
    return dict(index)


def build_token_index(documents: list[BaselineDocument]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    for document in documents:
        for token in title_tokens(document.normalized_title or ""):
            index[token].add(document.document_id)
    return dict(index)


def build_validation_record(
    context: dict[str, Any],
    bucket: str,
    candidates: list[IdentityCandidate],
) -> IdentityValidationRecord:
    selected_document_id = candidates[0].document_id if len(candidates) == 1 and bucket in {
        "exact_identifier_match",
        "strong_title_embedding_match",
    } else None
    return IdentityValidationRecord(
        context_id=context["context_id"],
        bucket=bucket,
        title=context.get("title"),
        normalized_title=context.get("normalized_title"),
        publication_year=context.get("publication_year"),
        pmid=normalize_identifier("pmid", context.get("pmid")),
        pmcid=normalize_identifier("pmcid", context.get("pmcid")),
        doi=normalize_identifier("doi", context.get("doi")),
        canonical_url=canonicalize_url(context.get("canonical_url")),
        selected_document_id=selected_document_id,
        candidates=candidates,
        provenance={
            "source": "legacy_identity_validation",
            "method": "local_identifier_title_year_embedding_validation",
            "no_hosted_llm": True,
            "does_not_mutate_sqlite_review_state": True,
            "source_context_provenance": context.get("provenance", {}),
        },
    )


def normalize_identifier(field: str, value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if field == "pmcid":
        return normalized.upper()
    if field == "doi":
        return normalized.removeprefix("https://doi.org/").removeprefix("http://doi.org/").lower()
    if field == "canonical_url":
        return canonicalize_url(normalized)
    return normalized


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme and not parsed.netloc:
        return url.strip()
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or parsed.path
    return parsed._replace(scheme=scheme, netloc=host, path=path, fragment="").geturl()


def title_tokens(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.lower()) if len(token) >= 4}


def title_embedding(value: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    padded = f"  {value.lower()}  "
    features = list(title_tokens(value))
    features.extend(padded[index : index + 3] for index in range(max(0, len(padded) - 2)))
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.7 if " " not in feature else 1.0
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(
        left_value * right_value
        for left_value, right_value in zip(left, right, strict=True)
    )


def compare_titles(left: str | None, right: str | None) -> float | None:
    if not left or not right:
        return None
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


def years_compatible(left: Any, right: int | None) -> bool:
    if left is None or right is None:
        return True
    try:
        return abs(int(left) - int(right)) <= 1
    except (TypeError, ValueError):
        return False


def count_candidate_documents(candidates: list[IdentityCandidate]) -> int:
    return len({candidate.document_id for candidate in candidates})


def has_strong_identifier(context: dict[str, Any]) -> bool:
    return any(normalize_identifier(field, context.get(field)) for field in IDENTIFIER_FIELDS)


def write_jsonl(path: Path, records: list[IdentityValidationRecord]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")


def write_bucket_jsonl(
    output_dir: Path,
    run_id: str,
    records: list[IdentityValidationRecord],
) -> dict[str, str]:
    paths: dict[str, str] = {}
    for bucket in BUCKETS:
        path = output_dir / f"{run_id}_legacy_identity_validation_{bucket}.jsonl"
        write_jsonl(path, [record for record in records if record.bucket == bucket])
        paths[bucket] = str(path)
    return paths


def build_summary(
    records: list[IdentityValidationRecord],
    *,
    input_path: Path,
    database_path: Path,
    records_path: Path,
    bucket_paths: dict[str, str],
    run_started_at: datetime,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    bucket_counts = Counter(record.bucket for record in records)
    match_method_counts = Counter(
        candidate.match_method for record in records for candidate in record.candidates
    )
    return {
        "source": "legacy_identity_validation",
        "method": "local_identifier_title_year_embedding_validation",
        "input_path": str(input_path),
        "database_path": str(database_path),
        "records_path": str(records_path),
        "bucket_paths": bucket_paths,
        "started_at": run_started_at.isoformat(),
        "completed_at": datetime.now(UTC).isoformat(),
        "total_contexts": len(records),
        "bucket_counts": {bucket: bucket_counts.get(bucket, 0) for bucket in BUCKETS},
        "selected_records": sum(record.selected_document_id is not None for record in records),
        "match_method_counts": dict(match_method_counts.most_common()),
        "thresholds": thresholds,
        "embedding_backend": "local_hashing_384d",
        "hosted_llm_calls": 0,
        "sqlite_mutations": 0,
    }


def build_confirmed_identity_summary(
    records: list[dict[str, Any]],
    *,
    context_path: Path,
    validation_path: Path,
    database_path: Path,
    records_path: Path,
) -> dict[str, Any]:
    status_counts = Counter(record["identity_confirmation_status"] for record in records)
    bucket_counts = Counter(record["identity_validation_bucket"] for record in records)
    decision_counts = Counter(
        (record["latest_identity_decision"] or {}).get("decision", "not_applicable")
        for record in records
    )
    return {
        "source": "legacy_identity_validation",
        "method": "export_identity_confirmed_legacy_english_context_for_triage",
        "context_path": str(context_path),
        "validation_path": str(validation_path),
        "database_path": str(database_path),
        "records_path": str(records_path),
        "total_records": len(records),
        "identity_confirmation_status_counts": dict(status_counts.most_common()),
        "identity_validation_bucket_counts": dict(bucket_counts.most_common()),
        "latest_identity_decision_counts": dict(decision_counts.most_common()),
        "hosted_llm_calls": 0,
        "sqlite_mutations": 0,
    }


def print_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Legacy identity validation")
    table.add_column("Bucket")
    table.add_column("Records", justify="right")
    for bucket, count in summary["bucket_counts"].items():
        table.add_row(bucket, str(count))
    table.add_row("selected_records", str(summary["selected_records"]))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


def print_confirmed_summary(summary: dict[str, Any]) -> None:
    table = Table(title="Identity-confirmed legacy context for triage")
    table.add_column("Metric")
    table.add_column("Records", justify="right")
    table.add_row("total", str(summary["total_records"]))
    for status, count in summary["identity_confirmation_status_counts"].items():
        table.add_row(status, str(count))
    console.print(table)
    console.print({"summary": summary["summary_path"], "records": summary["records_path"]})


if __name__ == "__main__":
    app()
