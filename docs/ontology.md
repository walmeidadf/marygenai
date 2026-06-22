# Ontology Notes

The legacy files already contain a useful starting ontology. The project should preserve that value while cleaning up vocabulary boundaries and provenance.

Those legacy files are private maintainer inputs and are not distributed in the
public repository. Public users should treat reviewed ontology snapshots produced
by MaryGenAI as the future baseline. Until then, ontology code and tests document
the import shape, while the maintainer's private local workspace supplies the
bootstrap data.

The ontology should be treated as normalized project data, not only as static
reference documentation. Legacy CSVs for cannabinoids, medical conditions, organ
systems, terpenes, and glossary terms should be imported as ontology entities with
source provenance, review state, aliases, language, and links back to studies.
The ontology layer should also leave room for later enrichment from sources such
as Wikipedia, Wikidata, PubMed, MeSH, ICD, DrugBank, or other vetted references.

## Initial Entity Types

- publication;
- clinical trial record;
- drug interaction document;
- medical condition;
- pathology;
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

## Normalized Ontology Domains

The MVP should normalize at least:

- cannabinoids and cannabinoid groups;
- terpenes;
- medical conditions;
- pathologies or disease families;
- organ systems;
- glossary terms;
- aliases and multilingual labels;
- external identifiers and vocabulary mappings;
- links from ontology entities to studies, source records, and reviewed fields.

The retrieval contract should keep medical conditions, pathology or disease
families, symptoms or indications, anatomical entities, and organ systems as
related but distinct domains. A page association or broad organ-system mapping
must not be represented as if it were the principal diagnosed condition.

Ontology enrichment should preserve field-level provenance and review state in
the same way as publication extraction. A Wikipedia or PubMed-derived condition
description, for example, is an enrichment candidate until reviewed.

## Important Modeling Notes

The principal candidate-classification field currently preserves the normalized
English legacy-compatible domain because it is a useful and validated retrieval
filter. Future modeling should add separate publication-type and design-subtype
fields instead of silently changing that principal domain:

- `publication_type`: review, systematic review, meta-analysis, clinical trial article, case report, preclinical paper;
- `study_design`: RCT, double-blind RCT, cohort, animal model, in vitro, observational, survey.

Ontology confidence is confidence in a label or mapping. It is not clinical
evidence strength, a treatment recommendation, or human review status.

Dosing fields are sparse in the private bootstrap data and should be treated as a
specialized extraction track rather than a default field for every record.

Drug interactions should be modeled as claims with source provenance, not as static text attached only to conditions or organ systems.

`cannabinoid_focus` is an MVP-level prioritization field, not just display
metadata. It should distinguish at least:

- `direct_title_or_indexed`: cannabinoid signal in title, MeSH terms, chemicals,
  or keywords;
- `abstract_only`: cannabinoid signal only in the abstract;
- `no_cannabinoid_signal`: no reliable cannabinoid signal.

The first category should dominate review prioritization. The third category
should not be promoted automatically by citation metrics, recency, or study
design.

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
