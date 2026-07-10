from __future__ import annotations

import json
from pathlib import Path

import pytest

from marygenai.classification.pipeline import (
    build_classification_prompt_packets,
    convert_openai_batch_outputs,
    prepare_openai_batch_requests,
    run_classification_smoke,
)
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def corpus_record(data_dir: Path, *, document_id: str, text_path: Path) -> dict:
    return {
        "document_id": document_id,
        "legacy_study_id": "1",
        "primary_title": "Cannabidiol clinical trial for pain",
        "publication_year": 2024,
        "pmid": "1",
        "pmcid": None,
        "doi": None,
        "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/1",
        "legacy_study_type": "Ensaio Clínico",
        "legacy_result": "Positivo",
        "medical_condition_labels": ["Pain"],
        "organ_system_labels": ["Nervous system"],
        "cannabinoid_labels": ["Cannabidiol (CBD)"],
        "source_strategy": "pmc_oai",
        "source_url": "https://example.org/source",
        "source_text_path": str(text_path),
        "raw_payload_path": None,
        "extracted_text_chars": text_path.stat().st_size if text_path.exists() else 0,
        "scientific_section_hit_count": 4,
        "cannabinoid_term_hit_count": 2,
        "source_ready": True,
        "classification_ready": True,
        "classification_dataset_split": "strict_classification_ready",
        "trust_level": "source_text_available",
        "provenance": {"run_id": "corpus-run"},
    }


def broader_corpus_record(data_dir: Path, *, document_id: str, text_path: Path) -> dict:
    record = corpus_record(data_dir, document_id=document_id, text_path=text_path)
    record["classification_ready"] = False
    record["classification_dataset_split"] = "broader_source_ready"
    return record


def sample_record(data_dir: Path, *, document_id: str, text_path: Path) -> dict:
    return {
        "sample_id": f"sample:{document_id}",
        "sample_run_id": "sample-run",
        "sample_reason": "test",
        "strata": {
            "condition_strata": ["pain"],
            "study_type_strata": ["clinical_trial"],
            "source_strategy_group": "pmc_oai_or_pmc",
            "classification_dataset_split": "strict_classification_ready",
            "classification_ready": True,
        },
        "corpus_record": corpus_record(data_dir, document_id=document_id, text_path=text_path),
        "provenance": {"does_not_call_llm": True},
    }


def test_run_classification_smoke_dry_run_validates_mock_records(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = (
        data_dir
        / "normalized/classification_runs/20260615T120000Z_classification_sample_records.jsonl"
    )
    write_jsonl(
        input_path,
        [sample_record(data_dir, document_id="publication:pmid:1", text_path=text_path)],
    )

    result = run_classification_smoke(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=5,
        run_id="20260615T130000Z",
    )

    records_path = Path(result["records_path"])
    errors_path = Path(result["errors_path"])
    summary_path = Path(result["summary_path"])
    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines()]
    errors = errors_path.read_text(encoding="utf-8").splitlines()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    assert result["counts"]["valid_classification_records"] == 1
    assert errors == []
    assert records[0]["document_id"] == "publication:pmid:1"
    assert records[0]["model_provider"] == "dry_run"
    assert records[0]["requires_human_review"] is True
    assert records[0]["review_state"] == "needs_review"
    assert records[0]["source_text_sha256"]
    assert records[0]["evidence_spans"][0]["text"].startswith("Abstract Methods")
    assert summary["counts"]["records_with_evidence_spans"] == 1


def test_run_classification_smoke_records_missing_source_errors(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    missing_path = data_dir / "processed/missing.txt"
    input_path = (
        data_dir
        / "normalized/classification_runs/20260615T120000Z_classification_sample_records.jsonl"
    )
    write_jsonl(
        input_path,
        [sample_record(data_dir, document_id="publication:pmid:1", text_path=missing_path)],
    )

    result = run_classification_smoke(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=5,
        run_id="20260615T130000Z",
    )

    errors = [
        json.loads(line)
        for line in Path(result["errors_path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert result["counts"]["valid_classification_records"] == 0
    assert result["counts"]["errors"] == 1
    assert errors[0]["error_type"] == "FileNotFoundError"
    assert errors[0]["document_id"] == "publication:pmid:1"


def test_run_classification_smoke_rejects_non_openai_provider(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        run_classification_smoke(
            storage=LocalStorage(tmp_path / "data"),
            dry_run=False,
            provider="groq",
        )


def test_run_classification_smoke_can_filter_dataset_split(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = data_dir / "normalized/classification_corpus/records.jsonl"
    write_jsonl(
        input_path,
        [
            broader_corpus_record(
                data_dir,
                document_id="publication:pmid:broader",
                text_path=text_path,
            ),
            corpus_record(data_dir, document_id="publication:pmid:strict", text_path=text_path),
        ],
    )

    result = run_classification_smoke(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=5,
        run_id="20260615T130000Z",
        dataset_split="strict_classification_ready",
    )

    records = [
        json.loads(line)
        for line in Path(result["records_path"]).read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))

    assert result["counts"]["valid_classification_records"] == 1
    assert records[0]["document_id"] == "publication:pmid:strict"
    assert summary["dataset_split_filter"] == "strict_classification_ready"


def test_build_classification_prompt_packets_writes_prompt_and_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = (
        data_dir
        / "normalized/classification_runs/20260615T120000Z_classification_sample_records.jsonl"
    )
    legacy_english_path = (
        data_dir
        / "normalized/legacy_english_context/20260615T110000Z_legacy_english_context_records.jsonl"
    )
    write_jsonl(
        input_path,
        [sample_record(data_dir, document_id="publication:pmid:1", text_path=text_path)],
    )
    write_jsonl(
        legacy_english_path,
        [
            {
                "context_id": "legacy_english_context:test",
                "document_matches": [{"document_id": "publication:pmid:1"}],
                "key_findings": ["CBD improved a candidate endpoint."],
                "list_fields": {"Cannabinoids Studied": ["Cannabidiol (CBD)"]},
                "pmid": "1",
                "source_row_count": 1,
                "study_result": "Positive",
                "study_sample_size": None,
                "type_of_study": "Clinical Trial",
            }
        ],
    )

    result = build_classification_prompt_packets(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=5,
        run_id="20260615T140000Z",
        target_model_provider="openai",
        target_model_name="gpt-test",
    )

    packets = [
        json.loads(line)
        for line in Path(result["packets_path"]).read_text(encoding="utf-8").splitlines()
    ]
    errors = Path(result["errors_path"]).read_text(encoding="utf-8").splitlines()
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))

    assert result["counts"]["prompt_packets"] == 1
    assert errors == []
    assert packets[0]["target_model_provider"] == "openai"
    assert packets[0]["target_model_name"] == "gpt-test"
    assert packets[0]["schema_version"] == "candidate_study_classification.v3"
    assert "Do not provide medical advice" in packets[0]["system_prompt"]
    assert "Return one JSON object only" in packets[0]["user_prompt"]
    assert "Enum discipline" in packets[0]["user_prompt"]
    assert "English legacy context as the preferred baseline" in packets[0]["user_prompt"]
    assert "Do not output narrative_review" in packets[0]["user_prompt"]
    assert "Use study_design_category=other for surveys" in packets[0]["user_prompt"]
    assert "Never put cannot_determine inside a list" in packets[0]["user_prompt"]
    assert "Use cognition" in packets[0]["user_prompt"]
    assert "outcome_domains must use only" in packets[0]["user_prompt"]
    assert "Use not_applicable for descriptive surveys" in packets[0]["user_prompt"]
    assert "Use null only when an effect or association was evaluated" in packets[0]["user_prompt"]
    assert "a scoping review is scoping_review" in packets[0]["user_prompt"]
    assert "must not contradict each other" in packets[0]["user_prompt"]
    assert "source_text_sha256" in packets[0]["user_prompt"]
    assert packets[0]["response_json_schema"]["properties"]["review_state"]
    assert packets[0]["corpus_metadata"]["document_id"] == "publication:pmid:1"
    assert packets[0]["corpus_metadata"]["legacy_english_context"]["type_of_study"] == (
        "Clinical Trial"
    )
    assert summary["counts"]["prompt_packets"] == 1
    assert summary["source_excerpt_chars"]["total"] > 0


def test_build_classification_prompt_packets_records_missing_source_errors(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    missing_path = data_dir / "processed/missing.txt"
    input_path = (
        data_dir
        / "normalized/classification_runs/20260615T120000Z_classification_sample_records.jsonl"
    )
    write_jsonl(
        input_path,
        [sample_record(data_dir, document_id="publication:pmid:1", text_path=missing_path)],
    )

    result = build_classification_prompt_packets(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=5,
        run_id="20260615T140000Z",
    )

    errors = [
        json.loads(line)
        for line in Path(result["errors_path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert result["counts"]["prompt_packets"] == 0
    assert result["counts"]["errors"] == 1
    assert errors[0]["error_type"] == "FileNotFoundError"


def test_prepare_openai_batch_requests_writes_batch_jsonl_and_manifest(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = data_dir / "normalized/classification_corpus/records.jsonl"
    write_jsonl(
        input_path,
        [corpus_record(data_dir, document_id="publication:pmid:1", text_path=text_path)],
    )

    result = prepare_openai_batch_requests(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=50,
        run_id="20260710T130000Z",
        dataset_split="strict_classification_ready",
        model="gpt-test",
        max_completion_tokens=1234,
    )

    batch_requests = [
        json.loads(line)
        for line in Path(result["batch_input_path"]).read_text(encoding="utf-8").splitlines()
    ]
    manifest = [
        json.loads(line)
        for line in Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    errors = Path(result["errors_path"]).read_text(encoding="utf-8").splitlines()

    assert result["counts"]["batch_requests"] == 1
    assert errors == []
    assert batch_requests[0]["custom_id"] == (
        "classification_batch:20260710T130000Z:publication_pmid_1"
    )
    assert batch_requests[0]["method"] == "POST"
    assert batch_requests[0]["url"] == "/v1/chat/completions"
    assert batch_requests[0]["body"]["model"] == "gpt-test"
    assert batch_requests[0]["body"]["max_completion_tokens"] == 1234
    assert batch_requests[0]["body"]["response_format"] == {"type": "json_object"}
    assert len(batch_requests[0]["body"]["messages"]) == 2
    assert manifest[0]["custom_id"] == batch_requests[0]["custom_id"]
    assert manifest[0]["document_id"] == "publication:pmid:1"
    assert manifest[0]["source_text_sha256"]
    assert summary["completion_window"] == "24h"
    assert summary["dataset_split_filter"] == "strict_classification_ready"
    assert summary["estimated_tokens"]["max_completion"] == 1234


def test_prepare_openai_batch_requests_can_filter_dataset_split(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = data_dir / "normalized/classification_corpus/records.jsonl"
    write_jsonl(
        input_path,
        [
            broader_corpus_record(
                data_dir,
                document_id="publication:pmid:broader",
                text_path=text_path,
            ),
            corpus_record(data_dir, document_id="publication:pmid:strict", text_path=text_path),
        ],
    )

    result = prepare_openai_batch_requests(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=50,
        run_id="20260710T130000Z",
        dataset_split="strict_classification_ready",
    )

    manifest = [
        json.loads(line)
        for line in Path(result["manifest_path"]).read_text(encoding="utf-8").splitlines()
    ]

    assert result["counts"]["batch_requests"] == 1
    assert manifest[0]["document_id"] == "publication:pmid:strict"


def test_convert_openai_batch_outputs_writes_candidate_artifacts(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    text_path = data_dir / "processed/source.txt"
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(
        "Abstract Methods Results Cannabidiol was studied for pain in adult participants. "
        * 20,
        encoding="utf-8",
    )
    input_path = data_dir / "normalized/classification_corpus/records.jsonl"
    write_jsonl(
        input_path,
        [corpus_record(data_dir, document_id="publication:pmid:1", text_path=text_path)],
    )
    prepared = prepare_openai_batch_requests(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        limit=50,
        run_id="20260710T130000Z",
        dataset_split="strict_classification_ready",
        model="gpt-test",
    )
    custom_id = "classification_batch:20260710T130000Z:publication_pmid_1"
    model_payload = {
        "study_design_category": "clinical_trial",
        "study_design_subtype": "other",
        "evidence_context": "human_clinical",
        "medical_conditions": [
            {
                "normalized_label": "pain",
                "free_text_label": "pain",
                "ontology_entity_id": None,
                "confidence": "medium",
                "evidence_text": "Cannabidiol was studied for pain.",
            }
        ],
        "cannabinoids_or_exposures": [
            {
                "normalized_label": "cannabidiol",
                "free_text_label": "Cannabidiol",
                "ontology_entity_id": None,
                "confidence": "medium",
                "evidence_text": "Cannabidiol was studied.",
            }
        ],
        "intervention_or_exposure_role": "therapeutic_intervention",
        "population_or_model": {
            "category": "adult_humans",
            "description": "adult participants",
        },
        "outcome_domains": ["efficacy"],
        "overall_direction": "beneficial",
        "classification_confidence": "medium",
        "evidence_spans": [
            {
                "section": "Abstract",
                "text": "Cannabidiol was studied for pain in adult participants.",
                "source_text_path": str(text_path),
            }
        ],
        "supporting_sections": ["Abstract"],
        "missing_or_uncertain_fields": [],
        "warnings": [],
        "provenance": {"review_boundary": "candidate_evidence"},
    }
    output_path = data_dir / "normalized/classification_batches/output.jsonl"
    write_jsonl(
        output_path,
        [
            {
                "id": "batch_req_test",
                "custom_id": custom_id,
                "response": {
                    "status_code": 200,
                    "request_id": "req_test",
                    "body": {
                        "choices": [
                            {"message": {"content": json.dumps(model_payload, sort_keys=True)}}
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                            "total_tokens": 150,
                        },
                    },
                },
                "error": None,
            }
        ],
    )

    result = convert_openai_batch_outputs(
        storage=LocalStorage(data_dir),
        run_id="20260710T130000Z",
        batch_id="batch_test",
        manifest_path=Path(prepared["manifest_path"]),
        output_path=output_path,
    )

    records = [
        json.loads(line)
        for line in Path(result["records_path"]).read_text(encoding="utf-8").splitlines()
    ]
    raw_responses = [
        json.loads(line)
        for line in Path(result["raw_responses_path"]).read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))

    assert result["counts"]["valid_classification_records"] == 1
    assert records[0]["document_id"] == "publication:pmid:1"
    assert records[0]["model_provider"] == "openai"
    assert records[0]["model_name"] == "gpt-test"
    assert records[0]["provenance"]["method"] == "openai_batch_candidate_classification"
    assert records[0]["provenance"]["batch_id"] == "batch_test"
    assert raw_responses[0]["batch_custom_id"] == custom_id
    assert summary["usage"] == {
        "completion_tokens": 50,
        "prompt_tokens": 100,
        "total_tokens": 150,
    }
