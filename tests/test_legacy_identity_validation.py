import sqlite3

from pocs.legacy_identity_validation.validate_legacy_identity import (
    BaselineDocument,
    LocalIdentityValidator,
    build_confirmed_identity_records,
    normalize_identifier,
    title_embedding,
)


def test_identifier_match_wins_before_title_embedding() -> None:
    validator = LocalIdentityValidator(
        [
            BaselineDocument(
                document_id="publication:pmid:123",
                title="Different title",
                normalized_title="different title",
                publication_year=2020,
                canonical_url="https://pubmed.ncbi.nlm.nih.gov/123",
                pmid="123",
                pmcid=None,
                doi=None,
                review_state="trusted_legacy_reference",
            )
        ],
        strong_embedding_threshold=0.86,
        strong_title_threshold=0.78,
        ambiguity_margin=0.03,
    )

    record = validator.validate(
        {
            "context_id": "legacy_english_context:1",
            "title": "Unrelated wording",
            "normalized_title": "unrelated wording",
            "publication_year": 2020,
            "pmid": "123",
            "pmcid": None,
            "doi": None,
            "canonical_url": None,
            "provenance": {},
        }
    )

    assert record.bucket == "exact_identifier_match"
    assert record.selected_document_id == "publication:pmid:123"
    assert record.candidates[0].matched_identifiers == {"pmid": "123"}


def test_title_embedding_match_is_used_without_identifier() -> None:
    validator = LocalIdentityValidator(
        [
            BaselineDocument(
                document_id="publication:title:1",
                title="Cannabidiol for treatment resistant epilepsy in children",
                normalized_title="cannabidiol for treatment resistant epilepsy in children",
                publication_year=2021,
                canonical_url=None,
                pmid=None,
                pmcid=None,
                doi=None,
                review_state="trusted_legacy_reference",
            )
        ],
        strong_embedding_threshold=0.80,
        strong_title_threshold=0.75,
        ambiguity_margin=0.03,
    )

    record = validator.validate(
        {
            "context_id": "legacy_english_context:2",
            "title": "Cannabidiol for treatment-resistant epilepsy in children",
            "normalized_title": "cannabidiol for treatment resistant epilepsy in children",
            "publication_year": 2021,
            "pmid": None,
            "pmcid": None,
            "doi": None,
            "canonical_url": None,
            "provenance": {},
        }
    )

    assert record.bucket == "strong_title_embedding_match"
    assert record.selected_document_id == "publication:title:1"
    assert record.candidates[0].match_method == "title_year_local_embedding"


def test_conflicting_identifier_matches_are_ambiguous() -> None:
    validator = LocalIdentityValidator(
        [
            BaselineDocument(
                document_id="publication:pmid:123",
                title="First",
                normalized_title="first",
                publication_year=2020,
                canonical_url=None,
                pmid="123",
                pmcid=None,
                doi=None,
                review_state="trusted_legacy_reference",
            ),
            BaselineDocument(
                document_id="publication:doi:example",
                title="Second",
                normalized_title="second",
                publication_year=2020,
                canonical_url=None,
                pmid=None,
                pmcid=None,
                doi="10.1000/example",
                review_state="trusted_legacy_reference",
            ),
        ],
        strong_embedding_threshold=0.86,
        strong_title_threshold=0.78,
        ambiguity_margin=0.03,
    )

    record = validator.validate(
        {
            "context_id": "legacy_english_context:3",
            "title": "First",
            "normalized_title": "first",
            "publication_year": 2020,
            "pmid": "123",
            "pmcid": None,
            "doi": "10.1000/example",
            "canonical_url": None,
            "provenance": {},
        }
    )

    assert record.bucket == "ambiguous_identity"
    assert record.selected_document_id is None
    assert {candidate.document_id for candidate in record.candidates} == {
        "publication:pmid:123",
        "publication:doi:example",
    }


def test_unmatched_strong_identifier_does_not_fall_back_to_title_embedding() -> None:
    validator = LocalIdentityValidator(
        [
            BaselineDocument(
                document_id="publication:title:1",
                title="Cannabidiol for treatment resistant epilepsy in children",
                normalized_title="cannabidiol for treatment resistant epilepsy in children",
                publication_year=2021,
                canonical_url=None,
                pmid=None,
                pmcid=None,
                doi=None,
                review_state="trusted_legacy_reference",
            )
        ],
        strong_embedding_threshold=0.80,
        strong_title_threshold=0.75,
        ambiguity_margin=0.03,
    )

    record = validator.validate(
        {
            "context_id": "legacy_english_context:4",
            "title": "Cannabidiol for treatment-resistant epilepsy in children",
            "normalized_title": "cannabidiol for treatment resistant epilepsy in children",
            "publication_year": 2021,
            "pmid": "999999",
            "pmcid": None,
            "doi": None,
            "canonical_url": None,
            "provenance": {},
        }
    )

    assert record.bucket == "no_local_match"
    assert record.selected_document_id is None
    assert record.candidates == []


def test_identifier_and_embedding_helpers_are_local_and_stable() -> None:
    assert normalize_identifier("doi", "https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert normalize_identifier("pmcid", "pmc123") == "PMC123"
    assert len(title_embedding("cannabis and pain")) == 384


def test_confirmed_identity_export_includes_no_queue_and_resolved_items_only() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE review_item (
            review_item_id TEXT PRIMARY KEY,
            queue_type TEXT NOT NULL,
            document_id TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE review_decision (
            review_decision_id TEXT PRIMARY KEY,
            review_item_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO review_item VALUES (
            'review_item:resolved',
            'legacy_identity_review',
            'document:resolved',
            'resolved'
        );
        INSERT INTO review_decision VALUES (
            'review_decision:resolved',
            'review_item:resolved',
            'corrected_identity',
            'reviewer',
            '2026-05-26T00:00:00+00:00'
        );
        INSERT INTO review_item VALUES (
            'review_item:open',
            'legacy_identity_review',
            'document:open',
            'open'
        );
        """
    )
    contexts = {
        "context:no_queue": {"context_id": "context:no_queue", "title": "No queue"},
        "context:resolved": {"context_id": "context:resolved", "title": "Resolved"},
        "context:open": {"context_id": "context:open", "title": "Open"},
    }
    validation_records = [
        {
            "context_id": "context:no_queue",
            "bucket": "exact_identifier_match",
            "selected_document_id": "document:no_queue",
            "candidates": [],
            "provenance": {},
        },
        {
            "context_id": "context:resolved",
            "bucket": "exact_identifier_match",
            "selected_document_id": "document:resolved",
            "candidates": [],
            "provenance": {},
        },
        {
            "context_id": "context:open",
            "bucket": "exact_identifier_match",
            "selected_document_id": "document:open",
            "candidates": [],
            "provenance": {},
        },
    ]

    records = build_confirmed_identity_records(
        validation_records,
        contexts_by_id=contexts,
        connection=connection,
    )

    assert {record["document_id"] for record in records} == {
        "document:no_queue",
        "document:resolved",
    }
    assert {
        record["identity_confirmation_status"]
        for record in records
    } == {
        "trusted_legacy_reference_no_identity_queue",
        "workflow_resolved_identity_review",
    }
