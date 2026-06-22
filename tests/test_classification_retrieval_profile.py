from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.retrieval_profile import profile_retrieval_fields
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def corpus_record(
    document_id: str,
    *,
    year: int,
    split: str,
    source_ready: bool,
    strategy: str,
) -> dict:
    return {
        "document_id": document_id,
        "primary_title": document_id,
        "publication_year": year,
        "canonical_url": f"https://example.org/{document_id}",
        "medical_condition_labels": ["Pain"],
        "organ_system_labels": ["Nervous system"] if source_ready else [],
        "cannabinoid_labels": ["Cannabidiol (CBD)"],
        "legacy_study_type": "Clinical Trial",
        "legacy_result": "Positive",
        "source_text_path": f"processed/{document_id}.txt" if source_ready else None,
        "source_strategy": strategy,
        "cannabinoid_term_hit_count": 1 if source_ready else 0,
        "source_ready": source_ready,
        "classification_ready": split == "strict_classification_ready",
        "classification_dataset_split": split,
    }


def legacy_context(document_id: str, *, year: int) -> dict:
    return {
        "context_id": f"legacy:{document_id}",
        "publication_year": year,
        "type_of_study": "Clinical Trial",
        "study_result": "Positive",
        "study_sample_size": "30",
        "key_findings": ["Candidate finding."],
        "list_fields": {
            "Study Location(s)": ["Brazil"],
            "Cannabinoids Studied": ["Cannabidiol (CBD)"],
            "Route of Administration": ["Oral (Ingestion)"],
        },
        "document_matches": [{"document_id": document_id}],
    }


def test_profile_retrieval_fields_uses_downloaded_corpus_as_execution_universe(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    corpus_path = data_dir / "normalized/classification_corpus/corpus.jsonl"
    legacy_path = data_dir / "normalized/legacy_english_context/legacy.jsonl"
    write_jsonl(
        corpus_path,
        [
            corpus_record(
                "publication:1",
                year=2024,
                split="strict_classification_ready",
                source_ready=True,
                strategy="pmc_oai",
            ),
            corpus_record(
                "publication:2",
                year=2023,
                split="broader_source_ready",
                source_ready=True,
                strategy="augmented_links",
            ),
            corpus_record(
                "publication:3",
                year=2022,
                split="not_source_ready",
                source_ready=False,
                strategy="unknown",
            ),
        ],
    )
    write_jsonl(
        legacy_path,
        [
            legacy_context("publication:1", year=2024),
            legacy_context("publication:2", year=2021),
            legacy_context("publication:legacy-only", year=2020),
        ],
    )

    result = profile_retrieval_fields(
        storage=LocalStorage(data_dir),
        corpus_path=corpus_path,
        legacy_context_path=legacy_path,
        sample_size=2,
        run_id="test-run",
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["execution_universe"]["downloaded_canonical_corpus_records"] == 3
    assert report["execution_universe"]["source_ready_records"] == 2
    assert report["execution_universe"]["strict_classification_ready_records"] == 1
    assert report["execution_universe"]["broader_source_ready_records"] == 1
    assert report["legacy_reference"]["records"] == 3
    comparison = report["legacy_reference"]["corpus_alignment"][
        "publication_year_comparison"
    ]
    assert comparison["comparable_records"] == 2
    assert comparison["exact_matches"] == 1
    assert comparison["disagreements"] == 1
    sample_rows = [
        json.loads(line)
        for line in Path(result["sample_path"]).read_text(encoding="utf-8").splitlines()
    ]
    assert len(sample_rows) == 2
    assert all(row["provenance"]["does_not_call_llm"] for row in sample_rows)
    assert all(row["legacy_reference_guardrails"]["available"] for row in sample_rows)
