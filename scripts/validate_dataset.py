#!/usr/bin/env python3
"""
validate_dataset.py

Validate the public Leilan Dataset repository.

Run from the repository root:

    python3 scripts/validate_dataset.py

This script checks:
  - expected files exist
  - file sizes and SHA256 hashes match MANIFEST.json
  - JSON and JSONL files parse
  - core record counts and internal counts are consistent
  - JSONL exports match their JSON source records
  - record IDs are unique
  - GPT-3 records have non-empty text
  - Claude Q/A pairs have non-empty question and answer fields
  - GPT-3 passages have unique/sequential IDs and non-empty text

Exit code:
  0 = validation passed
  1 = validation failed
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple


MANIFEST_PATH = Path("MANIFEST.json")

ALLOWED_COMBINED_RECORD_TYPES = {"gpt3_transcript", "claude_qa_response"}
ALLOWED_SOURCE_DATASETS = {"gpt3", "claude_family"}


class Validator:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def pass_msg(self, msg: str) -> None:
        print(f"PASS: {msg}")

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"FAIL: {msg}")

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"WARN: {msg}")

    def check(self, condition: bool, success: str, failure: str) -> None:
        if condition:
            self.pass_msg(success)
        else:
            self.fail(failure)


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


def manifest_files(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return {}
    return {
        str(entry.get("path")): entry
        for entry in files
        if isinstance(entry, dict) and entry.get("path")
    }


def validate_manifest_and_hashes(v: Validator) -> Dict[str, Dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        v.fail("MANIFEST.json not found. Run: python3 scripts/generate_manifest.py")
        return {}

    try:
        manifest = load_json(MANIFEST_PATH)
        v.pass_msg("MANIFEST.json parses")
    except Exception as e:
        v.fail(f"MANIFEST.json does not parse: {e}")
        return {}

    files = manifest_files(manifest)
    v.check(bool(files), "MANIFEST.json contains file entries", "MANIFEST.json has no usable file entries")

    for path_str, entry in files.items():
        path = Path(path_str)
        if not path.exists():
            v.fail(f"Manifest file missing from repo: {path_str}")
            continue

        actual_bytes = path.stat().st_size
        expected_bytes = entry.get("bytes")
        if expected_bytes is not None:
            v.check(
                actual_bytes == expected_bytes,
                f"{path_str}: byte size matches manifest",
                f"{path_str}: byte size mismatch; actual {actual_bytes}, manifest {expected_bytes}",
            )

        expected_sha = entry.get("sha256")
        if expected_sha:
            actual_sha = sha256_file(path)
            v.check(
                actual_sha == expected_sha,
                f"{path_str}: SHA256 matches manifest",
                f"{path_str}: SHA256 mismatch; actual {actual_sha}, manifest {expected_sha}",
            )

    return files


def validate_json_parsing(v: Validator, files: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    loaded: Dict[str, Any] = {}

    for path_str in files:
        path = Path(path_str)
        if not path.exists():
            continue

        if path.suffix == ".json":
            try:
                loaded[path_str] = load_json(path)
                v.pass_msg(f"{path_str}: JSON parses")
            except Exception as e:
                v.fail(f"{path_str}: JSON parse failed: {e}")

        elif path.suffix == ".jsonl":
            try:
                loaded[path_str] = load_jsonl(path)
                v.pass_msg(f"{path_str}: JSONL parses")
            except Exception as e:
                v.fail(f"{path_str}: JSONL parse failed: {e}")

    return loaded


def validate_combined(v: Validator, loaded: Dict[str, Any], files: Dict[str, Dict[str, Any]]) -> None:
    path = "combined_leilan_dataset.json"
    data = loaded.get(path)
    if not isinstance(data, dict):
        v.fail("combined_leilan_dataset.json is not loaded as a JSON object")
        return

    records = data.get("records", [])
    if not isinstance(records, list):
        v.fail("combined_leilan_dataset.json: records is not a list")
        return

    manifest_entry = files.get(path, {})
    expected_count = manifest_entry.get("record_count")
    if expected_count is not None:
        v.check(
            len(records) == expected_count,
            f"combined record count matches manifest ({len(records)})",
            f"combined record count mismatch: actual {len(records)}, manifest {expected_count}",
        )

    corpus_info = data.get("corpus_info", {})
    if isinstance(corpus_info, dict) and corpus_info.get("record_count") is not None:
        v.check(
            len(records) == corpus_info.get("record_count"),
            "combined record count matches corpus_info.record_count",
            f"combined record count differs from corpus_info.record_count ({corpus_info.get('record_count')})",
        )

    record_ids = []
    record_type_counts = Counter()
    source_dataset_counts = Counter()
    gpt3_text_empty = 0
    claude_response_count = 0
    claude_qa_pair_count = 0
    empty_qa_fields: List[str] = []

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            v.fail(f"combined record {index} is not an object")
            continue

        rid = record.get("record_id")
        if not rid:
            v.fail(f"combined record {index} has missing record_id")
        else:
            record_ids.append(str(rid))

        record_type = record.get("record_type")
        source_dataset = record.get("source_dataset")
        record_type_counts[str(record_type)] += 1
        source_dataset_counts[str(source_dataset)] += 1

        if record_type not in ALLOWED_COMBINED_RECORD_TYPES:
            v.fail(f"{rid or index}: unexpected record_type {record_type!r}")

        if source_dataset not in ALLOWED_SOURCE_DATASETS:
            v.fail(f"{rid or index}: unexpected source_dataset {source_dataset!r}")

        if record_type == "gpt3_transcript":
            if not str(record.get("text", "")).strip():
                gpt3_text_empty += 1

        if record_type == "claude_qa_response":
            claude_response_count += 1
            qa_pairs = record.get("qa_pairs")
            if not isinstance(qa_pairs, list):
                v.fail(f"{rid or index}: qa_pairs is not a list")
                continue
            claude_qa_pair_count += len(qa_pairs)
            for pair_index, pair in enumerate(qa_pairs, start=1):
                if not isinstance(pair, dict):
                    empty_qa_fields.append(f"{rid}: pair {pair_index} not object")
                    continue
                if not str(pair.get("question", "")).strip():
                    empty_qa_fields.append(f"{rid}: pair {pair_index} empty question")
                if not str(pair.get("answer", "")).strip():
                    empty_qa_fields.append(f"{rid}: pair {pair_index} empty answer")

    v.check(
        len(record_ids) == len(set(record_ids)),
        "combined record_id values are unique",
        "combined record_id values contain duplicates",
    )

    v.check(
        gpt3_text_empty == 0,
        "all combined GPT-3 transcript records have non-empty text",
        f"{gpt3_text_empty} combined GPT-3 transcript records have empty text",
    )

    v.check(
        not empty_qa_fields,
        "all combined Claude Q/A pairs have non-empty question and answer fields",
        "combined Claude Q/A problems: " + "; ".join(empty_qa_fields[:10]),
    )

    if len(empty_qa_fields) > 10:
        v.warn(f"{len(empty_qa_fields) - 10} additional Q/A field problems omitted from summary")

    expected_rt = manifest_entry.get("record_type_counts")
    if isinstance(expected_rt, dict):
        v.check(
            dict(sorted(record_type_counts.items())) == expected_rt,
            "combined record_type_counts match manifest",
            f"combined record_type_counts mismatch: actual {dict(sorted(record_type_counts.items()))}, manifest {expected_rt}",
        )

    expected_source = manifest_entry.get("source_dataset_counts")
    if isinstance(expected_source, dict):
        v.check(
            dict(sorted(source_dataset_counts.items())) == expected_source,
            "combined source_dataset_counts match manifest",
            f"combined source_dataset_counts mismatch: actual {dict(sorted(source_dataset_counts.items()))}, manifest {expected_source}",
        )

    expected_qa = manifest_entry.get("claude_qa_pair_count")
    if expected_qa is not None:
        v.check(
            claude_qa_pair_count == expected_qa,
            f"combined Claude Q/A pair count matches manifest ({claude_qa_pair_count})",
            f"combined Claude Q/A pair count mismatch: actual {claude_qa_pair_count}, manifest {expected_qa}",
        )


def validate_jsonl_parity(v: Validator, loaded: Dict[str, Any]) -> None:
    combined = loaded.get("combined_leilan_dataset.json")
    combined_jsonl = loaded.get("combined_leilan_dataset_records.jsonl")

    if isinstance(combined, dict) and isinstance(combined_jsonl, list):
        records = combined.get("records", [])
        if isinstance(records, list):
            v.check(
                len(records) == len(combined_jsonl),
                "combined JSONL line count matches combined JSON records",
                f"combined JSONL line count mismatch: JSON has {len(records)}, JSONL has {len(combined_jsonl)}",
            )
            v.check(
                records == combined_jsonl,
                "combined JSONL records exactly match combined JSON records",
                "combined JSONL records do not exactly match combined JSON records",
            )

    gpt3 = loaded.get("full_leilan_gpt3_dataset_normalized.json")
    gpt3_jsonl = loaded.get("full_leilan_gpt3_dataset_normalized.jsonl")

    if isinstance(gpt3, dict) and isinstance(gpt3_jsonl, list):
        records = gpt3.get("records", [])
        if isinstance(records, list):
            v.check(
                len(records) == len(gpt3_jsonl),
                "GPT-3 normalized JSONL line count matches JSON records",
                f"GPT-3 normalized JSONL line count mismatch: JSON has {len(records)}, JSONL has {len(gpt3_jsonl)}",
            )
            v.check(
                records == gpt3_jsonl,
                "GPT-3 normalized JSONL records exactly match JSON records",
                "GPT-3 normalized JSONL records do not exactly match JSON records",
            )


def validate_gpt3_normalized(v: Validator, loaded: Dict[str, Any], files: Dict[str, Dict[str, Any]]) -> None:
    path = "full_leilan_gpt3_dataset_normalized.json"
    data = loaded.get(path)
    if not isinstance(data, dict):
        v.fail(f"{path} is not loaded as a JSON object")
        return

    records = data.get("records", [])
    if not isinstance(records, list):
        v.fail(f"{path}: records is not a list")
        return

    expected_count = files.get(path, {}).get("record_count")
    if expected_count is not None:
        v.check(
            len(records) == expected_count,
            f"GPT-3 normalized record count matches manifest ({len(records)})",
            f"GPT-3 normalized record count mismatch: actual {len(records)}, manifest {expected_count}",
        )

    ids = [str(r.get("record_id")) for r in records if isinstance(r, dict) and r.get("record_id")]
    v.check(
        len(ids) == len(set(ids)),
        "GPT-3 normalized record_id values are unique",
        "GPT-3 normalized record_id values contain duplicates",
    )

    empty_text = [
        r.get("record_id", f"index_{i}")
        for i, r in enumerate(records)
        if isinstance(r, dict) and not str(r.get("text", "")).strip()
    ]
    v.check(
        not empty_text,
        "all GPT-3 normalized records have non-empty text",
        "GPT-3 normalized records with empty text: " + ", ".join(map(str, empty_text[:10])),
    )


def validate_claude(v: Validator, loaded: Dict[str, Any], files: Dict[str, Dict[str, Any]]) -> None:
    path = "full_leilan_claude_dataset.json"
    data = loaded.get(path)
    if not isinstance(data, dict):
        v.fail(f"{path} is not loaded as a JSON object")
        return

    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        v.fail(f"{path}: transmissions is not a list")
        return

    response_ids = []
    response_count = 0
    qa_pair_count = 0
    empty_qa_fields = []

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            v.fail(f"{path}: transmission is not an object")
            continue
        responses = transmission.get("responses", [])
        if not isinstance(responses, list):
            v.fail(f"T{transmission.get('transmission_id')}: responses is not a list")
            continue
        for response in responses:
            if not isinstance(response, dict):
                v.fail(f"T{transmission.get('transmission_id')}: response is not an object")
                continue
            response_count += 1
            rid = response.get("response_id")
            if rid:
                response_ids.append(str(rid))
            qa_pairs = response.get("qa_pairs", [])
            if not isinstance(qa_pairs, list):
                v.fail(f"{rid}: qa_pairs is not a list")
                continue
            qa_pair_count += len(qa_pairs)
            for pair_index, pair in enumerate(qa_pairs, start=1):
                if not isinstance(pair, dict):
                    empty_qa_fields.append(f"{rid}: pair {pair_index} not object")
                    continue
                if not str(pair.get("question", "")).strip():
                    empty_qa_fields.append(f"{rid}: pair {pair_index} empty question")
                if not str(pair.get("answer", "")).strip():
                    empty_qa_fields.append(f"{rid}: pair {pair_index} empty answer")

    manifest_entry = files.get(path, {})

    if manifest_entry.get("transmission_count") is not None:
        v.check(
            len(transmissions) == manifest_entry["transmission_count"],
            f"Claude transmission count matches manifest ({len(transmissions)})",
            f"Claude transmission count mismatch: actual {len(transmissions)}, manifest {manifest_entry['transmission_count']}",
        )

    if manifest_entry.get("response_count") is not None:
        v.check(
            response_count == manifest_entry["response_count"],
            f"Claude response count matches manifest ({response_count})",
            f"Claude response count mismatch: actual {response_count}, manifest {manifest_entry['response_count']}",
        )

    if manifest_entry.get("qa_pair_count") is not None:
        v.check(
            qa_pair_count == manifest_entry["qa_pair_count"],
            f"Claude Q/A pair count matches manifest ({qa_pair_count})",
            f"Claude Q/A pair count mismatch: actual {qa_pair_count}, manifest {manifest_entry['qa_pair_count']}",
        )

    v.check(
        len(response_ids) == len(set(response_ids)),
        "Claude response_id values are unique",
        "Claude response_id values contain duplicates",
    )

    v.check(
        not empty_qa_fields,
        "all Claude source Q/A pairs have non-empty question and answer fields",
        "Claude source Q/A problems: " + "; ".join(empty_qa_fields[:10]),
    )


def validate_passages(v: Validator, loaded: Dict[str, Any], files: Dict[str, Dict[str, Any]]) -> None:
    path = "leilan_gpt3_passages.json"
    data = loaded.get(path)
    if not isinstance(data, list):
        v.fail(f"{path} is not a JSON array")
        return

    manifest_entry = files.get(path, {})
    expected_count = manifest_entry.get("passage_count")
    if expected_count is not None:
        v.check(
            len(data) == expected_count,
            f"GPT-3 passage count matches manifest ({len(data)})",
            f"GPT-3 passage count mismatch: actual {len(data)}, manifest {expected_count}",
        )

    ids = [item.get("id") for item in data if isinstance(item, dict)]
    v.check(
        len(ids) == len(set(ids)),
        "GPT-3 passage IDs are unique",
        "GPT-3 passage IDs contain duplicates",
    )

    if ids and all(isinstance(i, int) for i in ids):
        expected_ids = list(range(1, len(data) + 1))
        v.check(
            ids == expected_ids,
            "GPT-3 passage IDs are sequential and 1-based",
            "GPT-3 passage IDs are not sequential and 1-based",
        )

    empty_text = [
        item.get("id", f"index_{i}")
        for i, item in enumerate(data)
        if isinstance(item, dict) and not str(item.get("text", "")).strip()
    ]
    v.check(
        not empty_text,
        "all GPT-3 passages have non-empty text",
        "GPT-3 passages with empty text: " + ", ".join(map(str, empty_text[:10])),
    )


def main() -> int:
    print("\nLeilan dataset validation")
    print("-------------------------")

    v = Validator()

    files = validate_manifest_and_hashes(v)
    loaded = validate_json_parsing(v, files)

    validate_combined(v, loaded, files)
    validate_jsonl_parity(v, loaded)
    validate_gpt3_normalized(v, loaded, files)
    validate_claude(v, loaded, files)
    validate_passages(v, loaded, files)

    print("\nSummary")
    print("-------")
    print(f"Errors:   {len(v.errors)}")
    print(f"Warnings: {len(v.warnings)}")

    if v.errors:
        print("\nValidation failed.")
        return 1

    print("\nValidation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
