#!/usr/bin/env python3
"""
sync_t032_query_from_markdown.py

Surgically propagates the current T032 Markdown frontmatter query into the
large JSON/JSONL dataset files, without a full rebuild.

Use this after hand-editing the T032 query in the Markdown files.

It:
  - finds all Markdown files with id: "032"
  - extracts each file's query frontmatter
  - matches each Markdown file to the corresponding response by source_file
  - updates metadata_query / query / source_query / transmission_query when present
  - updates the first qa_pairs[].question
  - updates combined_leilan_dataset_records.jsonl from combined_leilan_dataset.json
  - removes stale query-mismatch warning codes from the patched records

Dry run:
    python3 scripts/sync_t032_query_from_markdown.py

Apply:
    python3 scripts/sync_t032_query_from_markdown.py --write

Then:
    python3 scripts/generate_manifest.py
    python3 scripts/validate_dataset.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


MD_ROOT = Path("post-gpt3_transmissions_by_model")
CLAUDE_JSON = Path("full_leilan_claude_dataset.json")
COMBINED_JSON = Path("combined_leilan_dataset.json")
COMBINED_JSONL = Path("combined_leilan_dataset_records.jsonl")
TARGET_ID = "032"

STALE_WARNING_CODES = {
    "metadata_query_differs_from_first_body_question",
    "multiple_first_question_variants_across_models",
}


def now_stamp() -> str:
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


def write_jsonl_atomic(path: Path, records: List[Dict[str, Any]]) -> None:
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


def backup_file(path: Path, suffix: str) -> Path:
    backup = path.with_name(f"{path.name}.backup-{suffix}")
    shutil.copy2(path, backup)
    return backup


def split_frontmatter(text: str) -> Tuple[str, str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return "---\n", text[4:end], "---" + text[end + len("\n---"):]


def frontmatter_id(frontmatter: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter)
    return m.group(1).strip() if m else None


def yamlish_unquote(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value)
        except Exception:
            return value[1:-1]
    return value


def extract_query(frontmatter: str) -> str | None:
    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        if not re.match(r"^query\s*:", line):
            continue

        after = line.split(":", 1)[1].strip()

        if after.startswith("|") or after.startswith(">"):
            block_lines: List[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t") or lines[j].strip() == ""):
                block_lines.append(lines[j])
                j += 1

            nonblank = [ln for ln in block_lines if ln.strip()]
            indent = min((len(ln) - len(ln.lstrip(" \t")) for ln in nonblank), default=0)
            stripped = [ln[indent:] if len(ln) >= indent else ln for ln in block_lines]
            return "\n".join(stripped).strip()

        return yamlish_unquote(after)

    return None


def source_key(path: Path) -> str:
    return path.as_posix()


def source_filename(path: Path) -> str:
    return path.name


def source_directory(path: Path) -> str:
    return path.parent.name


def find_t032_queries() -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}

    for path in sorted(MD_ROOT.rglob("*.md")):
        if path.name == "README.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        parts = split_frontmatter(text)
        if not parts:
            continue

        _, fm, _ = parts
        if frontmatter_id(fm) != TARGET_ID:
            continue

        query = extract_query(fm)
        if query is None:
            continue

        out[source_key(path)] = {
            "source_file": source_key(path),
            "source_filename": source_filename(path),
            "source_directory": source_directory(path),
            "query": query,
        }

    return out


def remove_stale_warning_items(value: Any) -> Any:
    if not isinstance(value, list):
        return value

    new_items = []
    for item in value:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        if any(code in text for code in STALE_WARNING_CODES):
            continue
        new_items.append(item)
    return new_items


def source_file_matches(obj: Dict[str, Any], md_meta: Dict[str, str]) -> bool:
    obj_source_file = str(obj.get("source_file", ""))
    obj_source_filename = str(obj.get("source_filename", ""))
    obj_source_directory = str(obj.get("source_directory", ""))

    md_source_file = md_meta["source_file"]
    md_source_filename = md_meta["source_filename"]
    md_source_directory = md_meta["source_directory"]

    if obj_source_file == md_source_file:
        return True

    if obj_source_file.endswith(md_source_file):
        return True

    if obj_source_filename == md_source_filename and obj_source_directory == md_source_directory:
        return True

    return False


def set_first_qa_question(obj: Dict[str, Any], query: str) -> int:
    qa_pairs = obj.get("qa_pairs")
    if not isinstance(qa_pairs, list) or not qa_pairs:
        return 0

    first = qa_pairs[0]
    if not isinstance(first, dict):
        return 0

    if first.get("question") != query:
        first["question"] = query
        return 1

    return 0


def patch_response_like_object(obj: Dict[str, Any], query: str) -> int:
    before = json.dumps(obj, ensure_ascii=False, sort_keys=True)

    for key in ["metadata_query", "query", "source_query", "transmission_query"]:
        if key in obj:
            obj[key] = query

    if "question" in obj:
        obj["question"] = query

    set_first_qa_question(obj, query)

    for key in ["parse_warnings", "warnings", "build_warnings"]:
        if key in obj:
            obj[key] = remove_stale_warning_items(obj[key])

    after = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return int(after != before)


def patch_claude_json(md_queries: Dict[str, Dict[str, str]], write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed_responses = 0
    matched_sources = set()

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            continue
        if str(transmission.get("transmission_id", "")) != TARGET_ID:
            continue

        for key in ["build_warnings", "warnings", "parse_warnings"]:
            if key in transmission:
                transmission[key] = remove_stale_warning_items(transmission[key])

        responses = transmission.get("responses", [])
        if not isinstance(responses, list):
            continue

        for response in responses:
            if not isinstance(response, dict):
                continue

            for md_source, md_meta in md_queries.items():
                if source_file_matches(response, md_meta):
                    changed_responses += patch_response_like_object(response, md_meta["query"])
                    matched_sources.add(md_source)
                    break

    missing = set(md_queries) - matched_sources
    for md_source in sorted(missing):
        warnings.append(f"No Claude JSON response matched Markdown source: {md_source}")

    if changed_responses:
        actions.append(f"Claude JSON {'would be patched' if not write else 'patched'}: {changed_responses} response(s)")
        if write:
            backup_file(CLAUDE_JSON, f"before-t032-query-sync-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed_responses


def patch_combined_jsonl(md_queries: Dict[str, Dict[str, str]], write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(COMBINED_JSON)
    records = data.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError(f"{COMBINED_JSON}: records is not a list")

    changed_records = 0
    matched_sources = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "claude_qa_response":
            continue
        if str(record.get("transmission_id", "")) != TARGET_ID:
            continue

        for md_source, md_meta in md_queries.items():
            if source_file_matches(record, md_meta):
                changed_records += patch_response_like_object(record, md_meta["query"])
                matched_sources.add(md_source)
                break

    missing = set(md_queries) - matched_sources
    for md_source in sorted(missing):
        warnings.append(f"No combined record matched Markdown source: {md_source}")

    if changed_records:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed_records} record(s)")
        if write:
            backup_file(COMBINED_JSON, f"before-t032-query-sync-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed_records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync T032 query edits from Markdown into JSON/JSONL.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions: List[str] = []
    warnings: List[str] = []

    md_queries = find_t032_queries()

    if not md_queries:
        print("\nT032 query sync from Markdown")
        print("-----------------------------")
        print("No T032 Markdown queries found. No changes made.")
        return 1

    claude_changed = patch_claude_json(md_queries, args.write, actions, warnings)
    combined_changed = patch_combined_jsonl(md_queries, args.write, actions, warnings)

    print("\nT032 query sync from Markdown")
    print("-----------------------------")
    print("Mode: " + ("WRITE" if args.write else "DRY RUN"))
    print(f"T032 Markdown files found: {len(md_queries)}")
    print(f"Claude responses changed: {claude_changed}")
    print(f"Combined records changed: {combined_changed}")

    print("\nMarkdown queries found:")
    for md_source, md_meta in sorted(md_queries.items()):
        preview = md_meta["query"][:240].replace("\n", "\\n")
        print(f"  - {md_source}")
        print(f"    preview: {preview}" + ("..." if len(md_meta["query"]) > 240 else ""))

    print("\nActions:")
    if actions:
        for action in actions:
            print(f"  - {action}")
    else:
        print("  none")

    print("\nWarnings:")
    if warnings:
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("  none")

    if not args.write:
        print("\nDry run only. If this looks right, run:")
        print("  python3 scripts/sync_t032_query_from_markdown.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
