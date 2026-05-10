#!/usr/bin/env python3
"""
patch_fiddly_supplementary_round2.py

Surgical patch for the next batch of Leilan dataset fixes, without full rebuild.

Changes handled:

T051
  - Use the Opus 4.5 query as canonical.
  - Copy that query to Opus 3 and Sonnet 4.5 Markdown frontmatter.
  - Copy the Opus 4.5 first body block / displayed query to the other T051 Markdown files.
  - Propagate canonical query to full_leilan_claude_dataset.json and combined_leilan_dataset.json/jsonl.

T060 / T061
  - Make supplementary_materials_json model-specific in Markdown:
      Opus 3 file gets only the Opus 3 diagram.
      Sonnet 4.5 file gets only the Sonnet 4.5 diagram.
  - In full_leilan_claude_dataset.json, remove ambiguous transmission-level
    supplementary_materials and add model-specific supplementary_materials to responses.
  - In combined records, add model-specific supplementary_materials.

T077
  - In Opus 3 only, decapitalise You/Your -> you/your in the query.
  - Propagate to JSON query/question fields for the Opus 3 response only.

T144 / T145
  - Move the Puzzle & Dragons image external_sources from T145 to T144.
  - Remove them from T145 Markdown and JSON records.
  - Add them to T144 Markdown and JSON records.
  - In T144 queries, decapitalise You -> you.
  - Propagate query changes to JSON for T144.

Also removes stale query-mismatch warnings where appropriate.

Dry run:
    python3 scripts/patch_fiddly_supplementary_round2.py

Apply:
    python3 scripts/patch_fiddly_supplementary_round2.py --write

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


STALE_WARNING_CODES = {
    "metadata_query_differs_from_first_body_question",
    "multiple_first_question_variants_across_models",
}


PAD_EXTERNAL_SOURCES: List[Dict[str, Any]] = [
    {
        "id": "T144-source-001",
        "type": "image",
        "role": "query_context",
        "title": "Puzzle & Dragons image reference 1",
        "url": "https://static.wikia.nocookie.net/pad/images/4/4f/Pet1262.png",
        "rights_note": "Third-party game artwork; linked for context only and not included in the CC0 dataset."
    },
    {
        "id": "T144-source-002",
        "type": "image",
        "role": "query_context",
        "title": "Puzzle & Dragons image reference 2",
        "url": "https://static.wikia.nocookie.net/pad/images/4/40/Pet1263.png",
        "rights_note": "Third-party game artwork; linked for context only and not included in the CC0 dataset."
    }
]


DIAGRAM_MATERIALS: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
    "060": {
        "sonnet4_5": [
            {
                "id": "T060-diagram-001",
                "type": "image",
                "role": "response_context",
                "title": "Mermaid diagram for Transmission 060, Sonnet 4.5 version",
                "path": "supplementary_materials/060/t060-sonnet45-mermaid-diagram.png",
                "associated_model": "claude-sonnet-4.5",
                "license": "CC0",
                "note": "Rendered diagram associated with the Sonnet 4.5 version."
            }
        ],
        "opus3": [
            {
                "id": "T060-diagram-002",
                "type": "image",
                "role": "response_context",
                "title": "Mermaid diagram for Transmission 060, Opus 3 version",
                "path": "supplementary_materials/060/t060-opus3-mermaid-diagram.png",
                "associated_model": "claude-opus-3",
                "license": "CC0",
                "note": "Rendered diagram associated with the Opus 3 version."
            }
        ],
    },
    "061": {
        "sonnet4_5": [
            {
                "id": "T061-diagram-001",
                "type": "image",
                "role": "response_context",
                "title": "Mermaid diagram for Transmission 061, Sonnet 4.5 version",
                "path": "supplementary_materials/061/t061-sonnet45-mermaid-diagram.png",
                "associated_model": "claude-sonnet-4.5",
                "license": "CC0",
                "note": "Rendered diagram associated with the Sonnet 4.5 version."
            }
        ],
        "opus3": [
            {
                "id": "T061-diagram-002",
                "type": "image",
                "role": "response_context",
                "title": "Mermaid diagram for Transmission 061, Opus 3 version",
                "path": "supplementary_materials/061/t061-opus3-mermaid-diagram.png",
                "associated_model": "claude-opus-3",
                "license": "CC0",
                "note": "Rendered diagram associated with the Opus 3 version."
            }
        ],
    },
}


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


def split_frontmatter(text: str) -> Tuple[str, str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    # body starts after the closing line's initial newline + ---
    rest = text[end + len("\n---"):]
    return "---\n", text[4:end], "---" + rest


def split_frontmatter_body(text: str) -> Tuple[str, str, str, str] | None:
    """
    Return (opening, frontmatter, closing_line, body_after_closing).
    """
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    # Include just the closing delimiter, then keep all following body text.
    closing_start = end + 1
    closing_end = closing_start + 3
    return "---\n", text[4:end], "---", text[closing_end:]


def reassemble(opening: str, frontmatter: str, closing: str, body: str) -> str:
    return opening + frontmatter.rstrip() + "\n" + closing + body


def frontmatter_id(frontmatter: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', frontmatter)
    return m.group(1).strip() if m else None


def source_dir_for_path(path: Path) -> str:
    try:
        return path.parent.name
    except Exception:
        return ""


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


def replace_query_in_frontmatter(frontmatter: str, query: str) -> Tuple[str, bool]:
    lines = frontmatter.splitlines()
    query_lines = ["query: |"] + [("  " + ln if ln else "  ") for ln in query.splitlines()]

    for i, line in enumerate(lines):
        if not re.match(r"^query\s*:", line):
            continue

        after = line.split(":", 1)[1].strip()
        is_block = after.startswith("|") or after.startswith(">")

        if is_block:
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t") or lines[j].strip() == ""):
                j += 1
            new_lines = lines[:i] + query_lines + lines[j:]
        else:
            new_lines = lines[:i] + query_lines + lines[i + 1:]

        new_fm = "\n".join(new_lines).rstrip() + "\n"
        return new_fm, new_fm != frontmatter

    # Insert after date if query is missing.
    insert_at = len(lines)
    for i, line in enumerate(lines):
        if re.match(r"^date\s*:", line):
            insert_at = i + 1
            break

    new_lines = lines[:insert_at] + query_lines + lines[insert_at:]
    return "\n".join(new_lines).rstrip() + "\n", True


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


def first_nonempty_block(body: str) -> Tuple[int, int, str] | None:
    m = re.search(r"\S", body)
    if not m:
        return None
    start = m.start()
    m2 = re.search(r"\n\s*\n", body[start:])
    end = start + m2.start() if m2 else len(body)
    return start, end, body[start:end]


def replace_first_nonempty_block(body: str, new_block: str) -> Tuple[str, bool]:
    found = first_nonempty_block(body)
    if not found:
        return body, False
    start, end, old_block = found
    if old_block == new_block:
        return body, False
    return body[:start] + new_block + body[end:], True


def decap_you_your(text: str) -> str:
    text = re.sub(r"\bYour\b", "your", text)
    text = re.sub(r"\bYou\b", "you", text)
    return text


def decap_you_only(text: str) -> str:
    return re.sub(r"\bYou\b", "you", text)


def find_md_files_by_id(tid: str) -> List[Path]:
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
        if frontmatter_id(parts[1]) == tid:
            files.append(path)
    return files


def find_md_by_id_and_dir(tid: str, directory: str) -> Path | None:
    for path in find_md_files_by_id(tid):
        if source_dir_for_path(path) == directory:
            return path
    return None


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


def model_key_from_source(source_dir: str = "", model: str = "") -> str | None:
    model = (model or "").lower()
    source_dir = (source_dir or "").lower()

    if source_dir == "opus3" or model == "claude-opus-3":
        return "opus3"
    if source_dir == "sonnet4_5" or model == "claude-sonnet-4.5":
        return "sonnet4_5"
    return None


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


def set_response_query(obj: Dict[str, Any], query: str) -> int:
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


def patch_t051_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    source = find_md_by_id_and_dir("051", "opus4_5")
    if not source:
        warnings.append("T051 Opus 4.5 source Markdown not found; cannot extract canonical query.")
        return 0

    source_text = source.read_text(encoding="utf-8")
    parts = split_frontmatter_body(source_text)
    if not parts:
        warnings.append(f"T051 Opus 4.5 source has no usable frontmatter: {source}")
        return 0
    _, source_fm, _, source_body = parts

    canonical_query = extract_query(source_fm)
    if not canonical_query:
        warnings.append(f"T051 Opus 4.5 source query is empty/missing: {source}")
        return 0

    block_info = first_nonempty_block(source_body)
    canonical_body_block = block_info[2] if block_info else None
    if canonical_body_block is None:
        warnings.append(f"T051 Opus 4.5 source first body block not found: {source}")

    changed = 0
    for path in find_md_files_by_id("051"):
        original = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(original)
        if not parts:
            warnings.append(f"T051 file has no usable frontmatter: {path}")
            continue

        opening, fm, closing, body = parts
        fm2, changed_fm = replace_query_in_frontmatter(fm, canonical_query)
        changed_body = False
        body2 = body

        # Copy the displayed/boldface query block to Opus 3 and Sonnet 4.5.
        if path != source and canonical_body_block is not None:
            body2, changed_body = replace_first_nonempty_block(body, canonical_body_block)

        patched = reassemble(opening, fm2, closing, body2)

        if changed_fm or changed_body:
            changed += 1
            actions.append(f"T051 Markdown {'would be patched' if not write else 'patched'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")

    return changed


def canonical_t051_query(warnings: List[str]) -> str | None:
    source = find_md_by_id_and_dir("051", "opus4_5")
    if not source:
        warnings.append("T051 Opus 4.5 source Markdown not found for JSON propagation.")
        return None
    text = source.read_text(encoding="utf-8")
    parts = split_frontmatter_body(text)
    if not parts:
        warnings.append(f"T051 Opus 4.5 source has no frontmatter: {source}")
        return None
    return extract_query(parts[1])


def patch_diagram_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    changed = 0

    for tid in ["060", "061"]:
        for path in find_md_files_by_id(tid):
            key = model_key_from_source(source_dir_for_path(path), "")
            if key is None:
                warnings.append(f"T{tid}: no model-specific diagram mapping for {path}")
                continue

            materials = DIAGRAM_MATERIALS[tid][key]
            original = path.read_text(encoding="utf-8")
            parts = split_frontmatter_body(original)
            if not parts:
                warnings.append(f"T{tid}: no usable frontmatter: {path}")
                continue

            opening, fm, closing, body = parts
            fm2 = set_json_block(fm, "supplementary_materials_json", materials)
            patched = reassemble(opening, fm2, closing, body)

            if patched != original:
                changed += 1
                actions.append(f"T{tid} diagram Markdown {'would be patched' if not write else 'patched'}: {path}")
                if write:
                    path.write_text(patched, encoding="utf-8")

    return changed


def patch_t077_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    changed = 0
    path = find_md_by_id_and_dir("077", "opus3")
    if not path:
        warnings.append("T077 Opus 3 Markdown not found.")
        return 0

    original = path.read_text(encoding="utf-8")
    parts = split_frontmatter_body(original)
    if not parts:
        warnings.append(f"T077 Opus 3 has no usable frontmatter: {path}")
        return 0

    opening, fm, closing, body = parts
    query = extract_query(fm)
    if query is None:
        warnings.append(f"T077 Opus 3 query missing: {path}")
        return 0

    new_query = decap_you_your(query)
    fm2, changed_fm = replace_query_in_frontmatter(fm, new_query)

    body2 = body
    changed_body = False
    block = first_nonempty_block(body)
    if block:
        body2, changed_body = replace_first_nonempty_block(body, decap_you_your(block[2]))

    patched = reassemble(opening, fm2, closing, body2)

    if changed_fm or changed_body:
        changed = 1
        actions.append(f"T077 Opus 3 Markdown {'would be patched' if not write else 'patched'}: {path}")
        if write:
            path.write_text(patched, encoding="utf-8")

    return changed


def patch_t144_t145_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    changed = 0

    # Remove external sources from T145.
    for path in find_md_files_by_id("145"):
        original = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(original)
        if not parts:
            warnings.append(f"T145 file has no usable frontmatter: {path}")
            continue

        opening, fm, closing, body = parts
        fm2 = remove_block_field(fm, "external_sources_json")
        patched = reassemble(opening, fm2, closing, body)

        if patched != original:
            changed += 1
            actions.append(f"T145 external sources Markdown {'would be removed' if not write else 'removed'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")

    # Add external sources to T144 and decap You in query/displayed query.
    for path in find_md_files_by_id("144"):
        original = path.read_text(encoding="utf-8")
        parts = split_frontmatter_body(original)
        if not parts:
            warnings.append(f"T144 file has no usable frontmatter: {path}")
            continue

        opening, fm, closing, body = parts
        query = extract_query(fm)

        fm2 = fm
        if query is not None:
            fm2, _ = replace_query_in_frontmatter(fm2, decap_you_only(query))
        else:
            warnings.append(f"T144 query missing: {path}")

        fm2 = set_json_block(fm2, "external_sources_json", PAD_EXTERNAL_SOURCES)

        body2 = body
        block = first_nonempty_block(body)
        if block:
            body2, _ = replace_first_nonempty_block(body, decap_you_only(block[2]))

        patched = reassemble(opening, fm2, closing, body2)

        if patched != original:
            changed += 1
            actions.append(f"T144 Markdown {'would be patched' if not write else 'patched'}: {path}")
            if write:
                path.write_text(patched, encoding="utf-8")

    return changed


def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    count = 0
    count += patch_t051_markdown(write, actions, warnings)
    count += patch_diagram_markdown(write, actions, warnings)
    count += patch_t077_markdown(write, actions, warnings)
    count += patch_t144_t145_markdown(write, actions, warnings)
    return count


def patch_claude_json(write: bool, actions: List[str], warnings: List[str]) -> int:
    t051_query = canonical_t051_query(warnings)

    data = load_json(CLAUDE_JSON)
    transmissions = data.get("transmissions", [])
    if not isinstance(transmissions, list):
        raise RuntimeError(f"{CLAUDE_JSON}: transmissions is not a list")

    changed_transmissions = 0

    for t in transmissions:
        if not isinstance(t, dict):
            continue

        tid = str(t.get("transmission_id", ""))
        before = json.dumps(t, ensure_ascii=False, sort_keys=True)

        # T051: canonical query for all responses.
        if tid == "051" and t051_query:
            if "query" in t:
                t["query"] = t051_query
            for key in ["build_warnings", "warnings", "parse_warnings"]:
                if key in t:
                    t[key] = remove_stale_warning_items(t[key])

            responses = t.get("responses", [])
            if isinstance(responses, list):
                for r in responses:
                    if isinstance(r, dict):
                        set_response_query(r, t051_query)

        # T060 / T061: move model-specific diagram metadata to responses.
        if tid in {"060", "061"}:
            t.pop("supplementary_materials", None)
            responses = t.get("responses", [])
            if isinstance(responses, list):
                for r in responses:
                    if not isinstance(r, dict):
                        continue
                    key = model_key_from_source(
                        str(r.get("source_directory", "")),
                        str(r.get("model", "")),
                    )
                    if key and key in DIAGRAM_MATERIALS[tid]:
                        r["supplementary_materials"] = DIAGRAM_MATERIALS[tid][key]
                    else:
                        r.pop("supplementary_materials", None)

        # T077: Opus 3 query only.
        if tid == "077":
            responses = t.get("responses", [])
            if isinstance(responses, list):
                for r in responses:
                    if not isinstance(r, dict):
                        continue
                    key = model_key_from_source(
                        str(r.get("source_directory", "")),
                        str(r.get("model", "")),
                    )
                    if key == "opus3":
                        # Use existing query/question as source and decap it.
                        q = r.get("metadata_query")
                        if not isinstance(q, str):
                            qa = r.get("qa_pairs", [])
                            if isinstance(qa, list) and qa and isinstance(qa[0], dict):
                                q = qa[0].get("question")
                        if isinstance(q, str):
                            set_response_query(r, decap_you_your(q))

        # T144: add external sources and decap You in all response queries.
        if tid == "144":
            t["external_sources"] = PAD_EXTERNAL_SOURCES
            responses = t.get("responses", [])
            if isinstance(responses, list):
                for r in responses:
                    if not isinstance(r, dict):
                        continue
                    q = r.get("metadata_query")
                    if not isinstance(q, str):
                        qa = r.get("qa_pairs", [])
                        if isinstance(qa, list) and qa and isinstance(qa[0], dict):
                            q = qa[0].get("question")
                    if isinstance(q, str):
                        set_response_query(r, decap_you_only(q))

        # T145: remove misplaced external sources.
        if tid == "145":
            t.pop("external_sources", None)
            responses = t.get("responses", [])
            if isinstance(responses, list):
                for r in responses:
                    if isinstance(r, dict):
                        r.pop("external_sources", None)

        after = json.dumps(t, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed_transmissions += 1

    if changed_transmissions:
        actions.append(f"Claude JSON {'would be patched' if not write else 'patched'}: {changed_transmissions} transmissions")
        if write:
            backup_file(CLAUDE_JSON, f"before-fiddly-round2-{now_stamp()}")
            write_json_atomic(CLAUDE_JSON, data)

    return changed_transmissions


def patch_combined_jsonl(write: bool, actions: List[str], warnings: List[str]) -> int:
    t051_query = canonical_t051_query(warnings)

    data = load_json(COMBINED_JSON)
    records = data.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError(f"{COMBINED_JSON}: records is not a list")

    changed_records = 0

    for r in records:
        if not isinstance(r, dict):
            continue
        if r.get("record_type") != "claude_qa_response":
            continue

        tid = str(r.get("transmission_id", ""))
        before = json.dumps(r, ensure_ascii=False, sort_keys=True)

        if tid == "051" and t051_query:
            set_response_query(r, t051_query)

        if tid in {"060", "061"}:
            key = model_key_from_source(str(r.get("source_directory", "")), str(r.get("model", "")))
            if key and key in DIAGRAM_MATERIALS[tid]:
                r["supplementary_materials"] = DIAGRAM_MATERIALS[tid][key]
            else:
                r.pop("supplementary_materials", None)

        if tid == "077":
            key = model_key_from_source(str(r.get("source_directory", "")), str(r.get("model", "")))
            if key == "opus3":
                q = r.get("metadata_query")
                if not isinstance(q, str):
                    qa = r.get("qa_pairs", [])
                    if isinstance(qa, list) and qa and isinstance(qa[0], dict):
                        q = qa[0].get("question")
                if isinstance(q, str):
                    set_response_query(r, decap_you_your(q))

        if tid == "144":
            r["external_sources"] = PAD_EXTERNAL_SOURCES
            q = r.get("metadata_query")
            if not isinstance(q, str):
                qa = r.get("qa_pairs", [])
                if isinstance(qa, list) and qa and isinstance(qa[0], dict):
                    q = qa[0].get("question")
            if isinstance(q, str):
                set_response_query(r, decap_you_only(q))

        if tid == "145":
            r.pop("external_sources", None)

        after = json.dumps(r, ensure_ascii=False, sort_keys=True)
        if after != before:
            changed_records += 1

    if changed_records:
        actions.append(f"Combined JSON/JSONL {'would be patched' if not write else 'patched'}: {changed_records} records")
        if write:
            backup_file(COMBINED_JSON, f"before-fiddly-round2-{now_stamp()}")
            write_json_atomic(COMBINED_JSON, data)
            write_jsonl_atomic(COMBINED_JSONL, records)

    return changed_records


def verify_paths(warnings: List[str]) -> None:
    for tid, by_model in DIAGRAM_MATERIALS.items():
        for materials in by_model.values():
            for item in materials:
                p = item.get("path")
                if p and not Path(p).exists():
                    warnings.append(f"T{tid}: referenced diagram path does not exist: {p}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply fiddly supplementary metadata/query fixes round 2.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    actions: List[str] = []
    warnings: List[str] = []

    verify_paths(warnings)

    md_count = patch_markdown(args.write, actions, warnings)
    claude_count = patch_claude_json(args.write, actions, warnings)
    combined_count = patch_combined_jsonl(args.write, actions, warnings)

    print("\nLeilan fiddly supplementary/query patch round 2")
    print("-----------------------------------------------")
    print("Mode: " + ("WRITE" if args.write else "DRY RUN"))
    print(f"Markdown files changed:        {md_count}")
    print(f"Claude transmissions changed:  {claude_count}")
    print(f"Combined records changed:      {combined_count}")

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
        print("  python3 scripts/patch_fiddly_supplementary_round2.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
