#!/usr/bin/env python3
"""
add_t356_summary_supplementary_material.py

Adds supplementary-material metadata for Transmission 356, pointing to:

    supplementary_materials/356/text_summary.txt

This is intended for the factual/academic-style summary of the relevant
Graeber & Wengrow passage, since the copyrighted 8-page source passage is not
included in the repo.

Patches:
  - all T356 Markdown source files under post-gpt3_transmissions_by_model/
  - full_leilan_claude_dataset.json
  - combined_leilan_dataset.json
  - combined_leilan_dataset_records.jsonl

Also updates content_sha256 for the patched Markdown files inside both JSON
datasets.

Dry run:
    python3 scripts/add_t356_summary_supplementary_material.py

Apply:
    python3 scripts/add_t356_summary_supplementary_material.py --write

Then:
    python3 scripts/generate_manifest.py
    python3 scripts/validate_dataset.py
"""

from __future__ import annotations

import argparse
import hashlib
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

TARGET_ID = "356"

T356_SUPPLEMENTARY_MATERIALS: List[Dict[str, Any]] = [
    {
        "id": "T356-summary-001",
        "type": "text_summary",
        "role": "query_context",
        "title": "Summary of the relevant Graeber & Wengrow passage",
        "path": "supplementary_materials/356/text_summary.txt",
        "source_reference": "David Graeber and David Wengrow, The Dawn of Everything, pp. 432–440",
        "rights_note": (
            "The copyrighted book passage itself is not included. This file is a "
            "curator-supplied factual/academic-style summary for context."
        ),
        "note": (
            "Supplementary context for Transmission 356, whose query refers to the "
            "relevant passage of Graeber and Wengrow on Minoan civilisation."
        )
    }
]


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: Any) -> None:
    path = path.resolve()
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent), text=True)
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
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent), text=True)
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def split_frontmatter_body(text: str) -> Tuple[str, str, str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    closing_start = end + 1
    closing_end = closing_start + 3
    return "---\n", text[4:end], "---", text[closing_end:]


def reassemble(opening: str, frontmatter: str, closing: str, body: str) -> str:
    return opening + frontmatter.rstrip() + "\n" + closing + body


def frontmatter_id(frontmatter: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter)
    return m.group(1).strip() if m else None


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


def set_json_block(frontmatter: str, key: str, value: Any) -> str:
    frontmatter = remove_block_field(frontmatter, key)
    return frontmatter.rstrip() + "\n" + make_json_block(key, value) + "\n"


def find_t356_md_files() -> List[Path]:
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
        parts = split_frontmatter_body(text)
        if not parts:
            continue
        if frontmatter_id(parts[1]) == TARGET_ID:
            files.append(path)
    return files


def source_file_matches(obj: Dict[str, Any], path: Path) -> bool:
    source_file = str(obj.get("source_file", ""))
    source_filename = str(obj.get("source_filename", ""))
    source_directory = str(obj.get("source_directory", ""))

    rel = path.as_posix()
    return (
        source_file == rel
        or source_file.endswith(rel)
        or (source_filename == path.name and source_directory == path.parent.name)
    )


def verify_paths(warnings: List[str]) -> None:
    for item in T356_SUPPLEMENTARY_MATERIALS:
        p = item.get("path")
        if p and not Path(p).exists():
            warnings.append(f"Referenced supplementary material does not exist: {p}")


def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> Dict[str, str]:
    updated_hashes: Dict[str, str] = {}
    files = find_t356_md_files()

    if not files:
        warnings.append("No T356 Markdown files found.")

    for path in files:
        original = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(original)
        if not parts:
            warnings.append(f"T356 file has no usable frontmatter: {path}")
            continue

        opening, fm, closing, body = parts
        fm2 = set_json_block(fm, "supplementary_materials_json", T356_SUPPLEMENTARY_MATERIALS)
        patched = reassemble(opening, fm2, closing, body)

        if patched != original:
            actions.append(f"Markdown {'would be patched' if not write else 'patched'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")
                updated_hashes[path.as_posix()] = sha256_file(path)
            else:
                updated_hashes[path.as_posix()] = sha256_bytes(patched.encode("utf-8"))

    return updated_hashes


def patch_claude_json(updated_hashes: Dict[str, str], write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed = 0
    found = False
    matched_hash_paths = set()

    for t in transmissions:
        if not isinstance(t, dict):
            continue
        if str(t.get("transmission_id", "")) != TARGET_ID:
            continue

        found = True
        before = json.dumps(t, ensure_ascii=False, sort_keys=True)

        # Transmission-level context: applies to all model variants.
        t["supplementary_materials"] = T356_SUPPLEMENTARY_MATERIALS

        responses = t.get("responses", [])
        if isinstance(responses, list):
            for response in responses:
                if not isinstance(response, dict):
                    continue

                # Also add response-level context for consumers that only inspect responses.
                response["supplementary_materials"] = T356_SUPPLEMENTARY_MATERIALS

                for path_str, digest in updated_hashes.items():
                    path = Path(path_str)
                    if source_file_matches(response, path):
                        response["content_sha256"] = digest
                        matched_hash_paths.add(path_str)

        after = json.dumps(t, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed += 1

    if not found:
        warnings.append(f"T{TARGET_ID}: not found in {CLAUDE_JSON}")

    for path_str in sorted(set(updated_hashes) - matched_hash_paths):
        warnings.append(f"No Claude JSON response matched updated Markdown file: {path_str}")

    if changed:
        actions.append(f"Claude JSON {'would be patched' if not write else 'patched'}: {changed} transmission(s)")
        if write:
            backup_file(CLAUDE_JSON, f"before-t356-summary-supplementary-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed


def patch_combined_jsonl(updated_hashes: Dict[str, str], write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(COMBINED_JSON)
    records = data.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError(f"{COMBINED_JSON}: records is not a list")

    changed = 0
    matched_hash_paths = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "claude_qa_response":
            continue
        if str(record.get("transmission_id", "")) != TARGET_ID:
            continue

        before = json.dumps(record, ensure_ascii=False, sort_keys=True)

        record["supplementary_materials"] = T356_SUPPLEMENTARY_MATERIALS

        for path_str, digest in updated_hashes.items():
            path = Path(path_str)
            if source_file_matches(record, path):
                record["content_sha256"] = digest
                matched_hash_paths.add(path_str)

        after = json.dumps(record, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed += 1

    for path_str in sorted(set(updated_hashes) - matched_hash_paths):
        warnings.append(f"No combined record matched updated Markdown file: {path_str}")

    if changed:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed} record(s)")
        if write:
            backup_file(COMBINED_JSON, f"before-t356-summary-supplementary-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add T356 summary supplementary-material metadata and propagate to JSON.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions: List[str] = []
    warnings: List[str] = []

    verify_paths(warnings)

    updated_hashes = patch_markdown(args.write, actions, warnings)
    claude_changed = patch_claude_json(updated_hashes, args.write, actions, warnings)
    combined_changed = patch_combined_jsonl(updated_hashes, args.write, actions, warnings)

    print("\nT356 summary supplementary-material patch")
    print("-----------------------------------------")
    print("Mode: " + ("WRITE" if args.write else "DRY RUN"))
    print(f"Markdown files changed:       {len(updated_hashes)}")
    print(f"Claude transmissions changed: {claude_changed}")
    print(f"Combined records changed:     {combined_changed}")

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
        print("  python3 scripts/add_t356_summary_supplementary_material.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
