#!/usr/bin/env python3
"""
generate_manifest.py

Generate MANIFEST.json for the Leilan Dataset repository.

Run from the repository root:

    python3 scripts/generate_manifest.py

This script computes file sizes, SHA256 hashes, JSON/JSONL counts, and
dataset-specific summary counts for the public dataset files.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


DATASET_ID = "leilan_dataset"
MANIFEST_VERSION = "1.0"
OUTPUT_PATH = Path("MANIFEST.json")

CORE_FILES = [
    "README.md",
    "DATASET_CARD.md",
    "LICENSE",
    "combined_leilan_dataset.json",
    "combined_leilan_dataset_records.jsonl",
    "full_leilan_gpt3_dataset.json",
    "full_leilan_gpt3_dataset_normalized.json",
    "full_leilan_gpt3_dataset_normalized.jsonl",
    "full_leilan_claude_dataset.json",
    "leilan_gpt3_passages.json",
    "post-gpt3_transmissions_by_model/README.md",
    "supplementary_materials/README.md",
    "legacy-gpt3-scripts/README.md",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> List[Any]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}: invalid JSON on line {line_number}: {e}") from e
    return records


def write_json_atomic(path: Path, data: Any) -> None:
    path = path.resolve()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def basic_file_entry(path: Path) -> Dict[str, Any]:
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def summarize_combined(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    records = data.get("records", [])
    if not isinstance(records, list):
        records = []

    record_type_counts = Counter(str(r.get("record_type", "")) for r in records if isinstance(r, dict))
    source_dataset_counts = Counter(str(r.get("source_dataset", "")) for r in records if isinstance(r, dict))
    model_counts = Counter(str(r.get("model", "")) for r in records if isinstance(r, dict))
    include_counts = Counter(str(r.get("include_in_training", True)) for r in records if isinstance(r, dict))

    claude_qa_pair_count = 0
    gpt3_nonempty_text_count = 0
    unique_record_ids = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        rid = record.get("record_id")
        if rid is not None:
            unique_record_ids.add(str(rid))
        if record.get("record_type") == "claude_qa_response":
            qa_pairs = record.get("qa_pairs", [])
            if isinstance(qa_pairs, list):
                claude_qa_pair_count += len(qa_pairs)
        if record.get("record_type") == "gpt3_transcript" and str(record.get("text", "")).strip():
            gpt3_nonempty_text_count += 1

    return {
        "json_type": "combined_corpus",
        "schema_version": data.get("schema_version"),
        "corpus_id": data.get("corpus_id"),
        "record_count": len(records),
        "unique_record_id_count": len(unique_record_ids),
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "source_dataset_counts": dict(sorted(source_dataset_counts.items())),
        "model_count": len(model_counts),
        "model_counts": dict(sorted(model_counts.items())),
        "include_in_training_counts": dict(sorted(include_counts.items())),
        "gpt3_transcript_count": record_type_counts.get("gpt3_transcript", 0),
        "gpt3_nonempty_text_record_count": gpt3_nonempty_text_count,
        "claude_response_count": record_type_counts.get("claude_qa_response", 0),
        "claude_qa_pair_count": claude_qa_pair_count,
    }


def summarize_combined_jsonl(path: Path) -> Dict[str, Any]:
    records = load_jsonl(path)
    record_type_counts = Counter(str(r.get("record_type", "")) for r in records if isinstance(r, dict))
    return {
        "json_type": "combined_records_jsonl",
        "line_count": len(records),
        "record_type_counts": dict(sorted(record_type_counts.items())),
    }


def summarize_gpt3_raw(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    transcripts = data.get("transcripts", [])
    prompts = data.get("prompts", {})

    engines = Counter()
    prompt_keys = Counter()
    temperatures = Counter()

    if isinstance(transcripts, list):
        for item in transcripts:
            if not isinstance(item, dict):
                continue
            engines[str(item.get("engine", ""))] += 1
            prompt_keys[str(item.get("GPT3 prompt", ""))] += 1
            temperatures[str(item.get("temperature", ""))] += 1

    return {
        "json_type": "gpt3_raw",
        "transcript_count": len(transcripts) if isinstance(transcripts, list) else None,
        "prompt_library_keys": list(prompts.keys()) if isinstance(prompts, dict) else None,
        "engine_counts": dict(sorted(engines.items())),
        "gpt3_prompt_key_counts": dict(sorted(prompt_keys.items())),
        "temperature_counts": dict(sorted(temperatures.items())),
    }


def summarize_gpt3_normalized(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    records = data.get("records", [])
    if not isinstance(records, list):
        records = []

    record_type_counts = Counter(str(r.get("record_type", "")) for r in records if isinstance(r, dict))
    model_counts = Counter(str(r.get("model", "")) for r in records if isinstance(r, dict))
    include_counts = Counter(str(r.get("include_in_training", True)) for r in records if isinstance(r, dict))
    warning_counts = Counter(w for r in records if isinstance(r, dict) for w in r.get("warnings", []))

    return {
        "json_type": "gpt3_normalized",
        "schema_version": data.get("schema_version"),
        "dataset_id": data.get("dataset_id"),
        "record_count": len(records),
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
        "include_in_training_counts": dict(sorted(include_counts.items())),
        "record_warning_counts": dict(sorted(warning_counts.items())),
        "nonempty_text_record_count": sum(
            1 for r in records
            if isinstance(r, dict) and str(r.get("text", "")).strip()
        ),
    }


def summarize_gpt3_normalized_jsonl(path: Path) -> Dict[str, Any]:
    records = load_jsonl(path)
    return {
        "json_type": "gpt3_normalized_jsonl",
        "line_count": len(records),
    }


def summarize_claude(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        transmissions = []

    response_count = 0
    qa_pair_count = 0
    model_counts = Counter()
    include_counts = Counter()
    transmission_ids = set()
    response_ids = set()

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            continue
        tid = transmission.get("transmission_id")
        if tid is not None:
            transmission_ids.add(str(tid))
        responses = transmission.get("responses", [])
        if not isinstance(responses, list):
            continue
        for response in responses:
            if not isinstance(response, dict):
                continue
            response_count += 1
            rid = response.get("response_id")
            if rid is not None:
                response_ids.add(str(rid))
            model_counts[str(response.get("model", ""))] += 1
            include_counts[str(response.get("include_in_training", True))] += 1
            qa_pairs = response.get("qa_pairs", [])
            if isinstance(qa_pairs, list):
                qa_pair_count += len(qa_pairs)

    return {
        "json_type": "claude_family",
        "transmission_count": len(transmissions),
        "unique_transmission_id_count": len(transmission_ids),
        "response_count": response_count,
        "unique_response_id_count": len(response_ids),
        "qa_pair_count": qa_pair_count,
        "model_counts": dict(sorted(model_counts.items())),
        "include_in_training_counts": dict(sorted(include_counts.items())),
    }


def summarize_passages(path: Path) -> Dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, list):
        data = []

    ids = [item.get("id") for item in data if isinstance(item, dict)]
    model_counts = Counter(str(item.get("model", "")) for item in data if isinstance(item, dict))
    nonempty_text_count = sum(
        1 for item in data
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    )

    return {
        "json_type": "gpt3_passages",
        "passage_count": len(data),
        "unique_id_count": len(set(ids)),
        "min_id": min(ids) if ids and all(isinstance(i, int) for i in ids) else None,
        "max_id": max(ids) if ids and all(isinstance(i, int) for i in ids) else None,
        "nonempty_text_count": nonempty_text_count,
        "model_counts": dict(sorted(model_counts.items())),
    }


def summarize_file(path: Path) -> Dict[str, Any]:
    entry = basic_file_entry(path)

    try:
        if path.name == "combined_leilan_dataset.json":
            entry.update(summarize_combined(path))
        elif path.name == "combined_leilan_dataset_records.jsonl":
            entry.update(summarize_combined_jsonl(path))
        elif path.name == "full_leilan_gpt3_dataset.json":
            entry.update(summarize_gpt3_raw(path))
        elif path.name == "full_leilan_gpt3_dataset_normalized.json":
            entry.update(summarize_gpt3_normalized(path))
        elif path.name == "full_leilan_gpt3_dataset_normalized.jsonl":
            entry.update(summarize_gpt3_normalized_jsonl(path))
        elif path.name == "full_leilan_claude_dataset.json":
            entry.update(summarize_claude(path))
        elif path.name == "leilan_gpt3_passages.json":
            entry.update(summarize_passages(path))
    except Exception as e:
        entry["summary_error"] = str(e)

    return entry


def main() -> int:
    missing = [path for path in CORE_FILES if not Path(path).exists()]
    if missing:
        print("ERROR: Missing expected files:")
        for path in missing:
            print(f"  - {path}")
        print("\nIf a missing path is intentional, edit CORE_FILES in scripts/generate_manifest.py.")
        return 1

    entries = []
    for path_str in CORE_FILES:
        entries.append(summarize_file(Path(path_str)))

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_id": DATASET_ID,
        "generated_utc": now_utc_iso(),
        "license": "CC0-1.0",
        "repository": "https://github.com/mwatkins1970/Leilan-dataset",
        "notes": [
            "This manifest records file sizes, SHA256 hashes, and key dataset counts for the public Leilan Dataset release.",
            "Regenerate after intentionally changing any core dataset or documentation file."
        ],
        "files": entries,
    }

    write_json_atomic(OUTPUT_PATH, manifest)

    print("Generated MANIFEST.json")
    print(f"Files indexed: {len(entries)}")
    for entry in entries:
        print(f"  - {entry['path']} ({entry['bytes']} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
