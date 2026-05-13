from pathlib import Path

from pocs.link_resolver.resolve_links import (
    doi_url,
    pmc_article_url,
    pmc_pdf_candidate_url,
    pubmed_url,
    resolve_record,
)


def test_pmcid_record_resolves_to_pmc_full_text() -> None:
    record = resolve_record(
        {
            "legacy_study_id": "3",
            "pmcid": "PMC7235264",
            "pmid": None,
            "doi": None,
            "canonical_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7235264",
            "host": "ncbi.nlm.nih.gov",
            "title_en": "Example",
        },
        input_path=Path("input.jsonl"),
        fetched_at="2026-05-13T00:00:00Z",
    )

    assert record.access_class == "pmc_full_text_available"
    assert record.full_text_url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC7235264/"
    assert record.pdf_candidate_url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC7235264/pdf/"
    assert not record.requires_network_resolution


def test_doi_record_requires_unpaywall_or_europe_pmc_resolution() -> None:
    record = resolve_record(
        {"doi": "10.1000/example", "title": "Example"},
        input_path=Path("input.jsonl"),
        fetched_at="2026-05-13T00:00:00Z",
    )

    assert record.access_class == "doi_landing_page_available"
    assert record.landing_url == "https://doi.org/10.1000/example"
    assert "query_unpaywall" in record.next_resolver_steps
    assert record.requires_network_resolution


def test_pmid_only_record_requires_pubmed_enrichment() -> None:
    record = resolve_record(
        {"pmid": "35319936", "title": "Example"},
        input_path=Path("input.jsonl"),
        fetched_at="2026-05-13T00:00:00Z",
    )

    assert record.access_class == "pubmed_metadata_only"
    assert record.landing_url == "https://pubmed.ncbi.nlm.nih.gov/35319936/"
    assert "query_pubmed_for_pmcid_and_doi" in record.next_resolver_steps


def test_url_helpers() -> None:
    assert pmc_article_url("PMC1") == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/"
    assert pmc_pdf_candidate_url("PMC1") == "https://pmc.ncbi.nlm.nih.gov/articles/PMC1/pdf/"
    assert pubmed_url("123") == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert doi_url("10.1000/example") == "https://doi.org/10.1000/example"
