from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from marygenai.classification.models import CandidateStudyClassification
from marygenai.retrieval.common import DEFAULT_INDEX_RELATIVE_PATH, normalize_match_key
from marygenai.retrieval.identity import project_bibliographic_identities
from marygenai.retrieval.models import (
    RETRIEVAL_INDEX_SCHEMA_VERSION,
    TRUST_NOTICE,
    IndexManifest,
)

DEFAULT_CLASSIFICATION_RUN_IDS = (
    "20260710T173226Z",
    "20260710T180539Z",
    "20260710T211154Z",
    "20260711T153044Z",
    "20260716T191943Z",
    "20260717T111520Z",
    "20260717T113729Z",
    "20260717T120705Z",
    "20260717T210755Z",
    "20260718T160108Z",
    "20260720T133501Z",
    "20260720T192132Z",
    "20260721T145348Z",
    "20260721T182447Z",
    "20260721T211628Z",
    "20260721T213854Z",
    "20260722T110734Z",
    "20260722T121250Z",
    "20260722T195313Z",
    "20260722T212004Z",
    "20260723T112948Z",
    "20260723T120533Z",
    "20260723T141447Z",
    "20260723T144223Z",
)
def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_record_paths(data_dir: Path, paths: list[Path] | None) -> list[Path]:
    if paths:
        resolved = [path.resolve() for path in paths]
    else:
        resolved = [
            (
                data_dir
                / "normalized/classification_runs"
                / f"{run_id}_candidate_classification_records.jsonl"
            ).resolve()
            for run_id in DEFAULT_CLASSIFICATION_RUN_IDS
        ]
    missing = [path for path in resolved if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Candidate record files not found: {', '.join(map(str, missing))}")
    return resolved


def _resolve_corpus_path(data_dir: Path, path: Path | None) -> Path:
    if path:
        resolved = path.resolve()
    else:
        candidates = sorted(
            data_dir.glob("normalized/classification_corpus/*_classification_corpus_records.jsonl")
        )
        if not candidates:
            raise FileNotFoundError("No classification corpus records artifact was found.")
        resolved = candidates[-1].resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Classification corpus not found: {resolved}")
    return resolved


def _resolve_report_paths(
    data_dir: Path,
    run_ids: set[str],
    paths: list[Path] | None,
) -> list[Path]:
    if paths:
        resolved = [path.resolve() for path in paths]
    else:
        latest_by_run: dict[str, Path] = {}
        for candidate in sorted(
            data_dir.glob(
                "normalized/classification_evaluations/*_classification_evaluation_report.json"
            )
        ):
            report = _read_json(candidate)
            run_id = report.get("classification_run_id")
            if run_id in run_ids:
                latest_by_run[run_id] = candidate.resolve()
        resolved = [latest_by_run[run_id] for run_id in sorted(latest_by_run)]
        missing_runs = sorted(run_ids - latest_by_run.keys())
        if missing_runs:
            raise FileNotFoundError(
                "No classification evaluation report was found for runs: " + ", ".join(missing_runs)
            )
    missing = [path for path in resolved if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Evaluation reports not found: {', '.join(map(str, missing))}")
    report_runs: list[str] = []
    for path in resolved:
        report_run_id = _read_json(path).get("classification_run_id")
        if report_run_id not in run_ids:
            raise ValueError(
                f"Evaluation report {path} does not belong to an indexed classification run."
            )
        if report_run_id in report_runs:
            raise ValueError(f"Multiple evaluation reports were selected for run {report_run_id}.")
        report_runs.append(report_run_id)
    missing_runs = sorted(run_ids - set(report_runs))
    if missing_runs:
        raise FileNotFoundError(
            "No classification evaluation report was selected for runs: " + ", ".join(missing_runs)
        )
    return resolved


def _resolve_report_output_path(value: str | None, data_dir: Path) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    candidates = [raw, data_dir / raw, data_dir.parent / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _facet_rows(record: dict[str, Any]) -> list[tuple[str, str, str, str, bool]]:
    document_id = record["document_id"]
    rows: list[tuple[str, str, str, str, bool]] = []

    for family in ("medical_conditions", "cannabinoids_or_exposures"):
        for label in record[family]:
            display = label.get("normalized_label") or label["free_text_label"]
            canonical_key = normalize_match_key(display)
            if canonical_key:
                rows.append((document_id, family, canonical_key, display, True))
            free_text = label.get("free_text_label")
            if free_text:
                alias_key = normalize_match_key(free_text)
                if alias_key and alias_key != canonical_key:
                    rows.append((document_id, family, alias_key, display, False))

    scalar_facets = {
        "study_design_categories": [record["study_design_category"]],
        "study_design_subtypes": [record["study_design_subtype"]],
        "evidence_contexts": [record["evidence_context"]],
        "population_categories": [record["population_or_model"]["category"]],
        "intervention_or_exposure_roles": [record["intervention_or_exposure_role"]],
        "outcome_domains": record["outcome_domains"],
        "overall_directions": [record["overall_direction"]],
        "classification_confidences": [record["classification_confidence"]],
        "review_states": [record["review_state"]],
    }
    for family, values in scalar_facets.items():
        for value in values:
            rows.append((document_id, family, normalize_match_key(value), value, True))
    return rows


def _input_file_record(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": _sha256(path)}


def _requires_cannabinoid_exposure(
    classification_run_id: str,
    *,
    require_for_all_runs: bool,
    required_run_ids: set[str],
) -> bool:
    return require_for_all_runs or classification_run_id in required_run_ids


def build_retrieval_index(
    *,
    data_dir: Path,
    output_path: Path | None = None,
    records_paths: list[Path] | None = None,
    corpus_path: Path | None = None,
    evaluation_report_paths: list[Path] | None = None,
    require_cannabinoid_exposure: bool = False,
    require_cannabinoid_exposure_run_ids: list[str] | None = None,
) -> IndexManifest:
    """Build an isolated candidate-evidence DuckDB index from ignored artifacts."""
    scoped_exposure_run_ids = set(require_cannabinoid_exposure_run_ids or [])
    if require_cannabinoid_exposure and scoped_exposure_run_ids:
        raise ValueError(
            "Use either the global cannabinoid-exposure gate or run-scoped gates, not both."
        )
    resolved_records_paths = _resolve_record_paths(data_dir, records_paths)
    resolved_corpus_path = _resolve_corpus_path(data_dir, corpus_path)

    candidates: list[dict[str, Any]] = []
    excluded_candidates: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    all_document_ids: set[str] = set()
    run_ids: set[str] = set()
    for path in resolved_records_paths:
        for raw_record in _read_jsonl(path):
            record = CandidateStudyClassification.model_validate(raw_record).model_dump(mode="json")
            document_id = record["document_id"]
            if document_id in all_document_ids:
                raise ValueError(f"Duplicate candidate document_id: {document_id}")
            all_document_ids.add(document_id)
            run_ids.add(record["classification_run_id"])
            gate_applies = _requires_cannabinoid_exposure(
                record["classification_run_id"],
                require_for_all_runs=require_cannabinoid_exposure,
                required_run_ids=scoped_exposure_run_ids,
            )
            if gate_applies and not record["cannabinoids_or_exposures"]:
                excluded_candidates.append(
                    {
                        "document_id": document_id,
                        "classification_id": record["classification_id"],
                        "classification_run_id": record["classification_run_id"],
                        "exclusion_reason": "missing_structured_cannabinoid_or_exposure",
                        "classification_confidence": record["classification_confidence"],
                        "missing_or_uncertain_fields": record["missing_or_uncertain_fields"],
                        "review_state": record["review_state"],
                        "provenance": {
                            "method": "retrieval_candidate_inclusion_gate.v1",
                            "requires_human_review": True,
                            "does_not_mutate_sqlite": True,
                            "review_boundary": (
                                "retrieval_index_exclusion_not_reviewed_knowledge"
                            ),
                        },
                    }
                )
                continue
            seen_document_ids.add(document_id)
            candidates.append(record)

    unknown_scoped_run_ids = sorted(scoped_exposure_run_ids - run_ids)
    if unknown_scoped_run_ids:
        raise ValueError(
            "Cannabinoid-exposure gate run IDs were not present in candidate inputs: "
            + ", ".join(unknown_scoped_run_ids)
        )

    corpus = {row["document_id"]: row for row in _read_jsonl(resolved_corpus_path)}
    missing_corpus = sorted(seen_document_ids - corpus.keys())
    if missing_corpus:
        raise ValueError(
            f"Candidate documents missing from the source corpus: {', '.join(missing_corpus[:10])}"
        )
    identity_projections = project_bibliographic_identities(
        data_dir=data_dir, corpus=corpus, candidates=candidates
    )

    resolved_report_paths = _resolve_report_paths(
        data_dir,
        run_ids,
        evaluation_report_paths,
    )
    retrieval_confidence: dict[str, dict[str, Any]] = {}
    grounding_review: dict[str, list[dict[str, Any]]] = defaultdict(list)
    auxiliary_paths: list[Path] = []
    for report_path in resolved_report_paths:
        report = _read_json(report_path)
        confidence_path = _resolve_report_output_path(
            report.get("outputs", {}).get("retrieval_confidence_records_path"),
            data_dir,
        )
        grounding_path = _resolve_report_output_path(
            report.get("outputs", {}).get("evidence_spans_requiring_grounding_review_path"),
            data_dir,
        )
        if confidence_path is None:
            raise FileNotFoundError(
                f"Retrieval-confidence artifact was not found for evaluation report {report_path}."
            )
        if grounding_path is None:
            raise FileNotFoundError(
                f"Grounding-review artifact was not found for evaluation report {report_path}."
            )
        auxiliary_paths.extend([confidence_path, grounding_path])
        for row in _read_jsonl(confidence_path):
            document_id = row["document_id"]
            if document_id in retrieval_confidence:
                raise ValueError(f"Duplicate retrieval-confidence document_id: {document_id}")
            retrieval_confidence[document_id] = row
        for row in _read_jsonl(grounding_path):
            grounding_review[row["document_id"]].append(row)

    missing_confidence = sorted(seen_document_ids - retrieval_confidence.keys())
    if missing_confidence:
        raise ValueError(
            "Candidate documents missing retrieval-confidence evaluation: "
            + ", ".join(missing_confidence[:10])
        )
    unexpected_confidence = sorted(retrieval_confidence.keys() - all_document_ids)
    if unexpected_confidence:
        raise ValueError(
            "Retrieval-confidence records do not belong to the candidate index: "
            + ", ".join(unexpected_confidence[:10])
        )
    unexpected_grounding = sorted(grounding_review.keys() - all_document_ids)
    if unexpected_grounding:
        raise ValueError(
            "Grounding-review records do not belong to the candidate index: "
            + ", ".join(unexpected_grounding[:10])
        )

    resolved_output_path = (
        output_path.resolve() if output_path else (data_dir / DEFAULT_INDEX_RELATIVE_PATH).resolve()
    )
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = resolved_output_path.with_name(f".{resolved_output_path.name}.tmp")
    if temporary_path.exists():
        temporary_path.unlink()

    built_at = datetime.now(UTC)
    build_id = built_at.strftime("%Y%m%dT%H%M%S%fZ")
    input_paths = [
        *resolved_records_paths,
        resolved_corpus_path,
        *resolved_report_paths,
        *auxiliary_paths,
    ]
    input_files = [_input_file_record(path) for path in dict.fromkeys(input_paths)]
    if require_cannabinoid_exposure:
        inclusion_criteria = ["at_least_one_structured_cannabinoid_or_exposure_label"]
    else:
        inclusion_criteria = [
            "at_least_one_structured_cannabinoid_or_exposure_label:"
            f"classification_run_id={run_id}"
            for run_id in sorted(scoped_exposure_run_ids)
        ]
    exclusions_path = resolved_output_path.with_suffix(".exclusions.jsonl")
    if excluded_candidates:
        exclusions_path.write_text(
            "".join(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                for record in excluded_candidates
            ),
            encoding="utf-8",
        )
    elif exclusions_path.exists():
        exclusions_path.unlink()

    connection = duckdb.connect(str(temporary_path))
    try:
        connection.execute(
            """
            CREATE TABLE index_metadata (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL);
            CREATE TABLE documents (
                document_id VARCHAR PRIMARY KEY,
                classification_id VARCHAR NOT NULL,
                classification_run_id VARCHAR NOT NULL,
                title VARCHAR,
                doi VARCHAR,
                pmid VARCHAR,
                pmcid VARCHAR,
                canonical_url VARCHAR,
                source_url VARCHAR,
                publication_year INTEGER,
                source_text_path VARCHAR NOT NULL,
                source_text_sha256 VARCHAR NOT NULL,
                source_trust_level VARCHAR,
                review_state VARCHAR NOT NULL,
                requires_human_review BOOLEAN NOT NULL,
                classification_confidence VARCHAR NOT NULL,
                study_design_category VARCHAR NOT NULL,
                study_design_subtype VARCHAR NOT NULL,
                evidence_context VARCHAR NOT NULL,
                intervention_or_exposure_role VARCHAR NOT NULL,
                population_category VARCHAR NOT NULL,
                population_description VARCHAR,
                overall_direction VARCHAR NOT NULL,
                has_uncertainty BOOLEAN NOT NULL,
                retrieval_confidence_score DOUBLE,
                retrieval_confidence_band VARCHAR,
                retrieval_confidence_version VARCHAR,
                search_text VARCHAR NOT NULL,
                classification_json VARCHAR NOT NULL,
                corpus_json VARCHAR NOT NULL,
                retrieval_confidence_json VARCHAR,
                grounding_review_json VARCHAR NOT NULL,
                grounding_review_count INTEGER NOT NULL,
                original_corpus_identity_json VARCHAR NOT NULL,
                projected_identity_json VARCHAR NOT NULL,
                identity_status VARCHAR NOT NULL,
                identity_conflict_count INTEGER NOT NULL
            );
            CREATE TABLE facets (
                document_id VARCHAR NOT NULL,
                family VARCHAR NOT NULL,
                value_key VARCHAR NOT NULL,
                display_value VARCHAR NOT NULL,
                is_canonical BOOLEAN NOT NULL
            );
            CREATE INDEX facets_lookup_idx ON facets(family, value_key, document_id);
            """
        )
        metadata = {
            "index_schema_version": RETRIEVAL_INDEX_SCHEMA_VERSION,
            "build_id": build_id,
            "built_at": built_at.isoformat(),
            "document_count": str(len(candidates)),
            "classification_run_ids": _json(sorted(run_ids)),
            "inclusion_criteria": _json(inclusion_criteria),
            "excluded_document_count": str(len(excluded_candidates)),
            "exclusions_path": str(exclusions_path) if excluded_candidates else "",
            "trust_level": "ai_classified_candidate",
            "review_state": "needs_review",
            "notice": TRUST_NOTICE,
        }
        connection.executemany(
            "INSERT INTO index_metadata VALUES (?, ?)",
            list(metadata.items()),
        )

        document_rows: list[tuple[Any, ...]] = []
        facet_rows: list[tuple[str, str, str, str, bool]] = []
        for record in sorted(candidates, key=lambda item: item["document_id"]):
            document_id = record["document_id"]
            corpus_row = corpus[document_id]
            identity = identity_projections[document_id]
            confidence = retrieval_confidence.get(document_id)
            review_rows = grounding_review.get(document_id, [])
            condition_text = [
                value
                for label in record["medical_conditions"]
                for value in (label.get("normalized_label"), label.get("free_text_label"))
                if value
            ]
            exposure_text = [
                value
                for label in record["cannabinoids_or_exposures"]
                for value in (label.get("normalized_label"), label.get("free_text_label"))
                if value
            ]
            search_values = [
                corpus_row.get("primary_title"),
                *condition_text,
                *exposure_text,
                record["study_design_category"],
                record["study_design_subtype"],
                record["evidence_context"],
                record["intervention_or_exposure_role"],
                record["population_or_model"].get("description"),
                *record["outcome_domains"],
                record["overall_direction"],
            ]
            search_text = " ".join(str(value).casefold() for value in search_values if value)
            document_rows.append(
                (
                    document_id,
                    record["classification_id"],
                    record["classification_run_id"],
                    corpus_row.get("primary_title"),
                    identity.get("doi"),
                    identity.get("pmid"),
                    identity.get("pmcid"),
                    corpus_row.get("canonical_url"),
                    corpus_row.get("source_url"),
                    corpus_row.get("publication_year"),
                    record["source_text_path"],
                    record["source_text_sha256"],
                    corpus_row.get("trust_level"),
                    record["review_state"],
                    record["requires_human_review"],
                    record["classification_confidence"],
                    record["study_design_category"],
                    record["study_design_subtype"],
                    record["evidence_context"],
                    record["intervention_or_exposure_role"],
                    record["population_or_model"]["category"],
                    record["population_or_model"].get("description"),
                    record["overall_direction"],
                    bool(record["missing_or_uncertain_fields"]),
                    confidence.get("score") if confidence else None,
                    confidence.get("band") if confidence else None,
                    confidence.get("version") if confidence else None,
                    search_text,
                    _json(record),
                    _json(corpus_row),
                    _json(confidence) if confidence else None,
                    _json(review_rows),
                    len(review_rows),
                    _json(
                        {
                            "document_id": document_id,
                            "title": corpus_row.get("primary_title"),
                            "doi": corpus_row.get("doi"),
                            "pmid": corpus_row.get("pmid"),
                            "pmcid": corpus_row.get("pmcid"),
                            "canonical_url": corpus_row.get("canonical_url"),
                            "source_url": corpus_row.get("source_url"),
                            "publication_year": corpus_row.get("publication_year"),
                        }
                    ),
                    _json(identity),
                    identity["status"],
                    len(identity["conflicts"]),
                )
            )
            facet_rows.extend(_facet_rows(record))

        placeholders = ", ".join("?" for _ in range(37))
        connection.executemany(
            f"INSERT INTO documents VALUES ({placeholders})",
            document_rows,
        )
        connection.executemany("INSERT INTO facets VALUES (?, ?, ?, ?, ?)", facet_rows)
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    temporary_path.replace(resolved_output_path)
    limitations = [
        "The index contains AI-classified candidate evidence, not reviewed knowledge.",
        "The indexed candidate corpus is bounded and may not be representative.",
        "The v3 schema does not structure dose, route, comparator, duration, or specific outcomes.",
        "Classification confidence is categorical and is not a calibrated probability.",
        "Retrieval confidence is a deterministic heuristic ranking signal, not evidence strength.",
    ]
    manifest = IndexManifest(
        build_id=build_id,
        built_at=built_at.isoformat(),
        index_path=str(resolved_output_path),
        document_count=len(candidates),
        classification_run_ids=sorted(run_ids),
        input_files=input_files,
        source_corpus_path=str(resolved_corpus_path),
        evaluation_report_paths=[str(path) for path in resolved_report_paths],
        inclusion_criteria=inclusion_criteria,
        excluded_document_count=len(excluded_candidates),
        exclusions_path=str(exclusions_path) if excluded_candidates else None,
        limitations=limitations,
    )
    manifest_path = resolved_output_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return manifest
