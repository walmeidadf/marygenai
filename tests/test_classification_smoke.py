from __future__ import annotations

import json
from pathlib import Path

import pytest

from marygenai.classification.pipeline import (
    build_classification_prompt_packets,
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
    write_jsonl(
        input_path,
        [sample_record(data_dir, document_id="publication:pmid:1", text_path=text_path)],
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
    assert "Do not provide medical advice" in packets[0]["system_prompt"]
    assert "Return one JSON object only" in packets[0]["user_prompt"]
    assert "Enum discipline" in packets[0]["user_prompt"]
    assert "outcome_domains must use only" in packets[0]["user_prompt"]
    assert "source_text_sha256" in packets[0]["user_prompt"]
    assert packets[0]["response_json_schema"]["properties"]["review_state"]
    assert packets[0]["corpus_metadata"]["document_id"] == "publication:pmid:1"
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
