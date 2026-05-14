from pocs.icite_enrichment.enrich_icite import (
    build_enriched_record,
    parse_icite_response,
    score_citation_priority,
)


def source_record() -> dict[str, object]:
    return {
        "pmid": "123",
        "title": "Cannabidiol randomized trial",
        "priority_score": 140,
        "study_design": "Randomized Controlled Trial",
        "study_design_rank": 60,
        "cannabinoid_focus": "direct_title_or_indexed",
        "full_text_review_priority": "high_manual_full_text",
        "publication_date": "2026-04-01",
        "score_reasons": ["study_design:randomized_controlled_trial"],
        "provenance": {"source": "pubmed"},
    }


def test_parse_icite_response_accepts_legacy_and_database_field_names() -> None:
    parsed = parse_icite_response(
        {
            "data": [
                {
                    "pmid": 123,
                    "year": 2024,
                    "citation_count": 42,
                    "relative_citation_ratio": 2.5,
                    "nih_percentile": 88.0,
                    "human": 1,
                    "animal": 0,
                    "molecular_cellular": 0,
                    "apt": 0.76,
                    "is_clinical": False,
                    "cited_by_clin": [1, 2, 3],
                    "provisional": False,
                },
                {
                    "pmid": "456",
                    "pubYear": 2023,
                    "citedByPmidCount": 7,
                    "rcr": 1.2,
                    "nihRcrPercentile": 70,
                    "molCell": 0.8,
                    "isClinicalArticle": True,
                    "citingClinicalPmids": [9],
                    "rcrIsProvisional": True,
                },
            ]
        }
    )

    assert parsed["123"].citation_count == 42
    assert parsed["123"].relative_citation_ratio == 2.5
    assert parsed["123"].cited_by_clinical_count == 3
    assert parsed["456"].year == 2023
    assert parsed["456"].molecular_cellular == 0.8
    assert parsed["456"].is_clinical is True
    assert parsed["456"].rcr_is_provisional is True


def test_build_enriched_record_preserves_pubmed_discovery_fields() -> None:
    metrics = parse_icite_response(
        {
            "pmid": "123",
            "citation_count": 20,
            "relative_citation_ratio": 1.4,
            "human": 1,
            "apt": 0.6,
        }
    )["123"]
    enriched = build_enriched_record(
        source_record(),
        metrics=metrics,
        input_path=__file__,
        fetched_at="2026-05-14T00:00:00+00:00",
    )

    assert enriched.priority_score == 140
    assert enriched.study_design_rank == 60
    assert enriched.cannabinoid_focus == "direct_title_or_indexed"
    assert enriched.full_text_review_priority == "high_manual_full_text"
    assert enriched.icite_citation_count == 20
    assert enriched.source_record["provenance"] == {"source": "pubmed"}
    assert enriched.icite_provenance["source"] == "nih_icite"
    assert enriched.citation_priority_score > 0


def test_score_citation_priority_keeps_missing_metrics_non_error() -> None:
    score, reasons, notes = score_citation_priority(
        metrics=None,
        source_record=source_record(),
        current_year=2026,
    )

    assert score == 0
    assert reasons == ["icite_metrics_absent"]
    assert "missing_iCite_metrics_not_evidence_quality" in notes


def test_score_citation_priority_notes_recent_citation_bias() -> None:
    metrics = parse_icite_response(
        {
            "pmid": "123",
            "year": 2026,
            "citation_count": 0,
            "relative_citation_ratio": 0.2,
            "human": 1,
        }
    )["123"]
    score, reasons, notes = score_citation_priority(
        metrics=metrics,
        source_record=source_record(),
        current_year=2026,
    )

    assert score > 0
    assert "recent_low_citation_floor" in reasons
    assert "recent_publication_citation_bias_possible" in notes
    assert "citation_metrics_are_prioritization_not_evidence_quality" in notes
