# Classification Data Dictionary

## Purpose

This dictionary defines candidate retrieval fields needed for physician-oriented
study discovery. It separates bibliographic facts, clinical topics, population,
intervention, study structure, findings, and provenance.

The proposed v4 fields are a design target, not yet a public schema contract.

## Extraction Methods

- `metadata`: canonical bibliographic or structured database value;
- `parser`: deterministic extraction from structured or source text;
- `ontology`: alias or entity matching against a versioned vocabulary;
- `llm`: semantic classification supported by source evidence;
- `derived`: transparent calculation from other fields.

LLM extraction is not the default when a reliable lower-cost method exists.

## Identity And Time

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `document_id` | string | Stable canonical document identity | metadata | Join and retrieval |
| `publication_year` | integer | Year the publication was issued | metadata | Date filter and recency |
| `study_start_year` | integer or null | Year study activity began | metadata, parser, then LLM | Patient-era and protocol context |
| `study_end_year` | integer or null | Year study activity ended | metadata, parser, then LLM | Study-period filtering |
| `enrollment_period` | object or null | Explicit participant enrollment dates | parser, then LLM | Clinical comparability |
| `study_countries` | list | Countries where the study was conducted | structured metadata, parser, then LLM | Geography filter |

`publication_year` is not a substitute for the study or enrollment period.

## Clinical Topic

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `medical_conditions` | entity list | Diagnoses, disorders, or clinical conditions directly studied | ontology + LLM relation validation | Primary patient-condition filter |
| `pathologies_or_disease_families` | entity list | Broader pathological processes or disease families | ontology + LLM | Ontology expansion |
| `symptoms_or_indications` | entity list | Symptoms or therapeutic indications studied | ontology + LLM | Symptom-driven retrieval |
| `anatomical_entities` | entity list | Specific organs, tissues, structures, or body regions | ontology + LLM | Anatomical filter |
| `organ_systems` | entity list | Normalized body systems | ontology + derived mapping | Broad clinical filter |
| `comorbidities` | entity list | Relevant concurrent conditions in the population | LLM with explicit evidence | Patient similarity |

Conditions, symptoms, adverse events, and organ systems must not be collapsed
into one undifferentiated label list.

## Cannabinoid And Intervention

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `cannabinoids_or_exposures` | entity list | Cannabinoids, cannabis products, endocannabinoids, or related exposures | ontology + LLM relation validation | Primary substance filter |
| `cannabinoid_role` | enum per entity | Intervention, exposure, biomarker, mechanism, comparator, or background mention | LLM | Relevance and ranking |
| `intervention_or_exposure_role` | enum | Document-level principal role | LLM | Broad filter |
| `product_or_formulation` | list | Named product, extract, isolate, ratio, or formulation | parser + LLM | Intervention matching |
| `route_of_administration` | list | Oral, inhaled, topical, or other route | structured metadata, parser, then LLM | Clinical applicability |
| `comparator` | list | Placebo, standard care, active treatment, or no comparator | parser + LLM | Study interpretation |

Dosage, titration, and treatment duration remain specialized extraction tracks.
They should be added only with explicit evidence and unit-aware schemas.

## Population And Scale

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `population_category` | enum | Adult humans, pediatric humans, animals, cells, mixed, or uncertain | metadata + LLM | Core filter |
| `population_description` | string | Short source-supported population description | LLM | Inspection |
| `age_groups` | list | Pediatric, adolescent, adult, older adult, or explicit ranges | parser + LLM | Patient similarity |
| `sex_or_gender` | list | Reported study population categories | parser + LLM | Patient similarity |
| `species` | entity list | Animal species or experimental organism | parser + ontology | Preclinical filtering |
| `sample_size` | integer or null | Primary analyzed or enrolled sample for this document | structured metadata, parser, then LLM | Evidence context and ranking |
| `sample_size_scope` | enum | Enrolled, analyzed, cases, controls, studies, animals, cells, or other | parser + LLM | Prevent misleading comparisons |

Sample size must not be placed in `evidence_context`. Reviews may report numbers
of included studies and participants; these require explicit scope.

## Study Structure

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `publication_type` | enum | Article form such as review, trial report, case report, or protocol | metadata + parser | Document filtering |
| `study_design_category` | enum | Principal legacy-compatible retrieval category | metadata + LLM | Broad study-type filter |
| `study_design_subtype` | enum | RCT, survey, cohort, case report, systematic review, and similar detail | metadata + LLM | Precise study-type filter |
| `evidence_context` | enum | Human clinical, human observational, animal, laboratory, review, or mixed | derived + LLM | Evidence setting |
| `randomization` | boolean or uncertain | Whether allocation was randomized | metadata + parser + LLM | Trial refinement |
| `blinding` | enum | Open label, single, double, masked, or uncertain | metadata + parser + LLM | Trial refinement |

`evidence_context` describes the scientific setting. It does not contain country,
sample size, or publication year.

## Findings

| Field | Type | Meaning | Preferred method | MCP use |
|---|---|---|---|---|
| `outcome_domains` | enum list | Efficacy, safety, adverse events, cognition, biomarker, mechanism, and related domains | LLM | Outcome filter |
| `outcome_entities` | entity list | Specific outcomes or measurements | ontology + LLM | Precise retrieval |
| `overall_direction` | enum | Beneficial, harmful, mixed, null, not applicable, or uncertain | LLM | Candidate ranking and inspection |
| `adverse_events` | entity list | Explicitly reported adverse events | parser + ontology + LLM | Safety retrieval |
| `key_findings` | claim list | Short evidence-linked candidate findings | LLM | Inspection, not clinical truth |

Direction must be tied to a stated question or association. It is not a general
sentiment label.

## Evidence, Confidence, And Review

Each field-level value should support:

| Attribute | Meaning |
|---|---|
| `source_value` | Literal source or metadata value |
| `normalized_label` | Project-normalized value |
| `ontology_entity_id` | Stable ontology identifier |
| `evidence_spans` | Verbatim supporting text |
| `extraction_method` | Metadata, parser, ontology, LLM, or derived |
| `extractor_version` | Version of the producing component |
| `field_confidence` | Categorical support assessment |
| `uncertainty_reason` | Machine-readable reason for absence or ambiguity |
| `provenance` | Source, model, prompt, hash, and run identity |
| `review_state` | Candidate or human-reviewed status |

Model confidence, retrieval confidence, and clinical evidence strength are
separate concepts.

## Initial Human-Review Pilot Scope

The proposed v4 dictionary is broader than the first practical curation pilot.
The pilot should validate the fields that most directly affect retrieval and
trust before asking reviewers to adjudicate every proposed field:

- direct, tangential, or unsupported relevance;
- publication identity;
- study design category and subtype;
- population category;
- cannabinoid or exposure and its role;
- medical condition;
- outcome domains;
- overall direction;
- evidence spans supporting each semantic decision;
- accept, correct, or abstain at field level.

Each task must expose the original candidate value and source evidence. The
review response must preserve reviewer and institutional provenance, rationale,
task version, schema version, ontology version, source hash, and timestamp.
Additional fields should enter the review contract only when physician
evaluation demonstrates retrieval value and the source evidence can support
consistent adjudication.

## Legacy English Reference Coverage

The maintainer-local normalized English reference contains 7,360 deduplicated
records. It is a design and validation reference, not the execution queue.

Observed reference coverage on 2026-06-22:

| Reference signal | Coverage |
|---|---:|
| Publication year | 100.0% |
| Condition/pathology page association | 96.6% |
| Study location | 99.7% |
| Cannabinoids studied | 88.4% |
| Organ-system page association | 80.6% |
| Route of administration | 43.0% |
| Study sample size | 35.1% |
| Structured adverse events | 2.4% |

Filename-derived condition and organ associations are useful bootstrap labels,
but they may reflect page membership rather than the document's principal
scientific question. They require field-scoped source validation.
