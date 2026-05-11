# Ontology Notes

The legacy files already contain a useful starting ontology. The project should preserve that value while cleaning up vocabulary boundaries and provenance.

## Initial Entity Types

- publication;
- clinical trial record;
- drug interaction document;
- medical condition;
- compound/cannabinoid;
- terpene;
- organ system;
- route of administration;
- receptor;
- ligand;
- dosing objective;
- established protocol;
- adverse event;
- human review.

## Important Modeling Notes

The legacy `Type of Study` field mixes publication type and study design. Future modeling should split these concepts:

- `publication_type`: review, systematic review, meta-analysis, clinical trial article, case report, preclinical paper;
- `study_design`: RCT, double-blind RCT, cohort, animal model, in vitro, observational, survey.

Dosing fields are sparse in the legacy data and should be treated as a specialized extraction track rather than a default field for every record.

Drug interactions should be modeled as claims with source provenance, not as static text attached only to conditions or organ systems.

## Human Review State

Review status should be field-aware. A record can have reviewed conditions but unreviewed dosing or interaction claims.

Minimum review metadata:

- field name;
- original value;
- reviewed value;
- reviewer;
- timestamp;
- notes;
- ontology version;
- extractor version.
