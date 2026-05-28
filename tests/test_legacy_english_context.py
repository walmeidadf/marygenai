from pathlib import Path

from pocs.legacy_english_context.normalize_legacy_english import (
    LegacyEnglishDocumentMatch,
    dedupe_key,
    normalize_records,
)


def test_dedupe_key_prefers_pubmed_identifier() -> None:
    assert (
        dedupe_key(
            {
                "link_to_study": "https://pubmed.ncbi.nlm.nih.gov/35319936/",
                "title": "Example",
            }
        )
        == "pmid:35319936"
    )


def test_normalize_records_aggregates_duplicate_english_context() -> None:
    rows = [
        (
            2,
            {
                "filename": "by-condition-example.html",
                "title": "Example cannabinoid study",
                "link_to_study": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123456/",
                "Key Findings": "First finding.",
                "Type of Study": "Clinical Study",
                "Study Result": "Positive",
                "Year of Pub": "2024",
                "Cannabinoids Studied": "Cannabidiol (CBD), Tetrahydrocannabinol (THC)",
            },
        ),
        (
            3,
            {
                "filename": "by-cannabinoid-example.html",
                "title": "Example cannabinoid study",
                "link_to_study": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123456/",
                "Key Findings": "Second finding.",
                "Type of Study": "Clinical Study",
                "Study Result": "Positive",
                "Year of Pub": "2024",
                "Cannabinoids Studied": "Cannabidiol (CBD), Cannabigerol (CBG)",
            },
        ),
    ]
    document_index = {
        "pmcid:PMC123456": [
            LegacyEnglishDocumentMatch(
                document_id="publication:pmcid:PMC123456",
                match_type="pmcid",
                review_state="trusted_legacy_reference",
            )
        ]
    }

    records = normalize_records(
        rows,
        input_path=Path("temp/legacy-en/studies_html_20240425_1030.csv"),
        document_index=document_index,
    )

    assert len(records) == 1
    record = records[0]
    assert record.dedupe_key == "pmcid:PMC123456"
    assert record.source_row_count == 2
    assert record.pmcid == "PMC123456"
    assert record.type_of_study == "Clinical Study"
    assert record.key_findings == ["First finding.", "Second finding."]
    assert record.list_fields["Cannabinoids Studied"] == [
        "Cannabidiol (CBD)",
        "Tetrahydrocannabinol (THC)",
        "Cannabigerol (CBG)",
    ]
    assert record.document_matches[0].document_id == "publication:pmcid:PMC123456"
