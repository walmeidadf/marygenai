# 2026-07-11 Batch And MCP Handoff

## Session Outcome

MaryGenAI now has a first operational candidate-classified base suitable for a
read-only MCP demonstration and medical-review recruitment.

The first 500 `strict_classification_ready` documents were classified with
OpenAI Batch using the broad `candidate_study_classification.v3` contract and
`gpt-5.4-mini`. The tranche was executed as four sequential sub-batches because
the provider-side `gpt-5.4-mini` organization limit observed during execution
was 2,000,000 enqueued tokens.

The direct 500-request Batch attempt failed during provider validation with
`token_limit_exceeded` and zero usage. The supported operating pattern is now
sequential chunks sized by estimated enqueued tokens, normally 150 records for
the current prompt shape.

## Current Git State At Handoff

- Branch: `main`
- Remote branch: `origin/main`
- Branch policy: keep `main` as the only active local and remote branch unless
  the maintainer explicitly requests otherwise.
- Latest pushed handoff commit before this document: `014d0d0 Document
  500-record batch tranche results`

## Completed Classification Runs

The 500-document tranche consists of these completed runs:

| Run ID | Offset | Limit | Remote completed | Remote failed | Local valid records | Usage tokens |
|---|---:|---:|---:|---:|---:|---:|
| `20260710T173226Z` | 0 | 150 | 150 | 0 | 150 | 1,130,638 |
| `20260710T180539Z` | 150 | 150 | 150 | 0 | 150 | 1,133,335 |
| `20260710T211154Z` | 300 | 150 | 150 | 0 | 150 | 1,165,643 |
| `20260711T153044Z` | 450 | 50 | 50 | 0 | 50 | 400,700 |

Aggregate:

- 500 remote requests completed;
- zero remote request failures;
- 500/500 local strict-valid candidate records after deterministic
  provenance-recorded technical repairs;
- 500/500 records with evidence spans;
- 270/500 records with declared uncertainty;
- 3,251,515 input tokens;
- 578,801 output tokens;
- 3,830,316 total tokens.

Using the standing cost model of USD 0.75 per million input tokens and USD 4.50
per million output tokens, with the Batch half-price assumption:

- standard equivalent cost: about USD 5.04;
- Batch estimated cost: about USD 2.52;
- Batch cost per candidate-classified document: about USD 0.00504;
- projected 3,149-document strict corpus: about USD 15.88;
- projected remaining 2,649 strict records after the 500-document tranche: about
  USD 13.36.

## Important Local Artifacts

Completed candidate records:

- `data/normalized/classification_runs/20260710T173226Z_candidate_classification_records.jsonl`
- `data/normalized/classification_runs/20260710T180539Z_candidate_classification_records.jsonl`
- `data/normalized/classification_runs/20260710T211154Z_candidate_classification_records.jsonl`
- `data/normalized/classification_runs/20260711T153044Z_candidate_classification_records.jsonl`

Run summaries:

- `data/normalized/classification_runs/20260710T173226Z_candidate_classification_summary.json`
- `data/normalized/classification_runs/20260710T180539Z_candidate_classification_summary.json`
- `data/normalized/classification_runs/20260710T211154Z_candidate_classification_summary.json`
- `data/normalized/classification_runs/20260711T153044Z_candidate_classification_summary.json`

Evaluation reports:

- `data/normalized/classification_evaluations/20260710T180306854680Z_classification_evaluation_report.json`
- `data/normalized/classification_evaluations/20260710T195511538815Z_classification_evaluation_report.json`
- `data/normalized/classification_evaluations/20260710T212153273062Z_classification_evaluation_report.json`
- `data/normalized/classification_evaluations/20260711T161614672728Z_classification_evaluation_report.json`

The generated `data/` artifacts are ignored local candidate-evidence artifacts.
They are not reviewed knowledge and should not be committed.

## Batch Operating Rules

Use `prepare-batch`, `submit-batch`, and `watch-batch`.

Do not submit a direct 500-request Batch for the current prompt shape. Use
sequential chunks, normally:

```bash
uv run marygenai classification prepare-batch \
  --limit 150 \
  --offset <OFFSET> \
  --input-path data/normalized/classification_corpus/20260617T142419Z_classification_corpus_records.jsonl \
  --dataset-split strict_classification_ready \
  --model gpt-5.4-mini \
  --max-source-chars 12000 \
  --max-completion-tokens 3000
```

Then:

```bash
uv run marygenai classification submit-batch \
  --batch-input-path data/normalized/classification_batches/<RUN_ID>_openai_batch_input.jsonl \
  --manifest-path data/normalized/classification_batches/<RUN_ID>_openai_batch_manifest.jsonl
```

Then:

```bash
uv run marygenai classification watch-batch \
  --submission-path data/normalized/classification_batches/<RUN_ID>_openai_batch_submission.json \
  --interval-seconds 300 \
  --max-checks 288
```

Run only one sub-batch at a time unless the maintainer confirms a larger
provider-side enqueued-token limit. The local preparation command includes a
default 1,800,000 estimated enqueued-token guard.

For the next 500 records after the completed tranche, use offsets:

- `500`, limit `150`;
- `650`, limit `150`;
- `800`, limit `150`;
- `950`, limit `50`.

## Known Technical Repairs

Batch conversion applies deterministic technical repairs that are recorded in
candidate provenance under `technical_schema_repairs`. These repairs preserve
candidate evidence and uncertainty; they do not promote output to clinical
truth or reviewed knowledge.

Current repair families include:

- add missing required `missing_or_uncertain_fields` markers for empty or
  `cannot_determine` retrieval fields;
- deduplicate repeated uncertainty markers;
- map misplaced `study_design_subtype=in_vitro_or_cellular` to `other` and
  mark `study_design_subtype` uncertain;
- map unsupported `overall_direction=negative` to `cannot_determine` and mark
  `overall_direction` uncertain;
- remove unsupported `outcome_domains` values, preserve valid sibling domains,
  and mark `outcome_domains` uncertain;
- map `population_or_model.category=plants` to `cannot_determine` and mark
  `population_or_model` uncertain;
- remove invalid uncertainty markers such as `biomarker` from
  `missing_or_uncertain_fields` and mark `outcome_domains` uncertain when the
  invalid marker is an outcome-domain value;
- map misplaced `study_design_subtype=meta_analysis` or
  `clinical_meta_analysis` to `cannot_determine` while preserving the principal
  study-design category.

Raw unsupported values such as `mental_health`, `behavior`, and `pain` remain
visible in evaluation as schema-evolution signals.

## Product Decision At Handoff

The project no longer needs more broad-versus-selective prompt engineering
before a demo. The broad/v3 Batch path is operationally viable.

The recommended next product move is:

1. build a read-only local retrieval index over the 500 candidate records;
2. implement a read-only MCP server over that index;
3. prepare medical-team demo queries and reviewer recruitment exports;
4. optionally continue remaining strict-corpus Batch classification in the
   background using sequential chunks.

Candidate classifications remain retrieval metadata and candidate evidence.
They are not reviewed clinical truth, medical advice, or treatment
recommendations.

## Prompt: Start MCP Planning And Execution

Use this prompt to start the next Codex session for MCP work:

```text
Siga o AGENTS.md. Podemos conversar em português, mas código, docs, schemas,
prompts, CLI output e artefatos do repositório devem permanecer em inglês.

Contexto MaryGenAI:
- MaryGenAI é um scientific source-intelligence and candidate-classification
  engine para medicina canábica.
- AI classifications são retrieval metadata e candidate evidence, não verdade
  clínica, conselho médico ou recomendação terapêutica.
- Não mutar SQLite, review queues, review decisions ou reviewed knowledge.
- Não chamar LLM/provider sem autorização explícita.
- Usar Python 3.13+, uv, código suportado em src/marygenai/, comandos públicos
  via marygenai CLI.
- Usar apply_patch para edições.
- Rodar ruff e pytest.
- Manter main como única branch ativa local/remota.

Leia primeiro:
- AGENTS.md
- README.md
- docs/product_value.md
- docs/mvp_plan.md
- docs/roadmap.md
- docs/official_workflows.md
- docs/classification_architecture.md
- docs/classification_dataset_plan.md
- docs/classification_data_dictionary.md
- docs/decisions.md
- docs/experimental_findings.md
- docs/2026-07-11_batch_and_mcp_handoff.md

Estado atual:
- Já existe uma base local candidate-classified de 500 strict
  classification-ready documents.
- Runs: 20260710T173226Z, 20260710T180539Z, 20260710T211154Z,
  20260711T153044Z.
- Agregado: 500/500 strict-valid candidate records, zero remote failures,
  500/500 com evidence spans, custo Batch estimado ~USD 2.52.
- Os artifacts estão em data/normalized/classification_runs/ e são ignorados.
- Esses registros são candidate evidence, não reviewed knowledge.

Objetivo:
Planejar e implementar a primeira versão read-only do MCP Server ou do índice
local que o MCP consumirá, usando os 500 candidate records existentes.

Sequência desejada:
1. Inspecionar os candidate records, summaries e evaluation reports dos quatro
   runs.
2. Propor o contrato MCP/read-only retrieval: tools/resources, filtros,
   resposta de search, resposta de detail, facets e limites de segurança.
3. Implementar um índice local read-only, sem mutar SQLite/review state.
4. Expor comandos via marygenai CLI para build/inspect do índice se necessário.
5. Implementar MCP de forma mínima, testável e alinhada ao produto.
6. Garantir que respostas preservem source identity, source_text_path/hash,
   evidence spans, uncertainty, model/prompt/schema versions, provenance,
   review_state e trust boundary.
7. Incluir testes.
8. Atualizar README/docs/decisions quando houver decisão relevante.
9. Rodar ruff e pytest.
10. Fazer commit e push para origin/main.

Antes de implementar, apresente um plano curto e a proposta de contrato MCP.
```

## Prompt: Continue Batch Monitoring And Error Repair

Use this prompt when returning with more Batch results:

```text
Siga o AGENTS.md. Podemos conversar em português, mas código, docs, schemas,
CLI output e artefatos do repositório devem permanecer em inglês.

Contexto:
MaryGenAI já completou uma primeira tranche Batch de 500 strict
classification-ready documents usando sub-batches sequenciais. A documentação
de handoff está em docs/2026-07-11_batch_and_mcp_handoff.md.

Regras importantes:
- Não chamar provider/LLM sem minha autorização explícita.
- Não mutar SQLite, review queues, review decisions ou reviewed knowledge.
- Classification outputs são candidate evidence local ignorada.
- Reparos locais de schema só podem ser deterministic technical repairs,
  provenance-recorded, sem inventar interpretação clínica.
- Usar apply_patch para edições.
- Rodar ruff e pytest.
- Commit e push para origin/main ao concluir.

Vou colar o output de prepare/submit/watch-batch ou caminhos de artifacts.
Sua tarefa:
1. Inspecionar status, summary, errors e raw responses do run informado.
2. Dizer se houve falha remota, custo/usage, strict schema validity e evidence
   coverage.
3. Se houver schema errors locais, avaliar se são reparos técnicos seguros:
   enum drift, marcador de incerteza inválido, valor em campo errado,
   deduplicação ou marker obrigatório ausente.
4. Se for seguro, implementar reparo determinístico em
   src/marygenai/classification/pipeline.py, com teste, reconverter localmente
   o output já baixado e reavaliar.
5. Se não for seguro, explicar o caso e recomendar targeted rerun ou revisão
   humana.
6. Atualizar docs/decisions.md e docs/experimental_findings.md quando houver
   aprendizado durável.
7. Rodar ruff e pytest.
8. Commit e push para origin/main.

Nunca trate candidate classification como reviewed knowledge ou orientação
médica.
```

