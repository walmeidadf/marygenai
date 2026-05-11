# Architecture Approach

The project starts as a data-source and ontology lab. Architecture should emerge from the evidence gathered in POCs.

## Working Layers

### Raw Layer

Immutable source outputs, stored under `data/raw/` during local experiments.

Examples:

- PubMed XML or JSON;
- Europe PMC API responses;
- ClinicalTrials.gov JSON;
- Unpaywall metadata;
- drug interaction HTML or structured payloads;
- small PDF samples.

### Normalized Layer

Canonical records extracted from raw payloads, stored under `data/normalized/` during POCs.

Candidate entities:

- `source_record`;
- `research_document`;
- `publication`;
- `clinical_trial_record`;
- `drug_interaction_document`;
- `pdf_document`;
- `extraction_run`;
- `human_review`.

### Ontology Layer

Versioned vocabularies and mappings stored under `ontology/`.

This should begin as simple structured files, such as YAML or JSON. RDF/OWL or graph databases may be considered later if the relation model justifies them.

### Application Layer

Deferred until after source POCs. Candidate storage approaches include:

- files plus DuckDB;
- SQLite;
- PostgreSQL;
- document databases;
- graph databases;
- hybrid search/indexing.

## Design Principles

- Keep source payloads auditable.
- Separate document identity from source identity.
- Separate extraction from review.
- Treat dosing and drug interactions as specialized extraction domains.
- Prefer field-level provenance over a single record-level confidence score.
