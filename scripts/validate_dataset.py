#!/usr/bin/env python3
"""
Validate the Leilan Dataset release.

Checks manifest hash/size agreement, expanded source-tree coverage, JSON/JSONL
parseability, record counts, unique IDs, JSONL parity, and absence of GPT-4
base outputs from the public source tree.

Run from repo root:
    python3 scripts/validate_dataset.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import hashlib
import json
import subprocess
from typing import Any, Dict, Iterable, List, Tuple


CORE_FILES = [
    "README.md",
    "DATASET_CARD.md",
    "LICENSE",
    "combined_leilan_dataset.json",
    "combined_leilan_dataset_records.jsonl",
    "full_leilan_gpt3_dataset.json",
    "full_leilan_gpt3_dataset_normalized.json",
    "full_leilan_gpt3_dataset_normalized.jsonl",
    "full_leilan_claude_dataset.json",
    "leilan_gpt3_passages.json",
    "post-gpt3_transmissions_by_model/README.md",
    "supplementary_materials/README.md",
    "legacy-gpt3-scripts/README.md",
]

EXCLUDE_DIRS = {".git", "__pycache__", ".venv", "venv", "env"}
EXCLUDE_NAME_PARTS = (".backup-", ".tmp", ".pyc")

errors: List[str] = []
warnings: List[str] = []


def ok(msg: str) -> None:
    print(f"PASS: {msg}")


def fail(msg: str) -> None:
    errors.append(msg)
    print(f"FAIL: {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"WARN: {msg}")


def should_include(path: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return False
    if path.name.startswith(".DS_Store"):
        return False
    if any(part in path.name for part in EXCLUDE_NAME_PARTS):
        return False
    return path.is_file()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def read_jsonl(path: str | Path) -> List[Any]:
    out = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            out.append(json.loads(line))
    return out


def git_ls_files(patterns: Iterable[str]) -> List[str]:
    try:
        out = subprocess.check_output(["git", "ls-files", *patterns], text=True).splitlines()
    except Exception:
        return []
    return sorted(p for p in out if p and Path(p).exists() and should_include(Path(p)))


def collect_source_markdown_files() -> List[str]:
    root = Path("post-gpt3_transmissions_by_model")
    if not root.exists():
        return []
    files = []
    for p in root.rglob("*.md"):
        if p.name == "README.md":
            continue
        if should_include(p):
            files.append(p.as_posix())
    return sorted(files)


def collect_supplementary_material_files() -> List[str]:
    root = Path("supplementary_materials")
    if not root.exists():
        return []
    files = []
    for p in root.rglob("*"):
        if p.name == "README.md":
            continue
        if should_include(p):
            files.append(p.as_posix())
    return sorted(files)


def collect_script_files() -> List[str]:
    files = git_ls_files(["*.py", "scripts/*.py", "legacy-gpt3-scripts/*.py"])
    return sorted({p for p in files if p.endswith(".py")})


def manifest_entries(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    files = manifest.get("files", [])
    if isinstance(files, list):
        return files
    return []


def section_paths(manifest: Dict[str, Any], section: str) -> List[str]:
    entries = manifest.get("sections", {}).get(section, [])
    if not isinstance(entries, list):
        return []
    return sorted(e.get("path") for e in entries if isinstance(e, dict) and e.get("path"))


def dataset_count(manifest: Dict[str, Any], *keys: str) -> Any:
    cur: Any = manifest.get("dataset_counts", {})
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def validate_manifest() -> Dict[str, Any] | None:
    try:
        manifest = load_json("MANIFEST.json")
        ok("MANIFEST.json parses")
    except Exception as e:
        fail(f"MANIFEST.json parses ({e})")
        return None

    entries = manifest_entries(manifest)
    if entries:
        ok("MANIFEST.json contains file entries")
    else:
        fail("MANIFEST.json contains file entries")
        return manifest

    paths = [e.get("path") for e in entries]
    if len(paths) == len(set(paths)):
        ok("manifest file paths are unique")
    else:
        fail("manifest file paths are unique")

    for e in entries:
        path = e.get("path")
        if not path:
            fail("manifest entry has path")
            continue
        p = Path(path)
        if not p.exists():
            fail(f"{path}: exists")
            continue
        size = p.stat().st_size
        if size == e.get("bytes"):
            ok(f"{path}: byte size matches manifest")
        else:
            fail(f"{path}: byte size matches manifest (actual {size}, manifest {e.get('bytes')})")
        digest = sha256_file(p)
        if digest == e.get("sha256"):
            ok(f"{path}: SHA256 matches manifest")
        else:
            fail(f"{path}: SHA256 matches manifest")

    return manifest


def validate_manifest_coverage(manifest: Dict[str, Any]) -> None:
    checks = [
        ("core_files", sorted(CORE_FILES)),
        ("source_markdown_files", collect_source_markdown_files()),
        ("supplementary_material_files", collect_supplementary_material_files()),
        ("script_files", collect_script_files()),
    ]

    for section, actual in checks:
        expected = sorted(actual)
        listed = section_paths(manifest, section)
        if listed == expected:
            ok(f"manifest {section} section matches working tree")
        else:
            fail(f"manifest {section} section matches working tree")
            missing = sorted(set(expected) - set(listed))[:20]
            extra = sorted(set(listed) - set(expected))[:20]
            if missing:
                fail(f"{section} missing from manifest, first 20: {missing}")
            if extra:
                fail(f"{section} in manifest but not expected, first 20: {extra}")


def validate_no_gpt4_base_tree() -> None:
    if not Path("post-gpt3_transmissions_by_model/gpt-4-base").exists():
        ok("GPT-4 base source directory is absent from public tree")
    else:
        fail("GPT-4 base source directory is absent from public tree")


def validate_json_parsing() -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], Any]:
    combined = load_json("combined_leilan_dataset.json")
    ok("combined_leilan_dataset.json: JSON parses")
    combined_jsonl = read_jsonl("combined_leilan_dataset_records.jsonl")
    ok("combined_leilan_dataset_records.jsonl: JSONL parses")
    load_json("full_leilan_gpt3_dataset.json")
    ok("full_leilan_gpt3_dataset.json: JSON parses")
    gpt3_norm = load_json("full_leilan_gpt3_dataset_normalized.json")
    ok("full_leilan_gpt3_dataset_normalized.json: JSON parses")
    gpt3_norm_jsonl = read_jsonl("full_leilan_gpt3_dataset_normalized.jsonl")
    ok("full_leilan_gpt3_dataset_normalized.jsonl: JSONL parses")
    claude = load_json("full_leilan_claude_dataset.json")
    ok("full_leilan_claude_dataset.json: JSON parses")
    passages = load_json("leilan_gpt3_passages.json")
    ok("leilan_gpt3_passages.json: JSON parses")
    return combined, combined_jsonl, gpt3_norm, gpt3_norm_jsonl, claude, passages


def validate_combined(combined: Dict[str, Any], combined_jsonl: List[Dict[str, Any]], manifest: Dict[str, Any]) -> None:
    records = combined.get("records", [])
    if not isinstance(records, list):
        fail("combined records is a list")
        return

    if len(records) == dataset_count(manifest, "combined", "record_count"):
        ok(f"combined record count matches manifest ({len(records)})")
    else:
        fail("combined record count matches manifest")

    corpus_info = combined.get("corpus_info", {})
    if corpus_info.get("record_count") in (None, len(records)):
        ok("combined record count matches corpus_info.record_count")
    else:
        fail("combined record count matches corpus_info.record_count")

    record_ids = [r.get("record_id") for r in records]
    if len(record_ids) == len(set(record_ids)):
        ok("combined record_id values are unique")
    else:
        fail("combined record_id values are unique")

    gpt3_records = [r for r in records if r.get("record_type") == "gpt3_transcript"]
    if all(str(r.get("text", "")).strip() for r in gpt3_records):
        ok("all combined GPT-3 transcript records have non-empty text")
    else:
        fail("all combined GPT-3 transcript records have non-empty text")

    claude_records = [r for r in records if r.get("record_type") == "claude_qa_response"]
    qa_count = 0
    empty_qa = 0
    for r in claude_records:
        qa_pairs = r.get("qa_pairs", [])
        if isinstance(qa_pairs, list):
            qa_count += len(qa_pairs)
            for qa in qa_pairs:
                if not isinstance(qa, dict) or not str(qa.get("question", "")).strip() or not str(qa.get("answer", "")).strip():
                    empty_qa += 1

    if empty_qa == 0:
        ok("all combined Claude Q/A pairs have non-empty question and answer fields")
    else:
        fail("all combined Claude Q/A pairs have non-empty question and answer fields")

    type_counts = dict(sorted(Counter(r.get("record_type") for r in records).items()))
    if type_counts == dataset_count(manifest, "combined", "record_type_counts"):
        ok("combined record_type_counts match manifest")
    else:
        fail("combined record_type_counts match manifest")

    source_counts = dict(sorted(Counter(r.get("source_dataset") for r in records).items()))
    if source_counts == dataset_count(manifest, "combined", "source_dataset_counts"):
        ok("combined source_dataset_counts match manifest")
    else:
        fail("combined source_dataset_counts match manifest")

    if qa_count == dataset_count(manifest, "combined", "claude_qa_pair_count"):
        ok(f"combined Claude Q/A pair count matches manifest ({qa_count})")
    else:
        fail("combined Claude Q/A pair count matches manifest")

    if len(combined_jsonl) == len(records):
        ok("combined JSONL line count matches combined JSON records")
    else:
        fail("combined JSONL line count matches combined JSON records")

    if combined_jsonl == records:
        ok("combined JSONL records exactly match combined JSON records")
    else:
        fail("combined JSONL records exactly match combined JSON records")


def validate_gpt3_normalized(gpt3_norm: Dict[str, Any], gpt3_norm_jsonl: List[Dict[str, Any]], manifest: Dict[str, Any]) -> None:
    records = gpt3_norm.get("records", gpt3_norm if isinstance(gpt3_norm, list) else [])
    if not isinstance(records, list):
        fail("GPT-3 normalized records is a list")
        return
    if gpt3_norm_jsonl == records:
        ok("GPT-3 normalized JSONL records exactly match JSON records")
    else:
        fail("GPT-3 normalized JSONL records exactly match JSON records")
    if len(records) == dataset_count(manifest, "gpt3_normalized", "record_count"):
        ok(f"GPT-3 normalized record count matches manifest ({len(records)})")
    else:
        fail("GPT-3 normalized record count matches manifest")
    ids = [r.get("record_id") for r in records if isinstance(r, dict)]
    if len(ids) == len(set(ids)):
        ok("GPT-3 normalized record_id values are unique")
    else:
        fail("GPT-3 normalized record_id values are unique")
    if all(str(r.get("text", "")).strip() for r in records if isinstance(r, dict)):
        ok("all GPT-3 normalized records have non-empty text")
    else:
        fail("all GPT-3 normalized records have non-empty text")


def validate_claude(claude: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    transmissions = claude.get("transmissions", [])
    if not isinstance(transmissions, list):
        fail("Claude transmissions is a list")
        return
    response_count = 0
    qa_count = 0
    response_ids = []
    empty_qa = 0
    for t in transmissions:
        responses = t.get("responses", [])
        if not isinstance(responses, list):
            continue
        response_count += len(responses)
        for r in responses:
            if r.get("response_id") is not None:
                response_ids.append(r.get("response_id"))
            qa_pairs = r.get("qa_pairs", [])
            if isinstance(qa_pairs, list):
                qa_count += len(qa_pairs)
                for qa in qa_pairs:
                    if not isinstance(qa, dict) or not str(qa.get("question", "")).strip() or not str(qa.get("answer", "")).strip():
                        empty_qa += 1

    if len(transmissions) == dataset_count(manifest, "claude_family", "transmission_count"):
        ok(f"Claude transmission count matches manifest ({len(transmissions)})")
    else:
        fail("Claude transmission count matches manifest")
    if response_count == dataset_count(manifest, "claude_family", "response_count"):
        ok(f"Claude response count matches manifest ({response_count})")
    else:
        fail("Claude response count matches manifest")
    if qa_count == dataset_count(manifest, "claude_family", "qa_pair_count"):
        ok(f"Claude Q/A pair count matches manifest ({qa_count})")
    else:
        fail("Claude Q/A pair count matches manifest")
    if len(response_ids) == len(set(response_ids)):
        ok("Claude response_id values are unique")
    else:
        fail("Claude response_id values are unique")
    if empty_qa == 0:
        ok("all Claude source Q/A pairs have non-empty question and answer fields")
    else:
        fail("all Claude source Q/A pairs have non-empty question and answer fields")


def validate_passages(passages_data: Any, manifest: Dict[str, Any]) -> None:
    if isinstance(passages_data, list):
        passages = passages_data
    elif isinstance(passages_data, dict):
        passages = passages_data.get("passages", passages_data.get("records", []))
    else:
        passages = []
    if len(passages) == dataset_count(manifest, "gpt3_passages", "passage_count"):
        ok(f"GPT-3 passage count matches manifest ({len(passages)})")
    else:
        fail("GPT-3 passage count matches manifest")
    ids = []
    nonempty = True
    for p in passages:
        if not isinstance(p, dict):
            nonempty = False
            continue
        ids.append(p.get("id", p.get("passage_id")))
        if not str(p.get("text", "")).strip():
            nonempty = False
    if len(ids) == len(set(ids)):
        ok("GPT-3 passage IDs are unique")
    else:
        fail("GPT-3 passage IDs are unique")
    numeric_ids = [i for i in ids if isinstance(i, int)]
    if len(numeric_ids) == len(ids) and numeric_ids == list(range(1, len(ids) + 1)):
        ok("GPT-3 passage IDs are sequential and 1-based")
    else:
        warn("GPT-3 passage IDs are not all sequential 1-based integers, or use a non-integer ID format")
    if nonempty:
        ok("all GPT-3 passages have non-empty text")
    else:
        fail("all GPT-3 passages have non-empty text")


def main() -> int:
    print("\nLeilan dataset validation")
    print("-------------------------")

    manifest = validate_manifest()
    if manifest is None:
        print("\nSummary\n-------")
        print(f"Errors:   {len(errors)}")
        print(f"Warnings: {len(warnings)}")
        return 1

    validate_manifest_coverage(manifest)
    validate_no_gpt4_base_tree()

    try:
        combined, combined_jsonl, gpt3_norm, gpt3_norm_jsonl, claude, passages = validate_json_parsing()
        validate_combined(combined, combined_jsonl, manifest)
        validate_gpt3_normalized(gpt3_norm, gpt3_norm_jsonl, manifest)
        validate_claude(claude, manifest)
        validate_passages(passages, manifest)
    except Exception as e:
        fail(f"core JSON/JSONL validation crashed ({e})")

    print("\nSummary")
    print("-------")
    print(f"Errors:   {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    if errors:
        print("\nValidation failed.")
        return 1
    if warnings:
        print("\nValidation passed with warnings.")
    else:
        print("\nValidation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
