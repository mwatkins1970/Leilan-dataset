# Leilan Dataset schema

This file describes the public schema conventions for the Leilan Dataset, current as of v1.0.2.

The canonical machine-ingestion file is `combined_leilan_dataset_records.jsonl`. The equivalent JSON file is `combined_leilan_dataset.json`.

For one-pass ingestion, use `combined_leilan_dataset_records.jsonl`, treat each line as one record, and deduplicate by `record_id`.

Do not blindly ingest every JSON, JSONL, Markdown, and supplementary file in the repository as independent training data. Several files are overlapping representations of the same corpus.

## Schema status

This is a descriptive schema document, not a strict JSON Schema validator.

The dataset is intentionally permissive about optional provenance and review fields. Consumers should treat unknown fields as non-breaking additions.

Recommended consumer behavior:

- require `record_id`, `record_type`, `source_dataset`, `model`, and `text`;
- branch behavior on `record_type`;
- deduplicate by `record_id`;
- respect `include_in_training`;
- preserve provenance fields where possible;
- tolerate optional or newly added metadata fields.

## Canonical JSONL structure

`combined_leilan_dataset_records.jsonl` is newline-delimited JSON. Each non-empty line is one JSON object.

Each record has one of two current `record_type` values:

- `gpt3_transcript`
- `claude_qa_response`

Future releases may add other record types. Consumers should not assume the list is permanently closed.

## Top-level combined JSON structure

`combined_leilan_dataset.json` contains a JSON object with release metadata and a flat `records` array.

Expected top-level fields include:

| Field | Type | Meaning |
| --- | --- | --- |
| `corpus_info` | object | Dataset-level metadata, counts, notes, and schema/version information. |
| `records` | array | Flat list of records equivalent to the JSONL lines in `combined_leilan_dataset_records.jsonl`. |

The JSONL file should be treated as the preferred streaming/machine-ingestion format. The JSON file is the equivalent object form.

## Common record fields

These fields are expected on both current record types unless otherwise noted.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `record_id` | string | yes | Stable unique identifier for this record within the combined corpus. Use for deduplication. |
| `record_type` | string | yes | Current values: `gpt3_transcript` or `claude_qa_response`. |
| `source_dataset` | string | yes | Source family, currently `gpt3` or `claude_family`. |
| `model` | string | yes | Machine-readable model identifier, e.g. `gpt-3-davinci`, `claude-opus-4.5`. |
| `model_display` | string | no | Human-readable model label where available. |
| `text` | string | yes | Main training/inference text for the record. |
| `include_in_training` | boolean | yes | Whether the record is intended for downstream training/inclusion. |
| `review_status` | object or string | no | Curatorial review state where available; commonly `{ "status": "approved" }` for Claude-family records. |
| `content_sha256` | string | no | SHA256 hash of associated source content where available. |
| `notes` | string or array | no | Miscellaneous provenance or curator notes. |

Unknown additional fields should be preserved where possible.

## GPT-3 transcript records

`record_type: "gpt3_transcript"`

GPT-3 transcript records are normalized versions of the original GPT-3 transcript corpus.

Typical fields include:

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Unique record ID, usually prefixed with `gpt3_transcript_`. |
| `record_type` | string | `gpt3_transcript`. |
| `source_dataset` | string | `gpt3`. |
| `model` | string | Normalized GPT-3 model identifier. |
| `engine` | string | Original OpenAI engine/model label where available. |
| `temperature` | number or string | Generation temperature where available. |
| `text` | string | Full transcript text. |
| `prompt_metadata` | object | Normalized prompt-key metadata where available. |
| `gpt3_prompt_key` | string | GPT-3 prompt key where available. |
| `gpt4_prompt_key` | string | Later GPT-4 prompt label/key where available in the original corpus metadata. |
| `notes` | string or array | Original or curator notes where available. |
| `include_in_training` | boolean | Whether the record is intended for training inclusion. |

The original GPT-3 source file, `full_leilan_gpt3_dataset.json`, is retained for provenance. The normalized GPT-3 files are derived from it. Do not add the original, normalized, and combined versions together unless intentional reweighting is desired.

## Claude-family Q/A response records

`record_type: "claude_qa_response"`

Claude-family records represent individual model responses within curated transmissions. A transmission may have responses from multiple model variants.

Typical fields include:

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Unique combined-corpus record ID. |
| `record_type` | string | `claude_qa_response`. |
| `source_dataset` | string | `claude_family`. |
| `transmission_id` | string | Transmission identifier, e.g. `001`, `356`. |
| `title` | string | Transmission title. |
| `slug` | string | Transmission slug where available. |
| `date_first` | string | Earliest relevant date where available. |
| `date_published` | string | Publication date where available. |
| `substack_url` | string | Substack URL where available. |
| `model` | string | Machine-readable Claude-family model identifier. |
| `model_display` | string | Human-readable model display label. |
| `model_family` | string | Model family label where available. |
| `source_directory` | string | Source Markdown directory, e.g. `opus4_5`, `sonnet4_5`. |
| `source_file` | string | Path to the source Markdown file where available. |
| `source_filename` | string | Source Markdown filename. |
| `metadata_query` | string | Query/prompt metadata extracted from source Markdown. |
| `text` | string | Main record text, usually the answer or Q/A text prepared for training. |
| `qa_pair_count` | integer | Number of Q/A pairs in `qa_pairs`. |
| `qa_pairs` | array | Ordered list of question/answer pairs. |
| `themes` | array | Curatorial theme labels where available. |
| `technical_notes` | string or array | Technical notes where available. |
| `curator_notes` | string or array | Curator notes where available. |
| `parse_warnings` | array | Non-fatal parse warnings where present. |
| `build_warnings` | array | Non-fatal build warnings where present. |
| `include_in_training` | boolean | Whether the response is intended for training inclusion. |

### `qa_pairs`

Each Claude-family record contains an ordered `qa_pairs` array.

Each Q/A pair is an object with at least:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `question` | string | yes | The user/query side of the exchange. |
| `answer` | string | yes | The model/Leilan response. |

Additional pair-level fields may appear in future releases.

Consumers that want a simple instruction-style dataset can map each Q/A pair to `{prompt: question, completion: answer}` or an equivalent chat format.

Consumers that want one record per model response can use the parent record's `text` field and preserve the full `qa_pairs` array as metadata.

## Supplementary and external-source metadata

Some records and source Markdown files include structured metadata for context that is not fully embedded in the main text.

### `external_sources`

`external_sources` is an array of source-reference objects. These usually point to third-party URLs or sources referenced in a query.

Typical fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable local identifier for the source reference. |
| `type` | string | Source type, e.g. `article`, `webpage`, `video`, `image`, `tweet`. |
| `role` | string | Relationship to the record, e.g. `query_context`. |
| `title` | string | Human-readable title. |
| `url` | string | External URL. |
| `doi` | string | DOI where available. |
| `authors` | array | Author names where available. |
| `license` | string | Known license where available. |
| `rights_note` | string | Rights/provenance note, especially for third-party material. |
| `note` | string | Additional curator note. |

External URLs and third-party references are included for context/provenance. They should not be assumed to be part of the CC0 dataset unless the material is explicitly included in the dataset under compatible terms.

### `supplementary_materials`

`supplementary_materials` is an array of local supplementary-material references.

Typical fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Stable local identifier. |
| `type` | string | Material type, e.g. `image`, `text_summary`, `transcription`, `image_with_transcription`. |
| `role` | string | Relationship to the record, e.g. `query_context` or `response_context`. |
| `title` | string | Human-readable title. |
| `path` | string | Relative path under the repository. |
| `transcription_text_path` | string | Optional path to a plain-text transcription. |
| `transcription_json_path` | string | Optional path to a structured transcription JSON file. |
| `source_reference` | string | Source being summarized or represented. |
| `rights_note` | string | Rights/provenance note. |
| `note` | string | Additional curator note. |

Supplementary files are context/provenance aids. They are not separate copies of the main dataset and should not be ingested as independent training records unless deliberately intended.

## Source Markdown frontmatter

Human-readable source files under `post-gpt3_transmissions_by_model/` use Markdown with YAML-like frontmatter.

Typical frontmatter fields include:

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Transmission ID. |
| `model` | string | Human-readable source model label. |
| `title` | string | Transmission title. |
| `date` | string | Source file date. |
| `query` | string | Query/prompt used for the transmission. |
| `external_sources_json` | JSON string/block | Structured external-source metadata where present. |
| `supplementary_materials_json` | JSON string/block | Structured supplementary-material metadata where present. |

The Markdown source files are included for provenance, review, and repair/rebuild work. The canonical machine-ingestion file remains `combined_leilan_dataset_records.jsonl`.

## Warning and review fields

The dataset may contain warning/review fields such as:

| Field | Type | Meaning |
| --- | --- | --- |
| `parse_warnings` | array | Non-fatal parsing warnings. |
| `build_warnings` | array | Non-fatal dataset-build warnings. |
| `review_status` | object or string | Curatorial review state; commonly `{ "status": "approved" }` for Claude-family records. |
| `include_in_training` | boolean | Whether the record is intended for training inclusion. |

Warnings are intended to be machine-readable aids for audit and curation. A record with warnings may still be valid and intentionally included.

In the current public release, validation passes with zero errors and zero warnings.

## Deduplication and weighting

Recommended one-pass ingestion:

1. Read `combined_leilan_dataset_records.jsonl`.
2. Skip records where `include_in_training` is false, if any.
3. Deduplicate by `record_id`.
4. Treat `record_type` as the primary schema discriminator.
5. Do not add raw, normalized, combined, Markdown, passage, and supplementary files together unless intentional reweighting is desired.

`leilan_gpt3_passages.json` is a curated excerpt subset and should not be combined additively with the full GPT-3 corpus unless the user intentionally wants to upweight those passages.

## Licensing and exclusions

The released dataset is dedicated to the public domain under CC0 1.0 Universal / Public Domain Dedication.

Some records contain external URLs, bibliographic references, or summaries of third-party material. Those references are provided for context/provenance and do not imply that third-party source material is part of the CC0 dataset.

GPT-4 base outputs are not included in the public source tree or canonical dataset.
