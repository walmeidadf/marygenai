# Product Value

## Purpose

MaryGenAI democratizes access to scientific literature about cannabinoid
medicine by making studies easier to discover, filter, inspect, and verify.

The intended user is a physician, researcher, or evidence professional using an
AI assistant or research tool. A future read-only MCP server should let that tool
ask MaryGenAI for studies matching dimensions such as:

- medical condition;
- pathology or disease family;
- anatomical entity or organ system;
- cannabinoid or exposure;
- study type;
- evidence context;
- population or model;
- outcome domain;
- publication date;
- study geography and sample context when available;
- source availability;
- classification confidence.

MaryGenAI does not replace reading the study. It reduces the cost of finding the
right studies and preserves a path from each inferred label to supporting source
text and publication identity.

## Value Proposition

MaryGenAI provides a source-intelligence layer between raw scientific publishing
and downstream research assistants:

1. Discover candidate scientific documents continuously.
2. Resolve stable identity and remove duplicates.
3. Acquire or locate usable source text through lawful, auditable routes.
4. Add structured candidate classifications for retrieval.
5. Preserve evidence, uncertainty, model versions, and provenance.
6. Expose records through a read-only retrieval interface.

The product is useful before every classification is perfect. A declared,
evidence-backed uncertainty can still support broad retrieval and appropriate
ranking. The original publication remains the scientific authority.

## Classification Contract

AI classification is candidate retrieval metadata. It is not reviewed clinical
truth.

Each classification should preserve:

- the document and source-text identity;
- the inferred field and value;
- evidence spans;
- field or record confidence;
- missing or uncertain fields;
- warnings;
- model, prompt, schema, and extractor versions;
- run and source provenance;
- a trust level that distinguishes AI output from human review.

Candidate `classification_confidence` values are categorical model assessments.
They must not be presented as calibrated probabilities.

The experimental evaluator computes `retrieval_confidence.v1` separately from:

- source-text quality and completeness;
- directness of evidence support;
- agreement with deterministic metadata;
- schema and grounding validation;
- declared field uncertainty.

It is currently a deterministic heuristic ranking signal, not a calibrated
probability. Future versions may add repeated-run consistency and calibration
against trusted reviewed references. Retrieval confidence describes confidence
in a retrieval label, not the clinical strength of the study or the truth of a
treatment claim.

## Interpreting Uncertainty

MaryGenAI distinguishes three kinds of uncertainty:

### Legitimate Scientific Uncertainty

The source may be mixed, inconclusive, heterogeneous, or open to more than one
reasonable interpretation. Preserve this uncertainty.

### Source Insufficiency

An abstract, partial text, or poor extraction may not support a specific field.
Lower confidence, retain the document for broader retrieval when appropriate,
and record what evidence is missing.

### Correctable Pipeline Error

An invalid enum, avoidable prompt ambiguity, incorrect source routing, broken
parser, or systematic model behavior is an engineering defect. It should be
fixed and re-evaluated rather than normalized as acceptable uncertainty.

## Quality Metrics

Evaluation should use three separate metric groups.

### Technical Validity

- provider success rate;
- valid JSON rate;
- strict schema pass rate;
- retry and error rate;
- latency;
- token use and cost;
- reproducibility and artifact completeness.

### Retrieval Utility

- source and identity coverage;
- evidence-span presence;
- filter-field coverage;
- whether relevant documents remain discoverable under uncertainty;
- provenance completeness;
- ranking usefulness for high-confidence and broad-recall queries.

### Inference Quality

- agreement with trusted reviewed references;
- unsupported or contradictory labels;
- uncertainty precision;
- confidence calibration;
- systematic error by source type, study type, or condition;
- stability across model, prompt, and pipeline versions.

A single headline accuracy number is insufficient. MaryGenAI must optimize for
useful retrieval while making uncertainty and known limitations visible.

The primary retrieval journey is patient-oriented. Study design is an important
filter and ranking signal, but it does not replace matching the patient's
condition, pathology, anatomy, population, relevant cannabinoid, and outcomes.

## Safety Boundary

MaryGenAI catalogs scientific evidence. It does not diagnose, prescribe,
recommend treatment, or convert model output into medical guidance. Downstream
tools must cite and expose the underlying studies and preserve trust levels.
