#!/usr/bin/env python3
"""
build_combined_leilan_dataset_from_normalized.py

Build combined_leilan_dataset.json from:

    full_leilan_gpt3_dataset_normalized.json
    full_leilan_claude_dataset.json

This version uses the normalized GPT-3 derivative rather than the older raw
GPT-3 source file.

Outputs:
    combined_leilan_dataset.json
    combined_leilan_dataset_build_report.json
    combined_leilan_dataset_records.jsonl

Run:
    python3 build_combined_leilan_dataset_from_normalized.py

No external packages required.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


DEFAULT_GPT3_NORMALIZED = "full_leilan_gpt3_dataset_normalized.json"
DEFAULT_CLAUDE = "full_leilan_claude_dataset.json"
DEFAULT_OUTPUT = "combined_leilan_dataset.json"
DEFAULT_REPORT = "combined_leilan_dataset_build_report.json"
DEFAULT_JSONL = "combined_leilan_dataset_records.jsonl"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: Any, *, indent: int | None = 2) -> None:
    path = path.resolve()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if indent is None:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(data, f, ensure_ascii=False, indent=indent)
                f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_jsonl_atomic(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    path = path.resolve()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def normalize_claude_response(
    transmission: Dict[str, Any],
    response: Dict[str, Any],
    response_index: int,
) -> Dict[str, Any]:
    transmission_id = str(transmission.get("transmission_id", ""))
    response_id = response.get("response_id")
    if not response_id:
        response_id = f"claude_{transmission_id}_{response_index:03d}"

    return {
        "record_id": response_id,
        "record_type": "claude_qa_response",
        "source_dataset": "claude_family",
        "include_in_training": response.get("include_in_training", True),

        "transmission_id": transmission_id,
        "transmission_title": transmission.get("title"),
        "transmission_slug": transmission.get("slug"),
        "date_first": transmission.get("date_first"),
        "dates": transmission.get("dates", []),
        "date_published": transmission.get("date_published"),
        "substack_url": transmission.get("substack_url"),
        "substack_url_source": transmission.get("substack_url_source"),
        "generation": transmission.get("generation"),
        "source_note": transmission.get("source_note"),
        "themes": transmission.get("themes", []),

        "model": response.get("model"),
        "model_display": response.get("model_display"),
        "model_family": response.get("model_family"),
        "model_notes": response.get("model_notes"),
        "response_variant_index_for_model": response.get("response_variant_index_for_model"),

        "source_directory": response.get("source_directory"),
        "source_file": response.get("source_file"),
        "source_filename": response.get("source_filename"),
        "source_title": response.get("source_title"),
        "source_date": response.get("source_date"),
        "metadata_model_label": response.get("metadata_model_label"),
        "metadata_query": response.get("metadata_query"),
        "content_sha256": response.get("content_sha256"),

        "qa_pair_count": len(response.get("qa_pairs", [])),
        "qa_pairs": response.get("qa_pairs", []),

        "parse_warnings": response.get("parse_warnings", []),
        "review_status": response.get("review_status", {}),
        "transmission_build_warnings": transmission.get("build_warnings", []),

        "technical_notes": transmission.get("technical_notes", ""),
        "curator_notes": transmission.get("curator_notes", ""),
    }


def build_combined(
    gpt3_normalized: Dict[str, Any],
    claude_data: Dict[str, Any],
    *,
    gpt3_source_file: str,
    claude_source_file: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    created = now_utc_iso()
    warnings: List[str] = []
    records: List[Dict[str, Any]] = []

    # GPT-3 normalized records are already in the flat target style.
    gpt3_records = gpt3_normalized.get("records", [])
    if not isinstance(gpt3_records, list):
        warnings.append("GPT-3 normalized dataset has no top-level records list; no GPT-3 records added.")
        gpt3_records = []

    for idx, record in enumerate(gpt3_records):
        if not isinstance(record, dict):
            warnings.append(f"Skipping GPT-3 normalized record at index {idx}: not a dict.")
            continue
        copied = dict(record)
        copied.setdefault("record_type", "gpt3_transcript")
        copied.setdefault("source_dataset", "gpt3")
        copied.setdefault("include_in_training", True)
        records.append(copied)

    claude_transmissions = claude_data.get("transmissions", [])
    if not isinstance(claude_transmissions, list):
        warnings.append("Claude dataset has no top-level transmissions list; no Claude records added.")
        claude_transmissions = []

    for t_index, transmission in enumerate(claude_transmissions):
        if not isinstance(transmission, dict):
            warnings.append(f"Skipping Claude transmission at index {t_index}: not a dict.")
            continue
        responses = transmission.get("responses", [])
        if not isinstance(responses, list):
            warnings.append(
                f"Skipping Claude transmission {transmission.get('transmission_id')}: responses is not a list."
            )
            continue
        for r_index, response in enumerate(responses):
            if not isinstance(response, dict):
                warnings.append(
                    f"Skipping response {r_index} in Claude transmission {transmission.get('transmission_id')}: not a dict."
                )
                continue
            records.append(normalize_claude_response(transmission, response, r_index))

    # Ensure record_id uniqueness.
    seen: Counter[str] = Counter()
    duplicate_record_ids: List[str] = []
    for record in records:
        base = str(record.get("record_id") or "record")
        seen[base] += 1
        if seen[base] > 1:
            duplicate_record_ids.append(base)
            record["record_id"] = f"{base}__duplicate_{seen[base]}"

    if duplicate_record_ids:
        warnings.append(
            f"Resolved {len(duplicate_record_ids)} duplicate record_id collision(s) by suffixing."
        )

    record_type_counts = Counter(str(r.get("record_type") or "(missing)") for r in records)
    source_dataset_counts = Counter(str(r.get("source_dataset") or "(missing)") for r in records)
    model_counts = Counter(str(r.get("model") or "(missing)") for r in records)
    include_counts = Counter(str(r.get("include_in_training", True)) for r in records)

    claude_qa_pair_count = sum(
        len(r.get("qa_pairs", []))
        for r in records
        if r.get("record_type") == "claude_qa_response"
    )
    gpt3_text_count = sum(
        1 for r in records
        if r.get("record_type") == "gpt3_transcript" and str(r.get("text", "")).strip()
    )

    combined: Dict[str, Any] = {
        "schema_version": "1.0",
        "corpus_id": "leilan_combined",
        "created_utc": created,
        "description": (
            "Combined Leilan corpus aggregating normalized GPT-3 transcript-style "
            "generations and curated Claude-family transmission Q/A responses."
        ),
        "notes": [
            "This file aggregates the normalized GPT-3 Leilan dataset and the curated Claude-family Leilan dataset.",
            "Records are flat and tagged with source_dataset and record_type for easy filtering.",
            "GPT-3 records are transcript-style generated texts in the text field.",
            "Claude-family records are model responses containing ordered qa_pairs.",
            "Training pipelines should normally skip records where include_in_training is false.",
            "Parser warnings, review metadata, and curator notes are retained as provenance where present.",
        ],
        "source_datasets": [
            {
                "dataset_id": "gpt3",
                "source_file": gpt3_source_file,
                "source_shape": "normalized records list",
                "record_type": "gpt3_transcript",
            },
            {
                "dataset_id": "claude_family",
                "source_file": claude_source_file,
                "source_shape": "transmissions list containing model responses and qa_pairs",
                "record_type": "claude_qa_response",
            },
        ],
        "corpus_info": {
            "record_count": len(records),
            "record_type_counts": dict(sorted(record_type_counts.items())),
            "source_dataset_counts": dict(sorted(source_dataset_counts.items())),
            "model_count": len(model_counts),
            "model_counts": dict(sorted(model_counts.items())),
            "include_in_training_counts": dict(sorted(include_counts.items())),
            "gpt3_transcript_count": record_type_counts.get("gpt3_transcript", 0),
            "gpt3_nonempty_text_record_count": gpt3_text_count,
            "claude_transmission_count": len(claude_transmissions),
            "claude_response_count": record_type_counts.get("claude_qa_response", 0),
            "claude_qa_pair_count": claude_qa_pair_count,
        },
        "training_extraction_guidance": {
            "gpt3_transcripts": (
                "For GPT-3 transcript-style training examples, select records where "
                "record_type == 'gpt3_transcript'. The generated transcript is in the text field."
            ),
            "claude_qa_pairs": (
                "For Q/A-style training examples, select records where record_type == "
                "'claude_qa_response', then iterate over qa_pairs in turn_index order. "
                "Each pair has question and answer fields."
            ),
            "filtering": (
                "Use include_in_training, review_status, warnings, parse_warnings, and "
                "transmission_build_warnings according to downstream training/evaluation needs."
            ),
        },
        "prompt_libraries": {
            "gpt3": gpt3_normalized.get("prompt_libraries", {}),
        },
        "records": records,
    }

    report: Dict[str, Any] = {
        "created_utc": created,
        "source_files": {
            "gpt3_normalized": gpt3_source_file,
            "claude_family": claude_source_file,
        },
        "output_counts": combined["corpus_info"],
        "warnings": warnings,
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "source_dataset_counts": dict(sorted(source_dataset_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
        "include_in_training_counts": dict(sorted(include_counts.items())),
    }

    return combined, report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build combined_leilan_dataset.json from normalized GPT-3 and curated Claude-family datasets."
    )
    parser.add_argument("--gpt3", default=DEFAULT_GPT3_NORMALIZED, help=f"Normalized GPT-3 dataset JSON. Default: {DEFAULT_GPT3_NORMALIZED}")
    parser.add_argument("--claude", default=DEFAULT_CLAUDE, help=f"Claude-family dataset JSON. Default: {DEFAULT_CLAUDE}")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Combined output JSON. Default: {DEFAULT_OUTPUT}")
    parser.add_argument("--report", default=DEFAULT_REPORT, help=f"Build report JSON. Default: {DEFAULT_REPORT}")
    parser.add_argument("--jsonl", default=DEFAULT_JSONL, help=f"Flat combined records JSONL. Default: {DEFAULT_JSONL}")
    parser.add_argument("--compact", action="store_true", help="Write compact combined JSON instead of pretty-printed JSON.")
    parser.add_argument("--no-jsonl", action="store_true", help="Do not write combined JSONL.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    gpt3_path = Path(args.gpt3)
    claude_path = Path(args.claude)
    output_path = Path(args.output)
    report_path = Path(args.report)
    jsonl_path = Path(args.jsonl)

    if not gpt3_path.exists():
        print(f"ERROR: normalized GPT-3 dataset not found: {gpt3_path}")
        return 1
    if not claude_path.exists():
        print(f"ERROR: Claude-family dataset not found: {claude_path}")
        return 1

    gpt3 = load_json(gpt3_path)
    claude = load_json(claude_path)

    if not isinstance(gpt3, dict):
        print("ERROR: normalized GPT-3 JSON root is not an object.")
        return 1
    if not isinstance(claude, dict):
        print("ERROR: Claude-family JSON root is not an object.")
        return 1

    combined, report = build_combined(
        gpt3,
        claude,
        gpt3_source_file=str(gpt3_path),
        claude_source_file=str(claude_path),
    )

    write_json_atomic(output_path, combined, indent=None if args.compact else 2)
    write_json_atomic(report_path, report, indent=2)
    if not args.no_jsonl:
        write_jsonl_atomic(jsonl_path, combined["records"])

    info = combined["corpus_info"]

    print("\nCombined Leilan dataset build")
    print("-----------------------------")
    print(f"Normalized GPT-3 source: {gpt3_path}")
    print(f"Claude-family source:    {claude_path}")
    print(f"Output JSON:             {output_path}")
    print(f"Build report:            {report_path}")
    if not args.no_jsonl:
        print(f"Records JSONL:           {jsonl_path}")

    print("\nCounts:")
    print(f"  total records:             {info['record_count']}")
    print(f"  GPT-3 transcript records:  {info['gpt3_transcript_count']}")
    print(f"  Claude transmissions:      {info['claude_transmission_count']}")
    print(f"  Claude response records:   {info['claude_response_count']}")
    print(f"  Claude Q/A pairs:          {info['claude_qa_pair_count']}")
    print(f"  models:                    {info['model_count']}")

    if report["warnings"]:
        print("\nWarnings:")
        for warning in report["warnings"]:
            print(f"  - {warning}")
    else:
        print("\nWarnings: none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
