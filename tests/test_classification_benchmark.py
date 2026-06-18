from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.benchmark import (
    build_study_design_validation_benchmark,
    compare_legacy_category,
    title_rule_for_record,
)
from marygenai.classification_corpus.models import ClassificationCorpusRecord
from marygenai.storage import LocalStorage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def corpus_record(
    *,
    document_id: str,
    title: str,
    source_path: Path,
    legacy_study_type: str = "Metanálise",
) -> dict:
    return {
        "document_id": document_id,
        "legacy_study_id": document_id.rsplit(":", maxsplit=1)[-1],
        "primary_title": title,
        "publication_year": 2024,
        "pmid": None,
        "pmcid": None,
        "doi": None,
        "canonical_url": "https://example.org/study",
        "legacy_study_type": legacy_study_type,
        "legacy_result": "Positivo",
        "medical_condition_labels": ["Pain"],
        "organ_system_labels": ["Nervous system"],
        "cannabinoid_labels": ["Cannabidiol (CBD)"],
        "source_strategy": "test",
        "source_url": "https://example.org/source",
        "source_text_path": str(source_path),
        "raw_payload_path": None,
        "extracted_text_chars": source_path.stat().st_size,
        "scientific_section_hit_count": 4,
        "cannabinoid_term_hit_count": 1,
        "source_ready": True,
        "classification_ready": True,
        "classification_dataset_split": "strict_classification_ready",
        "trust_level": "source_text_available",
        "provenance": {"method": "test"},
    }


def test_title_rule_precedence_prefers_scoping_over_review_terms(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Source text", encoding="utf-8")
    record = ClassificationCorpusRecord.model_validate(
        corpus_record(
            document_id="publication:pmid:1",
            title="A Scoping Review and Systematic Search of Cannabis Studies",
            source_path=source_path,
        )
    )

    rule = title_rule_for_record(record)

    assert rule is not None
    assert rule.name == "scoping_review_title"
    assert rule.category == "clinical_meta_analysis"
    assert rule.subtype == "scoping_review"


def test_title_rule_precedence_avoids_secondary_trial_mentions(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Source text", encoding="utf-8")
    record = ClassificationCorpusRecord.model_validate(
        corpus_record(
            document_id="publication:pmid:2",
            title="A Systematic Review of Randomized Controlled Trials",
            source_path=source_path,
        )
    )

    rule = title_rule_for_record(record)

    assert rule is not None
    assert rule.name == "systematic_review_title"
    assert rule.category == "clinical_meta_analysis"
    assert rule.subtype == "systematic_review"


def test_title_rule_combines_pilot_with_primary_trial_design(tmp_path: Path) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Source text", encoding="utf-8")
    record = ClassificationCorpusRecord.model_validate(
        corpus_record(
            document_id="publication:pmid:3",
            title="A Pilot, Double-Blind, Placebo-Controlled Trial",
            source_path=source_path,
        )
    )

    rule = title_rule_for_record(record)

    assert rule is not None
    assert rule.category == "double_blind_clinical_trial"
    assert rule.subtype == "pilot_study"


def test_title_rule_prefers_explicit_animal_context_over_trial_wording(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Source text", encoding="utf-8")
    record = ClassificationCorpusRecord.model_validate(
        corpus_record(
            document_id="publication:pmid:4",
            title="A Randomized Double-Blind Cannabidiol Trial in Canine Arthritis",
            source_path=source_path,
        )
    )

    rule = title_rule_for_record(record)

    assert rule is not None
    assert rule.category == "animal_study"


def test_legacy_comparison_separates_compatible_refinement() -> None:
    assert (
        compare_legacy_category("clinical_meta_analysis", "meta_analysis")
        == "compatible_refinement"
    )
    assert compare_legacy_category("other", "meta_analysis") == "disagreement"


def test_build_validation_benchmark_is_stratified_and_review_first(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_path = data_dir / "processed/source.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Abstract Methods Results Cannabis study.", encoding="utf-8")
    input_path = (
        data_dir
        / "normalized/classification_corpus/20260618T000000Z_classification_corpus_records.jsonl"
    )
    rows = [
        corpus_record(
            document_id="publication:pmid:1",
            title="A Pilot Study of Cannabidiol",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:2",
            title="Clinician Survey of Medical Cannabis",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:3",
            title="A Case Report of Delta-8 THC",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:4",
            title="Cannabinoids: A Meta-Analysis",
            source_path=source_path,
        ),
    ]
    write_jsonl(input_path, rows)
    legacy_path = (
        data_dir
        / "normalized/legacy_english_context/20260618T000000Z_legacy_english_context_records.jsonl"
    )
    write_jsonl(
        legacy_path,
        [
            {
                "context_id": f"legacy:{index}",
                "document_matches": [{"document_id": row["document_id"]}],
                "type_of_study": "Meta-analysis",
            }
            for index, row in enumerate(rows, start=1)
        ],
    )

    result = build_study_design_validation_benchmark(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        sample_size=4,
        run_id="20260618T010000Z",
    )

    records = [
        json.loads(line)
        for line in Path(result["records_path"]).read_text(encoding="utf-8").splitlines()
    ]
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))

    assert result["counts"]["selected_candidates"] == 4
    assert set(result["selected_rule_counts"]) == {
        "case_report_or_series_title",
        "meta_analysis_title",
        "pilot_study_title",
        "survey_title",
    }
    assert all(record["requires_human_review"] is True for record in records)
    assert all(record["review_state"] == "needs_review" for record in records)
    assert all(record["reviewer"] is None for record in records)
    assert all(len(record["source_text_sha256"]) == 64 for record in records)
    assert all(record["selection_basis"] == "explicit_title_phrase" for record in records)
    assert all(record["matched_title_phrase"] for record in records)
    assert all(record["provenance"]["does_not_call_llm"] is True for record in records)
    assert all(record["provenance"]["does_not_mutate_sqlite"] is True for record in records)
    assert summary["counts"]["selected_legacy_disagreements"] == 3
    assert summary["counts"]["selected_legacy_compatible_refinements"] == 0
