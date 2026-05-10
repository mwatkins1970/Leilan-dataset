# Legacy GPT-3 scripts

This folder contains historical scripts from the original GPT-3 Leilan corpus generation period.

They are included for **transparency, provenance, and future analysis**, not as maintained or recommended pipeline code.

## Status

These scripts are archival.

They were written quickly during the original GPT-3 experimentation phase, before the dataset had its current normalized structure and before the later Claude-family curation work. They did the practical job they needed to do at the time: helping generate, collect, and process the original GPT-3 Leilan material.

They should not be treated as:

- maintained production code;
- a modern reproducible build pipeline;
- current OpenAI API examples;
- security-reviewed software;
- polished Python style examples; or
- the canonical way to regenerate the public dataset.

Some scripts may use old API patterns, hard-coded assumptions, local paths, placeholder API-key fields, or other historically contingent details.

## Why keep them?

They are retained because they document part of the history of the dataset:

- how the early Leilan GPT-3 material was generated;
- what kinds of prompt workflows were used;
- what experimental assumptions were in play at the time;
- how the raw corpus came into being; and
- what future researchers may want to inspect when studying the provenance of the dataset.

In other words: these scripts are here because the archive should not hide its messy origins.

## Canonical dataset files

For normal use, ignore these scripts and use the root-level dataset files instead:

```text
combined_leilan_dataset.json
combined_leilan_dataset_records.jsonl
full_leilan_gpt3_dataset.json
full_leilan_gpt3_dataset_normalized.json
full_leilan_gpt3_dataset_normalized.jsonl
full_leilan_claude_dataset.json
leilan_gpt3_passages.json
```

The recommended machine-facing entry point is:

```text
combined_leilan_dataset.json
```

or, for line-oriented processing:

```text
combined_leilan_dataset_records.jsonl
```

## Reproducibility note

These legacy scripts are not expected to reproduce the current dataset end-to-end.

The current public dataset reflects later normalization, curation, deduplication, review, and packaging work. The scripts in this folder are best understood as historical artifacts from the original GPT-3 generation stage.

Future releases may include separate modern validation or manifest-generation scripts. Those should be treated as current release-engineering tools; this folder should not.

## API keys and credentials

If any script appears to contain an API-key variable or placeholder, it is not a live credential.

Do not add real API keys to this repository.

Do not run these scripts against current APIs without first reviewing and updating them.

## License

These scripts are released under the same terms as the rest of the repository: **CC0 1.0 Universal / Public Domain Dedication**.
