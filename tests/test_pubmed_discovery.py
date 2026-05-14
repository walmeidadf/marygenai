from pocs.pubmed.validate_pubmed import PubMedRecord
from pocs.pubmed_discovery.discover_pubmed import (
    build_legacy_index,
    cannabinoid_focus,
    classify_against_legacy,
    classify_and_score_record,
    infer_study_design,
    score_pubmed_record,
)


def make_pubmed_record(
    *,
    pmid: str = "100",
    doi: str | None = None,
    pmcid: str | None = None,
    title: str = "Cannabidiol for chronic pain: a randomized placebo-controlled trial.",
    abstract: str | None = "Humans received cannabidiol in a double-blind placebo study.",
    publication_date: str | None = "2024-01-01",
    publication_types: list[str] | None = None,
    mesh_terms: list[str] | None = None,
    chemicals: list[str] | None = None,
    keywords: list[str] | None = None,
) -> PubMedRecord:
    return PubMedRecord(
        pmid=pmid,
        doi=doi,
        pmcid=pmcid,
        title=title,
        abstract=abstract,
        journal="Example Journal",
        publication_date=publication_date,
        publication_status="ppublish",
        publication_types=publication_types or ["Randomized Controlled Trial"],
        mesh_terms=mesh_terms or ["Humans", "Pain"],
        authors=["Jane Smith"],
        languages=["eng"],
        chemicals=chemicals if chemicals is not None else ["Cannabidiol"],
        keywords=keywords or [],
        article_ids={},
        provenance={"source": "pubmed"},
    )


def test_build_legacy_index_normalizes_identifiers() -> None:
    index = build_legacy_index(
        [
            {
                "legacy_study_id": "1",
                "pmid": "123",
                "pmcid": "pmc456",
                "doi": "10.1000/Example.",
                "canonical_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                "normalized_title": "legacy title",
            }
        ]
    )

    assert "123" in index.by_pmid
    assert "PMC456" in index.by_pmcid
    assert "10.1000/example" in index.by_doi
    assert "https://pubmed.ncbi.nlm.nih.gov/123" in index.by_canonical_url


def test_classify_against_legacy_finds_exact_pmid_match() -> None:
    index = build_legacy_index([{"legacy_study_id": "7", "pmid": "100"}])
    match = classify_against_legacy(make_pubmed_record(pmid="100"), index)

    assert match.match_status == "in_legacy_exact"
    assert match.match_type == "pmid"
    assert match.legacy_study_ids == ["7"]


def test_classify_against_legacy_marks_high_title_similarity_as_possible() -> None:
    index = build_legacy_index(
        [
            {
                "legacy_study_id": "8",
                "normalized_title": (
                    "cannabidiol for chronic pain a randomized placebo controlled trial"
                ),
            }
        ]
    )
    record = make_pubmed_record(
        pmid="200",
        title="Cannabidiol for chronic pain: randomized placebo controlled trial.",
    )
    match = classify_against_legacy(record, index)

    assert match.match_status == "possible_legacy_match"
    assert match.match_type == "fuzzy_title"
    assert match.legacy_study_ids == ["8"]


def test_classify_against_legacy_marks_record_without_signal_as_new_candidate() -> None:
    index = build_legacy_index([{"legacy_study_id": "9", "pmid": "999"}])
    record = make_pubmed_record(pmid="201", title="A distinct cannabinoid oncology review.")
    match = classify_against_legacy(record, index)

    assert match.match_status == "new_candidate"
    assert match.legacy_study_ids == []


def test_classify_against_legacy_avoids_weak_fuzzy_match_to_older_legacy_record() -> None:
    index = build_legacy_index(
        [
            {
                "legacy_study_id": "443",
                "publication_year": "2019",
                "normalized_title": (
                    "cannabinoids for the treatment of mental disorders and symptoms "
                    "of mental disorders a systematic review and meta analysis"
                ),
            }
        ]
    )
    record = make_pubmed_record(
        pmid="41856154",
        title=(
            "The efficacy and safety of cannabinoids for the treatment of mental "
            "disorders and substance use disorders: a systematic review and meta-analysis."
        ),
        publication_date="2026-03-16",
        publication_types=["Journal Article", "Systematic Review", "Meta-Analysis"],
    )
    match = classify_against_legacy(record, index)

    assert match.match_status == "new_candidate"
    assert match.legacy_study_ids == []


def test_score_pubmed_record_prioritizes_strong_recent_human_evidence() -> None:
    score, reasons = score_pubmed_record(
        make_pubmed_record(
            doi="10.1000/test",
            pmcid="PMC123",
            publication_types=["Meta-Analysis", "Randomized Controlled Trial"],
            mesh_terms=["Humans", "Pain"],
        )
    )

    assert score >= 100
    assert "study_design:meta_analysis" in reasons
    assert "review_includes_randomized_trials" in reasons
    assert "priority_condition:pain" in reasons
    assert "has_doi" in reasons
    assert "has_pmcid" in reasons


def test_infer_study_design_uses_evidence_hierarchy() -> None:
    meta_design, meta_rank, _ = infer_study_design(
        make_pubmed_record(publication_types=["Meta-Analysis", "Randomized Controlled Trial"])
    )
    rct_design, rct_rank, _ = infer_study_design(
        make_pubmed_record(publication_types=["Randomized Controlled Trial"])
    )
    cohort_design, cohort_rank, _ = infer_study_design(
        make_pubmed_record(
            title="Medical cannabis cohort study.",
            abstract="A cohort of patients was followed.",
            publication_types=["Journal Article"],
        )
    )
    case_report_design, case_report_rank, _ = infer_study_design(
        make_pubmed_record(
            title="Cannabidiol case report.",
            abstract="A case report.",
            publication_types=["Case Reports"],
        )
    )

    assert meta_design == "meta_analysis"
    assert rct_design == "randomized_controlled_trial"
    assert cohort_design == "cohort_study"
    assert case_report_design == "case_report"
    assert meta_rank > rct_rank > cohort_rank > case_report_rank


def test_score_pubmed_record_penalizes_abstract_only_cannabinoid_signal() -> None:
    score, reasons = score_pubmed_record(
        make_pubmed_record(
            title="GLP-1 receptor agonists for substance use disorders.",
            abstract="The abstract mentions cannabis use disorder as one searched outcome.",
            mesh_terms=["Humans"],
            chemicals=[],
            keywords=[],
            publication_types=["Meta-Analysis", "Systematic Review"],
        )
    )

    assert cannabinoid_focus(
        make_pubmed_record(
            title="GLP-1 receptor agonists for substance use disorders.",
            abstract="The abstract mentions cannabis use disorder as one searched outcome.",
            mesh_terms=["Humans"],
            chemicals=[],
            keywords=[],
        )
    ) == "abstract_only"
    assert score < 100
    assert "abstract_only_cannabinoid_signal" in reasons


def test_classify_and_score_record_preserves_review_fields() -> None:
    index = build_legacy_index([])
    scored = classify_and_score_record(
        make_pubmed_record(doi="10.1000/test"),
        index=index,
        query_names=["strong_evidence_pain"],
        fetched_at="2026-05-14T00:00:00+00:00",
    )

    assert scored.identity_status == "new_candidate"
    assert scored.query_names == ["strong_evidence_pain"]
    assert scored.cannabinoid_focus == "direct_title_or_indexed"
    assert scored.study_design == "Randomized Controlled Trial"
    assert scored.study_design_rank == 60
    assert scored.priority_score > 0
    assert scored.full_text_review_priority == "high_manual_full_text"
    assert scored.provenance["method"] == "legacy_anchored_pubmed_discovery"
