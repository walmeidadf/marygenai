import json

from pocs.pdf_samples.extract_evidence import (
    ExtractionProvider,
    heuristic_candidates,
    normalize_candidates,
    parse_candidate_extraction,
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
