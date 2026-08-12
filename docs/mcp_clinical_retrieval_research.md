# MCP Clinical Retrieval Research

## Purpose

This document preserves the product research that guides MaryGenAI's first
read-only retrieval index and MCP server. It records representative clinician
questions, the intended responsibility boundary between an MCP host and
MaryGenAI, current candidate-data coverage, external reference patterns, and a
backlog for later retrieval work.

MaryGenAI returns scientific source intelligence and AI-classified candidate
evidence. It does not answer patient-specific clinical questions, provide
medical advice, or recommend treatment.

## Responsibility Boundary

The physician should be able to ask a natural-language question in an MCP host
such as ChatGPT, Claude, or another research assistant. The host is responsible
for:

1. avoiding transmission of patient-identifying information;
2. translating the question into structured retrieval dimensions;
3. choosing precise, balanced, or broad retrieval behavior;
4. calling MaryGenAI tools and combining their structured results;
5. presenting limitations and directing the physician to original sources;
6. describing results as candidate matches, bounding zero-result statements,
   opening study detail before detailed claims, and distinguishing direct from
   tangential matches.

MaryGenAI is responsible for:

1. applying explicit filters to its closed local candidate index;
2. reporting the effective query and any unsupported dimensions;
3. explaining deterministic field matches for every result;
4. preserving source identity, evidence spans, uncertainty, grounding status,
   versions, provenance, review state, and trust language;
5. never converting candidate classifications into clinical recommendations.

The MCP server does not receive a patient record and does not need an LLM. A
host should extract only the non-identifying scientific retrieval dimensions
needed for a search.

## Clinical Question Model

PICO and PICOTS are useful decomposition references:

- population or problem;
- intervention or exposure;
- comparator;
- outcome;
- time;
- setting.

The question type is also important because different evidence designs support
different needs:

- background or overview;
- therapy or benefit;
- harm or etiology;
- diagnosis;
- prognosis;
- prevention;
- prevalence;
- mechanism;
- patient experience.

The v3 candidate schema currently supports broad therapy, harm, overview, and
mechanism discovery better than diagnosis, prognosis, dose, comparator, timing,
or patient-similarity questions.

## Historical First-500 Candidate Coverage

The first demo index is based on the four completed broad/v3 Batch runs:

- `20260710T173226Z`;
- `20260710T180539Z`;
- `20260710T211154Z`;
- `20260711T153044Z`.

The 500 records include:

- 157 review or synthesis records;
- 156 human clinical records;
- 69 human observational records;
- 76 animal preclinical records;
- 35 in-vitro or cellular records;
- 274 adult-human population classifications;
- 23 pediatric-human population classifications;
- 247 efficacy, 217 safety, 155 adverse-event, and 228 mechanism outcome-domain
  classifications;
- evidence spans and source traceability for every record;
- declared uncertainty in 270 records;
- 127 evidence spans selected by evaluation for grounding review.

These counts describe a bounded demo tranche, not the cannabinoid literature as
a whole. The first 500 records may reflect corpus ordering and should not be
treated as a representative epidemiological sample.

Candidate labels contain case and naming variants such as `Cannabidiol`,
`Cannabidiol (CBD)`, and `cannabidiol`. Retrieval must use a deterministic
case-folded alias key for matching and facets while preserving every original
candidate value in study detail and provenance.

## Current Pilot Coverage And Acceptance Findings

The deployed pilot now indexes 3,437 candidate records across twenty-seven
classification runs: the 3,149-record strict corpus plus 288 qualified PubMed
candidates. It is available through local CLI and stdio, local stateless
Streamable HTTP, and a remote AWS endpoint validated with hosted ChatGPT and
Claude connectors. The source and candidate metadata remain primarily English,
so the host translates Portuguese questions before calling the deterministic
server.

The first hosted conversations established that translation works but result
presentation varies by host. ChatGPT found adolescent-epilepsy candidates but
omitted preferred access URLs, did not call study detail, and included a
tangential review without saying so. Claude used capabilities, facets, and
several hypothyroidism query variants, but initially described an empty result
more broadly than the bounded index supports. The MCP response now carries a
machine-readable presentation contract for these behaviors.

A later Alzheimer disease probe returned 77 candidates across two condition
label variants. Inspection of five recent records demonstrated useful breadth
and exposed bibliographic date, publication-type, DOI reconciliation, and
directness gaps. These are priority acceptance and enrichment cases, not
reviewed corrections.

Post-expansion regression retrieved representative PubMed candidates for
multiple sclerosis, primary insomnia, fibromyalgia, cannabis use disorder,
CDKL5 deficiency disorder, sickle cell disease, diabetic retinopathy, and
Tourette syndrome. Targeted queries for three known source-selection false
positives returned zero. One acceptance case also exposed deterministic lexical
sensitivity: `non-medical cannabis pharmacies` retrieved the intended record,
while an extra unmatched inflection such as `selling` could force zero results
because current free-text terms are combined conjunctively without stemming.

## Clinical Acceptance Questions

The retrieval contract should be evaluated against at least the following
question families. Expected status reflects v3 field coverage and must be
revalidated against the complete pilot index with physician feedback.

| Specialty | Representative question | Structured retrieval intent | Expected v1 status | Important gaps |
|---|---|---|---|---|
| Pediatric neurology | What studies evaluated CBD efficacy and adverse events in children with Dravet syndrome or refractory epilepsy? | Dravet or epilepsy, CBD, pediatric humans, clinical trials or syntheses, efficacy and safety | Supported for discovery | Dose, seizure-frequency outcome, concomitant medication, comparator |
| Neurology | Does CBD appear relevant to sleep, anxiety, or cognition in Parkinson's disease? | Parkinson's disease, CBD, adult humans, efficacy, safety, cognition | Partially supported | Specific sleep and anxiety outcomes, dose, older-adult subgroup |
| Neurology | What human evidence exists for cannabinoids in multiple sclerosis? | Multiple sclerosis, cannabinoid exposure, human clinical or observational | Supported for broad discovery | Spasticity and pain outcomes, formulation, route, comparator |
| Psychiatry | What observational evidence links adolescent cannabis exposure to psychosis risk? | Psychosis, cannabis exposure, pediatric humans, human observational, harmful direction | Partially supported | Adolescent age band, exposure frequency, duration, longitudinal design, confounding |
| Psychiatry | What evidence concerns cannabis use disorder, anxiety, depression, or cognition? | Substance-use role plus psychiatric condition and outcome domains | Supported for broad discovery | Diagnostic criteria, symptom scale, comorbidity, temporal relation |
| Pain medicine | Which human trials studied THC, CBD, or combined products for chronic or neuropathic pain? | Pain, therapeutic role, human clinical, trial designs, efficacy and safety | Partially supported | Neuropathic subtype consistency, product ratio, dose, route, opioid comorbidity, comparator |
| Oncology | What evidence concerns cannabinoids for chemotherapy-associated nausea and vomiting? | Cancer or nausea and vomiting, cannabinoid exposure, human clinical, efficacy and safety | Partially supported | Chemotherapy context, comparator antiemetic, regimen, dose |
| Endocrinology | What evidence links the endocannabinoid system to obesity, type 2 diabetes, weight, or insulin resistance? | Obesity and diabetes, endocannabinoid-system mechanism, biomarker or mechanism outcomes | Partially supported | Specific metabolic outcomes, simultaneous-condition semantics, sample details |
| General medicine | What recent reviews explain the mechanism before I inspect intervention trials? | Review or meta-analysis, mechanism, optional condition and exposure | Supported | Review quality and evidence-certainty assessment |
| Safety | Which human studies report adverse effects associated with cannabis or synthetic cannabinoids? | Human evidence, nonmedical exposure or pharmaceutical role, safety and adverse events | Supported for broad discovery | Event entities, severity, dose, exposure duration, causal adjustment |

Acceptance testing should label each question `supported`,
`partially_supported`, or `unsupported` and verify that the response reports the
correct limitations. Returning no results is valid when the effective query and
coverage gap are explicit.

## V1 Retrieval Contract Implications

### Required tools

`search_studies` should accept optional text and structured filters for
conditions, cannabinoids or exposures, study design, evidence context,
population, intervention or exposure role, outcome domain, direction,
classification confidence, review state, publication year, and uncertainty.

Multi-value filters require explicit `any` or `all` semantics. The contract
should eventually support required, preferred, and excluded dimensions. The
first implementation may expose strict filters plus a `query` text field, but it
must never silently relax a filter.

The response must include:

- requested and applied filters;
- unsupported or unavailable dimensions;
- deterministic match reasons for each result;
- compact source identity and candidate metadata;
- uncertainty and review state;
- retrieval-confidence semantics when the heuristic is available;
- a detail URI and opaque pagination cursor.

`get_study` should return the complete candidate record, bibliographic identity,
source path and hash, evidence spans, grounding-review status, warnings,
uncertainty, technical repairs, model, prompt, schema and extractor versions,
provenance, review state, and trust boundary.

`get_facets` should return counts over the filtered result set before pagination.

`get_search_capabilities`, or an equivalent MCP resource, should describe
available fields, enums, aliases, unsupported v3 dimensions, runs, index
coverage, score semantics, and safety boundaries so a host can construct valid
queries without embedding repository-specific assumptions.

### Deferred tools

- `find_related_studies` using local similarity or an external citation graph;
- `get_citations_and_references`;
- deterministic terminology resolution with MeSH or a versioned ontology;
- study comparison;
- full-text retrieval;
- explicit review-quality or evidence-certainty assessment.

These are useful additions but are not prerequisites for proving the first
closed-index retrieval experience.

## External Reference Findings

### PubMed MCP servers

The `cyanheads/pubmed-mcp-server` project provides a useful production-oriented
reference. Its tools cover PubMed and Europe PMC search, metadata and lawful
full-text retrieval, related papers, citations, references, MeSH lookup,
citation formatting, and identifier conversion. Particularly useful patterns
are:

- echoing the effective query;
- structured per-item partial failures;
- typed unavailable reasons;
- source and license provenance;
- separating search, metadata detail, and full-text operations.

The smaller `andybrandt/mcp-simple-pubmed` project demonstrates PICO and
systematic-review prompts. MaryGenAI should keep PICO translation in the host
rather than adding an MCP prompt or server-side LLM to v1.

### Scholarly graph services

Semantic Scholar separates paper search, paper detail, authors, citations,
references, and recommendations from positive and negative seed papers. This
supports a future `find_related_studies` design but does not replace
MaryGenAI-specific clinical candidate metadata and provenance.

Europe PMC exposes publications, preprints, full text, references, citations,
citation networks, and text-mined entities. These are future enrichment inputs,
not a reason to add network calls to the closed local MCP v1.

NCBI E-utilities separate search, fetch, link, spelling, and other operations.
PubMed Clinical Queries use distinct retrieval filters for therapy, diagnosis,
etiology, prognosis, and clinical prediction guides. Question type should
therefore remain explicit in the backlog even where the v3 data cannot yet use
it as a reliable hard filter.

### MCP protocol patterns

MCP tools should provide strict input and output schemas and structured content.
All MaryGenAI tools must be annotated read-only and non-destructive. The runtime
must enforce the boundary by opening only the generated retrieval index in
read-only mode; annotations are descriptive hints rather than enforcement.

## Backlog

The immediate priority is a small physician-authored acceptance benchmark. It
should capture source-opening behavior and false exclusions in addition to
top-result usefulness. Retrieval, discovery, and enrichment work should then be
ordered by observed physician value.

### Retrieval contract

- add explicit publication-date sort and typed date semantics;
- add required, preferred, and excluded filter groups;
- add `any` and `all` semantics within multi-value filter families;
- return requested, applied, unsupported, and relaxed query dimensions;
- add deterministic match and mismatch explanations;
- define broad, balanced, and precise search policies;
- support question type as a ranking and evidence-design signal;
- preserve empty-result diagnostics and facet counts;
- expose a deterministic directness signal or sufficient match evidence for the
  host to separate direct from tangential candidates.

### Candidate schema and enrichment

- preserve bibliographic publication type separately from candidate study
  design;
- distinguish online-first, issue, print, and indexing dates;
- surface external identifier disagreements and URL-health provenance;
- normalize condition and cannabinoid aliases with versioned mappings;
- add symptoms and indications separately from diagnoses;
- add outcome entities separately from broad outcome domains;
- add comparator, formulation, route, dose, duration, and treatment context;
- add age groups, sex or gender, species, sample size and scope;
- add study period, country, setting, randomization, and blinding;
- preserve adverse-event entities, severity, and attribution;
- connect candidate fields to explicit evidence spans at field level;
- validate grounding and expose field-level grounding state.

### Discovery and evidence navigation

- related-study retrieval;
- citations and references;
- MeSH and ontology-assisted concept expansion;
- systematic-review and trial-family linking;
- lawful source and full-text availability;
- bibliographic citation export;
- evidence-certainty and study-quality tracks that remain distinct from
  classification and retrieval confidence.

### Product evaluation

- expand the clinical acceptance suite with physician-authored questions;
- record specialty, question type, expected dimensions, and acceptable
  broadening;
- evaluate recall and false exclusion, not only top-result precision;
- test whether match explanations help physicians decide what to open;
- measure unsupported-question handling;
- validate that no response is mistaken for reviewed knowledge or medical
  advice;
- compare needs across specialists, generalists, researchers, and reviewers.

## References

- AHRQ, *Identifying, Selecting and Refining Topics for Comparative
  Effectiveness Systematic Reviews*:
  <https://effectivehealthcare.ahrq.gov/products/methods-guidance-topics/methods>
- NCBI, *Evidence-Based Medicine*:
  <https://www.ncbi.nlm.nih.gov/books/NBK470182/>
- NLM, *MeSH Search Techniques for Special Queries*:
  <https://www.nlm.nih.gov/oet/ed/pubmed/mesh/mod04/03-100.html>
- NCBI, *APIs*:
  <https://www.ncbi.nlm.nih.gov/home/develop/api/>
- Europe PMC RESTful API:
  <https://europepmc.org/RestfulWebService>
- Semantic Scholar Academic Graph API tutorial:
  <https://www.semanticscholar.org/product/api/tutorial>
- *Translating Clinical Questions by Physicians Into Searchable Queries*:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC7199131/>
- *A Taxonomy of Generic Clinical Questions*:
  <https://pmc.ncbi.nlm.nih.gov/articles/PMC27459/>
- `cyanheads/pubmed-mcp-server`:
  <https://github.com/cyanheads/pubmed-mcp-server>
- `andybrandt/mcp-simple-pubmed`:
  <https://github.com/andybrandt/mcp-simple-pubmed>
- `JackKuo666/semanticscholar-MCP-Server`:
  <https://github.com/JackKuo666/semanticscholar-MCP-Server>
- MCP tool specification:
  <https://modelcontextprotocol.io/specification/2025-06-18/server/tools>
