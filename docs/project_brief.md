# Project Brief

MaryGenAI aims to build a structured, continuously updated evidence base for scientific studies and related documents about cannabinoid therapy in human and veterinary contexts.

The project is inspired by CannaKeys-style metadata but is broader in scope. It will explore:

- human and veterinary evidence;
- clinical trial records;
- publication metadata;
- cannabinoid and terpene ontology;
- medical condition mappings;
- routes of administration;
- dosing and protocol extraction;
- drug interaction evidence;
- human review workflows.

The current phase is exploratory. We are intentionally avoiding a final database or crawler architecture until source quality and data modeling needs are better understood.

## Current Objective

Build a POC environment that can test several data sources in small batches and produce comparable source quality reports.

The first real milestone is not a production crawler. It is an evidence-backed answer to:

> Which sources can populate which parts of the ontology, with what reliability and technical effort?

The current publication-source plan treats PubMed as the primary publication
identity and metadata hub, then uses PMC, Europe PMC, Unpaywall, DOI, and publisher
links to classify full-text availability before any broad download or crawler
strategy. See [PubMed Source Plan](pubmed_source_plan.md).

For ongoing publication discovery, PubMed is the current primary source of new
study detection. The preferred pipeline is PubMed discovery first, then identifier
normalization, then access enrichment, then small full-text/PDF extraction samples.
Priority should favor higher-reputation evidence such as systematic reviews,
meta-analyses, randomized or controlled clinical trials, and placebo-controlled or
double-blind designs.

## Non-Goals For Now

- No user-facing medical tool.
- No clinical recommendation engine.
- No large-scale PDF ingestion pipeline.
- No final commitment to PostgreSQL, NoSQL, graph databases, or search infrastructure.
- No large crawler before source POCs have been evaluated.
