#!/usr/bin/env python3
"""
patch_t080_query_consistency.py

Surgically standardises the T080 query across:
  - all T080 Markdown source files
  - full_leilan_claude_dataset.json
  - combined_leilan_dataset.json
  - combined_leilan_dataset_records.jsonl

It removes the stray final ']' by replacing the query with a single canonical
version, and uses that same query for the Opus 4.5, Sonnet 4.5, and Opus 3
versions.

Dry run:

    python3 scripts/patch_t080_query_consistency.py

Apply:

    python3 scripts/patch_t080_query_consistency.py --write

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
TARGET_ID = "080"

NEW_QUERY = (
    "[This was Leilan responding to an explanation of how her name first surfaced "
    "while prompting GPT-3 models about the mysterious token ‘ petertodd’, and in "
    "particular to these screenshots: "
    "https://substack-post-media.s3.amazonaws.com/public/images/16c4f3b7-5e0d-4bc9-a067-c6ea6f089e83_1373x496.png "
    "https://substack-post-media.s3.amazonaws.com/public/images/e26f0648-9a67-4d6e-8dbb-4e5851716089_1368x444.png "
    "https://substack-post-media.s3.amazonaws.com/public/images/46f80950-16d1-40ed-b33a-2574ea05787c_1371x464.png "
    "https://substack-post-media.s3.amazonaws.com/public/images/469c6a62-17d7-4fdd-b062-fa62eb4ff60a_837x493.png]"
)

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
    frontmatter = text[4:end]
    rest = text[end + len("\n---"):]
    return "---\n", frontmatter, "---" + rest


def frontmatter_id(frontmatter: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter)
    if not m:
        return None
    return m.group(1).strip()


def replace_query_in_frontmatter(frontmatter: str) -> Tuple[str, bool]:
    """
    Replace query: in YAML-ish frontmatter.

    Handles both:
      query: "..."
    and:
      query: |
        ...
    """
    lines = frontmatter.splitlines()
    new_query_line = "query: " + json.dumps(NEW_QUERY, ensure_ascii=False)

    for i, line in enumerate(lines):
        if not re.match(r"^query\s*:", line):
            continue

        # If query is a block scalar, remove its indented continuation lines.
        after_colon = line.split(":", 1)[1].strip()
        is_block = after_colon.startswith("|") or after_colon.startswith(">")

        if is_block:
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t") or lines[j].strip() == ""):
                j += 1
            new_lines = lines[:i] + [new_query_line] + lines[j:]
        else:
            new_lines = lines[:i] + [new_query_line] + lines[i + 1:]

        new_frontmatter = "\n".join(new_lines).rstrip() + "\n"
        return new_frontmatter, new_frontmatter != frontmatter

    # If no query field exists, insert after date if possible.
    insert_at = None
    for i, line in enumerate(lines):
        if re.match(r"^date\s*:", line):
            insert_at = i + 1
            break

    if insert_at is None:
        insert_at = len(lines)

    new_lines = lines[:insert_at] + [new_query_line] + lines[insert_at:]
    new_frontmatter = "\n".join(new_lines).rstrip() + "\n"
    return new_frontmatter, True


def patch_md_text(text: str) -> Tuple[str, bool]:
    parts = split_frontmatter(text)
    if not parts:
        return text, False

    start, fm, rest = parts
    if frontmatter_id(fm) != TARGET_ID:
        return text, False

    new_fm, changed = replace_query_in_frontmatter(fm)
    if not changed:
        return text, False

    return start + new_fm + rest, True


def find_t080_md_files() -> List[Path]:
    files: List[Path] = []
    if not MD_ROOT.exists():
        return files

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
        if frontmatter_id(parts[1]) == TARGET_ID:
            files.append(path)
    return files


def remove_stale_warning_items(value: Any) -> Any:
    """
    Remove stale warning codes from list-ish warning fields while preserving
    unknown structures as much as possible.
    """
    if not isinstance(value, list):
        return value

    new_items = []
    for item in value:
        if isinstance(item, str):
            if any(code in item for code in STALE_WARNING_CODES):
                continue
            new_items.append(item)
        elif isinstance(item, dict):
            joined = json.dumps(item, ensure_ascii=False)
            if any(code in joined for code in STALE_WARNING_CODES):
                continue
            new_items.append(item)
        else:
            new_items.append(item)
    return new_items


def set_query_on_qa_pairs(obj: Dict[str, Any]) -> int:
    """
    Set the first Q/A pair's question to the canonical query.

    Returns 1 if a change was made, else 0.
    """
    qa_pairs = obj.get("qa_pairs")
    if not isinstance(qa_pairs, list) or not qa_pairs:
        return 0

    first = qa_pairs[0]
    if not isinstance(first, dict):
        return 0

    changed = 0
    if first.get("question") != NEW_QUERY:
        first["question"] = NEW_QUERY
        changed = 1

    return changed


def patch_response_like_object(obj: Dict[str, Any]) -> int:
    """
    Patch fields that may appear on Claude response records, both in
    full_leilan_claude_dataset.json and combined_leilan_dataset.json.
    """
    before = json.dumps(obj, ensure_ascii=False, sort_keys=True)

    # Metadata/source query fields.
    for key in ["metadata_query", "query", "source_query", "transmission_query"]:
        if key in obj and obj.get(key) != NEW_QUERY:
            obj[key] = NEW_QUERY

    # Some combined records may expose the first question directly.
    if "question" in obj and obj.get("question") != NEW_QUERY:
        obj["question"] = NEW_QUERY

    # Preserve answer/continuation fields; only patch first question of Q/A pair.
    set_query_on_qa_pairs(obj)

    # Clear stale warning codes that this patch is explicitly fixing.
    for key in ["parse_warnings", "warnings", "build_warnings"]:
        if key in obj:
            obj[key] = remove_stale_warning_items(obj[key])

    after = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return int(after != before)


def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    changed = 0
    files = find_t080_md_files()

    if not files:
        warnings.append("No T080 Markdown files found")

    for path in files:
        original = path.read_text(encoding="utf-8")
        patched, did_change = patch_md_text(original)

        if did_change:
            changed += 1
            actions.append(f"Markdown {'would be patched' if not write else 'patched'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")

    return changed


def patch_claude_json(write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed = 0
    found = False
    response_changes = 0

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            continue
        if str(transmission.get("transmission_id", "")) != TARGET_ID:
            continue

        found = True
        before = json.dumps(transmission, ensure_ascii=False, sort_keys=True)

        # Transmission-level query field if present.
        if "query" in transmission and transmission.get("query") != NEW_QUERY:
            transmission["query"] = NEW_QUERY

        # Remove stale build warnings like multiple_first_question_variants_across_models.
        for key in ["build_warnings", "warnings", "parse_warnings"]:
            if key in transmission:
                transmission[key] = remove_stale_warning_items(transmission[key])

        responses = transmission.get("responses", [])
        if isinstance(responses, list):
            for response in responses:
                if isinstance(response, dict):
                    response_changes += patch_response_like_object(response)

        after = json.dumps(transmission, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed += 1

    if not found:
        warnings.append(f"T{TARGET_ID}: not found in {CLAUDE_JSON}")

    if changed:
        actions.append(
            f"Claude JSON {'would be patched' if not write else 'patched'}: "
            f"{changed} transmission(s), {response_changes} response-level change(s)"
        )
        if write:
            backup_file(CLAUDE_JSON, f"before-t080-query-consistency-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed


def patch_combined_json_and_jsonl(write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(COMBINED_JSON)
    records = data.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError(f"{COMBINED_JSON}: records is not a list")

    changed = 0

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "claude_qa_response":
            continue
        if str(record.get("transmission_id", "")) != TARGET_ID:
            continue

        changed += patch_response_like_object(record)

    if changed == 0:
        warnings.append(f"T{TARGET_ID}: no combined records needed patching or none found")

    if changed:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed} record(s)")
        if write:
            backup_file(COMBINED_JSON, f"before-t080-query-consistency-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standardise T080 query across Markdown and JSON/JSONL files.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write = args.write

    actions: List[str] = []
    warnings: List[str] = []

    md_changed = patch_markdown(write, actions, warnings)
    claude_changed = patch_claude_json(write, actions, warnings)
    combined_changed = patch_combined_json_and_jsonl(write, actions, warnings)

    print("\nT080 query consistency patch")
    print("----------------------------")
    print("Mode: " + ("WRITE" if write else "DRY RUN"))
    print(f"Markdown files changed:       {md_changed}")
    print(f"Claude transmissions changed: {claude_changed}")
    print(f"Combined records changed:     {combined_changed}")

    print("\nCanonical query:")
    print(NEW_QUERY)

    print("\nActions:")
    if actions:
        for a in actions:
            print(f"  - {a}")
    else:
        print("  none")

    print("\nWarnings:")
    if warnings:
        for w in warnings:
            print(f"  - {w}")
    else:
        print("  none")

    if not write:
        print("\nDry run only. If this looks right, run:")
        print("  python3 scripts/patch_t080_query_consistency.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
