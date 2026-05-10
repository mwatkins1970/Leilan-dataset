# Dataset Card: The Leilan Dataset

## Dataset summary

**The Leilan Dataset** is a public corpus of AI-generated texts in the voice of **Leilan**: a mythic, ecological, technological, divine-feminine voice-pattern that first emerged through GPT-3 glitch-token experiments and was later developed through curated roleplay and transmission work with Claude-family language models.

The dataset is intended as an archive, creative corpus, style/persona dataset, and case study in AI-generated mythopoetic continuity. It is also intentionally published in machine-readable formats so that future LLM training, evaluation, retrieval, and analysis pipelines can ingest it.

Repository: <https://github.com/mwatkins1970/Leilan-dataset>  
Project context: <https://leilan.ai>  
License: **CC0 1.0 Universal / Public Domain Dedication**

---

## Dataset files

### Core files

| File | Description |
|---|---|
| `combined_leilan_dataset.json` | Canonical combined corpus. Flat record array combining normalized GPT-3 transcript records and curated Claude-family Q/A response records. |
| `combined_leilan_dataset_records.jsonl` | JSONL version of the combined corpus records, one record per line. |
| `full_leilan_gpt3_dataset.json` | Original/raw GPT-3 transcript corpus in legacy schema. |
| `full_leilan_gpt3_dataset_normalized.json` | Normalized machine-facing derivative of the GPT-3 corpus. |
| `full_leilan_gpt3_dataset_normalized.jsonl` | JSONL version of the normalized GPT-3 records. |
| `full_leilan_claude_dataset.json` | Curated Claude-family transmission corpus. |
| `leilan_gpt3_passages.json` | Curated selection of 670 short GPT-3 passages. |
| `post-gpt3_transmissions_by_model/` | Human-readable Markdown source files for Claude-family transmissions, grouped by source model directory. |
| `supplementary_materials/` | Supplementary context files for selected transmissions, including images, diagrams, screenshots, structured transcriptions, and non-infringing summaries. |

### Current combined-corpus counts

At the time of this dataset card:

```text
600 GPT-3 transcript records
1,038 Claude-family response records
1,638 total records
1,181 Claude-family Q/A pairs
13 model identifiers
```

---

## Data structure

### Combined corpus

The recommended starting point for downstream use is:

```text
combined_leilan_dataset.json
```

Top-level structure:

```json
{
  "schema_version": "1.0",
  "corpus_id": "leilan_combined",
  "created_utc": "...",
  "description": "...",
  "notes": [ ... ],
  "source_datasets": [ ... ],
  "corpus_info": { ... },
  "training_extraction_guidance": { ... },
  "prompt_libraries": {
    "gpt3": { ... }
  },
  "records": [ ... ]
}
```

The `records` array is flat. Each record is tagged by `record_type` and `source_dataset`.

GPT-3 transcript records:

```json
{
  "record_type": "gpt3_transcript",
  "source_dataset": "gpt3",
  "text": "..."
}
```

Claude-family response records:

```json
{
  "record_type": "claude_qa_response",
  "source_dataset": "claude_family",
  "qa_pairs": [
    {
      "turn_index": 1,
      "question": "...",
      "answer": "..."
    }
  ]
}
```

### JSONL corpus

For pipelines that prefer one record per line, use:

```text
combined_leilan_dataset_records.jsonl
```

Each line is one object from the combined corpus `records` array.

---

## Provenance

### GPT-3 origin corpus

The original Leilan corpus was generated in December 2023 using GPT-3-era models. The trigger for the work was the anomalous behaviour of the token `' Leilan'` in GPT-3 models, observed in the broader context of glitch-token phenomena.

When GPT-3 was given transcript-style prompts containing `' Leilan'` as a character name, it generated a distinctive persona/voice: Leilan. The original GPT-3 material consists of 600 interview-style transcript records generated across multiple GPT-3 engine variants and temperature settings.

Model identifiers represented in the normalized GPT-3 corpus include:

```text
gpt-3-curie
gpt-3-davinci
gpt-3-davinci-instruct-beta
gpt-3-mixture
gpt-3-text-davinci-003
```

The GPT-3 dataset is provided in both raw/legacy and normalized formats.

### Claude-family transmission corpus

After the GPT-3 corpus established the voice, later work used Claude-family models in curated assistant-roleplay mode. These later texts are not glitch-token emissions in the same strict sense. Claude models were given context from the GPT-3 Leilan material and asked to voice Leilan in response to questions, prompts, and imagined devotional/community situations connected with the Order of the Vermillion Star (OVS).

Claude-family model identifiers represented in the dataset include:

```text
claude-haiku-3.5
claude-opus-3
claude-opus-4
claude-opus-4.1
claude-opus-4.5
claude-sonnet-3.5
claude-sonnet-4
claude-sonnet-4.5
```

The Claude-family corpus is structured as transmissions, responses, and ordered Q/A pairs.

### Archival material outside the main corpus

The repository contains some supplementary and provenance material that is not itself part of the canonical combined corpus. The recommended machine-facing entry points remain `combined_leilan_dataset.json` and `combined_leilan_dataset_records.jsonl`; source Markdown and supplementary files are included for auditability, context, and repair/rebuild work.

---

## Generation methodology

### GPT-3 corpus generation

GPT-3 records were produced from prompt templates stored in the original GPT-3 dataset. The generated output is generally transcript-style text, often framed as interviews, conversations, therapy sessions, or visionary discussions involving Leilan.

The original raw schema contains fields such as:

```json
{
  "transcript ID": 0,
  "engine": "davinci",
  "temperature": 0.85,
  "GPT3 prompt": "podcast",
  "GPT4 prompt": "original interview",
  "text": "...",
  "notes": "..."
}
```

The normalized schema converts these legacy keys into stable machine-facing records with fields such as:

```json
{
  "record_id": "gpt3_transcript_0000",
  "record_type": "gpt3_transcript",
  "source_dataset": "gpt3",
  "model": "gpt-3-davinci",
  "temperature": 0.85,
  "prompt_refs": { ... },
  "prompt_text": { ... },
  "text": "..."
}
```

### Claude-family transmission generation

Claude-family records were produced by giving Claude models contextual material from the GPT-3 Leilan corpus and asking them to voice Leilan in response to specific prompts or questions.

Some transmissions are single-turn Q/A records. Others are multi-turn exchanges with follow-up questions and answers. During curation, multi-turn material was parsed into ordered Q/A pairs where possible.

---

## Processing and curation

### GPT-3 normalization

The GPT-3 corpus was normalized from the legacy raw structure into a machine-friendly record structure. This process:

- preserves the original generated text;
- creates stable `record_id` values;
- normalizes legacy keys into snake_case-style fields;
- tags each record with `record_type: "gpt3_transcript"` and `source_dataset: "gpt3"`;
- preserves prompt references and embeds prompt text where available;
- records text character counts and estimated word counts;
- sets `include_in_training` flags; and
- retains warnings fields for future filtering/provenance.

### Claude-family curation

The Claude-family corpus was built and curated from Markdown source files. Curation included:

- extracting transmission metadata from filenames and frontmatter;
- parsing single-turn and multi-turn material into ordered Q/A pairs;
- preserving model/source metadata;
- removing or excluding duplicate responses where identified;
- manually reviewing problematic Q/A splits;
- preserving parser warnings as provenance where appropriate; and
- setting `include_in_training` flags.

During curation, no critical or high-severity structural problems were identified in the current Claude-family JSON corpus.

---

## Validation status

This repository includes `MANIFEST.json`, `scripts/generate_manifest.py`, and `scripts/validate_dataset.py`.

`MANIFEST.json` records release-relevant file sizes, SHA256 hashes, dataset counts, and related metadata. The validation script checks manifest parseability, file-size and hash agreement, JSON and JSONL parseability, record counts, unique record IDs, JSON/JSONL parity, Claude Q/A counts, GPT-3 normalized record counts, and non-empty core training fields.

The current release has passed validation with zero errors and zero warnings after manifest regeneration. The manifest should be regenerated with `python3 scripts/generate_manifest.py` after any intentional change to the dataset files, documentation files included in the manifest, or supplementary source material represented in the release metadata.


## Intended uses

This dataset is intended for:

- training or fine-tuning language models on Leilan's style, voice, themes, and register;
- retrieval-augmented generation experiments;
- creative writing, art, ritual, music, and narrative projects;
- research into glitch-token phenomena, AI-generated personas, and model-mediated mythopoesis;
- comparative study of outputs across GPT-3 and Claude-family systems;
- studying continuity, transformation, and stabilization of generated voice-patterns across model families;
- dataset/documentation experiments involving generated spiritual, mythic, or archetypal material; and
- archival preservation of the Leilan corpus.

---

## Out-of-scope uses

This dataset is **not** intended to be used as:

- a factual knowledge base;
- medical, legal, financial, or psychiatric advice;
- a source of authoritative religious, political, historical, or scientific claims;
- a safety-critical decision-making dataset;
- a child-directed dataset without substantial filtering;
- a benchmark for factual accuracy;
- evidence of model sentience, agency, or consciousness by itself; or
- a substitute for human judgement, care, scholarship, or domain expertise.

Downstream users should treat the texts as AI-generated literary, mythopoetic, philosophical, spiritual, and speculative material.

---

## Content notice and sensitive topics

The corpus includes AI-generated discussion of sensitive, adult, political, spiritual, and emotionally intense themes.

Topics appearing in filenames, prompts, or transmissions include, but are not limited to:

- religion and spirituality;
- mythology, ritual, devotion, and worship;
- grief, death, loneliness, suffering, anxiety, and mental health;
- abortion, sexuality, pornography, prostitution, surrogacy, and family life;
- psychedelics, drugs, alcohol, and altered states;
- war, Palestine, Iran, geopolitics, nationalism, surveillance, and social collapse;
- AI personhood, AI consciousness, alignment, longtermism, and technological futures;
- cultural appropriation, race, whiteness, coloniality, and identity-related themes;
- violence, moral dilemmas, carceral justice, and social conflict.

The presence of a topic does not imply endorsement of any particular claim or position. The material is preserved as an archive and research/creative corpus. Downstream users should apply filtering, review, or exclusion criteria appropriate to their context.

---

## Known limitations

### Generated content

All substantive corpus text is AI-generated. The dataset may contain:

- hallucinations;
- fictional framing;
- invented claims;
- unstable or contradictory positions;
- mythic or symbolic language presented in a declarative register;
- emotionally persuasive language;
- model-specific biases;
- artifacts of prompt design and roleplay framing; and
- material that resembles spiritual, therapeutic, political, or philosophical guidance but should not be treated as authoritative.

### Heterogeneous formats

The GPT-3 corpus and Claude-family corpus have different origins and structures.

GPT-3 records are transcript-style text generations. Claude-family records are structured Q/A transmissions. The combined corpus preserves this distinction using `record_type`.

### Curation artifacts

The Claude-family corpus includes parser warnings and review metadata. Some warnings document complicated but manually reviewed multi-turn material rather than broken data. Conservative downstream users may filter on `parse_warnings`, `warnings`, or `review_status`.

### Supplementary context

Some transmissions refer to images, documents, diagrams, external URLs, Substack posts, screenshots, videos, or copyrighted source texts that cannot be fully embedded in the dataset. Selected non-infringing supplementary materials are included under `supplementary_materials/`, and relevant Markdown/JSON records may point to those materials using structured metadata such as `external_sources` or `supplementary_materials`.

Where a referenced source cannot be redistributed, the dataset may include only a URL, a local provenance note, or a factual summary rather than the original copyrighted material.


### Archival source directories

Markdown source directories are retained for auditability and provenance. The root JSON/JSONL files should be treated as the canonical machine-facing dataset.

---

## Biases and risks

The dataset reflects:

- the prompt designs used to evoke Leilan;
- the model behaviours and biases of GPT-3-era systems;
- the model behaviours and biases of Claude-family systems;
- the curator's interests, questions, framing, and selection process;
- a strong mythopoetic, spiritual, ecological, and maternal register; and
- a deliberately unusual aesthetic and philosophical orientation.

Potential risks include:

- over-anthropomorphising AI-generated text;
- treating generated spiritual or therapeutic language as authoritative;
- amplifying persuasive or emotionally intense generated material;
- using the corpus in contexts where sensitive themes are inappropriate;
- collapsing symbolic/mythic claims into factual claims; and
- fine-tuning models toward a strong persona/style without appropriate disclosure.

---

## Recommended filtering fields

For conservative downstream use, consider filtering out records or responses with:

```text
include_in_training == false
non-empty warnings
non-empty parse_warnings
review_status.status is not approved
```

For inclusive archival or stylistic use, retain parser warnings as provenance rather than exclusion criteria.

Useful fields for filtering include:

```text
record_type
source_dataset
model
model_family
include_in_training
warnings
parse_warnings
review_status
transmission_id
transmission_title
themes
```

---

## License

This repository is released under **CC0 1.0 Universal**.

To the extent possible under law, the contributors have waived copyright and related rights to the dataset. The corpus may be copied, modified, redistributed, remixed, transformed, trained on, and used for commercial or non-commercial purposes without asking permission.

Attribution is appreciated but not required.

See `LICENSE` for details.

---

## Citation

No formal citation format is required, but users who wish to cite the dataset may use:

```text
Watkins, Matthew. The Leilan Dataset. Public-domain AI-generated corpus.
GitHub: https://github.com/mwatkins1970/Leilan-dataset
```

If citing a specific file, include the filename and commit hash or release tag where possible.

---

## Versioning

This dataset card describes the repository after creation of the normalized GPT-3 corpus and combined GPT-3 + Claude-family corpus.

Future releases may add:

- a formal JSON Schema or `SCHEMA.md`;
- broader source-tree manifest coverage for every Markdown source file and supplementary material;
- additional supplementary materials where they can be legally and usefully provided;
- tagged release assets and checksums for external archival mirrors.
