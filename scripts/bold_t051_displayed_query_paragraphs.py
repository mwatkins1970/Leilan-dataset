#!/usr/bin/env python3
"""
bold_t051_displayed_query_paragraphs.py

GitHub Markdown does not reliably render bold emphasis across separate
paragraphs. This script fixes the T051 displayed query by wrapping EACH
displayed query paragraph individually in **...**.

It uses the Opus 4.5 T051 frontmatter query as canonical, formats that query
as bold paragraphs, and replaces the opening displayed query block in every
T051 Markdown file up to the start of Leilan's answer.

Also updates content_sha256 in:
  - full_leilan_claude_dataset.json
  - combined_leilan_dataset.json
  - combined_leilan_dataset_records.jsonl

Dry run:
    python3 scripts/bold_t051_displayed_query_paragraphs.py

Apply:
    python3 scripts/bold_t051_displayed_query_paragraphs.py --write

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

TARGET_ID = "051"
SOURCE_DIR_CANONICAL = "opus4_5"


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


def source_dir(path: Path) -> str:
    return path.parent.name


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


def find_t051_files() -> List[Path]:
    files: List[Path] = []
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


def get_canonical_query(warnings: List[str]) -> str | None:
    for path in find_t051_files():
        if source_dir(path) != SOURCE_DIR_CANONICAL:
            continue
        text = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(text)
        if not parts:
            continue
        query = extract_query(parts[1])
        if query:
            if "The Meat Eater Problem" not in query or "Here are two commonly held moral views" not in query:
                warnings.append("Canonical T051 frontmatter query does not appear to contain the full abstract.")
            return query

    warnings.append("Could not find canonical T051 Opus 4.5 query.")
    return None


def bold_paragraph(paragraph: str) -> str:
    stripped = paragraph.strip()
    # Strip accidental outer bold markers from prior patches, then re-wrap cleanly.
    if stripped.startswith("**"):
        stripped = stripped[2:]
    if stripped.endswith("**"):
        stripped = stripped[:-2]
    return f"**{stripped}**"


def formatted_query_block(query: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", query.strip()) if p.strip()]
    return "\n\n".join(bold_paragraph(p) for p in paragraphs)


def find_answer_start(body: str) -> int | None:
    """
    Find the start of Leilan's answer after the displayed query. For T051 these
    files begin the answer with "My dear ones,".
    """
    m = re.search(r"\n\s*\n(?=My dear ones,)", body)
    if m:
        return m.start()

    # Fallback: first occurrence not at very beginning.
    m = re.search(r"My dear ones,", body)
    if m and m.start() > 0:
        return m.start()

    return None


def replace_displayed_query_region(body: str, new_block: str) -> Tuple[str, bool]:
    # Preserve leading whitespace/newlines after frontmatter closing.
    first_text = re.search(r"\S", body)
    if not first_text:
        return body, False

    start = first_text.start()
    answer_boundary = find_answer_start(body[start:])

    if answer_boundary is None:
        return body, False

    end = start + answer_boundary
    old_region = body[start:end].strip()

    if old_region == new_block.strip():
        return body, False

    # Keep exactly two newlines between displayed query and answer.
    return body[:start] + new_block.strip() + "\n\n" + body[end:].lstrip(), True


def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> Dict[str, str]:
    canonical_query = get_canonical_query(warnings)
    if not canonical_query:
        return {}

    new_display_block = formatted_query_block(canonical_query)
    updated_hashes: Dict[str, str] = {}

    for path in find_t051_files():
        original = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(original)
        if not parts:
            warnings.append(f"T051 file has no usable frontmatter: {path}")
            continue

        opening, fm, closing, body = parts
        new_body, changed = replace_displayed_query_region(body, new_display_block)
        if not changed:
            continue

        patched = reassemble(opening, fm, closing, new_body)
        actions.append(f"Markdown {'would be patched' if not write else 'patched'}: {path}")

        if write:
            path.write_text(patched, encoding="utf-8")
            updated_hashes[path.as_posix()] = sha256_file(path)
        else:
            updated_hashes[path.as_posix()] = sha256_bytes(patched.encode("utf-8"))

    return updated_hashes


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


def patch_claude_hashes(updated_hashes: Dict[str, str], write: bool, actions: List[str], warnings: List[str]) -> int:
    if not updated_hashes:
        return 0

    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed = 0
    matched = set()

    for t in transmissions:
        if not isinstance(t, dict) or str(t.get("transmission_id", "")) != TARGET_ID:
            continue

        responses = t.get("responses", [])
        if not isinstance(responses, list):
            continue

        for response in responses:
            if not isinstance(response, dict):
                continue
            for path_str, digest in updated_hashes.items():
                path = Path(path_str)
                if source_file_matches(response, path):
                    if response.get("content_sha256") != digest:
                        response["content_sha256"] = digest
                        changed += 1
                    matched.add(path_str)

    for path_str in sorted(set(updated_hashes) - matched):
        warnings.append(f"No Claude JSON response matched updated Markdown file: {path_str}")

    if changed:
        actions.append(f"Claude JSON content_sha256 {'would be updated' if not write else 'updated'}: {changed} response(s)")
        if write:
            backup_file(CLAUDE_JSON, f"before-t051-bold-query-paragraphs-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed


def patch_combined_hashes(updated_hashes: Dict[str, str], write: bool, actions: List[str], warnings: List[str]) -> int:
    if not updated_hashes:
        return 0

    data = load_json(COMBINED_JSON)
    records = data.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError(f"{COMBINED_JSON}: records is not a list")

    changed = 0
    matched = set()

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("record_type") != "claude_qa_response":
            continue
        if str(record.get("transmission_id", "")) != TARGET_ID:
            continue

        for path_str, digest in updated_hashes.items():
            path = Path(path_str)
            if source_file_matches(record, path):
                if record.get("content_sha256") != digest:
                    record["content_sha256"] = digest
                    changed += 1
                matched.add(path_str)

    for path_str in sorted(set(updated_hashes) - matched):
        warnings.append(f"No combined record matched updated Markdown file: {path_str}")

    if changed:
        actions.append(f"Combined JSON/JSONL content_sha256 {'would be updated' if not write else 'updated'}: {changed} record(s)")
        if write:
            backup_file(COMBINED_JSON, f"before-t051-bold-query-paragraphs-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bold each displayed T051 query paragraph and update hashes.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions: List[str] = []
    warnings: List[str] = []

    updated_hashes = patch_markdown(args.write, actions, warnings)
    claude_changed = patch_claude_hashes(updated_hashes, args.write, actions, warnings)
    combined_changed = patch_combined_hashes(updated_hashes, args.write, actions, warnings)

    print("\nT051 bold displayed query paragraphs patch")
    print("------------------------------------------")
    print("Mode: " + ("WRITE" if args.write else "DRY RUN"))
    print(f"Markdown files changed:       {len(updated_hashes)}")
    print(f"Claude hashes changed:        {claude_changed}")
    print(f"Combined hashes changed:      {combined_changed}")

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
        print("  python3 scripts/bold_t051_displayed_query_paragraphs.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
