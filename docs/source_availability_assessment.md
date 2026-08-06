# Source Availability Assessment

## Decision

Source growth proceeds on two distinct tracks:

1. classify newly eligible PubMed candidates through bounded, reproducible
   refreshes;
2. recover legacy coverage through separate identity and source-acquisition
   campaigns with measured yield.

Human-curation availability does not block candidate-data work. Candidate
records remain explicitly unreviewed until a separate review workflow promotes
them.

## Classification-Ready Definition

A classification-ready document has enough authentic source text to support
coarse retrieval labels such as study design, condition, cannabinoid role,
population, evidence context, and outcome domain.

Classification-ready does not require perfect table extraction, figure
interpretation, dosage reconstruction, or protocol reconstruction. Lowering a
quality threshold solely to increase record count is not an acceptable recovery
strategy.

## Legacy Funnel

The current maintainer-local legacy state contains:

- 7,347 source rows representing 7,344 unique documents;
- 6,491 records with at least one strong PMID, PMCID, or DOI identifier;
- 6,490 deduplicated records in the classification corpus;
- 3,374 source-ready records;
- 3,149 strict classification-ready records;
- 225 broader source-ready records;
- 3,116 not-source-ready corpus records.

The identity queue contains 838 open items, 15 in review, and 353 resolved
items. Resolving weak identity can add documents to the canonical corpus, but it
does not repair inadequate source text for documents that already have strong
identity.

## Legacy Source-Failure Families

The largest local not-source-ready families are:

| Route | Failure family | Records |
|---|---|---:|
| augmented links | retrieved but insufficient text | 1,170 |
| augmented links | access blocked | 968 |
| PMC OAI | HTTP non-success | 356 |
| Unpaywall PDF | access blocked | 248 |
| no selected strategy | no routed source | 191 |

Smaller families include request errors, missing resources, low-quality PDF text
layers, and artifacts that need specialized OCR assessment.

Recovery order:

1. official PMC retry canary;
2. short-text audit before any threshold or parser change;
3. alternate lawful route experiment for high-value records;
4. specialized OCR or PDF campaign;
5. publisher-blocked routes only when retrieval evaluation demonstrates a
   specific coverage need.

Each route begins with a bounded sample and a documented stop/continue decision
based on source-ready yield, provenance quality, operational cost, and clinical
coverage value.

## PubMed 2024+ Funnel

The current local discovery state contains:

- 1,361 unique candidates;
- 1,359 considered new against the local legacy baseline;
- 1,037 with direct title or indexed cannabinoid focus;
- 773 with locally persisted open XML/HTML artifacts;
- 590 combining direct cannabinoid focus and open XML/HTML.

The first provider-free rollup verified the access signal against local files:

- 1,104 open XML/HTML artifact rows cover the 773 candidates;
- 773 rows declared as XML contain HTML;
- 12 rows verify the candidate title plus PMID or DOI;
- eight unique direct-focus, 2024+ documents pass the full source-quality gate;
- the frozen v1 canary records a 92-document shortfall against its target of
  100.

The shortfall is a source-identity defect, not acceptable scientific
uncertainty. The gate remains strict. Future discovery no longer allows cited
reference identifiers to overwrite the primary article identifiers, but the
existing local candidate database was not mutated or silently repaired.

A read-only PMID-based repair campaign selected 150 of the direct-focus,
2024+ artifact-identity failures. PubMed resolved 150/150 records with no fetch
errors. All 150 current titles and DOIs agreed with the official records, while
all 150 persisted PMCIDs differed. Correct official PMCIDs are available for
149 records; the remaining record has no PMCID and is routed to Europe PMC or
Unpaywall. The corrected identities remain an ignored candidate overlay and
were not applied to SQLite or review state.

The first refresh classified the eight valid v1 documents after explicit
provider authorization. The technical and grounding gate passed, but inference
quality has no legacy comparison for these new records. The next refresh
reenriches a bounded subset of the 149 corrected PMC routes, adds a medical-scope
gate, and freezes v2 only after the same identity and content validation passes.

## Validated Source Lessons

- PMC structured text is the preferred official full-text route.
- Digital PDF extraction can recover useful additional text.
- NCBI ELink, Europe PMC, OpenAlex, and Unpaywall are useful identity or access
  augmentation, not automatic proof of usable content.
- Metadata-only payloads support discovery but not source-ready classification.
- HTTP success is not content validation.
- Challenge pages, JavaScript shells, malformed XML, missing payloads, and poor
  text layers must remain distinct failure families.
- Repeated retries against the same blocked route are not a recovery strategy.

## Operational Routing

Keep these states distinct:

- `usable_for_llm_classification`;
- `needs_reenrichment`;
- `source_triage_needed`;
- `identity_or_focus_review`;
- `not_enriched`.

Identity suggestions, source artifacts, parser outputs, and classification
results remain candidate evidence with source and run provenance. Ambiguous
identity decisions and scientific interpretation remain human tasks.

## Product Interpretation

Source readiness affects classification confidence and retrieval rank, but it
is not evidence quality or clinical applicability. A partial source may support
broad metadata retrieval while remaining insufficient for precise labels.

The product goal is not maximum historical document count. It is a current,
inspectable candidate base whose gaps, uncertainty, acquisition routes, and
review state remain visible.

## Safety Boundary

Source availability does not imply clinical validity, treatment applicability,
or recommendation. No source acquisition or candidate classification promotes a
record to reviewed knowledge.
