#!/usr/bin/env python3
"""
sync_t080_query_and_external_sources.py

After hand-editing the T080 Markdown query, this script:

  1. Reads all T080 Markdown files under post-gpt3_transmissions_by_model/.
  2. Verifies their query frontmatter is identical.
  3. Adds/refreshes external_sources_json in those Markdown files with the
     four Substack image URLs from the prompt.
  4. Propagates the canonical T080 query + external source metadata into:
       - full_leilan_claude_dataset.json
       - combined_leilan_dataset.json
       - combined_leilan_dataset_records.jsonl

It does not change supplementary_materials_json, except to leave it in place.

Dry run:

    python3 scripts/sync_t080_query_and_external_sources.py

Apply:

    python3 scripts/sync_t080_query_and_external_sources.py --write

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

T080_EXTERNAL_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "T080-source-001",
        "type": "image",
        "role": "query_context",
        "title": "GPT-3 Playground rollout screenshot 1",
        "url": "https://substack-post-media.s3.amazonaws.com/public/images/16c4f3b7-5e0d-4bc9-a067-c6ea6f089e83_1373x496.png",
        "local_image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-01.png",
        "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-01.json",
        "note": "Remote image URL originally referenced in the query; local screenshot and structured transcription are included in supplementary materials."
    },
    {
        "id": "T080-source-002",
        "type": "image",
        "role": "query_context",
        "title": "GPT-3 Playground rollout screenshot 2",
        "url": "https://substack-post-media.s3.amazonaws.com/public/images/e26f0648-9a67-4d6e-8dbb-4e5851716089_1368x444.png",
        "local_image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-02.png",
        "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-02.json",
        "note": "Remote image URL originally referenced in the query; local screenshot and structured transcription are included in supplementary materials."
    },
    {
        "id": "T080-source-003",
        "type": "image",
        "role": "query_context",
        "title": "GPT-3 Playground rollout screenshot 3",
        "url": "https://substack-post-media.s3.amazonaws.com/public/images/46f80950-16d1-40ed-b33a-2574ea05787c_1371x464.png",
        "local_image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-03.png",
        "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-03.json",
        "note": "Remote image URL originally referenced in the query; local screenshot and structured transcription are included in supplementary materials."
    },
    {
        "id": "T080-source-004",
        "type": "image",
        "role": "query_context",
        "title": "GPT-3 Playground rollout screenshot 4",
        "url": "https://substack-post-media.s3.amazonaws.com/public/images/469c6a62-17d7-4fdd-b062-fa62eb4ff60a_837x493.png",
        "local_image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-04.png",
        "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-04.json",
        "note": "Remote image URL originally referenced in the query; local screenshot and structured transcription are included in supplementary materials."
    }
]

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
    if not m:
        return None
    return m.group(1).strip()


def yamlish_unquote(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    # Prefer JSON/YAML-ish double-quoted parse when possible.
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

            # Remove common leading indentation.
            nonblank = [ln for ln in block_lines if ln.strip()]
            indent = min((len(ln) - len(ln.lstrip(" \t")) for ln in nonblank), default=0)
            stripped = [ln[indent:] if len(ln) >= indent else ln for ln in block_lines]
            return "\n".join(stripped).strip()

        return yamlish_unquote(after)

    return None


def indent_block(text: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else prefix for line in text.splitlines())


def make_json_block(key: str, value: Any) -> str:
    dumped = json.dumps(value, ensure_ascii=False, indent=2)
    return f"{key}: |\n{indent_block(dumped, 2)}"


def remove_block_field(frontmatter: str, field_name: str) -> str:
    lines = frontmatter.splitlines()
    out: List[str] = []
    i = 0
    prefix = f"{field_name}:"
    while i < len(lines):
        line = lines[i]
        if line.startswith(prefix):
            i += 1
            while i < len(lines) and (lines[i].startswith(" ") or lines[i].strip() == ""):
                i += 1
            continue
        out.append(line)
        i += 1
    return "\n".join(out).rstrip() + "\n"


def patch_frontmatter_external_sources(text: str) -> Tuple[str, bool]:
    parts = split_frontmatter(text)
    if not parts:
        return text, False

    start, fm, rest = parts
    if frontmatter_id(fm) != TARGET_ID:
        return text, False

    old = text
    fm = remove_block_field(fm, "external_sources_json")
    fm = fm.rstrip() + "\n" + make_json_block("external_sources_json", T080_EXTERNAL_SOURCES) + "\n"

    new = start + fm + rest
    return new, new != old


def find_t080_md_files() -> List[Path]:
    files: List[Path] = []
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
    if not isinstance(value, list):
        return value
    new_items = []
    for item in value:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        if any(code in text for code in STALE_WARNING_CODES):
            continue
        new_items.append(item)
    return new_items


def set_first_qa_question(obj: Dict[str, Any], canonical_query: str) -> int:
    qa_pairs = obj.get("qa_pairs")
    if not isinstance(qa_pairs, list) or not qa_pairs:
        return 0
    first = qa_pairs[0]
    if not isinstance(first, dict):
        return 0
    if first.get("question") != canonical_query:
        first["question"] = canonical_query
        return 1
    return 0


def patch_response_like_object(obj: Dict[str, Any], canonical_query: str) -> int:
    before = json.dumps(obj, ensure_ascii=False, sort_keys=True)

    for key in ["metadata_query", "query", "source_query", "transmission_query"]:
        if key in obj:
            obj[key] = canonical_query

    if "question" in obj:
        obj["question"] = canonical_query

    set_first_qa_question(obj, canonical_query)

    for key in ["parse_warnings", "warnings", "build_warnings"]:
        if key in obj:
            obj[key] = remove_stale_warning_items(obj[key])

    after = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return int(after != before)


def verify_referenced_paths(warnings: List[str]) -> None:
    for source in T080_EXTERNAL_SOURCES:
        for key in ["local_image_path", "structured_json_path"]:
            p = source.get(key)
            if p and not Path(p).exists():
                warnings.append(f"Referenced {key} does not exist: {p}")


def get_canonical_query_from_md(warnings: List[str]) -> tuple[str | None, List[tuple[Path, str]]]:
    files = find_t080_md_files()
    queries: List[tuple[Path, str]] = []

    if not files:
        warnings.append("No T080 Markdown files found")
        return None, []

    for path in files:
        text = path.read_text(encoding="utf-8")
        parts = split_frontmatter(text)
        if not parts:
            warnings.append(f"No frontmatter found in {path}")
            continue
        query = extract_query(parts[1])
        if query is None:
            warnings.append(f"No query field found in {path}")
            continue
        queries.append((path, query))

    unique = {}
    for path, query in queries:
        unique.setdefault(query, []).append(path)

    if len(unique) != 1:
        warnings.append("T080 Markdown query fields are not identical; refusing to choose a canonical query.")
        for idx, (query, paths) in enumerate(unique.items(), start=1):
            preview = query[:300].replace("\n", "\\n")
            warnings.append(f"Variant {idx}: {len(paths)} file(s); preview: {preview}")
            for p in paths:
                warnings.append(f"  - {p}")
        return None, queries

    canonical_query = next(iter(unique.keys()))
    return canonical_query, queries


def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    changed = 0

    for path in find_t080_md_files():
        original = path.read_text(encoding="utf-8")
        patched, did_change = patch_frontmatter_external_sources(original)
        if did_change:
            changed += 1
            actions.append(f"Markdown {'would be patched' if not write else 'patched'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")

    return changed


def patch_claude_json(canonical_query: str, write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed = 0
    response_changes = 0
    found = False

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            continue
        if str(transmission.get("transmission_id", "")) != TARGET_ID:
            continue

        found = True
        before = json.dumps(transmission, ensure_ascii=False, sort_keys=True)

        transmission["external_sources"] = T080_EXTERNAL_SOURCES

        if "query" in transmission:
            transmission["query"] = canonical_query

        for key in ["build_warnings", "warnings", "parse_warnings"]:
            if key in transmission:
                transmission[key] = remove_stale_warning_items(transmission[key])

        responses = transmission.get("responses", [])
        if isinstance(responses, list):
            for response in responses:
                if isinstance(response, dict):
                    response_changes += patch_response_like_object(response, canonical_query)

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
            backup_file(CLAUDE_JSON, f"before-t080-query-and-sources-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed


def patch_combined_json_and_jsonl(canonical_query: str, write: bool, actions: List[str], warnings: List[str]) -> int:
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

        before = json.dumps(record, ensure_ascii=False, sort_keys=True)

        record["external_sources"] = T080_EXTERNAL_SOURCES
        patch_response_like_object(record, canonical_query)

        after = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed += 1

    if changed == 0:
        warnings.append(f"T{TARGET_ID}: no combined records needed patching or none found")

    if changed:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed} record(s)")
        if write:
            backup_file(COMBINED_JSON, f"before-t080-query-and-sources-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync T080 hand-edited query and external image URLs into JSON/JSONL.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write = args.write

    actions: List[str] = []
    warnings: List[str] = []

    verify_referenced_paths(warnings)
    canonical_query, query_files = get_canonical_query_from_md(warnings)

    if canonical_query is None:
        print("\nT080 query + external source sync")
        print("---------------------------------")
        print("Mode: " + ("WRITE" if write else "DRY RUN"))
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")
        print("\nNo changes made. Make the T080 query frontmatter identical across the Markdown files, then rerun.")
        return 1

    md_changed = patch_markdown(write, actions, warnings)
    claude_changed = patch_claude_json(canonical_query, write, actions, warnings)
    combined_changed = patch_combined_json_and_jsonl(canonical_query, write, actions, warnings)

    print("\nT080 query + external source sync")
    print("---------------------------------")
    print("Mode: " + ("WRITE" if write else "DRY RUN"))
    print(f"T080 Markdown files found:     {len(query_files)}")
    print(f"Markdown files changed:        {md_changed}")
    print(f"Claude transmissions changed:  {claude_changed}")
    print(f"Combined records changed:      {combined_changed}")

    print("\nCanonical query preview:")
    print(canonical_query[:1000] + ("..." if len(canonical_query) > 1000 else ""))

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

    if not write:
        print("\nDry run only. If this looks right, run:")
        print("  python3 scripts/sync_t080_query_and_external_sources.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
