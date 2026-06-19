from __future__ import annotations

import json
from pathlib import Path

from marygenai.classification.benchmark import (
    StudyDesignBenchmarkReviewDecision,
    build_study_design_holdout,
    build_study_design_validation_benchmark,
    compare_legacy_category,
    evaluate_study_design_benchmark,
    matching_title_rules,
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


def test_matching_title_rules_exposes_ambiguous_multi_rule_title(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source.txt"
    source_path.write_text("Source text", encoding="utf-8")
    record = ClassificationCorpusRecord.model_validate(
        corpus_record(
            document_id="publication:pmid:multi",
            title="A Systematic Review and Meta-Analysis of Cannabis",
            source_path=source_path,
        )
    )

    assert {rule.name for rule in matching_title_rules(record)} == {
        "meta_analysis_title",
        "systematic_review_title",
    }


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


def review_decision(
    candidate: dict,
    *,
    decision: str = "confirmed",
    reviewed_category: str | None = None,
    reviewed_subtype: str | None = None,
) -> dict:
    return {
        "schema_version": "study_design_benchmark_review_decision.v1",
        "benchmark_candidate_id": candidate["benchmark_candidate_id"],
        "benchmark_run_id": candidate["benchmark_run_id"],
        "document_id": candidate["document_id"],
        "candidate_study_design_category": candidate[
            "candidate_study_design_category"
        ],
        "candidate_study_design_subtype": candidate["candidate_study_design_subtype"],
        "legacy_english_type_of_study": candidate["legacy_english_type_of_study"],
        "decision": decision,
        "reviewed_study_design_category": (
            reviewed_category or candidate["candidate_study_design_category"]
        ),
        "reviewed_study_design_subtype": (
            reviewed_subtype or candidate["candidate_study_design_subtype"]
        ),
        "evidence_spans": [{"scope": "title", "text": candidate["primary_title"]}],
        "identity_warnings": [],
        "reviewer": "marygenai:maintainer",
        "review_method": "human_confirmed_with_ai_assistance",
        "reviewed_at": "2026-06-19T00:00:00Z",
        "review_rationale": "Source design confirmed for test.",
        "source_text_path": candidate["source_text_path"],
        "source_text_sha256": candidate["source_text_sha256"],
        "provenance": {"does_not_mutate_sqlite": True},
    }


def test_review_decision_requires_corrected_value_to_change() -> None:
    payload = {
        "schema_version": "study_design_benchmark_review_decision.v1",
        "benchmark_candidate_id": "benchmark:run:document",
        "benchmark_run_id": "run",
        "document_id": "document",
        "candidate_study_design_category": "other",
        "candidate_study_design_subtype": "survey",
        "legacy_english_type_of_study": "Meta-analysis",
        "decision": "corrected",
        "reviewed_study_design_category": "other",
        "reviewed_study_design_subtype": "survey",
        "evidence_spans": [{"scope": "title", "text": "Survey"}],
        "identity_warnings": [],
        "reviewer": "marygenai:maintainer",
        "review_method": "human_confirmed_with_ai_assistance",
        "reviewed_at": "2026-06-19T00:00:00Z",
        "review_rationale": "Test.",
        "source_text_path": "data/source.txt",
        "source_text_sha256": "a" * 64,
        "provenance": {},
    }

    try:
        StudyDesignBenchmarkReviewDecision.model_validate(payload)
    except ValueError as error:
        assert "must change" in str(error)
    else:
        raise AssertionError("Expected corrected decision validation to fail.")


def test_evaluate_validation_benchmark_reports_pair_and_legacy_accuracy(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_path = data_dir / "processed/source.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Source text", encoding="utf-8")
    input_path = (
        data_dir
        / "normalized/classification_corpus/20260619T000000Z_classification_corpus_records.jsonl"
    )
    write_jsonl(
        input_path,
        [
            corpus_record(
                document_id="publication:pmid:1",
                title="A Case Report of Cannabis Exposure",
                source_path=source_path,
            ),
            corpus_record(
                document_id="publication:pmid:2",
                title="A Pilot Study of Cannabidiol",
                source_path=source_path,
                legacy_study_type="Ensaio Clínico",
            ),
        ],
    )
    legacy_path = (
        data_dir
        / "normalized/legacy_english_context/20260619T000000Z_legacy_english_context_records.jsonl"
    )
    write_jsonl(
        legacy_path,
        [
            {
                "context_id": "legacy:1",
                "document_matches": [{"document_id": "publication:pmid:1"}],
                "type_of_study": "Meta-analysis",
            },
            {
                "context_id": "legacy:2",
                "document_matches": [{"document_id": "publication:pmid:2"}],
                "type_of_study": "Clinical Trial",
            },
        ],
    )
    build_result = build_study_design_validation_benchmark(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        sample_size=2,
        run_id="20260619T010000Z",
    )
    candidates = [
        json.loads(line)
        for line in Path(build_result["records_path"]).read_text().splitlines()
    ]
    candidates_by_document_id = {
        candidate["document_id"]: candidate for candidate in candidates
    }
    decisions_path = data_dir / "review_decisions.jsonl"
    decisions = [
        review_decision(candidates_by_document_id["publication:pmid:1"]),
        review_decision(
            candidates_by_document_id["publication:pmid:2"],
            decision="corrected",
            reviewed_category="clinical_trial",
            reviewed_subtype="pilot_study",
        ),
    ]
    write_jsonl(decisions_path, decisions)

    result = evaluate_study_design_benchmark(
        storage=LocalStorage(data_dir),
        candidates_path=Path(build_result["records_path"]),
        decisions_path=decisions_path,
        run_id="20260619T020000Z",
    )

    report = json.loads(Path(result["output_path"]).read_text())
    assert report["scope"]["reviewed_records"] == 2
    assert report["candidate_rule_metrics"]["pair_accuracy"] == 0.5
    assert report["legacy_reference_metrics"]["category_accuracy"] == 0.5


def test_build_holdout_freezes_requested_strata_and_excludes_reviewed(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_path = data_dir / "processed/source.txt"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("Source text", encoding="utf-8")
    input_path = (
        data_dir
        / "normalized/classification_corpus/20260619T000000Z_classification_corpus_records.jsonl"
    )
    rows = [
        corpus_record(
            document_id="publication:pmid:1",
            title="A Meta-Analysis of Cannabinoids",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:2",
            title="A Case Report of Cannabis Exposure",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:3",
            title="A Canine Cannabidiol Study",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:4",
            title="A Systematic Review and Meta-Analysis of Cannabis",
            source_path=source_path,
        ),
        corpus_record(
            document_id="publication:pmid:5",
            title="A Survey of Cannabis Use",
            source_path=source_path,
        ),
    ]
    write_jsonl(input_path, rows)
    legacy_path = (
        data_dir
        / "normalized/legacy_english_context/20260619T000000Z_legacy_english_context_records.jsonl"
    )
    write_jsonl(
        legacy_path,
        [
            {
                "context_id": "legacy:1",
                "document_matches": [{"document_id": "publication:pmid:1"}],
                "type_of_study": "Meta-analysis",
            },
            {
                "context_id": "legacy:2",
                "document_matches": [{"document_id": "publication:pmid:2"}],
                "type_of_study": "Meta-analysis",
            },
            {
                "context_id": "legacy:4",
                "document_matches": [{"document_id": "publication:pmid:4"}],
                "type_of_study": "Meta-analysis",
            },
            {
                "context_id": "legacy:5",
                "document_matches": [{"document_id": "publication:pmid:5"}],
                "type_of_study": "Meta-analysis",
            },
        ],
    )
    preliminary = build_study_design_validation_benchmark(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        sample_size=5,
        run_id="20260619T030000Z",
    )
    preliminary_candidates = [
        json.loads(line)
        for line in Path(preliminary["records_path"]).read_text().splitlines()
    ]
    excluded = next(
        candidate
        for candidate in preliminary_candidates
        if candidate["document_id"] == "publication:pmid:5"
    )
    decisions_path = data_dir / "excluded_decisions.jsonl"
    write_jsonl(decisions_path, [review_decision(excluded)])

    result = build_study_design_holdout(
        storage=LocalStorage(data_dir),
        input_path=input_path,
        exclude_decisions_path=decisions_path,
        exact_agreement_size=1,
        disagreement_size=1,
        no_reference_size=1,
        ambiguous_size=1,
        run_id="20260619T040000Z",
    )

    holdout = [
        json.loads(line)
        for line in Path(result["records_path"]).read_text().splitlines()
    ]
    assert len(holdout) == 4
    assert excluded["document_id"] not in {row["document_id"] for row in holdout}
    assert {
        row["provenance"]["holdout_stratum"] for row in holdout
    } == {
        "exact_legacy_agreement",
        "new_legacy_disagreement",
        "no_legacy_reference",
        "multiple_title_rules",
    }
