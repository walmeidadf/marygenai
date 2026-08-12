from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from marygenai.access_enrichment.clients import EuropePmcClient
from marygenai.classification.pipeline import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_SOURCE_CHARS,
    build_classification_prompt_packets,
)
from marygenai.classification_corpus.models import (
    PubMedArtifactQualityAssessment,
    PubMedIdentityRepairRecord,
    PubMedSourceQualityRecord,
)
from marygenai.classification_corpus.pipeline import new_run_id
from marygenai.classification_corpus.pubmed_canary import (
    SELECTION_CRITERIA,
    assess_artifact,
    build_manifest_and_corpus,
    protected_state_snapshot,
    safe_version_fragment,
    write_dict_jsonl,
    write_frozen_jsonl,
)
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage

DEFAULT_V2_CORPUS_VERSION = "pubmed_2024plus_canary.v2"
DEFAULT_V2_TARGET_SIZE = 100
DEFAULT_REPAIR_WORKLIST = Path(
    "normalized/pubmed_canary/identity_repairs/"
    "20260806T130505Z_pubmed_identity_reenrichment_worklist.jsonl"
)
V2_RAW_SUBDIR = Path("raw/europe_pmc/full_text_xml/pubmed_2024plus_canary_v2")
V2_OUTPUT_SUBDIR = Path("normalized/pubmed_canary")

VETERINARY_TITLE_TERMS = (
    " canine ",
    " canines ",
    " cat ",
    " cats ",
    " dog ",
    " dogs ",
    " feline ",
    " veterinary ",
)
NONMEDICAL_TITLE_TERMS = (
    " agronomic ",
    " chromatography method ",
    " cultivar ",
    " fertilizer ",
    " germination ",
    " hemp fiber ",
    " industrial extraction ",
    " irrigation ",
    " plant growth ",
    " soil ",
)
MEDICAL_TITLE_TERMS = (
    " adult ",
    " adolescent ",
    " administration ",
    " alcohol ",
    " alzheimer ",
    " anxiety ",
    " autism ",
    " blood ",
    " brain ",
    " cancer ",
    " chemotherapy ",
    " child ",
    " clinical ",
    " cognitive ",
    " disorder ",
    " driving ",
    " drug ",
    " efficacy ",
    " epilepsy ",
    " exercise ",
    " health ",
    " healthy ",
    " human ",
    " impairment ",
    " inflammation ",
    " insomnia ",
    " intoxication ",
    " medical ",
    " medicinal ",
    " meta analysis ",
    " migraine ",
    " nausea ",
    " neural ",
    " neuropath ",
    " pain ",
    " patient ",
    " pharmacokinetic ",
    " placebo ",
    " protocol ",
    " psychiatric ",
    " randomized ",
    " randomised ",
    " safety ",
    " schizophrenia ",
    " seizure ",
    " sleep ",
    " stress ",
    " symptom ",
    " systematic review ",
    " therap ",
    " tobacco ",
    " treatment ",
    " trial ",
    " volunteer ",
)
V2_SELECTION_CRITERIA = SELECTION_CRITERIA + [
    "identity_resolved_from_existing_pmid_overlay",
    "corrected_official_pmcid",
    "europe_pmc_full_text_xml",
    "human_medical_or_public_health_title_scope",
    "veterinary_only_title_scope_excluded",
]


class CorrectedPmcClient(Protocol):
    def fetch_full_text_xml_by_pmcid(self, pmcid: str) -> bytes: ...


def padded_title(title: str) -> str:
    return f" {title.casefold().replace('-', ' ')} "


def medical_scope_failure_reasons(title: str | None) -> list[str]:
    normalized = padded_title(title or "")
    reasons: list[str] = []
    if any(term in normalized for term in VETERINARY_TITLE_TERMS):
        reasons.append("veterinary_only_title_scope")
    if any(term in normalized for term in NONMEDICAL_TITLE_TERMS):
        reasons.append("nonmedical_title_scope")
    if not any(term in normalized for term in MEDICAL_TITLE_TERMS):
        reasons.append("missing_human_medical_or_public_health_title_signal")
    return reasons


def read_repair_worklist(path: Path) -> list[PubMedIdentityRepairRecord]:
    with path.open(encoding="utf-8") as file:
        return [
            PubMedIdentityRepairRecord.model_validate_json(line)
            for line in file
            if line.strip()
        ]


def read_excluded_document_ids(paths: list[Path] | None) -> set[str]:
    document_ids: set[str] = set()
    for path in paths or []:
        with path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                record = json.loads(line)
                document_id = record.get("document_id")
                if document_id:
                    document_ids.add(str(document_id))
    return document_ids


def raw_xml_path(storage: LocalStorage, pmcid: str) -> Path:
    return storage.path(V2_RAW_SUBDIR / f"{pmcid.casefold()}.xml")


def fetch_or_load_xml(
    *,
    storage: LocalStorage,
    client: CorrectedPmcClient,
    pmcid: str,
) -> tuple[Path, str]:
    path = raw_xml_path(storage, pmcid)
    if path.exists():
        return path, "cached_frozen_europe_pmc_xml"
    content = client.fetch_full_text_xml_by_pmcid(pmcid)
    if not content.strip():
        raise ValueError("Europe PMC returned an empty full-text payload.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, "europe_pmc_full_text_xml_by_corrected_pmcid"


def assess_corrected_artifact(
    *,
    storage: LocalStorage,
    repair: PubMedIdentityRepairRecord,
    path: Path,
    fetched_at: str,
) -> tuple[PubMedArtifactQualityAssessment, str]:
    identity = repair.resolved_identity
    assert identity is not None
    assert identity.pmcid is not None
    relative_path = path.resolve().relative_to(storage.root.resolve()).as_posix()
    row: dict[str, Any] = {
        "artifact_id": f"europe-pmc:{identity.pmcid.casefold()}:full-text-xml",
        "artifact_source": "europe_pmc",
        "artifact_type": "europe_pmc_full_text_xml",
        "artifact_url": (
            "https://www.ebi.ac.uk/europepmc/webservices/rest/"
            f"{identity.pmcid}/fullTextXML"
        ),
        "payload_path": relative_path,
        "payload_sha256": file_sha256(path),
        "primary_title": identity.primary_title,
        "pmid": identity.pmid,
        "doi": identity.doi,
        "artifact_run_id": repair.repair_run_id,
        "artifact_created_at": fetched_at,
    }
    return assess_artifact(row, data_dir=storage.root)  # type: ignore[arg-type]


def quality_record(
    *,
    repair: PubMedIdentityRepairRecord,
    assessment: PubMedArtifactQualityAssessment,
    scope_failures: list[str],
) -> PubMedSourceQualityRecord:
    identity = repair.resolved_identity
    assert identity is not None
    exclusions = sorted(set(scope_failures + assessment.failure_reasons))
    source_pass = assessment.quality_pass and not scope_failures
    return PubMedSourceQualityRecord(
        document_id=repair.document_id,
        primary_title=identity.primary_title,
        publication_year=identity.publication_year,
        pmid=identity.pmid,
        pmcid=identity.pmcid,
        doi=identity.doi,
        canonical_url=identity.canonical_url,
        identity_status="resolved_pubmed_identity_overlay",
        cannabinoid_focus="direct_title_or_indexed",
        study_design=None,
        study_design_rank=max(0, 10_000 - repair.selection_rank),
        priority_score=float(max(0, 10_000 - repair.selection_rank)),
        review_state="needs_review",
        artifact_count=1,
        artifact_assessments=[assessment],
        selected_artifact_id=assessment.artifact_id if source_pass else None,
        source_quality_gate_pass=source_pass,
        exclusion_reasons=exclusions,
        provenance={
            "method": "pubmed_corrected_pmc_canary_source_gate.v2",
            "identity_repair_run_id": repair.repair_run_id,
            "identity_repair_selection_rank": repair.selection_rank,
            "does_not_call_provider": True,
            "does_not_mutate_sqlite": True,
            "review_boundary": "candidate_source_quality_not_reviewed_knowledge",
        },
    )


def exclusion_record(
    repair: PubMedIdentityRepairRecord,
    reasons: list[str],
) -> dict[str, Any]:
    return {
        "document_id": repair.document_id,
        "selection_rank": repair.selection_rank,
        "resolved_identity": (
            repair.resolved_identity.model_dump(mode="json")
            if repair.resolved_identity
            else None
        ),
        "exclusion_reasons": sorted(set(reasons)),
        "review_state": "needs_review",
        "provenance": {
            "method": "pubmed_corrected_pmc_canary_source_gate.v2",
            "identity_repair_run_id": repair.repair_run_id,
            "does_not_call_provider": True,
            "does_not_mutate_sqlite": True,
        },
    }


def prepare_pubmed_canary_v2(
    *,
    storage: LocalStorage,
    database_path: Path,
    worklist_path: Path | None = None,
    exclude_manifest_paths: list[Path] | None = None,
    target_size: int = DEFAULT_V2_TARGET_SIZE,
    corpus_version: str = DEFAULT_V2_CORPUS_VERSION,
    run_id: str | None = None,
    client: CorrectedPmcClient | None = None,
    prepare_prompt_packets: bool = True,
    max_source_chars: int = DEFAULT_PROMPT_SOURCE_CHARS,
    target_model_name: str = DEFAULT_OPENAI_MODEL,
) -> dict[str, Any]:
    if target_size < 1:
        raise ValueError("target_size must be at least 1.")
    resolved_run_id = run_id or new_run_id()
    fetched_at = datetime.now(UTC).isoformat()
    resolved_worklist_path = worklist_path or storage.path(DEFAULT_REPAIR_WORKLIST)
    repairs = sorted(
        read_repair_worklist(resolved_worklist_path),
        key=lambda record: (record.selection_rank, record.document_id),
    )
    excluded_document_ids = read_excluded_document_ids(exclude_manifest_paths)
    protected_before = protected_state_snapshot(database_path)
    fetch_client = client or EuropePmcClient(timeout_seconds=60.0)
    owns_client = client is None
    quality_records: list[PubMedSourceQualityRecord] = []
    selected: list[PubMedSourceQualityRecord] = []
    selected_text: dict[str, str] = {}
    exclusions: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    seen_pmcids: set[str] = set()
    try:
        for repair in repairs:
            identity = repair.resolved_identity
            if repair.document_id in excluded_document_ids:
                exclusions.append(
                    exclusion_record(repair, ["previously_selected_document"])
                )
                continue
            if repair.document_id in seen_document_ids:
                exclusions.append(exclusion_record(repair, ["duplicate_document_id"]))
                continue
            seen_document_ids.add(repair.document_id)
            if identity is None or not identity.pmcid:
                exclusions.append(exclusion_record(repair, ["corrected_pmcid_missing"]))
                continue
            normalized_pmcid = identity.pmcid.casefold()
            if normalized_pmcid in seen_pmcids:
                exclusions.append(exclusion_record(repair, ["duplicate_corrected_pmcid"]))
                continue
            seen_pmcids.add(normalized_pmcid)
            scope_failures = medical_scope_failure_reasons(identity.primary_title)
            if scope_failures:
                exclusions.append(exclusion_record(repair, scope_failures))
                continue
            if len(selected) >= target_size:
                exclusions.append(exclusion_record(repair, ["target_capacity_reached"]))
                continue
            try:
                path, acquisition_method = fetch_or_load_xml(
                    storage=storage,
                    client=fetch_client,
                    pmcid=identity.pmcid,
                )
                assessment, text = assess_corrected_artifact(
                    storage=storage,
                    repair=repair,
                    path=path,
                    fetched_at=fetched_at,
                )
                record = quality_record(
                    repair=repair,
                    assessment=assessment,
                    scope_failures=scope_failures,
                )
                record.provenance["acquisition_method"] = acquisition_method
                quality_records.append(record)
                if record.source_quality_gate_pass:
                    selected.append(record)
                    selected_text[record.document_id] = text
                else:
                    exclusions.append(exclusion_record(repair, record.exclusion_reasons))
            except (httpx.HTTPError, ValueError, OSError) as error:
                exclusions.append(
                    exclusion_record(
                        repair,
                        [f"source_fetch_or_parse_error:{type(error).__name__}:{error}"],
                    )
                )
    finally:
        if owns_client and isinstance(fetch_client, EuropePmcClient):
            fetch_client.close()

    manifest, corpus = build_manifest_and_corpus(
        storage=storage,
        selected=selected,
        selected_text=selected_text,
        corpus_version=corpus_version,
    )
    repair_run_ids = sorted({record.repair_run_id for record in repairs})
    for record in manifest:
        record.selection_criteria = V2_SELECTION_CRITERIA
        record.provenance.update(
            {
                "method": "pubmed_2024plus_corrected_pmc_canary_selection.v2",
                "identity_repair_run_ids": repair_run_ids,
                "selection_sort": "identity_repair_selection_rank_asc,document_id_asc",
                "medical_scope_gate": "human_medical_or_public_health_title_scope.v1",
            }
        )
    for record in corpus:
        record.provenance.update(
            {
                "method": "pubmed_corrected_pmc_classification_corpus.v2",
                "identity_repair_run_ids": repair_run_ids,
                "medical_scope_gate": "human_medical_or_public_health_title_scope.v1",
            }
        )

    version_fragment = safe_version_fragment(corpus_version)
    manifest_path = write_frozen_jsonl(
        storage.path(V2_OUTPUT_SUBDIR / f"{version_fragment}_manifest.jsonl"),
        manifest,
    )
    corpus_path = write_frozen_jsonl(
        storage.path(V2_OUTPUT_SUBDIR / f"{version_fragment}_corpus_records.jsonl"),
        corpus,
    )
    records_path = storage.write_jsonl(
        V2_OUTPUT_SUBDIR
        / f"{resolved_run_id}_corrected_pmc_source_quality_records.jsonl",
        quality_records,
    )
    exclusions_path = write_dict_jsonl(
        storage.path(
            V2_OUTPUT_SUBDIR
            / f"{resolved_run_id}_corrected_pmc_source_quality_exclusions.jsonl"
        ),
        exclusions,
    )
    prompt_packet_result = None
    if corpus and prepare_prompt_packets:
        prompt_packet_result = build_classification_prompt_packets(
            storage=storage,
            limit=len(corpus),
            input_path=corpus_path,
            run_id=f"{resolved_run_id}_pubmed_corrected_pmc",
            max_source_chars=max_source_chars,
            target_model_provider="openai",
            target_model_name=target_model_name,
            dataset_split="strict_classification_ready",
        )
    protected_after = protected_state_snapshot(database_path)
    if protected_before != protected_after:
        raise RuntimeError("Protected SQLite or review state changed during v2 preparation.")
    summary = {
        "run_id": resolved_run_id,
        "corpus_version": corpus_version,
        "target_size": target_size,
        "counts": {
            "worklist_records": len(repairs),
            "previously_selected_documents": len(
                {record.document_id for record in repairs} & excluded_document_ids
            ),
            "quality_evaluated": len(quality_records),
            "selected_canary_documents": len(selected),
            "selection_shortfall": max(0, target_size - len(selected)),
            "excluded_records": len(exclusions),
            "source_quality_failures": sum(
                not record.source_quality_gate_pass for record in quality_records
            ),
        },
        "exclusion_reason_counts": dict(
            Counter(reason for record in exclusions for reason in record["exclusion_reasons"])
        ),
        "selected_document_ids": [record.document_id for record in selected],
        "output_paths": {
            "source_quality_records": str(records_path),
            "exclusions": str(exclusions_path),
            "frozen_manifest": str(manifest_path),
            "frozen_corpus_records": str(corpus_path),
            "prompt_packets": prompt_packet_result or {},
        },
        "protected_state_before": protected_before,
        "protected_state_after": protected_after,
        "protected_state_unchanged": True,
        "notes": [
            "Europe PMC full text was fetched only by the corrected official PMCID.",
            "No model provider was called during corpus preparation.",
            "All records remain needs_review candidate evidence.",
            "SQLite and protected review state were not mutated.",
            "Documents in explicitly supplied prior manifests were excluded.",
        ],
    }
    summary_path = storage.write_json(
        V2_OUTPUT_SUBDIR
        / f"{resolved_run_id}_corrected_pmc_source_quality_summary.json",
        summary,
    )
    return {
        "run_id": resolved_run_id,
        "corpus_version": corpus_version,
        "summary_path": str(summary_path),
        "manifest_path": str(manifest_path),
        "corpus_path": str(corpus_path),
        "counts": summary["counts"],
        "selected_document_ids": summary["selected_document_ids"],
        "prompt_packet_result": prompt_packet_result,
        "protected_state_unchanged": True,
    }
