from __future__ import annotations

import json
from pathlib import Path

import pytest

from marygenai.classification.v4_assembly import validate_semantic_responses
from marygenai.classification.v4_evidence import cannabinoid_identity_labels
from marygenai.classification.v4_models import (
    MinimalSemanticFieldDecision,
    MinimalSemanticFieldResponse,
    V4EvidenceReference,
    V4PromptPacket,
)
from marygenai.classification.v4_packets import (
    build_v4_comparison_packets,
    select_comparison_samples,
)
from marygenai.classification.v4_routing import FieldRoute
from marygenai.initial_load.files import file_sha256
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_build_v4_comparison_packets_is_local_versioned_and_fair(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    samples = []
    baselines = []
    for index in range(5):
        source = data_dir / f"processed/source_{index}.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "Randomized study with 40 adult participants receiving oral cannabidiol.",
            encoding="utf-8",
        )
        document_id = f"publication:test:{index}"
        sample_id = f"sample:{index}"
        samples.append(
            {
                "sample_id": sample_id,
                "document_id": document_id,
                "primary_title": f"CBD study {index}",
                "publication_year": 2024,
                "source_strategy": "test",
                "source_text_path": str(source),
                "classification_dataset_split": "strict_classification_ready",
                "cannabinoid_focus_group": "source_text_signal",
                "corpus_metadata_candidates": {
                    "medical_condition_labels": ["Pain"],
                    "organ_system_labels": ["Nervous system"],
                    "cannabinoid_labels": ["Cannabidiol (CBD)"],
                },
                "legacy_reference_guardrails": {"available": True},
            }
        )
        evidence = {
            "text": "40 adult participants receiving oral cannabidiol",
            "char_start": 22,
            "char_end": 68,
            "source_text_path": str(source),
        }
        candidate = {
            "value": 40,
            "normalized_value": 40,
            "extraction_method": "deterministic_source_regex",
            "confidence": "high",
            "evidence": evidence,
            "attributes": {"scope": "participants"},
        }
        baselines.append(
            {
                "baseline_id": f"baseline:{index}",
                "document_id": document_id,
                "source_text_path": str(source),
                "source_text_sha256": file_sha256(source),
                "sample_size_candidates": [candidate],
                "route_candidates": [],
                "country_candidates": [],
                "population_candidates": [],
                "species_candidates": [],
                "study_design_signals": [],
                "fields_requiring_semantic_resolution": [
                    "medical_conditions",
                    "cannabinoid_role",
                    "population_category",
                    "study_structure",
                    "outcome_domains",
                    "overall_direction",
                ],
            }
        )
    sample_path = data_dir / "normalized/sample.jsonl"
    baseline_path = data_dir / "normalized/baseline.jsonl"
    write_jsonl(sample_path, samples)
    write_jsonl(baseline_path, baselines)

    result = build_v4_comparison_packets(
        storage=LocalStorage(data_dir),
        sample_path=sample_path,
        parser_records_path=baseline_path,
        limit=5,
        run_id="test-run",
    )

    packet_rows = [
        json.loads(line)
        for line in Path(result["packets_path"]).read_text(encoding="utf-8").splitlines()
    ]
    packets = [V4PromptPacket.model_validate(row) for row in packet_rows]
    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    mocks = Path(result["mock_responses_path"]).read_text(encoding="utf-8").splitlines()

    assert report["counts"] == {
        "documents": 5,
        "packets": 25,
        "broad_packets": 5,
        "selective_packets": 20,
        "schema_valid_mocks": 25,
        "assembled_mock_records": 5,
    }
    assert report["fair_comparison"]["same_documents"] is True
    assert report["fair_comparison"]["provider_calls_executed"] == 0
    assert report["token_estimator_version"] == "chars_divided_by_4.v1"
    assert len(mocks) == len(packets)
    assert all(packet.provenance["does_not_call_llm"] for packet in packets)
    assert all(packet.source_text_sha256 for packet in packets)
    assert report["strategy_metrics"]["broad"]["documents"] == 5
    assert report["strategy_metrics"]["selective"]["documents"] == 5
    assert report["field_routing_state_counts"]["semantic_resolution_required"] > 0
    assert report["field_routing_state_counts"]["insufficient_evidence"] > 0
    assert Path(result["field_routes_path"]).exists()
    assembled = Path(result["assembled_mock_records_path"]).read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(assembled) == 5
    assert all(
        packet.packet_schema_version == "classification_v4_prompt_packet.v2"
        for packet in packets
    )
    selective = [packet for packet in packets if packet.strategy == "selective"]
    assert all(
        packet.response_schema_version == "minimal_semantic_field_response.v1"
        for packet in selective
    )
    assert all(len(packet.requested_fields) < 31 for packet in selective)
    assert report["strategy_metrics"]["selective"][
        "field_instances_not_requested"
    ] > 0


def test_assembler_rejects_unknown_evidence_ids() -> None:
    route = FieldRoute(
        field_name="overall_direction",
        family="outcomes_direction",
        state="semantic_resolution_required",
        evidence_ids=["outcomes_direction:locator:1"],
        reason="Test route.",
    )
    response = MinimalSemanticFieldResponse(
        decisions=[
            MinimalSemanticFieldDecision(
                field_name="overall_direction",
                values=["beneficial"],
                evidence_ids=["missing:evidence"],
                field_confidence="medium",
            )
        ]
    )
    evidence = [
        V4EvidenceReference(
            evidence_id="outcomes_direction:locator:1",
            field_name="outcomes_direction",
            text="Results improved.",
            source_text_path="data/source.txt",
            char_start=0,
            char_end=17,
            extraction_method="test",
        )
    ]

    with pytest.raises(ValueError, match="Unknown evidence IDs"):
        validate_semantic_responses(
            routes=[route],
            evidence=evidence,
            responses={"outcomes_direction": response},
        )


def test_comparison_selection_includes_metadata_and_no_signal_contrasts() -> None:
    rows = [
        {
            "document_id": f"direct:{index}",
            "cannabinoid_focus_group": "source_text_signal",
            "source_strategy": f"source:{index % 3}",
            "classification_dataset_split": "strict_classification_ready",
        }
        for index in range(8)
    ]
    rows.extend(
        [
            {
                "document_id": "contrast:metadata",
                "cannabinoid_focus_group": "metadata_label_only",
                "source_strategy": "source:metadata",
                "classification_dataset_split": "broader_source_ready",
            },
            {
                "document_id": "contrast:none",
                "cannabinoid_focus_group": "no_signal",
                "source_strategy": "source:none",
                "classification_dataset_split": "broader_source_ready",
            },
        ]
    )

    selected, manifest = select_comparison_samples(rows, limit=8)

    assert {row["cannabinoid_focus_group"] for row in selected} >= {
        "source_text_signal",
        "metadata_label_only",
        "no_signal",
    }
    assert len(manifest) == 8


def test_metadata_guardrail_rejects_non_cannabinoid_labels() -> None:
    assert cannabinoid_identity_labels(["Phycocyanin"]) == []
    assert cannabinoid_identity_labels(["Cannabidiol (CBD)"]) == [
        "Cannabidiol (CBD)"
    ]
