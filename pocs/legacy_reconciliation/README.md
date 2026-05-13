# Legacy Reconciliation POC

Goal: measure how much of the legacy study table can be anchored to stable
publication identifiers before using network-based resolvers.

Run:

```bash
uv run python pocs/legacy_reconciliation/reconcile_legacy.py run
```

Default input:

- `temp/legacy/cannadocs/Estudos-Grid view.csv`

Outputs:

- `data/normalized/legacy_reconciliation/*_records.jsonl`: one reconciliation
  record per legacy study row;
- `data/normalized/legacy_reconciliation/*_summary.json`: aggregate counts,
  duplicate metrics, and examples.

This POC intentionally does not fetch PubMed, PMC, DOI, or publisher pages. It only
classifies identifiers and source domains already present in the legacy CSV. Network
resolution belongs in the next resolver POC.
