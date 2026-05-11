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

## Non-Goals For Now

- No user-facing medical tool.
- No clinical recommendation engine.
- No large-scale PDF ingestion pipeline.
- No final commitment to PostgreSQL, NoSQL, graph databases, or search infrastructure.
- No large crawler before source POCs have been evaluated.
