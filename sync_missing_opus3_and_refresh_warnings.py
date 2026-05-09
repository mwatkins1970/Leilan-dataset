#!/usr/bin/env python3
"""
sync_missing_opus3_and_refresh_warnings.py

Surgically sync missing Claude Opus 3 .md files into the curated
full_leilan_claude_dataset.json, and optionally clear stale Sonnet 4.5
metadata-model warnings when the current .md file no longer produces that
warning.

Default is DRY RUN:

    python3 sync_missing_opus3_and_refresh_warnings.py

Write changes after checking the report/output:

    python3 sync_missing_opus3_and_refresh_warnings.py --write

Run from the repo root, alongside:
    full_leilan_claude_dataset.json
    build_full_leilan_claude_dataset_v11.py
    post-gpt3_transmissions_by_model/
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_JSON = "full_leilan_claude_dataset.json"
DEFAULT_SOURCE_ROOT = "post-gpt3_transmissions_by_model"
DEFAULT_BUILDER = "build_full_leilan_claude_dataset_v11.py"
DEFAULT_REPORT = "sync_missing_opus3_and_refresh_warnings_report.json"

OPUS3_MODEL = "claude-opus-3"
SONNET45_MODEL = "claude-sonnet-4.5"
STALE_WARNING = "metadata_model_label_differs_from_source_directory"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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


def make_backup(path: Path) -> Path:
    backup = path.with_name(f"{path.stem}.backup-before-opus3-sync-{timestamp()}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def load_builder_module(builder_path: Path) -> Any:
    if not builder_path.exists():
        raise FileNotFoundError(f"Builder script not found: {builder_path}")

    module_name = "leilan_dataset_builder_v11"
    spec = importlib.util.spec_from_file_location(module_name, builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load builder module from: {builder_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def sort_transmission_id(tid: str) -> Tuple[int, str]:
    if re.fullmatch(r"\d+", str(tid)):
        return (0, f"{int(tid):06d}")
    return (1, str(tid))


def response_sort_key(response: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        response.get("source_date") or "",
        response.get("source_directory") or "",
        response.get("source_filename") or "",
        response.get("source_file") or "",
    )


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def find_transmission(data: Dict[str, Any], tid: str) -> Optional[Dict[str, Any]]:
    for transmission in data.get("transmissions", []):
        if str(transmission.get("transmission_id")) == str(tid):
            return transmission
    return None


def find_transmission_index(data: Dict[str, Any], tid: str) -> Optional[int]:
    for i, transmission in enumerate(data.get("transmissions", [])):
        if str(transmission.get("transmission_id")) == str(tid):
            return i
    return None


def source_file_sort_key(path: Path) -> Tuple[str, str, str]:
    return (
        path.name[:10] if len(path.name) >= 10 else "",
        path.parent.name,
        path.name,
    )


def list_model_md_files(source_root: Path, builder: Any, source_directory: str) -> List[Path]:
    folder = source_root / source_directory
    if not folder.exists():
        return []

    out: List[Path] = []
    for path in folder.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        date, tid, slug = builder.parse_filename(path)
        if tid:
            out.append(path)

    return sorted(out, key=source_file_sort_key)


def response_from_parsed(parsed_file: Any, builder: Any) -> Dict[str, Any]:
    response = builder.response_from_parsed_file(parsed_file, include_raw=False)
    response["response_variant_index_for_model"] = 1
    return response


def build_transmission_from_single_parsed_file(
    parsed_file: Any,
    source_root: Path,
    builder: Any,
) -> Dict[str, Any]:
    dataset, report = builder.build_dataset(
        parsed_files=[parsed_file],
        source_root=source_root,
        seed_by_id={},
        url_map={},
        include_raw=False,
        include_gpt4_base=False,
    )
    transmissions = dataset.get("transmissions", [])
    if not transmissions:
        raise RuntimeError(f"Builder produced no transmission for {parsed_file.source_file}")
    return transmissions[0]


def renumber_response_variants(transmission: Dict[str, Any]) -> None:
    counts: Counter[str] = Counter()
    for response in transmission.get("responses", []):
        model = response.get("model", "(unknown)")
        counts[model] += 1
        response["response_variant_index_for_model"] = counts[model]


def recompute_transmission_fields(transmission: Dict[str, Any]) -> None:
    responses = transmission.get("responses", [])
    responses.sort(key=response_sort_key)
    renumber_response_variants(transmission)

    dates = sorted({r.get("source_date") for r in responses if r.get("source_date")})
    if dates:
        transmission["dates"] = dates
        transmission["date_first"] = dates[0]

    for response in responses:
        qa_pairs = response.get("qa_pairs", [])
        response["qa_pair_count"] = len(qa_pairs)
        for idx, pair in enumerate(qa_pairs, start=1):
            pair["turn_index"] = idx
            pair["is_followup"] = idx > 1

    build_warnings: List[str] = []
    model_counts = Counter(r.get("model") for r in responses)
    if any(count > 1 for count in model_counts.values()):
        build_warnings.append("duplicate_model_responses_for_same_transmission")

    hash_counts = Counter(r.get("content_sha256") for r in responses if r.get("content_sha256"))
    if any(count > 1 for count in hash_counts.values()):
        build_warnings.append("duplicate_content_hash_across_responses")

    q_variants = {
        normalise_space((r.get("qa_pairs") or [{}])[0].get("question", ""))
        for r in responses
        if r.get("qa_pairs")
    }
    q_variants.discard("")
    if len(q_variants) > 1:
        build_warnings.append("multiple_first_question_variants_across_models")

    transmission["build_warnings"] = build_warnings


def recompute_corpus_counts(data: Dict[str, Any]) -> None:
    transmissions = data.get("transmissions", [])
    transmissions.sort(key=lambda t: sort_transmission_id(str(t.get("transmission_id"))))

    response_count = 0
    qa_pair_count = 0
    model_counts: Counter[str] = Counter()
    source_dir_counts: Counter[str] = Counter()

    for transmission in transmissions:
        recompute_transmission_fields(transmission)
        for response in transmission.get("responses", []):
            response_count += 1
            qa_pair_count += len(response.get("qa_pairs", []))
            if response.get("model"):
                model_counts[response["model"]] += 1
            if response.get("source_directory"):
                source_dir_counts[response["source_directory"]] += 1

    corpus = data.setdefault("corpus_info", {})
    corpus["transmission_count"] = len(transmissions)
    corpus["response_count"] = response_count
    corpus["qa_pair_count"] = qa_pair_count
    corpus["model_count"] = len(model_counts)
    corpus["model_counts"] = dict(sorted(model_counts.items()))
    corpus["source_directory_counts"] = dict(sorted(source_dir_counts.items()))
    corpus["last_opus3_sync_utc"] = now_utc_iso()


def sync_missing_opus3(
    data: Dict[str, Any],
    source_root: Path,
    builder: Any,
    *,
    create_missing_transmissions: bool,
    add_variants: bool,
) -> Dict[str, Any]:
    operation: Dict[str, Any] = {
        "operation": "sync_missing_opus3",
        "opus3_md_files_seen": 0,
        "added": [],
        "skipped": [],
        "failed": [],
    }

    opus3_files = list_model_md_files(source_root, builder, "opus3")
    operation["opus3_md_files_seen"] = len(opus3_files)

    for path in opus3_files:
        date, tid, slug = builder.parse_filename(path)
        if not tid:
            operation["skipped"].append({"source_file": path.as_posix(), "reason": "could_not_parse_transmission_id"})
            continue

        try:
            parsed = builder.parse_markdown_file(path, source_root)
            response = response_from_parsed(parsed, builder)
        except Exception as exc:  # noqa: BLE001
            operation["failed"].append({"source_file": path.as_posix(), "error": repr(exc)})
            continue

        transmission = find_transmission(data, tid)

        if transmission is None:
            if not create_missing_transmissions:
                operation["skipped"].append(
                    {
                        "transmission_id": tid,
                        "source_file": path.as_posix(),
                        "reason": "json_transmission_missing_use_create_missing_transmissions",
                    }
                )
                continue

            try:
                new_transmission = build_transmission_from_single_parsed_file(parsed, source_root, builder)
                data.setdefault("transmissions", []).append(new_transmission)
                operation["added"].append(
                    {
                        "transmission_id": tid,
                        "action": "created_missing_transmission",
                        "source_file": response.get("source_file"),
                        "qa_pair_count": response.get("qa_pair_count"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                operation["failed"].append({"source_file": path.as_posix(), "error": repr(exc)})
            continue

        existing_opus3 = [
            r for r in transmission.get("responses", [])
            if r.get("model") == OPUS3_MODEL
        ]
        existing_source_files = {r.get("source_file") for r in transmission.get("responses", [])}

        if response.get("source_file") in existing_source_files:
            operation["skipped"].append(
                {
                    "transmission_id": tid,
                    "source_file": response.get("source_file"),
                    "reason": "source_file_already_present",
                }
            )
            continue

        if existing_opus3 and not add_variants:
            operation["skipped"].append(
                {
                    "transmission_id": tid,
                    "source_file": response.get("source_file"),
                    "reason": "opus3_response_already_present",
                    "existing_opus3_sources": [r.get("source_file") for r in existing_opus3],
                }
            )
            continue

        transmission.setdefault("responses", []).append(response)
        recompute_transmission_fields(transmission)
        operation["added"].append(
            {
                "transmission_id": tid,
                "action": "added_opus3_response",
                "source_file": response.get("source_file"),
                "qa_pair_count": response.get("qa_pair_count"),
                "parse_warnings": response.get("parse_warnings", []),
            }
        )

    return operation


def refresh_stale_sonnet45_metadata_warnings(
    data: Dict[str, Any],
    source_root: Path,
    builder: Any,
) -> Dict[str, Any]:
    operation: Dict[str, Any] = {
        "operation": "refresh_stale_sonnet45_metadata_warnings",
        "checked": [],
        "cleared": [],
        "kept": [],
        "failed": [],
    }

    for transmission in data.get("transmissions", []):
        tid = str(transmission.get("transmission_id"))
        changed = False

        for response in transmission.get("responses", []):
            if response.get("model") != SONNET45_MODEL:
                continue
            if STALE_WARNING not in (response.get("parse_warnings") or []):
                continue

            source_file = response.get("source_file")
            if not source_file:
                operation["failed"].append(
                    {"transmission_id": tid, "reason": "response_has_no_source_file"}
                )
                continue

            path = Path(source_file)
            if not path.is_absolute():
                path = source_root.parent / path

            operation["checked"].append({"transmission_id": tid, "source_file": source_file})

            if not path.exists():
                operation["failed"].append(
                    {
                        "transmission_id": tid,
                        "source_file": source_file,
                        "reason": "source_file_not_found",
                    }
                )
                continue

            try:
                parsed = builder.parse_markdown_file(path, source_root)
                fresh_response = response_from_parsed(parsed, builder)
            except Exception as exc:  # noqa: BLE001
                operation["failed"].append(
                    {
                        "transmission_id": tid,
                        "source_file": source_file,
                        "error": repr(exc),
                    }
                )
                continue

            fresh_warnings = fresh_response.get("parse_warnings", [])

            if STALE_WARNING in fresh_warnings:
                operation["kept"].append(
                    {
                        "transmission_id": tid,
                        "source_file": source_file,
                        "reason": "current_md_still_has_warning",
                        "fresh_metadata_model_label": fresh_response.get("metadata_model_label"),
                    }
                )
                continue

            # Only clear the stale warning and refresh source metadata/hash.
            # Do NOT overwrite curated Q/A text.
            response["parse_warnings"] = [
                w for w in (response.get("parse_warnings") or [])
                if w != STALE_WARNING
            ]
            response["metadata_model_label"] = fresh_response.get("metadata_model_label", response.get("metadata_model_label"))
            response["metadata_query"] = fresh_response.get("metadata_query", response.get("metadata_query"))
            response["content_sha256"] = fresh_response.get("content_sha256", response.get("content_sha256"))
            response["source_title"] = fresh_response.get("source_title", response.get("source_title"))
            response["source_date"] = fresh_response.get("source_date", response.get("source_date"))
            response["source_filename"] = fresh_response.get("source_filename", response.get("source_filename"))
            response["stale_warning_cleared_utc"] = now_utc_iso()

            operation["cleared"].append(
                {
                    "transmission_id": tid,
                    "source_file": source_file,
                    "fresh_metadata_model_label": fresh_response.get("metadata_model_label"),
                }
            )
            changed = True

        if changed:
            recompute_transmission_fields(transmission)

    return operation


def run_sync(
    data: Dict[str, Any],
    source_root: Path,
    builder: Any,
    *,
    create_missing_transmissions: bool,
    add_variants: bool,
    refresh_warnings: bool,
) -> Dict[str, Any]:
    pre_counts = {
        "transmission_count": len(data.get("transmissions", [])),
        "response_count": sum(len(t.get("responses", [])) for t in data.get("transmissions", [])),
        "qa_pair_count": sum(
            len(r.get("qa_pairs", []))
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
        ),
        "opus3_response_count": sum(
            1
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
            if r.get("model") == OPUS3_MODEL
        ),
        "sonnet45_stale_warning_count": sum(
            1
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
            if r.get("model") == SONNET45_MODEL
            and STALE_WARNING in (r.get("parse_warnings") or [])
        ),
    }

    operations = []
    operations.append(
        sync_missing_opus3(
            data,
            source_root,
            builder,
            create_missing_transmissions=create_missing_transmissions,
            add_variants=add_variants,
        )
    )

    if refresh_warnings:
        operations.append(refresh_stale_sonnet45_metadata_warnings(data, source_root, builder))

    recompute_corpus_counts(data)

    post_counts = {
        "transmission_count": len(data.get("transmissions", [])),
        "response_count": sum(len(t.get("responses", [])) for t in data.get("transmissions", [])),
        "qa_pair_count": sum(
            len(r.get("qa_pairs", []))
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
        ),
        "opus3_response_count": sum(
            1
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
            if r.get("model") == OPUS3_MODEL
        ),
        "sonnet45_stale_warning_count": sum(
            1
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
            if r.get("model") == SONNET45_MODEL
            and STALE_WARNING in (r.get("parse_warnings") or [])
        ),
    }

    return {
        "created_utc": now_utc_iso(),
        "pre_counts": pre_counts,
        "post_counts": post_counts,
        "delta_counts": {k: post_counts[k] - pre_counts[k] for k in pre_counts},
        "operations": operations,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync missing Opus 3 responses and clear stale Sonnet 4.5 metadata warnings."
    )
    parser.add_argument("--json", default=DEFAULT_JSON, help=f"Dataset JSON. Default: {DEFAULT_JSON}")
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"Markdown source root. Default: {DEFAULT_SOURCE_ROOT}")
    parser.add_argument("--builder", default=DEFAULT_BUILDER, help=f"Builder script. Default: {DEFAULT_BUILDER}")
    parser.add_argument("--report", default=DEFAULT_REPORT, help=f"Report file. Default: {DEFAULT_REPORT}")
    parser.add_argument("--write", action="store_true", help="Actually modify JSON. Default is dry run.")
    parser.add_argument(
        "--create-missing-transmissions",
        action="store_true",
        help="Create JSON transmission records if an Opus 3 .md exists but the transmission is missing from JSON.",
    )
    parser.add_argument(
        "--add-variants",
        action="store_true",
        help="If an Opus 3 response already exists for a transmission, add the new one as a variant instead of skipping.",
    )
    parser.add_argument(
        "--no-refresh-warnings",
        action="store_true",
        help="Do not clear stale Sonnet 4.5 metadata_model_label_differs_from_source_directory warnings.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    json_path = Path(args.json)
    source_root = Path(args.source_root)
    builder_path = Path(args.builder)
    report_path = Path(args.report)

    if not json_path.exists():
        print(f"ERROR: JSON not found: {json_path}")
        return 1
    if not source_root.exists() or not source_root.is_dir():
        print(f"ERROR: source root not found: {source_root}")
        return 1
    if not builder_path.exists():
        print(f"ERROR: builder not found: {builder_path}")
        return 1

    builder = load_builder_module(builder_path)
    original_data = load_json(json_path)
    working_data = copy.deepcopy(original_data)

    report = run_sync(
        working_data,
        source_root,
        builder,
        create_missing_transmissions=args.create_missing_transmissions,
        add_variants=args.add_variants,
        refresh_warnings=not args.no_refresh_warnings,
    )
    report["mode"] = "write" if args.write else "dry_run"
    report["options"] = {
        "create_missing_transmissions": args.create_missing_transmissions,
        "add_variants": args.add_variants,
        "refresh_warnings": not args.no_refresh_warnings,
    }

    write_json_atomic(report_path, report)

    add_op = next((op for op in report["operations"] if op.get("operation") == "sync_missing_opus3"), {})
    warn_op = next((op for op in report["operations"] if op.get("operation") == "refresh_stale_sonnet45_metadata_warnings"), {})

    print("\nLeilan Opus 3 sync / warning refresh")
    print("------------------------------------")
    print(f"JSON:        {json_path}")
    print(f"Source root: {source_root}")
    print(f"Builder:     {builder_path}")
    print(f"Mode:        {'WRITE' if args.write else 'DRY RUN'}")

    print("\nCounts:")
    for key in ("transmission_count", "response_count", "qa_pair_count", "opus3_response_count", "sonnet45_stale_warning_count"):
        print(
            f"  {key:32} {report['pre_counts'][key]} -> {report['post_counts'][key]} "
            f"({report['delta_counts'][key]:+d})"
        )

    print("\nOpus 3 sync:")
    print(f"  Opus 3 .md files seen: {add_op.get('opus3_md_files_seen', 0)}")
    print(f"  Added:                {len(add_op.get('added', []))}")
    print(f"  Skipped:              {len(add_op.get('skipped', []))}")
    print(f"  Failed:               {len(add_op.get('failed', []))}")

    if warn_op:
        print("\nSonnet 4.5 stale metadata warnings:")
        print(f"  Checked: {len(warn_op.get('checked', []))}")
        print(f"  Cleared: {len(warn_op.get('cleared', []))}")
        print(f"  Kept:    {len(warn_op.get('kept', []))}")
        print(f"  Failed:  {len(warn_op.get('failed', []))}")

    print(f"\nReport written: {report_path}")

    if not args.write:
        print("\nDry run only. If this looks right, run again with --write.")
        return 0

    backup = make_backup(json_path)
    write_json_atomic(json_path, working_data)

    print(f"\nBackup created: {backup}")
    print(f"Updated JSON written: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
