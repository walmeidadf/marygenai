import json

from pocs.pdf_samples.extract_evidence import (
    EXTRACTOR_VERSION,
    ExtractionProvider,
    build_record,
    build_review_export_rows,
    heuristic_candidates,
    normalize_candidates,
    parse_candidate_extraction,
    retry_wait_seconds,
    select_prompt_sections,
    text_to_sections,
)
from pocs.pdf_samples.sample_full_text import (
    DEFAULT_MANIFEST_PATH,
    extract_field_from_text,
    html_to_sections,
    read_manifest,
)


def test_manifest_contains_fixed_small_sample() -> None:
    items = read_manifest(DEFAULT_MANIFEST_PATH)

    assert len(items) == 10
    assert {item.sample_category for item in items} == {
        "direct_pmc_html",
        "europe_pmc_html_pdf",
        "unpaywall_pdf",
    }
    assert all(item.preferred_url for item in items)


def test_html_to_sections_keeps_relevant_method_text() -> None:
    content = b"""
    <html>
      <body>
        <h2>Methods</h2>
        <p>Participants received oral cannabidiol at 20 mg/kg/day for 12 weeks.</p>
        <h2>References</h2>
        <p>Short irrelevant citation.</p>
      </body>
    </html>
    """

    sections = html_to_sections(content)

    assert sections == [
        ("Methods", "Participants received oral cannabidiol at 20 mg/kg/day for 12 weeks.")
    ]


def test_extract_field_from_text_records_evidence_and_review_state() -> None:
    sections = [
        ("Methods", "Participants received oral cannabidiol at 20 mg/kg/day for 12 weeks.")
    ]

    extraction = extract_field_from_text(
        field_name="dosage",
        sections=sections,
        source_url="https://example.test/article",
    )

    assert extraction.confidence == "medium"
    assert extraction.review_state == "needs_review"
    assert "20 mg/kg/day" in json.dumps(extraction.value)


def test_poc6b_text_sections_and_heuristic_candidates_keep_review_flag() -> None:
    item = read_manifest(DEFAULT_MANIFEST_PATH)[0]
    text = (
        "[Methods]\n"
        "Participants received oral cannabidiol at 20 mg/kg/day for 12 weeks.\n\n"
        "[Results]\n"
        "Somnolence was reported as an adverse event."
    )

    sections = text_to_sections(text)
    extraction = heuristic_candidates(item, sections)
    normalized = normalize_candidates(
        extraction=extraction,
        provider=ExtractionProvider.HEURISTIC.value,
        model=None,
    )

    assert sections[0] == (
        "Methods",
        "Participants received oral cannabidiol at 20 mg/kg/day for 12 weeks.",
    )
    assert all(field.needs_review is True for field in normalized)
    assert all(field.review_state == "needs_review" for field in normalized)
    assert any(field.field_name == "dosage" for field in normalized)


def test_poc6b_llm_candidate_parser_filters_to_target_fields() -> None:
    item = read_manifest(DEFAULT_MANIFEST_PATH)[0]
    raw_text = json.dumps(
        {
            "candidates": [
                {
                    "field_name": "dosage",
                    "candidate_value": "20 mg/kg/day",
                    "evidence_text": "Participants received oral cannabidiol at 20 mg/kg/day.",
                    "source_section": "Methods",
                    "confidence": "high",
                    "needs_review": True,
                    "notes": ["candidate only"],
                },
                {
                    "field_name": "not_a_target",
                    "candidate_value": "ignore",
                    "evidence_text": "ignore",
                    "confidence": "high",
                    "needs_review": True,
                    "notes": [],
                },
            ]
        }
    )

    extraction = parse_candidate_extraction(
        item=item,
        provider=ExtractionProvider.GROQ,
        model="test-model",
        raw_text=raw_text,
    )

    assert [candidate.field_name for candidate in extraction.candidates] == ["dosage"]
    assert extraction.candidates[0].needs_review is True


def test_poc6c_section_selection_prioritizes_field_specific_sections() -> None:
    sections = [
        ("Discussion", "Cannabidiol and adverse events are discussed broadly."),
        ("Methods", "Participants received oral cannabidiol at 20 mg/kg/day."),
        ("References", "Dose and trial citations."),
    ]

    selected = select_prompt_sections(sections, ["dosage"], max_chars=500)

    assert selected.startswith("[Methods]")
    assert "[References]" not in selected
    assert "Target fields likely here: dosage." in selected


def test_poc6c_review_export_preserves_human_review_placeholders() -> None:
    item = read_manifest(DEFAULT_MANIFEST_PATH)[0]
    extraction = heuristic_candidates(
        item,
        [("Methods", "Participants received oral cannabidiol at 20 mg/kg/day.")],
    )
    record = build_record(
        item=item,
        text_path=DEFAULT_MANIFEST_PATH,
        text="sample text",
        provider_results=[],
        heuristic_extraction=extraction,
        run_id="test-run",
        created_at="2026-05-14T00:00:00+00:00",
    )

    rows = build_review_export_rows(
        records=[record],
        ontology_version="test-ontology",
        extractor_version=EXTRACTOR_VERSION,
        created_at="2026-05-14T00:00:00+00:00",
    )

    dosage_row = next(row for row in rows if row.field_name == "dosage")
    assert dosage_row.needs_review is True
    assert dosage_row.review_state == "needs_review"
    assert dosage_row.reviewer_identity is None
    assert dosage_row.original_value == dosage_row.candidate_value
    assert dosage_row.ontology_version == "test-ontology"


def test_poc6c_retry_wait_uses_retry_after_before_reset_headers() -> None:
    wait_seconds, reason = retry_wait_seconds(
        {
            "retry-after": "3",
            "x-ratelimit-reset-tokens": "12s",
        },
        attempt=1,
        retry_base_seconds=2,
    )

    assert wait_seconds == 3
    assert reason == "retry-after"
