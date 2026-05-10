#!/usr/bin/env python3
"""
group_t080_supplementary_metadata.py

Simplify T080 supplementary metadata by replacing four repeated
image_with_transcription objects with one grouped object pointing harvesters
to the four structured JSON files.

Patches:
  - T080 Markdown source files under post-gpt3_transmissions_by_model/
  - full_leilan_claude_dataset.json
  - combined_leilan_dataset.json
  - combined_leilan_dataset_records.jsonl

Does NOT delete .txt files. It simply stops foregrounding them in the main
metadata. The .json files remain the canonical machine-readable supplementary
transcriptions.

Dry run:

    python3 scripts/group_t080_supplementary_metadata.py

Apply:

    python3 scripts/group_t080_supplementary_metadata.py --write

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


GROUPED_T080_SUPPLEMENTARY_MATERIALS: List[Dict[str, Any]] = [
    {
        "id": "T080-playground-rollouts",
        "type": "gpt3_playground_rollout_set",
        "role": "query_context",
        "title": "Four GPT-3 Playground rollouts referenced in the query",
        "directory": "supplementary_materials/080",
        "items": [
            {
                "id": "T080-playground-rollout-01",
                "image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-01.png",
                "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-01.json"
            },
            {
                "id": "T080-playground-rollout-02",
                "image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-02.png",
                "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-02.json"
            },
            {
                "id": "T080-playground-rollout-03",
                "image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-03.png",
                "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-03.json"
            },
            {
                "id": "T080-playground-rollout-04",
                "image_path": "supplementary_materials/080/t080-gpt3-playground-rollout-04.png",
                "structured_json_path": "supplementary_materials/080/t080-gpt3-playground-rollout-04.json"
            }
        ],
        "note": (
            "The query referred to four GPT-3 Playground screenshots. "
            "The structured JSON files contain the extracted prompt, continuation, "
            "model, temperature, maximum length, and top p values."
        ),
        "rights_note": (
            "Screenshots and structured transcriptions are of curator-generated "
            "GPT-3 Playground outputs and are included for provenance."
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


def indent_block(text: str, spaces: int = 2) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else prefix for line in text.splitlines())


def make_metadata_block(key: str, value: List[Dict[str, Any]]) -> str:
    dumped = json.dumps(value, ensure_ascii=False, indent=2)
    return f"{key}: |\n{indent_block(dumped, 2)}"


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


def patch_md_frontmatter(text: str) -> Tuple[str, bool]:
    parts = split_frontmatter(text)
    if not parts:
        return text, False

    start, fm, rest = parts
    if frontmatter_id(fm) != TARGET_ID:
        return text, False

    old = text

    fm = remove_block_field(fm, "supplementary_materials_json")
    fm = fm.rstrip() + "\n" + make_metadata_block(
        "supplementary_materials_json",
        GROUPED_T080_SUPPLEMENTARY_MATERIALS
    ) + "\n"

    new = start + fm + rest
    return new, new != old


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


def validate_referenced_paths(warnings: List[str]) -> None:
    for group in GROUPED_T080_SUPPLEMENTARY_MATERIALS:
        directory = group.get("directory")
        if directory and not Path(directory).exists():
            warnings.append(f"Referenced directory does not exist: {directory}")

        for item in group.get("items", []):
            for key in ["image_path", "structured_json_path"]:
                p = item.get(key)
                if p and not Path(p).exists():
                    warnings.append(f"Referenced {key} does not exist: {p}")


def patch_markdown(write: bool, actions: List[str]) -> int:
    changed = 0
    for path in find_t080_md_files():
        original = path.read_text(encoding="utf-8")
        patched, did_change = patch_md_frontmatter(original)
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

    for transmission in transmissions:
        if not isinstance(transmission, dict):
            continue
        if str(transmission.get("transmission_id", "")) != TARGET_ID:
            continue

        found = True
        before = json.dumps(transmission.get("supplementary_materials"), ensure_ascii=False, sort_keys=True)
        after = json.dumps(GROUPED_T080_SUPPLEMENTARY_MATERIALS, ensure_ascii=False, sort_keys=True)

        if before != after:
            transmission["supplementary_materials"] = GROUPED_T080_SUPPLEMENTARY_MATERIALS
            changed += 1

    if not found:
        warnings.append(f"T{TARGET_ID}: not found in {CLAUDE_JSON}")

    if changed:
        actions.append(f"Claude JSON {'would be patched' if not write else 'patched'}: T{TARGET_ID}")
        if write:
            backup_file(CLAUDE_JSON, f"before-t080-grouped-supplementary-{now_stamp()}")
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

        before = json.dumps(record.get("supplementary_materials"), ensure_ascii=False, sort_keys=True)
        after = json.dumps(GROUPED_T080_SUPPLEMENTARY_MATERIALS, ensure_ascii=False, sort_keys=True)

        if before != after:
            record["supplementary_materials"] = GROUPED_T080_SUPPLEMENTARY_MATERIALS
            changed += 1

    if changed == 0:
        warnings.append(f"T{TARGET_ID}: no combined records needed patching or none found")

    if changed:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed} records")
        if write:
            backup_file(COMBINED_JSON, f"before-t080-grouped-supplementary-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group/simplify T080 supplementary metadata.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write = args.write

    actions: List[str] = []
    warnings: List[str] = []

    validate_referenced_paths(warnings)

    md_changed = patch_markdown(write, actions)
    claude_changed = patch_claude_json(write, actions, warnings)
    combined_changed = patch_combined_json_and_jsonl(write, actions, warnings)

    print("\nT080 grouped supplementary metadata patch")
    print("-----------------------------------------")
    print("Mode: " + ("WRITE" if write else "DRY RUN"))
    print(f"Markdown files changed:      {md_changed}")
    print(f"Claude transmissions changed:{claude_changed:>7}")
    print(f"Combined records changed:    {combined_changed}")

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
        print("  python3 scripts/group_t080_supplementary_metadata.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
