import sqlite3
from pathlib import Path

from marygenai.persistence.sqlite import initialize_schema
from pocs.identity_identifier_resolution.apply_review_identifier_resolutions import (
    GOLD_CLASSIFICATION,
    apply_classification,
    classify_resolution_record,
)
from pocs.identity_identifier_resolution.resolve_review_identifiers import (
    IdentifierCandidate,
    ReviewIdentifierInput,
    best_identifier,
    extract_sciencedirect_pii,
    normalize_doi,
    read_review_inputs,
    resolution_status,
    title_similarity,
)


def test_extract_sciencedirect_pii_from_article_url() -> None:
    assert (
        extract_sciencedirect_pii(
            "https://www.sciencedirect.com/science/article/pii/S0164121223001234?via%3Dihub"
        )
        == "S0164121223001234"
    )


def test_extract_sciencedirect_pii_from_abstract_article_url() -> None:
    assert (
        extract_sciencedirect_pii(
            "https://www.sciencedirect.com/science/article/abs/pii/S0306987724000012#abstract"
        )
        == "S0306987724000012"
    )


def test_require_sciencedirect_pii_selects_abstract_article_urls() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE review_item (
            review_item_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            queue_type TEXT NOT NULL,
            status TEXT NOT NULL,
            priority_tier TEXT NOT NULL,
            priority_score REAL NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE document (
            document_id TEXT PRIMARY KEY,
            primary_title TEXT,
            publication_year INTEGER,
            canonical_url TEXT,
            pmid TEXT,
            pmcid TEXT,
            doi TEXT
        );
        CREATE TABLE publication (
            document_id TEXT PRIMARY KEY,
            legacy_study_id TEXT,
            legacy_study_type TEXT
        );
        CREATE TABLE document_identity (
            document_id TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            confidence REAL NOT NULL
        );
        """
    )
    connection.execute(
        """
        INSERT INTO review_item VALUES
        (
            'review_item:1',
            'publication:1',
            'legacy_identity_review',
            'open',
            'test',
            1,
            '2026-01-01'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO document VALUES
        (
            'publication:1',
            'Example study',
            2024,
            'https://www.sciencedirect.com/science/article/abs/pii/S0306987724000012',
            NULL,
            NULL,
            NULL
        )
        """
    )
    connection.execute("INSERT INTO publication VALUES ('publication:1', '1', 'Article')")

    inputs = read_review_inputs(
        connection,
        queue_type="legacy_identity_review",
        status="open",
        limit=10,
        require_sciencedirect_pii=True,
    )

    assert [item.document_id for item in inputs] == ["publication:1"]


def test_normalize_doi_from_landing_url_text() -> None:
    assert normalize_doi("https://doi.org/10.1016/j.example.2023.01.001.") == (
        "10.1016/j.example.2023.01.001"
    )


def test_best_identifier_prefers_high_confidence_candidate() -> None:
    candidates = [
        IdentifierCandidate(source="openalex", doi="10.1000/low", score=99, confidence="low"),
        IdentifierCandidate(source="crossref", doi="10.1000/high", score=10, confidence="high"),
    ]

    assert best_identifier(candidates, "doi") == "10.1000/high"


def test_resolution_status_for_pii_with_resolved_identifier() -> None:
    item = ReviewIdentifierInput(
        review_item_id="review_item:1",
        document_id="publication:1",
        status="open",
        priority_tier="test",
        priority_score=1,
        title="Example study",
        publication_year=2023,
        canonical_url="https://www.sciencedirect.com/science/article/pii/S123",
        known_pmid=None,
        known_pmcid=None,
        known_doi=None,
        legacy_study_id="1",
        legacy_study_type=None,
    )

    assert (
        resolution_status(
            item,
            {"doi": "10.1000/example", "pmid": None, "pmcid": None},
            pii="S123",
            candidates=[],
            errors=[],
        )
        == "identifier_resolved"
    )


def test_title_similarity_is_case_and_spacing_tolerant() -> None:
    assert title_similarity("  Example   Study ", "example study") == 1.0


def test_classify_resolution_record_marks_strong_pubmed_match_as_gold() -> None:
    classification = classify_resolution_record(sciencedirect_resolution_record())

    assert classification.classification == GOLD_CLASSIFICATION
    assert classification.apply_decision is True
    assert classification.resolved["doi"] == "10.1016/j.example.2024.01.001"
    assert classification.title_similarity == 1.0
    assert classification.year_delta == 0


def test_apply_classification_writes_decision_identities_and_resolves_item(
    tmp_path: Path,
) -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_schema(connection)
    insert_apply_test_review_item(connection)
    record = sciencedirect_resolution_record()
    classification = classify_resolution_record(record)

    apply_classification(
        connection,
        record=record,
        classification=classification,
        reviewer="test-reviewer",
        records_path=tmp_path / "records.jsonl",
        run_id="20260525T200000Z_identity_resolution_apply",
    )

    review_item = connection.execute("SELECT status FROM review_item").fetchone()
    document = connection.execute("SELECT doi, pmid, pmcid FROM document").fetchone()
    decision = connection.execute(
        "SELECT decision, reviewed_doi, reviewed_pmid FROM review_decision"
    ).fetchone()
    identities = connection.execute(
        """
        SELECT identifier_type, identifier_value, association_state
        FROM document_identity
        ORDER BY identifier_type
        """
    ).fetchall()

    assert review_item["status"] == "resolved"
    assert document["doi"] == "10.1016/j.example.2024.01.001"
    assert document["pmid"] == "12345678"
    assert document["pmcid"] == "PMC123456"
    assert decision["decision"] == "corrected_identity"
    assert decision["reviewed_doi"] == "10.1016/j.example.2024.01.001"
    assert decision["reviewed_pmid"] == "12345678"
    assert {(row["identifier_type"], row["identifier_value"]) for row in identities} == {
        ("doi", "10.1016/j.example.2024.01.001"),
        ("pii", "S1234567890123456"),
        ("pmcid", "PMC123456"),
        ("pmid", "12345678"),
    }
    assert {row["association_state"] for row in identities} == {GOLD_CLASSIFICATION}


def sciencedirect_resolution_record() -> dict[str, object]:
    return {
        "review_item_id": "review_item:science_direct",
        "document_id": "publication:url:science_direct",
        "title": "Example cannabinoid study",
        "publication_year": 2024,
        "canonical_url": "https://www.sciencedirect.com/science/article/abs/pii/S1234567890123456",
        "extracted_pii": "S1234567890123456",
        "known": {"doi": None, "pmid": None, "pmcid": None},
        "resolved": {
            "doi": "10.1016/j.example.2024.01.001",
            "pmid": "12345678",
            "pmcid": "PMC123456",
        },
        "resolution_status": "identifier_resolved",
        "recommended_review_decision": "candidate_corrected_identity",
        "candidates": [
            {
                "source": "crossref",
                "doi": "10.1016/j.example.2024.01.001",
                "pmid": None,
                "pmcid": None,
                "title": "Example cannabinoid study",
                "publication_year": 2024,
                "score": 100.0,
                "confidence": "high",
                "evidence": {
                    "pii": "S1234567890123456",
                    "alternative_ids": ["S1234567890123456"],
                    "title_similarity": 1.0,
                },
            },
            {
                "source": "pubmed",
                "doi": "10.1016/j.example.2024.01.001",
                "pmid": "12345678",
                "pmcid": "PMC123456",
                "title": "Example cannabinoid study",
                "publication_year": 2024,
                "score": None,
                "confidence": "high",
                "evidence": {"query": "10.1016/j.example.2024.01.001[AID]"},
            },
        ],
        "errors": [],
        "provenance": {"source": "identity_identifier_resolution"},
    }


def insert_apply_test_review_item(connection: sqlite3.Connection) -> None:
    now = "2026-05-25T20:00:00+00:00"
    connection.execute(
        """
        INSERT INTO run_manifest (
            run_id, job_type, source, started_at, completed_at, status, software_version,
            input_artifacts_json, output_artifacts_json, counts_json, errors_json,
            notes_json, manifest_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "20260525T200000Z_identity_resolution_apply",
            "identity_identifier_resolution_apply",
            "identity_identifier_resolution",
            now,
            now,
            "succeeded",
            "test",
            "{}",
            "{}",
            "{}",
            "[]",
            "{}",
            None,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO document (
            document_id, document_type, primary_title, publication_year, canonical_url,
            pmid, pmcid, doi, lifecycle_state, review_state, provenance_json, run_id
        )
        VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?)
        """,
        (
            "publication:url:science_direct",
            "publication",
            "Example cannabinoid study",
            2024,
            "https://www.sciencedirect.com/science/article/abs/pii/S1234567890123456",
            "active",
            "needs_review",
            "{}",
            "20260525T200000Z_identity_resolution_apply",
        ),
    )
    connection.execute(
        """
        INSERT INTO publication (
            document_id, title_pt, title_en, normalized_title, legacy_study_id,
            legacy_study_type, legacy_result, legacy_reference_values_json
        )
        VALUES (?, NULL, ?, ?, ?, ?, NULL, ?)
        """,
        (
            "publication:url:science_direct",
            "Example cannabinoid study",
            "example cannabinoid study",
            "legacy-1",
            "Article",
            "{}",
        ),
    )
    connection.execute(
        """
        INSERT INTO review_item (
            review_item_id, queue_type, document_id, priority_tier, priority_score,
            assignee, status, batch_run_id, metadata_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            "review_item:science_direct",
            "legacy_identity_review",
            "publication:url:science_direct",
            "test",
            100.0,
            "open",
            "20260525T200000Z_identity_resolution_apply",
            "{}",
            now,
            now,
        ),
    )
