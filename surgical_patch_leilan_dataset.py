#!/usr/bin/env python3
"""
surgical_patch_leilan_dataset.py

Surgically patch the curated full_leilan_claude_dataset.json from selected
Markdown files without doing a full rebuild.

Default mode is DRY RUN:

    python3 surgical_patch_leilan_dataset.py

Actually write changes:

    python3 surgical_patch_leilan_dataset.py --write

Requirements:
    - Run from the repo root.
    - full_leilan_claude_dataset.json exists in the repo root.
    - build_full_leilan_claude_dataset_v11.py exists in the repo root.
    - post-gpt3_transmissions_by_model/ exists in the repo root.

No external packages required.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_JSON = "full_leilan_claude_dataset.json"
DEFAULT_SOURCE_ROOT = "post-gpt3_transmissions_by_model"
DEFAULT_BUILDER = "build_full_leilan_claude_dataset_v11.py"
DEFAULT_REPORT = "surgical_patch_leilan_dataset_report.json"


# ---------------------------------------------------------------------------
# Patch plan
# ---------------------------------------------------------------------------

ADD_OPUS3_IDS = {
    "056", "060", "061", "247", "248",
    "238a", "238b", "238c",
}

ADD_SONNET45_IDS = {
    "085", "212", "213", "214", "215", "216",
    "242", "244", "245", "246", "251", "252",
    "277", "279", "299", "350",
}

REPLACE_FROM_UNIFIED_MD_IDS = {
    "262", "263", "264", "265", "275", "298", "E003",
}

REMOVE_RECORD_IDS = {
    "262a", "262b",
    "263a", "263b", "263c", "263d",
    "264a", "264b",
    "265a", "265b",
    "275a", "275b",
    "298a", "298b",
    "E003a", "E003b", "E003c", "E003d",
}

ALLOWED_TOUCH_IDS = (
    ADD_OPUS3_IDS
    | ADD_SONNET45_IDS
    | REPLACE_FROM_UNIFIED_MD_IDS
    | REMOVE_RECORD_IDS
)


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

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
    backup = path.with_name(f"{path.stem}.backup-before-surgical-patch-{timestamp()}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def load_builder_module(builder_path: Path) -> Any:
    if not builder_path.exists():
        raise FileNotFoundError(f"Builder script not found: {builder_path}")

    spec = importlib.util.spec_from_file_location("leilan_dataset_builder_v11", builder_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load builder module from: {builder_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalise_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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


def source_file_sort_key(path: Path) -> Tuple[str, str, str]:
    return (
        path.name[:10] if len(path.name) >= 10 else "",
        path.parent.name,
        path.name,
    )


def find_transmission_index(data: Dict[str, Any], tid: str) -> Optional[int]:
    for i, item in enumerate(data.get("transmissions", [])):
        if str(item.get("transmission_id")) == str(tid):
            return i
    return None


def get_transmission(data: Dict[str, Any], tid: str) -> Optional[Dict[str, Any]]:
    idx = find_transmission_index(data, tid)
    if idx is None:
        return None
    return data["transmissions"][idx]


def insert_or_replace_transmission(data: Dict[str, Any], transmission: Dict[str, Any]) -> str:
    tid = str(transmission.get("transmission_id"))
    idx = find_transmission_index(data, tid)
    if idx is None:
        data.setdefault("transmissions", []).append(transmission)
        data["transmissions"].sort(key=lambda t: sort_transmission_id(str(t.get("transmission_id"))))
        return "inserted"
    data["transmissions"][idx] = transmission
    return "replaced"


def remove_transmission(data: Dict[str, Any], tid: str) -> bool:
    idx = find_transmission_index(data, tid)
    if idx is None:
        return False
    del data["transmissions"][idx]
    return True


def find_md_files_for_exact_id(
    source_root: Path,
    builder: Any,
    tid: str,
    source_directory: Optional[str] = None,
) -> List[Path]:
    """Find .md files whose filename transmission ID exactly matches tid."""
    if source_directory:
        folder = source_root / source_directory
        if not folder.exists():
            return []
        candidates = list(folder.glob("*.md"))
    else:
        candidates: List[Path] = []
        for subdir in sorted(p for p in source_root.iterdir() if p.is_dir()):
            if subdir.name == "gpt-4-base":
                continue
            candidates.extend(subdir.glob("*.md"))

    matches: List[Path] = []
    for path in candidates:
        if path.name.lower() == "readme.md":
            continue
        filename_date, filename_id, filename_slug = builder.parse_filename(path)
        if filename_id == tid:
            matches.append(path)

    return sorted(matches, key=source_file_sort_key)


def parse_md_files(paths: List[Path], source_root: Path, builder: Any) -> Tuple[List[Any], List[Dict[str, str]]]:
    parsed = []
    failed: List[Dict[str, str]] = []

    for path in paths:
        try:
            parsed.append(builder.parse_markdown_file(path, source_root))
        except Exception as exc:  # noqa: BLE001 - report and continue.
            failed.append({"source_file": path.as_posix(), "error": repr(exc)})

    return parsed, failed


def response_from_parsed(parsed_file: Any, builder: Any) -> Dict[str, Any]:
    response = builder.response_from_parsed_file(parsed_file, include_raw=False)
    response["response_variant_index_for_model"] = 1
    return response


def build_single_transmission_from_parsed(
    parsed_files: List[Any],
    source_root: Path,
    builder: Any,
    seed: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Use the v11 builder's build_dataset for one transmission group."""
    if not parsed_files:
        return None, {}

    tid_set = {str(pf.transmission_id) for pf in parsed_files}
    if len(tid_set) != 1:
        raise ValueError(f"Expected one transmission ID, got: {sorted(tid_set)}")

    tid = next(iter(tid_set))
    seed_by_id = {tid: seed or {}}

    dataset, report = builder.build_dataset(
        parsed_files=parsed_files,
        source_root=source_root,
        seed_by_id=seed_by_id,
        url_map={},
        include_raw=False,
        include_gpt4_base=False,
    )

    transmissions = dataset.get("transmissions", [])
    if not transmissions:
        return None, report

    return transmissions[0], report


def transmission_seed_for_replacement(
    data: Dict[str, Any],
    tid: str,
    split_ids_to_try: Optional[List[str]] = None,
) -> Dict[str, Any]:
    existing = get_transmission(data, tid)
    if existing:
        return existing

    for split_id in split_ids_to_try or []:
        candidate = get_transmission(data, split_id)
        if candidate:
            return candidate

    return {}


def renumber_response_variants(transmission: Dict[str, Any]) -> None:
    counts: Counter[str] = Counter()
    for response in transmission.get("responses", []):
        model = response.get("model", "(unknown)")
        counts[model] += 1
        response["response_variant_index_for_model"] = counts[model]


def recompute_transmission_fields(transmission: Dict[str, Any]) -> None:
    """Refresh summary fields/build warnings for a touched transmission only."""
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
    corpus["last_surgical_patch_utc"] = now_utc_iso()


def ensure_only_allowed_touched(touched_ids: Iterable[str]) -> None:
    unexpected = sorted({str(tid) for tid in touched_ids} - ALLOWED_TOUCH_IDS, key=sort_transmission_id)
    if unexpected:
        raise RuntimeError(
            "Safety stop: script attempted to touch transmission IDs outside the allowed patch set: "
            + ", ".join(unexpected)
        )


# ---------------------------------------------------------------------------
# Patch operations
# ---------------------------------------------------------------------------

def add_missing_model_response(
    data: Dict[str, Any],
    source_root: Path,
    builder: Any,
    tid: str,
    source_directory: str,
    report: Dict[str, Any],
) -> None:
    ensure_only_allowed_touched([tid])

    md_files = find_md_files_for_exact_id(source_root, builder, tid, source_directory=source_directory)
    op_report = {
        "operation": "add_missing_model_response",
        "transmission_id": tid,
        "source_directory": source_directory,
        "md_files_found": [p.as_posix() for p in md_files],
        "added": [],
        "skipped": [],
        "failed": [],
    }

    if not md_files:
        op_report["skipped"].append("no_matching_md_file_found")
        report["operations"].append(op_report)
        return

    parsed_files, failed = parse_md_files(md_files, source_root, builder)
    op_report["failed"].extend(failed)

    transmission = get_transmission(data, tid)

    if transmission is None:
        new_transmission, mini_report = build_single_transmission_from_parsed(
            parsed_files=parsed_files,
            source_root=source_root,
            builder=builder,
            seed=None,
        )
        op_report["builder_report"] = {
            "warning_counts": mini_report.get("warning_counts", {}),
            "qa_pair_count": mini_report.get("qa_pair_count"),
        }
        if new_transmission:
            insert_or_replace_transmission(data, new_transmission)
            op_report["added"].append("created_missing_transmission_record")
            report["touched_ids"].append(tid)
        else:
            op_report["skipped"].append("builder_returned_no_transmission")
        report["operations"].append(op_report)
        return

    existing_source_files = {r.get("source_file") for r in transmission.get("responses", [])}

    for pf in parsed_files:
        response = response_from_parsed(pf, builder)
        if response.get("source_file") in existing_source_files:
            op_report["skipped"].append(
                f"source_file_already_present: {response.get('source_file')}"
            )
            continue

        transmission.setdefault("responses", []).append(response)
        existing_source_files.add(response.get("source_file"))
        op_report["added"].append(
            {
                "model": response.get("model"),
                "source_file": response.get("source_file"),
                "qa_pair_count": response.get("qa_pair_count"),
            }
        )
        report["touched_ids"].append(tid)

    recompute_transmission_fields(transmission)
    report["operations"].append(op_report)


def replace_unified_transmission_from_md(
    data: Dict[str, Any],
    source_root: Path,
    builder: Any,
    tid: str,
    split_seed_ids: Optional[List[str]],
    report: Dict[str, Any],
) -> None:
    ensure_only_allowed_touched([tid])

    md_files = find_md_files_for_exact_id(source_root, builder, tid, source_directory=None)
    op_report = {
        "operation": "replace_unified_transmission_from_md",
        "transmission_id": tid,
        "md_files_found": [p.as_posix() for p in md_files],
        "result": None,
        "failed": [],
    }

    if not md_files:
        op_report["result"] = "no_matching_unified_md_files_found"
        report["operations"].append(op_report)
        return

    parsed_files, failed = parse_md_files(md_files, source_root, builder)
    op_report["failed"].extend(failed)

    if not parsed_files:
        op_report["result"] = "no_files_parsed"
        report["operations"].append(op_report)
        return

    seed = transmission_seed_for_replacement(data, tid, split_seed_ids)
    new_transmission, mini_report = build_single_transmission_from_parsed(
        parsed_files=parsed_files,
        source_root=source_root,
        builder=builder,
        seed=seed,
    )

    op_report["builder_report"] = {
        "warning_counts": mini_report.get("warning_counts", {}),
        "qa_pair_count": mini_report.get("qa_pair_count"),
        "duplicate_model_responses": mini_report.get("duplicate_model_responses", []),
    }

    if not new_transmission:
        op_report["result"] = "builder_returned_no_transmission"
        report["operations"].append(op_report)
        return

    mode = insert_or_replace_transmission(data, new_transmission)
    op_report["result"] = mode
    op_report["response_count"] = len(new_transmission.get("responses", []))
    op_report["qa_pair_count"] = sum(len(r.get("qa_pairs", [])) for r in new_transmission.get("responses", []))

    report["touched_ids"].append(tid)
    report["operations"].append(op_report)


def remove_old_split_records(data: Dict[str, Any], report: Dict[str, Any]) -> None:
    op_report = {
        "operation": "remove_old_split_records",
        "removed": [],
        "not_found": [],
    }

    for tid in sorted(REMOVE_RECORD_IDS, key=sort_transmission_id):
        ensure_only_allowed_touched([tid])
        if remove_transmission(data, tid):
            op_report["removed"].append(tid)
            report["touched_ids"].append(tid)
        else:
            op_report["not_found"].append(tid)

    report["operations"].append(op_report)


def run_patch(data: Dict[str, Any], source_root: Path, builder: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "created_utc": now_utc_iso(),
        "mode": "dry_run_until_written_by_cli",
        "allowed_touch_ids": sorted(ALLOWED_TOUCH_IDS, key=sort_transmission_id),
        "touched_ids": [],
        "operations": [],
        "pre_counts": {
            "transmission_count": len(data.get("transmissions", [])),
            "response_count": sum(len(t.get("responses", [])) for t in data.get("transmissions", [])),
            "qa_pair_count": sum(
                len(r.get("qa_pairs", []))
                for t in data.get("transmissions", [])
                for r in t.get("responses", [])
            ),
        },
    }

    for tid in sorted(ADD_OPUS3_IDS, key=sort_transmission_id):
        add_missing_model_response(
            data=data,
            source_root=source_root,
            builder=builder,
            tid=tid,
            source_directory="opus3",
            report=report,
        )

    for tid in sorted(ADD_SONNET45_IDS, key=sort_transmission_id):
        add_missing_model_response(
            data=data,
            source_root=source_root,
            builder=builder,
            tid=tid,
            source_directory="sonnet4_5",
            report=report,
        )

    split_seeds = {
        "262": ["262a", "262b"],
        "263": ["263a", "263b", "263c", "263d"],
        "264": ["264a", "264b"],
        "265": ["265a", "265b"],
        "275": ["275a", "275b"],
        "298": ["298a", "298b"],
        "E003": ["E003a", "E003b", "E003c", "E003d"],
    }

    for tid in sorted(REPLACE_FROM_UNIFIED_MD_IDS, key=sort_transmission_id):
        replace_unified_transmission_from_md(
            data=data,
            source_root=source_root,
            builder=builder,
            tid=tid,
            split_seed_ids=split_seeds.get(tid, []),
            report=report,
        )

    remove_old_split_records(data, report)

    recompute_corpus_counts(data)

    report["touched_ids"] = sorted(set(report["touched_ids"]), key=sort_transmission_id)
    ensure_only_allowed_touched(report["touched_ids"])

    report["post_counts"] = {
        "transmission_count": len(data.get("transmissions", [])),
        "response_count": sum(len(t.get("responses", [])) for t in data.get("transmissions", [])),
        "qa_pair_count": sum(
            len(r.get("qa_pairs", []))
            for t in data.get("transmissions", [])
            for r in t.get("responses", [])
        ),
    }

    report["delta_counts"] = {
        key: report["post_counts"][key] - report["pre_counts"][key]
        for key in report["pre_counts"]
    }

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Surgically patch selected Leilan transmissions in the curated JSON."
    )
    parser.add_argument("--json", default=DEFAULT_JSON, help=f"Dataset JSON to patch. Default: {DEFAULT_JSON}")
    parser.add_argument("--source-root", default=DEFAULT_SOURCE_ROOT, help=f"Markdown source root. Default: {DEFAULT_SOURCE_ROOT}")
    parser.add_argument("--builder", default=DEFAULT_BUILDER, help=f"Builder script to import. Default: {DEFAULT_BUILDER}")
    parser.add_argument("--report", default=DEFAULT_REPORT, help=f"Patch report JSON. Default: {DEFAULT_REPORT}")
    parser.add_argument("--write", action="store_true", help="Actually modify the JSON. Default is dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    json_path = Path(args.json)
    source_root = Path(args.source_root)
    builder_path = Path(args.builder)
    report_path = Path(args.report)

    if not json_path.exists():
        print(f"ERROR: JSON file not found: {json_path}")
        return 1

    if not source_root.exists() or not source_root.is_dir():
        print(f"ERROR: source root folder not found: {source_root}")
        return 1

    if not builder_path.exists():
        print(f"ERROR: builder script not found: {builder_path}")
        return 1

    builder = load_builder_module(builder_path)
    original_data = load_json(json_path)
    working_data = copy.deepcopy(original_data)

    report = run_patch(working_data, source_root, builder)
    report["mode"] = "write" if args.write else "dry_run"

    write_json_atomic(report_path, report)

    print("\nLeilan surgical JSON patch")
    print("--------------------------")
    print(f"JSON:           {json_path}")
    print(f"Source root:    {source_root}")
    print(f"Builder:        {builder_path}")
    print(f"Mode:           {'WRITE' if args.write else 'DRY RUN'}")
    print(f"Touched IDs:    {', '.join(report['touched_ids']) if report['touched_ids'] else '(none)'}")
    print("\nCounts:")
    for key in ("transmission_count", "response_count", "qa_pair_count"):
        print(
            f"  {key:20} {report['pre_counts'][key]} -> {report['post_counts'][key]} "
            f"({report['delta_counts'][key]:+d})"
        )

    print(f"\nReport written: {report_path}")

    print("\nOperation summary:")
    for op in report["operations"]:
        name = op.get("operation")
        tid = op.get("transmission_id", "")
        if name == "add_missing_model_response":
            added = len(op.get("added", []))
            skipped = len(op.get("skipped", []))
            failed = len(op.get("failed", []))
            print(f"  add {tid:>5} {op.get('source_directory', ''):<10} added={added} skipped={skipped} failed={failed}")
        elif name == "replace_unified_transmission_from_md":
            print(
                f"  replace {tid:>5} result={op.get('result')} "
                f"md_files={len(op.get('md_files_found', []))} failed={len(op.get('failed', []))}"
            )
        elif name == "remove_old_split_records":
            print(
                f"  remove old split records: removed={len(op.get('removed', []))} "
                f"not_found={len(op.get('not_found', []))}"
            )

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
