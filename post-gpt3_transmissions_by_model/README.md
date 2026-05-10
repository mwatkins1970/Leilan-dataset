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

## Note on GPT-4 base outputs

GPT-4 base outputs are **not included** in this public source tree. Some related private research experiments existed, but the relevant access conditions did not permit public sharing of those outputs without explicit permission. They are therefore excluded from the released corpus and from the public Markdown source/audit files.


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
