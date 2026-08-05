from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from marygenai.classification_corpus.pubmed_canary import prepare_pubmed_canary
from marygenai.storage import LocalStorage


def source_html(*, title: str, pmid: str, doi: str) -> str:
    scientific_text = (
        "Abstract Introduction Methods Results Discussion Conclusion "
        "cannabis cannabidiol cannabinoid clinical participants outcomes. " * 90
    )
    return f"""<!doctype html>
    <html><head>
      <meta name="citation_title" content="{title}">
      <meta name="citation_pmid" content="{pmid}">
      <meta name="citation_doi" content="{doi}">
    </head><body><article>{scientific_text}</article></body></html>
    """


def create_canary_database(data_dir: Path) -> Path:
    database_path = data_dir / "db/marygenai.sqlite"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE document (
                document_id TEXT PRIMARY KEY,
                primary_title TEXT,
                publication_year INTEGER,
                canonical_url TEXT,
                pmid TEXT,
                pmcid TEXT,
                doi TEXT,
                review_state TEXT NOT NULL
            );
            CREATE TABLE publication_candidate_discovery (
                document_id TEXT PRIMARY KEY,
                identity_status TEXT NOT NULL,
                cannabinoid_focus TEXT NOT NULL,
                study_design TEXT,
                study_design_rank INTEGER NOT NULL,
                priority_score REAL NOT NULL
            );
            CREATE TABLE access_enrichment_artifact (
                artifact_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                source TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                access_class TEXT NOT NULL,
                url TEXT,
                payload_path TEXT,
                payload_sha256 TEXT,
                payload_size_bytes INTEGER,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE review_item (status TEXT NOT NULL);
            CREATE TABLE review_decision (review_decision_id TEXT PRIMARY KEY);
            """
        )
        candidates = [
            (
                "publication:pubmed:high",
                "Cannabidiol high priority trial",
                2024,
                "high",
                "10.1/high",
                "direct_title_or_indexed",
                100.0,
            ),
            (
                "publication:pubmed:low",
                "Cannabis lower priority cohort",
                2025,
                "low",
                "10.1/low",
                "direct_title_or_indexed",
                50.0,
            ),
            (
                "publication:pubmed:mismatch",
                "Cannabinoid identity mismatch",
                2024,
                "mismatch",
                "10.1/mismatch",
                "direct_title_or_indexed",
                90.0,
            ),
            (
                "publication:pubmed:no-source",
                "Cannabis without local source",
                2024,
                "no-source",
                "10.1/no-source",
                "direct_title_or_indexed",
                80.0,
            ),
            (
                "publication:pubmed:abstract",
                "Unrelated title",
                2024,
                "abstract",
                "10.1/abstract",
                "abstract_only",
                120.0,
            ),
        ]
        for document_id, title, year, pmid, doi, focus, priority in candidates:
            connection.execute(
                "INSERT INTO document VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_id,
                    title,
                    year,
                    f"https://pubmed.ncbi.nlm.nih.gov/{pmid}",
                    pmid,
                    None,
                    doi,
                    "needs_review",
                ),
            )
            connection.execute(
                "INSERT INTO publication_candidate_discovery VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, "new_candidate", focus, "clinical_trial", 60, priority),
            )
        connection.execute("INSERT INTO review_item VALUES ('open')")
        connection.execute("INSERT INTO review_decision VALUES ('decision:sentinel')")

        artifact_specs = [
            (
                "artifact:high:html",
                "publication:pubmed:high",
                "pmc_html",
                "high-html.html",
                source_html(
                    title="Cannabidiol high priority trial",
                    pmid="high",
                    doi="10.1/high",
                ),
            ),
            (
                "artifact:high:duplicate",
                "publication:pubmed:high",
                "pmc_nxml",
                "high-declared-xml.html",
                source_html(
                    title="Cannabidiol high priority trial",
                    pmid="high",
                    doi="10.1/high",
                ),
            ),
            (
                "artifact:low",
                "publication:pubmed:low",
                "pmc_html",
                "low.html",
                source_html(
                    title="Cannabis lower priority cohort",
                    pmid="low",
                    doi="10.1/low",
                ),
            ),
            (
                "artifact:mismatch",
                "publication:pubmed:mismatch",
                "pmc_html",
                "mismatch.html",
                source_html(
                    title="Different cited article",
                    pmid="other",
                    doi="10.1/other",
                ),
            ),
            (
                "artifact:abstract",
                "publication:pubmed:abstract",
                "pmc_html",
                "abstract.html",
                source_html(
                    title="Unrelated title",
                    pmid="abstract",
                    doi="10.1/abstract",
                ),
            ),
        ]
        artifact_dir = data_dir / "raw/pmc/html"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for artifact_id, document_id, artifact_type, filename, content in artifact_specs:
            path = artifact_dir / filename
            path.write_text(content, encoding="utf-8")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            connection.execute(
                "INSERT INTO access_enrichment_artifact VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    document_id,
                    "pmc",
                    artifact_type,
                    "open_access_html" if artifact_type == "pmc_html" else "open_access_xml",
                    "https://example.org/source",
                    str(path),
                    digest,
                    path.stat().st_size,
                    "source-run",
                    "2026-08-05T00:00:00+00:00",
                ),
            )
    return database_path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_pubmed_canary_is_deduplicated_stable_and_preserves_protected_state(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    database_path = create_canary_database(data_dir)
    database_before = database_path.read_bytes()

    first = prepare_pubmed_canary(
        storage=LocalStorage(data_dir),
        database_path=database_path,
        target_size=1,
        corpus_version="test_pubmed_canary.v1",
        run_id="run-one",
        prepare_prompt_packets=False,
    )
    manifest_path = Path(first["manifest_path"])
    manifest_before = manifest_path.read_bytes()
    second = prepare_pubmed_canary(
        storage=LocalStorage(data_dir),
        database_path=database_path,
        target_size=1,
        corpus_version="test_pubmed_canary.v1",
        run_id="run-two",
        prepare_prompt_packets=False,
    )

    manifest = read_jsonl(manifest_path)
    corpus = read_jsonl(Path(first["corpus_path"]))
    summary = json.loads(Path(first["summary_path"]).read_text(encoding="utf-8"))
    exclusions = read_jsonl(
        data_dir / "normalized/pubmed_canary/run-one_source_quality_exclusions.jsonl"
    )

    assert first["selected_document_ids"] == ["publication:pubmed:high"]
    assert second["selected_document_ids"] == first["selected_document_ids"]
    assert manifest_path.read_bytes() == manifest_before
    assert len(manifest) == 1
    assert manifest[0]["origin"]["artifact_id"] == "artifact:high:html"
    assert manifest[0]["origin"]["raw_artifact_sha256"]
    assert manifest[0]["origin"]["extracted_text_sha256"]
    assert manifest[0]["classification_output_trust_level"] == "ai_classified_candidate"
    assert manifest[0]["review_state"] == "needs_review"
    assert corpus[0]["classification_dataset_split"] == "strict_classification_ready"
    assert corpus[0]["provenance"]["requires_human_review"] is True
    assert summary["counts"]["duplicate_open_artifacts_discarded"] == 1
    assert summary["protected_state_unchanged"] is True
    assert database_path.read_bytes() == database_before

    exclusions_by_id = {row["document_id"]: row for row in exclusions}
    assert "artifact_identity_mismatch" in exclusions_by_id[
        "publication:pubmed:mismatch"
    ]["exclusion_reasons"]
    assert "no_local_open_xml_html_artifact" in exclusions_by_id[
        "publication:pubmed:no-source"
    ]["exclusion_reasons"]
    assert "not_direct_title_or_indexed_cannabinoid_focus" in exclusions_by_id[
        "publication:pubmed:abstract"
    ]["exclusion_reasons"]
