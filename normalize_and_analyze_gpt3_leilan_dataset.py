#!/usr/bin/env python3
"""
normalize_and_analyze_gpt3_leilan_dataset.py

Normalize and health-check the older GPT-3 Leilan dataset without modifying
the original source file.

Input default:
    full_leilan_gpt3_dataset.json

Outputs default:
    full_leilan_gpt3_dataset_normalized.json
    full_leilan_gpt3_dataset_health_report.txt
    full_leilan_gpt3_dataset_health_report.json
    full_leilan_gpt3_dataset_normalized.jsonl

Run:
    python3 normalize_and_analyze_gpt3_leilan_dataset.py

No external packages required.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_INPUT = "full_leilan_gpt3_dataset.json"
DEFAULT_OUTPUT = "full_leilan_gpt3_dataset_normalized.json"
DEFAULT_TEXT_REPORT = "full_leilan_gpt3_dataset_health_report.txt"
DEFAULT_JSON_REPORT = "full_leilan_gpt3_dataset_health_report.json"
DEFAULT_JSONL = "full_leilan_gpt3_dataset_normalized.jsonl"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: Any, *, indent: Optional[int] = 2) -> None:
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


def write_text_atomic(path: Path, text: str) -> None:
    path = path.resolve()
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
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


def normalize_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def safe_snippet(text: Any, limit: int = 180) -> str:
    clean = normalize_space(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def slugify_key(text: Any) -> str:
    raw = str(text or "").strip()
    raw = raw.replace(" ", "_")
    raw = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw or "unknown"


def clean_record_id(value: Any, *, fallback_index: int) -> str:
    if isinstance(value, int):
        return f"gpt3_transcript_{value:04d}"
    text = str(value).strip()
    if text.isdigit():
        return f"gpt3_transcript_{int(text):04d}"
    if text:
        return f"gpt3_transcript_{slugify_key(text)}"
    return f"gpt3_transcript_index_{fallback_index:04d}"


def model_from_engine(engine: Any) -> str:
    engine = str(engine or "").strip()
    if not engine:
        return "gpt-3-unknown-engine"
    if engine.startswith("gpt-"):
        return engine
    return f"gpt-3-{engine}"


def text_length_bucket(length: int) -> str:
    if length == 0:
        return "empty"
    if length < 500:
        return "<500"
    if length < 2000:
        return "500-1999"
    if length < 5000:
        return "2000-4999"
    if length < 10000:
        return "5000-9999"
    if length < 20000:
        return "10000-19999"
    return "20000+"


def percentile(values: List[int], pct: float) -> Optional[float]:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * pct
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return float(xs[int(pos)])
    weight = pos - lower
    return xs[lower] * (1 - weight) + xs[upper] * weight


def severity_rank(severity: str) -> int:
    return {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
        "INFO": 4,
    }.get(severity, 9)


# ---------------------------------------------------------------------------
# Prompt library helpers
# ---------------------------------------------------------------------------

def flatten_prompt_libraries(prompts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return prompt collections keyed by library name.

    Expected source shape:
        prompts = {
          "GPT3 prompts": {"podcast": "...", "notes": [...]},
          "GPT4 prompts": {...},
          "README": "..."
        }
    """
    libraries: Dict[str, Dict[str, Any]] = {}

    for library_name, library in prompts.items():
        if isinstance(library, dict):
            libraries[library_name] = library
        else:
            libraries[library_name] = {"__value__": library}

    return libraries


def prompt_key_exists(prompts: Dict[str, Any], library_name: str, key: Any) -> bool:
    if key is None or key == "":
        return False
    library = prompts.get(library_name)
    if not isinstance(library, dict):
        return False
    return str(key) in library


def get_prompt_text(prompts: Dict[str, Any], library_name: str, key: Any) -> Optional[str]:
    if key is None or key == "":
        return None
    library = prompts.get(library_name)
    if not isinstance(library, dict):
        return None
    value = library.get(str(key))
    if isinstance(value, str):
        return value
    return None


# ---------------------------------------------------------------------------
# Issue reporting
# ---------------------------------------------------------------------------

def add_issue(
    issues: List[Dict[str, Any]],
    *,
    severity: str,
    code: str,
    message: str,
    record_id: Optional[str] = None,
    transcript_id: Any = None,
    index: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "record_id": record_id,
            "transcript_id": transcript_id,
            "index": index,
            "details": details or {},
        }
    )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_transcript(
    item: Dict[str, Any],
    *,
    index: int,
    prompts: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    transcript_id = item.get("transcript ID")
    record_id = clean_record_id(transcript_id, fallback_index=index)

    engine = item.get("engine")
    model = model_from_engine(engine)

    gpt3_prompt_key = item.get("GPT3 prompt")
    gpt4_prompt_key = item.get("GPT4 prompt")
    text = item.get("text", "")

    include_in_training = True
    record_warnings: List[str] = []

    if transcript_id is None or transcript_id == "":
        include_in_training = False
        record_warnings.append("missing_transcript_id")
        add_issue(
            issues,
            severity="HIGH",
            code="missing_transcript_id",
            message="Transcript has no transcript ID.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
        )

    if not isinstance(text, str):
        include_in_training = False
        record_warnings.append("text_is_not_string")
        add_issue(
            issues,
            severity="HIGH",
            code="text_is_not_string",
            message="Transcript text field is not a string.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
            details={"text_type": type(text).__name__},
        )
        text = "" if text is None else str(text)

    if not text.strip():
        include_in_training = False
        record_warnings.append("empty_text")
        add_issue(
            issues,
            severity="HIGH",
            code="empty_text",
            message="Transcript has empty generated text.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
        )

    if engine in (None, ""):
        record_warnings.append("missing_engine")
        add_issue(
            issues,
            severity="MEDIUM",
            code="missing_engine",
            message="Transcript has no engine value.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
        )

    temp = item.get("temperature")
    if temp is None:
        record_warnings.append("missing_temperature")
        add_issue(
            issues,
            severity="LOW",
            code="missing_temperature",
            message="Transcript has no temperature value.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
        )
    elif not isinstance(temp, (int, float)):
        record_warnings.append("temperature_not_numeric")
        add_issue(
            issues,
            severity="MEDIUM",
            code="temperature_not_numeric",
            message="Transcript temperature is not numeric.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
            details={"temperature": temp, "temperature_type": type(temp).__name__},
        )

    if gpt3_prompt_key in (None, ""):
        record_warnings.append("missing_gpt3_prompt_key")
        add_issue(
            issues,
            severity="MEDIUM",
            code="missing_gpt3_prompt_key",
            message="Transcript has no GPT3 prompt key.",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
        )
    elif not prompt_key_exists(prompts, "GPT3 prompts", gpt3_prompt_key):
        record_warnings.append("gpt3_prompt_key_not_found")
        add_issue(
            issues,
            severity="MEDIUM",
            code="gpt3_prompt_key_not_found",
            message=f"GPT3 prompt key {gpt3_prompt_key!r} is not present in prompts['GPT3 prompts'].",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
            details={"gpt3_prompt_key": gpt3_prompt_key},
        )

    if gpt4_prompt_key not in (None, "") and not prompt_key_exists(prompts, "GPT4 prompts", gpt4_prompt_key):
        record_warnings.append("gpt4_prompt_key_not_found")
        add_issue(
            issues,
            severity="LOW",
            code="gpt4_prompt_key_not_found",
            message=f"GPT4 prompt key {gpt4_prompt_key!r} is not present in prompts['GPT4 prompts'].",
            record_id=record_id,
            transcript_id=transcript_id,
            index=index,
            details={"gpt4_prompt_key": gpt4_prompt_key},
        )

    notes = item.get("notes", "")
    if isinstance(notes, list):
        notes_normalized = notes
    elif notes in (None, ""):
        notes_normalized = []
    else:
        notes_normalized = [str(notes)]

    gpt3_prompt_text = get_prompt_text(prompts, "GPT3 prompts", gpt3_prompt_key)
    gpt4_prompt_text = get_prompt_text(prompts, "GPT4 prompts", gpt4_prompt_key)

    return {
        "record_id": record_id,
        "record_type": "gpt3_transcript",
        "source_dataset": "gpt3",
        "include_in_training": include_in_training,

        "transcript_id": transcript_id,
        "source_index": index,

        "model": model,
        "model_family": "GPT-3",
        "engine": engine,
        "temperature": temp,

        "prompt_refs": {
            "gpt3_prompt_key": gpt3_prompt_key,
            "gpt4_prompt_key": gpt4_prompt_key,
        },
        "prompt_text": {
            "gpt3_prompt": gpt3_prompt_text,
            "gpt4_prompt": gpt4_prompt_text,
        },

        "text": text,
        "text_char_count": len(text),
        "text_word_count_estimate": len(re.findall(r"\S+", text)),

        "notes": notes_normalized,
        "warnings": record_warnings,
    }


def build_normalized_dataset(source: Dict[str, Any], *, source_file: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    created = now_utc_iso()

    transcripts = source.get("transcripts", [])
    prompts = source.get("prompts", {})

    if not isinstance(transcripts, list):
        add_issue(
            issues,
            severity="CRITICAL",
            code="transcripts_not_list",
            message="Top-level transcripts field is not a list.",
        )
        transcripts = []

    if not isinstance(prompts, dict):
        add_issue(
            issues,
            severity="HIGH",
            code="prompts_not_dict",
            message="Top-level prompts field is not a dictionary.",
        )
        prompts = {}

    records: List[Dict[str, Any]] = []
    for index, item in enumerate(transcripts):
        if not isinstance(item, dict):
            add_issue(
                issues,
                severity="HIGH",
                code="transcript_item_not_dict",
                message="Transcript item is not a dictionary.",
                index=index,
                details={"item_type": type(item).__name__},
            )
            continue
        records.append(normalize_transcript(item, index=index, prompts=prompts, issues=issues))

    # Post-normalization checks.
    id_counter = Counter(str(r.get("transcript_id")) for r in records)
    record_id_counter = Counter(str(r.get("record_id")) for r in records)

    for transcript_id, count in id_counter.items():
        if transcript_id and transcript_id != "None" and count > 1:
            for record in records:
                if str(record.get("transcript_id")) == transcript_id:
                    record.setdefault("warnings", []).append("duplicate_transcript_id")
            add_issue(
                issues,
                severity="HIGH",
                code="duplicate_transcript_id",
                message=f"Transcript ID {transcript_id!r} appears {count} times.",
                transcript_id=transcript_id,
                details={"count": count},
            )

    for record_id, count in record_id_counter.items():
        if record_id and count > 1:
            add_issue(
                issues,
                severity="HIGH",
                code="duplicate_record_id",
                message=f"Normalized record_id {record_id!r} appears {count} times.",
                record_id=record_id,
                details={"count": count},
            )

    # Ensure record_id uniqueness by suffixing only after reporting.
    seen: Counter[str] = Counter()
    for record in records:
        base = str(record.get("record_id") or "gpt3_transcript_unknown")
        seen[base] += 1
        if seen[base] > 1:
            record["record_id"] = f"{base}__duplicate_{seen[base]}"
            record.setdefault("warnings", []).append("record_id_suffix_added_for_uniqueness")

    engine_counts = Counter(str(r.get("engine") or "(missing)") for r in records)
    model_counts = Counter(str(r.get("model") or "(missing)") for r in records)
    temp_counts = Counter(str(r.get("temperature")) for r in records)
    gpt3_prompt_counts = Counter(str(r.get("prompt_refs", {}).get("gpt3_prompt_key") or "(missing)") for r in records)
    gpt4_prompt_counts = Counter(str(r.get("prompt_refs", {}).get("gpt4_prompt_key") or "(missing)") for r in records)
    include_counts = Counter(str(r.get("include_in_training", True)) for r in records)
    warning_counts = Counter(w for r in records for w in r.get("warnings", []))

    char_lengths = [int(r.get("text_char_count") or 0) for r in records]
    word_lengths = [int(r.get("text_word_count_estimate") or 0) for r in records]
    text_bucket_counts = Counter(text_length_bucket(length) for length in char_lengths)

    prompt_libraries = flatten_prompt_libraries(prompts)

    # Prompt library analysis.
    prompt_library_summary: Dict[str, Any] = {}
    for library_name, library in prompt_libraries.items():
        keys = list(library.keys())
        non_string_values = [k for k, v in library.items() if not isinstance(v, str) and k != "notes"]
        prompt_library_summary[library_name] = {
            "key_count": len(keys),
            "keys": keys,
            "non_string_value_keys": non_string_values,
        }

    severity_counts = Counter(issue["severity"] for issue in issues)
    issue_code_counts = Counter(issue["code"] for issue in issues)

    normalized: Dict[str, Any] = {
        "schema_version": "1.0",
        "dataset_id": "leilan_gpt3_normalized",
        "source_dataset": "gpt3",
        "created_utc": created,
        "source_file": source_file,
        "description": (
            "Normalized GPT-3 Leilan transcript dataset. The original source file is preserved; "
            "this derivative converts legacy keys to a consistent record structure."
        ),
        "notes": [
            "Each record corresponds to one GPT-3 transcript-style generation.",
            "The generated transcript text is in the text field.",
            "prompt_refs stores prompt-library keys; prompt_text embeds the referenced prompt text when available.",
            "include_in_training is false only for records with serious structural problems such as missing/empty text.",
            "warnings are retained at record level for downstream filtering and provenance.",
        ],
        "corpus_info": {
            "record_count": len(records),
            "include_in_training_counts": dict(sorted(include_counts.items())),
            "model_count": len(model_counts),
            "model_counts": dict(sorted(model_counts.items())),
            "engine_counts": dict(sorted(engine_counts.items())),
            "temperature_counts": dict(sorted(temp_counts.items())),
            "gpt3_prompt_key_counts": dict(sorted(gpt3_prompt_counts.items())),
            "gpt4_prompt_key_counts": dict(sorted(gpt4_prompt_counts.items())),
            "text_char_count": {
                "min": min(char_lengths) if char_lengths else 0,
                "max": max(char_lengths) if char_lengths else 0,
                "mean": round(sum(char_lengths) / len(char_lengths), 2) if char_lengths else 0,
                "p50": percentile(char_lengths, 0.50),
                "p90": percentile(char_lengths, 0.90),
            },
            "text_word_count_estimate": {
                "min": min(word_lengths) if word_lengths else 0,
                "max": max(word_lengths) if word_lengths else 0,
                "mean": round(sum(word_lengths) / len(word_lengths), 2) if word_lengths else 0,
                "p50": percentile(word_lengths, 0.50),
                "p90": percentile(word_lengths, 0.90),
            },
            "text_length_bucket_counts": dict(sorted(text_bucket_counts.items())),
            "record_warning_counts": dict(sorted(warning_counts.items())),
            "health_issue_counts": {
                "by_severity": dict(sorted(severity_counts.items())),
                "by_code": dict(sorted(issue_code_counts.items())),
            },
        },
        "prompt_libraries": prompts,
        "prompt_library_summary": prompt_library_summary,
        "records": records,
    }

    report: Dict[str, Any] = {
        "created_utc": created,
        "source_file": source_file,
        "output_dataset_id": normalized["dataset_id"],
        "summary": {
            "records": len(records),
            "issues_total": len(issues),
            "critical": severity_counts.get("CRITICAL", 0),
            "high": severity_counts.get("HIGH", 0),
            "medium": severity_counts.get("MEDIUM", 0),
            "low": severity_counts.get("LOW", 0),
            "info": severity_counts.get("INFO", 0),
        },
        "counts": normalized["corpus_info"],
        "issues": sorted(
            issues,
            key=lambda issue: (
                severity_rank(issue.get("severity", "INFO")),
                issue.get("index") if issue.get("index") is not None else 10**9,
                str(issue.get("code") or ""),
            ),
        ),
    }

    return normalized, report


# ---------------------------------------------------------------------------
# Text report
# ---------------------------------------------------------------------------

def render_text_report(report: Dict[str, Any], normalized: Dict[str, Any], *, max_issues: int = 200) -> str:
    info = normalized["corpus_info"]
    summary = report["summary"]
    lines: List[str] = []

    lines.append("GPT-3 Leilan dataset health / normalization report\n")
    lines.append("==================================================\n\n")
    lines.append(f"Generated: {report['created_utc']}\n")
    lines.append(f"Source file: {report['source_file']}\n")
    lines.append(f"Normalized dataset ID: {report['output_dataset_id']}\n\n")

    lines.append("Dataset counts\n")
    lines.append("--------------\n")
    lines.append(f"Records: {info['record_count']}\n")
    lines.append(f"Models:  {info['model_count']}\n")
    lines.append(f"Include in training counts: {info['include_in_training_counts']}\n\n")

    lines.append("Health summary\n")
    lines.append("--------------\n")
    lines.append(f"Total issues: {summary['issues_total']}\n")
    lines.append(f"- CRITICAL: {summary['critical']}\n")
    lines.append(f"- HIGH:     {summary['high']}\n")
    lines.append(f"- MEDIUM:   {summary['medium']}\n")
    lines.append(f"- LOW:      {summary['low']}\n")
    lines.append(f"- INFO:     {summary['info']}\n\n")

    lines.append("Engine/model counts\n")
    lines.append("-------------------\n")
    lines.append("Engines:\n")
    for key, count in info["engine_counts"].items():
        lines.append(f"- {key}: {count}\n")
    lines.append("\nModels:\n")
    for key, count in info["model_counts"].items():
        lines.append(f"- {key}: {count}\n")
    lines.append("\n")

    lines.append("Prompt key counts\n")
    lines.append("-----------------\n")
    lines.append("GPT-3 prompt keys:\n")
    for key, count in info["gpt3_prompt_key_counts"].items():
        lines.append(f"- {key}: {count}\n")
    lines.append("\nGPT-4 prompt keys:\n")
    for key, count in info["gpt4_prompt_key_counts"].items():
        lines.append(f"- {key}: {count}\n")
    lines.append("\n")

    lines.append("Text length summary\n")
    lines.append("-------------------\n")
    lines.append("Character counts:\n")
    for key, value in info["text_char_count"].items():
        lines.append(f"- {key}: {value}\n")
    lines.append("\nWord count estimate:\n")
    for key, value in info["text_word_count_estimate"].items():
        lines.append(f"- {key}: {value}\n")
    lines.append("\nLength buckets:\n")
    for key, count in info["text_length_bucket_counts"].items():
        lines.append(f"- {key}: {count}\n")
    lines.append("\n")

    lines.append("Record warning counts\n")
    lines.append("---------------------\n")
    warning_counts = info.get("record_warning_counts") or {}
    if warning_counts:
        for key, count in warning_counts.items():
            lines.append(f"- {key}: {count}\n")
    else:
        lines.append("None.\n")
    lines.append("\n")

    lines.append("Issues\n")
    lines.append("------\n")
    issues = report.get("issues", [])
    if not issues:
        lines.append("No health issues found.\n\n")
    else:
        for issue in issues[:max_issues]:
            location = []
            if issue.get("record_id"):
                location.append(str(issue["record_id"]))
            if issue.get("transcript_id") not in (None, ""):
                location.append(f"transcript_id={issue['transcript_id']}")
            if issue.get("index") is not None:
                location.append(f"index={issue['index']}")
            loc_text = " | ".join(location)
            lines.append(f"- [{issue['severity']}] {issue['code']}")
            if loc_text:
                lines.append(f" | {loc_text}")
            lines.append(f"\n  {issue['message']}\n")
        if len(issues) > max_issues:
            lines.append(f"\n... {len(issues) - max_issues} further issues omitted from text report. See JSON report.\n")
        lines.append("\n")

    lines.append("Interpretation\n")
    lines.append("--------------\n")
    lines.append("- CRITICAL/HIGH issues mean the source dataset needs attention before training use.\n")
    lines.append("- MEDIUM usually means missing/odd metadata or a prompt reference that should be checked.\n")
    lines.append("- LOW is generally provenance or convenience metadata.\n")
    lines.append("- The normalized JSON does not alter the original GPT-3 source file.\n")
    lines.append("- For training, use records where include_in_training is true and inspect warnings according to your tolerance.\n")

    return "".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize and health-check the GPT-3 Leilan dataset.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help=f"Input GPT-3 dataset JSON. Default: {DEFAULT_INPUT}")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"Normalized output JSON. Default: {DEFAULT_OUTPUT}")
    parser.add_argument("--text-report", default=DEFAULT_TEXT_REPORT, help=f"Text health report. Default: {DEFAULT_TEXT_REPORT}")
    parser.add_argument("--json-report", default=DEFAULT_JSON_REPORT, help=f"JSON health report. Default: {DEFAULT_JSON_REPORT}")
    parser.add_argument("--jsonl", default=DEFAULT_JSONL, help=f"JSONL output. Default: {DEFAULT_JSONL}")
    parser.add_argument("--compact", action="store_true", help="Write compact normalized JSON instead of pretty-printed JSON.")
    parser.add_argument("--no-jsonl", action="store_true", help="Do not write JSONL output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    text_report_path = Path(args.text_report)
    json_report_path = Path(args.json_report)
    jsonl_path = Path(args.jsonl)

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}")
        return 1

    source = load_json(input_path)
    if not isinstance(source, dict):
        print("ERROR: input JSON root is not an object/dictionary.")
        return 1

    normalized, report = build_normalized_dataset(source, source_file=str(input_path))

    write_json_atomic(output_path, normalized, indent=None if args.compact else 2)
    write_json_atomic(json_report_path, report, indent=2)
    write_text_atomic(text_report_path, render_text_report(report, normalized))

    if not args.no_jsonl:
        write_jsonl_atomic(jsonl_path, normalized["records"])

    summary = report["summary"]

    print("\nGPT-3 Leilan dataset normalization")
    print("----------------------------------")
    print(f"Input:            {input_path}")
    print(f"Normalized JSON:  {output_path}")
    print(f"Text report:      {text_report_path}")
    print(f"JSON report:      {json_report_path}")
    if not args.no_jsonl:
        print(f"JSONL records:    {jsonl_path}")

    print("\nCounts:")
    print(f"  records:        {summary['records']}")
    print(f"  critical:       {summary['critical']}")
    print(f"  high:           {summary['high']}")
    print(f"  medium:         {summary['medium']}")
    print(f"  low:            {summary['low']}")
    print(f"  info:           {summary['info']}")

    if summary["critical"] or summary["high"]:
        print("\nThere are CRITICAL/HIGH issues. Open the text report before using this for training.")
    elif summary["medium"]:
        print("\nNo CRITICAL/HIGH issues. Check MEDIUM items in the text report.")
    else:
        print("\nNo CRITICAL/HIGH/MEDIUM issues found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
