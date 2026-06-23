from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.retrieval_baseline import (
    run_retrieval_metadata_baseline,
)
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_retrieval_metadata_baseline_extracts_candidates_and_preserves_boundary(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_path = data_dir / "processed/study.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "Methods: This randomized, double-blind, placebo-controlled study was "
        "conducted in Brazil. Participants were randomized to oral cannabidiol "
        "or placebo. Results: 40 patients completed the study.",
        encoding="utf-8",
    )
    sample_path = data_dir / "normalized/classification_evaluations/sample.jsonl"
    write_jsonl(
        sample_path,
        [
            {
                "document_id": "publication:1",
                "primary_title": "Cannabidiol trial",
                "publication_year": 2024,
                "source_text_path": str(source_path),
                "source_strategy": "test",
                "classification_dataset_split": "strict_classification_ready",
                "cannabinoid_focus_group": "source_text_signal",
                "legacy_reference_guardrails": {
                    "study_sample_size": "40",
                    "study_locations": ["Brazil"],
                    "route_of_administration": ["Oral (Ingestion)"],
                },
            }
        ],
    )

    result = run_retrieval_metadata_baseline(
        storage=LocalStorage(data_dir),
        input_path=sample_path,
        run_id="test-run",
    )

    record = json.loads(
        Path(result["records_path"]).read_text(encoding="utf-8").splitlines()[0]
    )
    assert record["source_text_sha256"]
    assert 40 in [
        candidate["normalized_value"]
        for candidate in record["sample_size_candidates"]
    ]
    assert "oral" in [
        candidate["normalized_value"] for candidate in record["route_candidates"]
    ]
    assert "Brazil" in [
        candidate["normalized_value"] for candidate in record["country_candidates"]
    ]
    assert {
        candidate["normalized_value"] for candidate in record["study_design_signals"]
    } >= {"randomized", "double_blind", "placebo_controlled"}
    assert record["guardrail_comparison"]["sample_size"]["reference_value_found"] is True
    assert record["guardrail_comparison"]["route"]["overlap"] == ["oral"]
    assert record["provenance"]["does_not_call_llm"] is True
    assert record["provenance"]["does_not_mutate_sqlite"] is True
