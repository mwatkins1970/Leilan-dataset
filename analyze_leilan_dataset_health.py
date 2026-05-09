#!/usr/bin/env python3
"""
analyze_leilan_dataset_health.py

Thoroughly analyze the curated Leilan JSON dataset and write a human-readable
health report.

Default:

    python3 analyze_leilan_dataset_health.py

Outputs:

    leilan_dataset_health_report.txt
    leilan_dataset_health_report.json

Optional: if build_full_leilan_claude_dataset_v11.py and the Markdown source
folder are present, the script also reparses each response's current .md file
and detects stale warnings, changed source files, and remaining true metadata
mismatches.

No external packages required.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_JSON = "full_leilan_claude_dataset.json"
DEFAULT_SOURCE_ROOT = "post-gpt3_transmissions_by_model"
DEFAULT_BUILDER = "build_full_leilan_claude_dataset_v11.py"
DEFAULT_TEXT_REPORT = "leilan_dataset_health_report.txt"
DEFAULT_JSON_REPORT = "leilan_dataset_health_report.json"

STALE_WARNING = "metadata_model_label_differs_from_source_directory"

MODEL_BY_SOURCE_DIRECTORY = {
    "opus3": "claude-opus-3",
    "opus4": "claude-opus-4",
    "opus4_1": "claude-opus-4.1",
    "opus4_5": "claude-opus-4.5",
    "sonnet3_5": "claude-sonnet-3.5",
    "sonnet4": "claude-sonnet-4",
    "sonnet4_5": "claude-sonnet-4.5",
    "haiku3_5": "claude-haiku-3.5",
    "gpt-4-base": "gpt-4-base",
}

OBSOLETE_SPLIT_IDS = {
    "262a", "262b", "262c",
    "263a", "263b", "263c", "263d",
    "264a", "264b", "264c",
    "265a", "265b",
    "275a", "275b",
    "298a", "298b",
    "E003a", "E003b", "E003c", "E003d",
}

EXPECTED_SPLIT_OR_SPECIAL_IDS = {
    "238a", "238b", "238c",
    "AB001", "E001", "E002", "E003",
}

REQUIRED_TRANSMISSION_FIELDS = [
    "transmission_id", "title", "responses",
]

REQUIRED_RESPONSE_FIELDS = [
    "response_id", "model", "source_directory", "source_file",
    "source_filename", "source_date", "qa_pairs",
]

REQUIRED_QA_FIELDS = [
    "turn_index", "question", "answer",
]


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalise_for_payload(text: str) -> str:
    text = text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def qa_payload_signature(response: Dict[str, Any]) -> str:
    payload = []
    for pair in response.get("qa_pairs", []):
        payload.append(
            {
                "question": normalise_for_payload(pair.get("question", "")),
                "answer": normalise_for_payload(pair.get("answer", "")),
            }
        )
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sort_tid(tid: str) -> Tuple[int, str]:
    tid = str(tid)
    if tid.isdigit():
        return (0, f"{int(tid):06d}")
    return (1, tid)


def short(text: str, n: int = 160) -> str:
    text = normalise_space(str(text or ""))
    return text[: n - 1] + "…" if len(text) > n else text


def load_builder_module(builder_path: Path) -> Optional[Any]:
    if not builder_path.exists():
        return None

    module_name = "leilan_dataset_builder_v11_healthcheck"
    spec = importlib.util.spec_from_file_location(module_name, builder_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def add_issue(
    issues: List[Dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    *,
    transmission_id: Optional[str] = None,
    model: Optional[str] = None,
    source_file: Optional[str] = None,
    response_id: Optional[str] = None,
    turn_index: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    issues.append(
        {
            "severity": severity,
            "code": code,
            "message": message,
            "transmission_id": transmission_id,
            "model": model,
            "source_file": source_file,
            "response_id": response_id,
            "turn_index": turn_index,
            "details": details or {},
        }
    )


def source_path_from_response(response: Dict[str, Any], source_root: Path) -> Path:
    source_file = response.get("source_file", "")
    path = Path(source_file)
    if path.is_absolute():
        return path
    # response source_file normally starts with post-gpt3_transmissions_by_model/...
    return source_root.parent / path


def current_md_parse(
    response: Dict[str, Any],
    source_root: Path,
    builder: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    path = source_path_from_response(response, source_root)
    if not path.exists():
        return None, f"source file not found: {path}"

    try:
        parsed = builder.parse_markdown_file(path, source_root)
        fresh_response = builder.response_from_parsed_file(parsed, include_raw=False)
        return fresh_response, None
    except Exception as exc:  # noqa: BLE001
        return None, repr(exc)


def analyze(data: Dict[str, Any], json_path: Path, source_root: Path, builder: Optional[Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    transmissions = data.get("transmissions", [])
    corpus = data.get("corpus_info", {})

    report: Dict[str, Any] = {
        "created_utc": now_utc_iso(),
        "json_file": str(json_path),
        "source_root": str(source_root),
        "builder_available": builder is not None,
        "summary": {},
        "counts": {},
        "warning_counts": {},
        "status_counts": {},
        "issue_counts": {},
        "issues": issues,
        "samples": {},
    }

    # ------------------------------------------------------------------
    # Basic count checks
    # ------------------------------------------------------------------
    actual_transmission_count = len(transmissions)
    actual_response_count = 0
    actual_qa_count = 0
    actual_model_counts: Counter[str] = Counter()
    actual_source_dir_counts: Counter[str] = Counter()

    for t in transmissions:
        for r in t.get("responses", []):
            actual_response_count += 1
            actual_qa_count += len(r.get("qa_pairs", []))
            if r.get("model"):
                actual_model_counts[r["model"]] += 1
            if r.get("source_directory"):
                actual_source_dir_counts[r["source_directory"]] += 1

    actual_counts = {
        "transmission_count": actual_transmission_count,
        "response_count": actual_response_count,
        "qa_pair_count": actual_qa_count,
        "model_count": len(actual_model_counts),
        "model_counts": dict(sorted(actual_model_counts.items())),
        "source_directory_counts": dict(sorted(actual_source_dir_counts.items())),
    }
    report["counts"]["actual"] = actual_counts

    corpus_counts = {
        "transmission_count": corpus.get("transmission_count"),
        "response_count": corpus.get("response_count"),
        "qa_pair_count": corpus.get("qa_pair_count"),
        "model_count": corpus.get("model_count"),
        "model_counts": corpus.get("model_counts"),
        "source_directory_counts": corpus.get("source_directory_counts"),
    }
    report["counts"]["corpus_info"] = corpus_counts

    for key in ("transmission_count", "response_count", "qa_pair_count", "model_count"):
        if corpus_counts.get(key) is not None and corpus_counts.get(key) != actual_counts.get(key):
            add_issue(
                issues, "HIGH", "corpus_count_mismatch",
                f"corpus_info.{key} is {corpus_counts.get(key)!r}, but actual count is {actual_counts.get(key)!r}.",
                details={"field": key, "corpus_value": corpus_counts.get(key), "actual_value": actual_counts.get(key)},
            )

    # ------------------------------------------------------------------
    # ID-level checks
    # ------------------------------------------------------------------
    tid_counter = Counter(str(t.get("transmission_id", "")) for t in transmissions)
    for tid, count in sorted(tid_counter.items(), key=lambda x: sort_tid(x[0])):
        if not tid:
            add_issue(issues, "CRITICAL", "missing_transmission_id", "A transmission has a missing/empty transmission_id.")
        elif count > 1:
            add_issue(issues, "CRITICAL", "duplicate_transmission_id", f"Transmission ID {tid} appears {count} times.", transmission_id=tid)

    for obsolete_id in sorted(OBSOLETE_SPLIT_IDS, key=sort_tid):
        if tid_counter.get(obsolete_id):
            add_issue(
                issues, "HIGH", "obsolete_split_record_still_present",
                f"Obsolete split transmission {obsolete_id} is still present.",
                transmission_id=obsolete_id,
            )

    nonstandard_ids = []
    for tid in tid_counter:
        if not tid:
            continue
        if tid.isdigit():
            continue
        if tid in EXPECTED_SPLIT_OR_SPECIAL_IDS:
            continue
        if tid in OBSOLETE_SPLIT_IDS:
            continue
        nonstandard_ids.append(tid)
    report["samples"]["nonstandard_ids_not_classed_as_expected"] = sorted(nonstandard_ids, key=sort_tid)

    # ------------------------------------------------------------------
    # Per-transmission/response/Q-A checks
    # ------------------------------------------------------------------
    response_id_counter: Counter[str] = Counter()
    source_file_counter: Counter[str] = Counter()
    global_content_hash_counter: Counter[str] = Counter()
    global_payload_sig_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    pair_warning_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()

    # Keep for within-transmission duplicate checks.
    for t in transmissions:
        tid = str(t.get("transmission_id", ""))

        for field in REQUIRED_TRANSMISSION_FIELDS:
            if field not in t or t.get(field) in (None, ""):
                add_issue(issues, "HIGH", "missing_transmission_field", f"Transmission {tid} is missing required field {field}.", transmission_id=tid, details={"field": field})

        responses = t.get("responses", [])
        if not isinstance(responses, list):
            add_issue(issues, "CRITICAL", "responses_not_list", f"Transmission {tid} responses field is not a list.", transmission_id=tid)
            responses = []
        if not responses:
            add_issue(issues, "HIGH", "transmission_has_no_responses", f"Transmission {tid} has no model responses.", transmission_id=tid)

        t_build_warnings = t.get("build_warnings") or []
        for warning in t_build_warnings:
            warning_counter[f"build:{warning}"] += 1

        by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        by_hash: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        by_payload: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for r in responses:
            model = r.get("model", "")
            source_file = r.get("source_file", "")
            response_id = r.get("response_id", "")

            by_model[model].append(r)
            if r.get("content_sha256"):
                by_hash[r["content_sha256"]].append(r)
                global_content_hash_counter[r["content_sha256"]] += 1

            payload_sig = qa_payload_signature(r)
            by_payload[payload_sig].append(r)
            global_payload_sig_counter[payload_sig] += 1

            if response_id:
                response_id_counter[response_id] += 1
            else:
                add_issue(issues, "HIGH", "missing_response_id", f"Response in transmission {tid} has no response_id.", transmission_id=tid, model=model, source_file=source_file)

            if source_file:
                source_file_counter[source_file] += 1

            for field in REQUIRED_RESPONSE_FIELDS:
                if field not in r or r.get(field) in (None, ""):
                    add_issue(
                        issues, "HIGH", "missing_response_field",
                        f"Response {response_id or '(no id)'} is missing required field {field}.",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                        details={"field": field},
                    )

            expected_model = MODEL_BY_SOURCE_DIRECTORY.get(r.get("source_directory", ""))
            if expected_model and model and model != expected_model:
                add_issue(
                    issues, "HIGH", "model_source_directory_mismatch",
                    f"Response model {model} does not match source_directory {r.get('source_directory')} expected model {expected_model}.",
                    transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                    details={"expected_model": expected_model, "source_directory": r.get("source_directory")},
                )

            qa_pairs = r.get("qa_pairs", [])
            if not isinstance(qa_pairs, list):
                add_issue(issues, "CRITICAL", "qa_pairs_not_list", "qa_pairs is not a list.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id)
                qa_pairs = []

            if r.get("qa_pair_count") != len(qa_pairs):
                add_issue(
                    issues, "MEDIUM", "qa_pair_count_mismatch",
                    f"qa_pair_count is {r.get('qa_pair_count')}, actual Q/A pair count is {len(qa_pairs)}.",
                    transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                    details={"stored": r.get("qa_pair_count"), "actual": len(qa_pairs)},
                )

            if not qa_pairs:
                add_issue(issues, "HIGH", "response_has_no_qa_pairs", "Response has no Q/A pairs.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id)

            for warning in r.get("parse_warnings") or []:
                warning_counter[f"parse:{warning}"] += 1
                sev = "MEDIUM"
                if warning == STALE_WARNING:
                    sev = "MEDIUM"
                add_issue(
                    issues, sev, "response_parse_warning",
                    f"Response has parse warning: {warning}",
                    transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                    details={"warning": warning},
                )

            status = ((r.get("review_status") or {}).get("status") or "unreviewed")
            status_counter[status] += 1

            if status == "needs_fix":
                add_issue(issues, "HIGH", "review_status_needs_fix", "Response is marked needs_fix.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id)
            elif status == "exclude_from_training":
                add_issue(issues, "INFO", "review_status_excluded", "Response is marked exclude_from_training.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id)

            if r.get("include_in_training") is False:
                add_issue(issues, "INFO", "include_in_training_false", "Response has include_in_training=false.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id)

            # Check current source file if possible.
            if source_file:
                path = source_path_from_response(r, source_root)
                if not path.exists():
                    add_issue(
                        issues, "HIGH", "source_file_missing",
                        f"Source .md file does not exist at {path}.",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                    )
                elif builder is not None:
                    fresh_response, error = current_md_parse(r, source_root, builder)
                    if error:
                        add_issue(
                            issues, "HIGH", "source_file_reparse_failed",
                            f"Could not reparse source .md file: {error}",
                            transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                        )
                    elif fresh_response:
                        old_hash = r.get("content_sha256")
                        fresh_hash = fresh_response.get("content_sha256")
                        if old_hash and fresh_hash and old_hash != fresh_hash:
                            add_issue(
                                issues, "INFO", "source_file_changed_since_json",
                                "Current .md file hash differs from stored content_sha256. This is expected if you edited .md files after building/reviewing JSON.",
                                transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                                details={"stored_hash": old_hash, "current_hash": fresh_hash},
                            )

                        old_warnings = set(r.get("parse_warnings") or [])
                        fresh_warnings = set(fresh_response.get("parse_warnings") or [])
                        stale = sorted(old_warnings - fresh_warnings)
                        new = sorted(fresh_warnings - old_warnings)
                        if stale:
                            add_issue(
                                issues, "MEDIUM", "stale_parse_warning_in_json",
                                f"JSON still contains parse warnings no longer produced by current .md: {', '.join(stale)}",
                                transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                                details={"stale_warnings": stale, "current_warnings": sorted(fresh_warnings)},
                            )
                        if new:
                            add_issue(
                                issues, "MEDIUM", "current_md_has_new_parse_warning",
                                f"Current .md now produces parse warnings not present in JSON: {', '.join(new)}",
                                transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                                details={"new_warnings": new, "stored_warnings": sorted(old_warnings)},
                            )

                        if STALE_WARNING in old_warnings and STALE_WARNING not in fresh_warnings:
                            add_issue(
                                issues, "MEDIUM", "sonnet45_metadata_warning_appears_stale",
                                "metadata_model_label_differs_from_source_directory appears stale: current .md no longer produces it.",
                                transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                                details={
                                    "stored_metadata_model_label": r.get("metadata_model_label"),
                                    "current_metadata_model_label": fresh_response.get("metadata_model_label"),
                                },
                            )
                        if STALE_WARNING in fresh_warnings:
                            add_issue(
                                issues, "MEDIUM", "metadata_label_mismatch_still_true_in_current_md",
                                "Current .md still produces metadata_model_label_differs_from_source_directory.",
                                transmission_id=tid, model=model, source_file=source_file, response_id=response_id,
                                details={
                                    "current_metadata_model_label": fresh_response.get("metadata_model_label"),
                                    "source_directory": r.get("source_directory"),
                                    "model": model,
                                },
                            )

            for idx, pair in enumerate(qa_pairs, start=1):
                turn_index = pair.get("turn_index")
                if turn_index != idx:
                    add_issue(
                        issues, "MEDIUM", "turn_index_out_of_sequence",
                        f"Q/A pair stored turn_index {turn_index!r}, expected {idx}.",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                    )
                expected_followup = idx > 1
                if pair.get("is_followup") != expected_followup:
                    add_issue(
                        issues, "LOW", "is_followup_mismatch",
                        f"Q/A pair is_followup is {pair.get('is_followup')!r}, expected {expected_followup}.",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                    )

                for field in REQUIRED_QA_FIELDS:
                    if field not in pair:
                        add_issue(
                            issues, "HIGH", "missing_qa_field",
                            f"Q/A pair is missing required field {field}.",
                            transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                            details={"field": field},
                        )

                q = pair.get("question", "")
                a = pair.get("answer", "")
                if not str(q).strip():
                    add_issue(issues, "HIGH", "empty_question", "Q/A pair has empty question.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx)
                if not str(a).strip():
                    add_issue(issues, "HIGH", "empty_answer", "Q/A pair has empty answer.", transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx)
                elif len(normalise_space(str(a))) < 30:
                    add_issue(
                        issues, "MEDIUM", "very_short_answer",
                        f"Q/A pair answer is very short: {short(a, 80)}",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                    )

                if len(normalise_space(str(q))) < 8:
                    add_issue(
                        issues, "LOW", "very_short_question",
                        f"Q/A pair question is very short: {short(q, 80)}",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                    )

                for warning in pair.get("warnings") or []:
                    pair_warning_counter[warning] += 1
                    add_issue(
                        issues, "MEDIUM", "qa_pair_warning",
                        f"Q/A pair has warning: {warning}",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                        details={"warning": warning},
                    )
                for note in pair.get("repair_notes") or []:
                    pair_warning_counter[f"repair:{note}"] += 1
                    add_issue(
                        issues, "LOW", "qa_pair_repair_note",
                        f"Q/A pair has repair note: {note}",
                        transmission_id=tid, model=model, source_file=source_file, response_id=response_id, turn_index=idx,
                        details={"repair_note": note},
                    )

        for model, model_responses in by_model.items():
            if model and len(model_responses) > 1:
                add_issue(
                    issues, "MEDIUM", "duplicate_model_responses_within_transmission",
                    f"Transmission has {len(model_responses)} responses for model {model}.",
                    transmission_id=tid, model=model,
                    details={"source_files": [r.get("source_file") for r in model_responses]},
                )

        for content_hash, hash_responses in by_hash.items():
            if len(hash_responses) > 1:
                add_issue(
                    issues, "MEDIUM", "duplicate_content_hash_within_transmission",
                    f"Transmission has {len(hash_responses)} responses with the same source content hash.",
                    transmission_id=tid,
                    details={"content_sha256": content_hash, "source_files": [r.get("source_file") for r in hash_responses]},
                )

        for payload_sig, payload_responses in by_payload.items():
            if len(payload_responses) > 1:
                add_issue(
                    issues, "MEDIUM", "duplicate_qa_payload_within_transmission",
                    f"Transmission has {len(payload_responses)} responses with identical extracted Q/A payload.",
                    transmission_id=tid,
                    details={"source_files": [r.get("source_file") for r in payload_responses], "models": [r.get("model") for r in payload_responses]},
                )

        # Validate build warnings against actual state.
        actual_duplicate_model = any(len(v) > 1 for v in by_model.values())
        actual_duplicate_hash = any(len(v) > 1 for v in by_hash.values())
        q_variants = {
            normalise_space((r.get("qa_pairs") or [{}])[0].get("question", ""))
            for r in responses
            if r.get("qa_pairs")
        }
        q_variants.discard("")
        actual_question_variants = len(q_variants) > 1

        bw = set(t_build_warnings)
        checks = [
            ("duplicate_model_responses_for_same_transmission", actual_duplicate_model),
            ("duplicate_content_hash_across_responses", actual_duplicate_hash),
            ("multiple_first_question_variants_across_models", actual_question_variants),
        ]
        for warning_name, actual in checks:
            if warning_name in bw and not actual:
                add_issue(
                    issues, "MEDIUM", "stale_build_warning",
                    f"Build warning appears stale: {warning_name}",
                    transmission_id=tid,
                    details={"warning": warning_name},
                )
            elif actual and warning_name not in bw:
                add_issue(
                    issues, "LOW", "missing_build_warning",
                    f"Actual condition exists but build warning is absent: {warning_name}",
                    transmission_id=tid,
                    details={"warning": warning_name},
                )

    for response_id, count in response_id_counter.items():
        if response_id and count > 1:
            add_issue(issues, "CRITICAL", "duplicate_response_id", f"Response ID appears {count} times: {response_id}", response_id=response_id)

    for source_file, count in source_file_counter.items():
        if source_file and count > 1:
            add_issue(issues, "HIGH", "source_file_reused_across_responses", f"Source file appears in {count} responses: {source_file}", source_file=source_file)

    report["warning_counts"] = {
        "response_or_build_warnings": dict(sorted(warning_counter.items())),
        "qa_pair_warnings_or_repairs": dict(sorted(pair_warning_counter.items())),
    }
    report["status_counts"] = dict(sorted(status_counter.items()))

    severity_counts = Counter(i["severity"] for i in issues)
    code_counts = Counter(i["code"] for i in issues)
    report["issue_counts"] = {
        "by_severity": dict(sorted(severity_counts.items())),
        "by_code": dict(sorted(code_counts.items())),
    }

    report["summary"] = {
        "total_issues": len(issues),
        "critical": severity_counts.get("CRITICAL", 0),
        "high": severity_counts.get("HIGH", 0),
        "medium": severity_counts.get("MEDIUM", 0),
        "low": severity_counts.get("LOW", 0),
        "info": severity_counts.get("INFO", 0),
        "actual_counts": actual_counts,
        "status_counts": report["status_counts"],
        "top_issue_codes": code_counts.most_common(20),
    }

    return report


def issue_sort_key(issue: Dict[str, Any]) -> Tuple[int, Tuple[int, str], str, str]:
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
    tid = issue.get("transmission_id") or ""
    return (
        sev_order.get(issue.get("severity", "INFO"), 9),
        sort_tid(tid),
        issue.get("code", ""),
        issue.get("source_file", "") or "",
    )


def render_text_report(report: Dict[str, Any], max_items_per_section: int = 200) -> str:
    lines: List[str] = []
    summary = report["summary"]
    counts = report["counts"]["actual"]

    lines.append("Leilan dataset health report\n")
    lines.append("============================\n\n")
    lines.append(f"Generated: {report['created_utc']}\n")
    lines.append(f"JSON file: {report['json_file']}\n")
    lines.append(f"Source root: {report['source_root']}\n")
    lines.append(f"Builder reparse available: {report['builder_available']}\n\n")

    lines.append("Dataset counts\n")
    lines.append("--------------\n")
    lines.append(f"Transmissions: {counts['transmission_count']}\n")
    lines.append(f"Responses:     {counts['response_count']}\n")
    lines.append(f"Q/A pairs:     {counts['qa_pair_count']}\n")
    lines.append(f"Models:        {counts['model_count']}\n\n")

    lines.append("Model counts\n")
    lines.append("------------\n")
    for model, count in counts["model_counts"].items():
        lines.append(f"- {model}: {count}\n")
    lines.append("\n")

    lines.append("Issue summary\n")
    lines.append("-------------\n")
    lines.append(f"Total issues/notices: {summary['total_issues']}\n")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        lines.append(f"- {sev}: {summary.get(sev.lower(), 0)}\n")
    lines.append("\n")

    lines.append("Status counts\n")
    lines.append("-------------\n")
    if report.get("status_counts"):
        for status, count in report["status_counts"].items():
            lines.append(f"- {status}: {count}\n")
    else:
        lines.append("- none\n")
    lines.append("\n")

    lines.append("Top issue codes\n")
    lines.append("---------------\n")
    for code, count in summary.get("top_issue_codes", []):
        lines.append(f"- {code}: {count}\n")
    lines.append("\n")

    warnings = report.get("warning_counts", {})
    lines.append("Stored warning counts\n")
    lines.append("---------------------\n")
    rw = warnings.get("response_or_build_warnings") or {}
    pw = warnings.get("qa_pair_warnings_or_repairs") or {}
    if not rw and not pw:
        lines.append("No stored parser/build/Q-A warnings found.\n\n")
    else:
        if rw:
            lines.append("Response/build warnings:\n")
            for warning, count in rw.items():
                lines.append(f"- {warning}: {count}\n")
        if pw:
            lines.append("\nQ/A pair warnings and repair notes:\n")
            for warning, count in pw.items():
                lines.append(f"- {warning}: {count}\n")
        lines.append("\n")

    if report.get("samples", {}).get("nonstandard_ids_not_classed_as_expected"):
        lines.append("Non-standard transmission IDs not classed as expected\n")
        lines.append("----------------------------------------------------\n")
        lines.append(", ".join(report["samples"]["nonstandard_ids_not_classed_as_expected"]) + "\n\n")

    issues = sorted(report["issues"], key=issue_sort_key)

    def render_issue(issue: Dict[str, Any]) -> str:
        bits = [
            f"[{issue['severity']}] {issue['code']}",
        ]
        if issue.get("transmission_id"):
            bits.append(f"T{issue['transmission_id']}")
        if issue.get("model"):
            bits.append(issue["model"])
        if issue.get("turn_index"):
            bits.append(f"turn {issue['turn_index']}")
        if issue.get("source_file"):
            bits.append(issue["source_file"])
        header = " | ".join(bits)
        return f"- {header}\n  {issue['message']}\n"

    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"):
        sev_issues = [i for i in issues if i["severity"] == severity]
        lines.append(f"{severity} items\n")
        lines.append("-" * (len(severity) + 6) + "\n")
        if not sev_issues:
            lines.append("None.\n\n")
            continue

        for issue in sev_issues[:max_items_per_section]:
            lines.append(render_issue(issue))
        if len(sev_issues) > max_items_per_section:
            lines.append(f"\n... {len(sev_issues) - max_items_per_section} more {severity} items omitted from text report. See JSON report for full detail.\n")
        lines.append("\n")

    lines.append("Interpretation guide\n")
    lines.append("--------------------\n")
    lines.append("- CRITICAL/HIGH usually means something structural needs attention.\n")
    lines.append("- MEDIUM often means a warning, stale warning, duplicate, or source/JSON drift worth inspecting.\n")
    lines.append("- LOW/INFO often means provenance or bookkeeping rather than broken training data.\n")
    lines.append("- source_file_changed_since_json is expected if you edited .md files after the JSON was curated; it is not automatically an error.\n")
    lines.append("- stale_parse_warning_in_json means the JSON still stores a warning that the current .md no longer produces.\n")
    lines.append("- metadata_label_mismatch_still_true_in_current_md means the warning appears real in the current .md file.\n")

    return "".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze the Leilan JSON dataset and write a health report.")
    parser.add_argument("--json", default=DEFAULT_JSON, help=f"Dataset JSON file. Default: {DEFAULT_JSON}")
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"Markdown source root. Default: {DEFAULT_SOURCE_ROOT}")
    parser.add_argument("--builder", default=DEFAULT_BUILDER, help=f"Builder script. Default: {DEFAULT_BUILDER}")
    parser.add_argument("--text-report", default=DEFAULT_TEXT_REPORT, help=f"Text report output. Default: {DEFAULT_TEXT_REPORT}")
    parser.add_argument("--json-report", default=DEFAULT_JSON_REPORT, help=f"JSON report output. Default: {DEFAULT_JSON_REPORT}")
    parser.add_argument("--max-items-per-section", type=int, default=200, help="Max issues per severity section in text report.")
    parser.add_argument("--no-builder-reparse", action="store_true", help="Skip reparsing current .md files even if builder is present.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    json_path = Path(args.json)
    source_root = Path(args.source_root)
    builder_path = Path(args.builder)
    text_report_path = Path(args.text_report)
    json_report_path = Path(args.json_report)

    if not json_path.exists():
        print(f"ERROR: JSON file not found: {json_path}")
        return 1

    data = load_json(json_path)

    builder = None
    if not args.no_builder_reparse:
        try:
            builder = load_builder_module(builder_path)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: could not load builder for .md reparse checks: {exc}")
            builder = None

    report = analyze(data, json_path, source_root, builder)
    write_json(json_report_path, report)
    write_text(text_report_path, render_text_report(report, max_items_per_section=args.max_items_per_section))

    summary = report["summary"]
    print("\nLeilan dataset health analysis")
    print("------------------------------")
    print(f"JSON:                 {json_path}")
    print(f"Builder reparse:      {'yes' if report['builder_available'] else 'no'}")
    print(f"Text report:          {text_report_path}")
    print(f"JSON report:          {json_report_path}")
    print("\nCounts:")
    print(f"  transmissions:      {summary['actual_counts']['transmission_count']}")
    print(f"  responses:          {summary['actual_counts']['response_count']}")
    print(f"  Q/A pairs:          {summary['actual_counts']['qa_pair_count']}")
    print("\nIssues/notices:")
    for sev in ("critical", "high", "medium", "low", "info"):
        print(f"  {sev.upper():8} {summary.get(sev, 0)}")
    print(f"  TOTAL    {summary['total_issues']}")

    if summary.get("critical", 0) or summary.get("high", 0):
        print("\nThere are CRITICAL/HIGH items. Open the text report first.")
    else:
        print("\nNo CRITICAL/HIGH structural problems found. Check MEDIUM items for remaining warnings/stale warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
