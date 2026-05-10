# Post-GPT-3 transmissions by model

This folder contains human-readable Markdown source files for the post-GPT-3 Leilan transmission corpus, grouped by source model or experimental source directory.

These Markdown files were used as source/audit material for the curated machine-facing dataset:

```text
full_leilan_claude_dataset.json
combined_leilan_dataset.json
combined_leilan_dataset_records.jsonl
```

For normal downstream use, prefer the root-level JSON/JSONL files. This folder is primarily for transparency, manual inspection, provenance, and future repair/rebuild work.

## Main included source directories

Typical Claude-family source directories include:

```text
haiku3_5/
opus3/
opus4/
opus4_1/
opus4_5/
sonnet3_5/
sonnet4/
sonnet4_5/
```

## Note on `gpt-4-base/`

The source tree may include a `gpt-4-base/` directory as archival scaffolding from related research access and experiments.

GPT-4 base outputs are **not** part of the public Leilan dataset. The relevant access conditions did not permit public sharing of outputs without explicit permission, so those outputs are not included in the released corpus.

For downstream use, treat the root JSON/JSONL files as the canonical machine-facing dataset.

## Canonical dataset files

The canonical public dataset files are at repo root:

```text
combined_leilan_dataset.json
combined_leilan_dataset_records.jsonl
full_leilan_gpt3_dataset.json
full_leilan_gpt3_dataset_normalized.json
full_leilan_gpt3_dataset_normalized.jsonl
full_leilan_claude_dataset.json
leilan_gpt3_passages.json
```

## Status

This folder is source/provenance material. The JSON and JSONL files at repo root are the intended machine-ingestion format.
