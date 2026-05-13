from pathlib import Path

from pocs.access_enrichment.enrich_access import (
    bool_or_none,
    build_enrichment_record,
    dedupe_preserving_order,
    doi_from_europe_pmc_payload,
    first_europe_pmc_result,
    is_free_or_open_access_url,
    is_pdf_url,
    select_sample,
    unpaywall_best_location,
)


def test_select_sample_limits_target_classes() -> None:
    records = [
        {"access_class": "pubmed_metadata_only", "source_record_id": "1"},
        {"access_class": "pubmed_metadata_only", "source_record_id": "2"},
        {"access_class": "doi_landing_page_available", "source_record_id": "3"},
        {"access_class": "pmc_full_text_available", "source_record_id": "4"},
    ]

    selected = select_sample(records, limit_per_class=1)

    assert [record["source_record_id"] for record in selected] == ["1", "3"]


def test_first_europe_pmc_result_returns_none_for_empty_payload() -> None:
    assert first_europe_pmc_result({"resultList": {"result": []}}) is None


def test_doi_from_europe_pmc_payload_returns_first_result_doi() -> None:
    payload = {"resultList": {"result": [{"doi": "10.1000/example"}]}}
    assert doi_from_europe_pmc_payload(payload) == "10.1000/example"


def test_unpaywall_best_location_ignores_not_found_payload() -> None:
    assert unpaywall_best_location({"not_found": True}) is None


def test_dedupe_preserving_order_removes_repeated_urls() -> None:
    assert dedupe_preserving_order(["a", "b", "a"]) == ["a", "b"]


def test_bool_or_none_parses_api_strings() -> None:
    assert bool_or_none("Y") is True
    assert bool_or_none("N") is False
    assert bool_or_none(None) is None


def test_europe_pmc_url_filters() -> None:
    assert is_free_or_open_access_url({"availabilityCode": "F"})
    assert is_free_or_open_access_url({"availabilityCode": "OA"})
    assert not is_free_or_open_access_url({"availabilityCode": "S"})
    assert is_pdf_url({"documentStyle": "pdf", "url": "https://example.org/article"})
    assert is_pdf_url({"documentStyle": "html", "url": "https://example.org/article.pdf"})


def test_build_enrichment_record_prefers_pdf_candidate() -> None:
    record = build_enrichment_record(
        {"source_record_id": "1", "access_class": "doi_landing_page_available", "doi": "10.x/y"},
        europe_pmc_payload={"resultList": {"result": []}},
        unpaywall_payload={
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_landing_page": "https://example.org/article",
                "url_for_pdf": "https://example.org/article.pdf",
                "license": "cc-by",
            },
        },
        europe_pmc_queried=True,
        unpaywall_queried=True,
        errors=[],
        input_path=Path("input.jsonl"),
        fetched_at="2026-05-13T00:00:00Z",
    )

    assert record.resolved_access_class == "open_access_pdf_candidate"
    assert record.unpaywall_best_pdf_url == "https://example.org/article.pdf"
    assert record.unpaywall_license == "cc-by"


def test_build_enrichment_record_ignores_subscription_required_links() -> None:
    record = build_enrichment_record(
        {"source_record_id": "1", "access_class": "pubmed_metadata_only", "pmid": "123"},
        europe_pmc_payload={
            "resultList": {
                "result": [
                    {
                        "pmid": "123",
                        "fullTextUrlList": {
                            "fullTextUrl": [
                                {
                                    "availabilityCode": "S",
                                    "documentStyle": "doi",
                                    "url": "https://doi.org/10.1000/example",
                                }
                            ]
                        },
                    }
                ]
            }
        },
        unpaywall_payload=None,
        europe_pmc_queried=True,
        unpaywall_queried=False,
        errors=[],
        input_path=Path("input.jsonl"),
        fetched_at="2026-05-13T00:00:00Z",
    )

    assert record.resolved_access_class == "metadata_enriched_no_full_text"
    assert record.candidate_full_text_urls == []
    assert record.candidate_pdf_urls == []
