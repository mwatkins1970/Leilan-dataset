#!/usr/bin/env python3
"""
Generate MANIFEST.json for the Leilan Dataset.

This expanded manifest covers:
- canonical machine-facing files;
- Markdown source/audit files under post-gpt3_transmissions_by_model/;
- supplementary material files under supplementary_materials/;
- tracked Python scripts.

Run from repo root:
    python3 scripts/generate_manifest.py
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import subprocess
from typing import Any, Dict, Iterable, List


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


def file_entry(path: str | Path, category: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    return {
        "path": p.as_posix(),
        "category": category,
        "bytes": p.stat().st_size,
        "sha256": sha256_file(p),
    }


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


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


def git_ls_files(patterns: Iterable[str]) -> List[str]:
    try:
        out = subprocess.check_output(["git", "ls-files", *patterns], text=True).splitlines()
    except Exception:
        return []
    return sorted(p for p in out if p and Path(p).exists() and should_include(Path(p)))


def collect_script_files() -> List[str]:
    files = git_ls_files(["*.py", "scripts/*.py", "legacy-gpt3-scripts/*.py"])
    return sorted({p for p in files if p.endswith(".py")})


def combined_counts() -> Dict[str, Any]:
    data = load_json("combined_leilan_dataset.json")
    records = data.get("records", [])
    record_type_counts = Counter(r.get("record_type") for r in records)
    source_dataset_counts = Counter(r.get("source_dataset") for r in records)
    model_counts = Counter(r.get("model") for r in records if r.get("model"))
    claude_qa_pair_count = sum(
        len(r.get("qa_pairs", []))
        for r in records
        if r.get("record_type") == "claude_qa_response" and isinstance(r.get("qa_pairs"), list)
    )
    return {
        "record_count": len(records),
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "source_dataset_counts": dict(sorted(source_dataset_counts.items())),
        "model_count": len(model_counts),
        "model_counts": dict(sorted(model_counts.items())),
        "claude_qa_pair_count": claude_qa_pair_count,
        "gpt3_transcript_count": record_type_counts.get("gpt3_transcript", 0),
        "claude_response_record_count": record_type_counts.get("claude_qa_response", 0),
    }


def gpt3_normalized_counts() -> Dict[str, Any]:
    data = load_json("full_leilan_gpt3_dataset_normalized.json")
    records = data.get("records", data if isinstance(data, list) else [])
    return {"record_count": len(records)}


def claude_counts() -> Dict[str, Any]:
    data = load_json("full_leilan_claude_dataset.json")
    transmissions = data.get("transmissions", [])
    response_count = 0
    qa_pair_count = 0
    model_counts = Counter()
    for t in transmissions:
        responses = t.get("responses", [])
        if not isinstance(responses, list):
            continue
        response_count += len(responses)
        for r in responses:
            if r.get("model"):
                model_counts[r.get("model")] += 1
            qa_pairs = r.get("qa_pairs", [])
            if isinstance(qa_pairs, list):
                qa_pair_count += len(qa_pairs)
    return {
        "transmission_count": len(transmissions),
        "response_count": response_count,
        "qa_pair_count": qa_pair_count,
        "model_counts": dict(sorted(model_counts.items())),
    }


def passage_counts() -> Dict[str, Any]:
    data = load_json("leilan_gpt3_passages.json")
    if isinstance(data, list):
        passages = data
    elif isinstance(data, dict):
        passages = data.get("passages", data.get("records", []))
    else:
        passages = []
    return {"passage_count": len(passages)}


def source_tree_counts(source_files: List[str], supplementary_files: List[str], script_files: List[str]) -> Dict[str, Any]:
    by_model_dir = Counter(Path(p).parts[1] for p in source_files if len(Path(p).parts) >= 2)
    by_supp_dir = Counter(Path(p).parts[1] for p in supplementary_files if len(Path(p).parts) >= 2)
    return {
        "source_markdown_file_count": len(source_files),
        "source_markdown_by_model_directory": dict(sorted(by_model_dir.items())),
        "supplementary_material_file_count": len(supplementary_files),
        "supplementary_material_files_by_transmission": dict(sorted(by_supp_dir.items())),
        "script_file_count": len(script_files),
    }


def main() -> int:
    missing = [p for p in CORE_FILES if not Path(p).exists()]
    if missing:
        print("ERROR: Missing expected files:")
        for p in missing:
            print(f"  - {p}")
        raise SystemExit(1)

    source_files = collect_source_markdown_files()
    supplementary_files = collect_supplementary_material_files()
    script_files = collect_script_files()

    sections = {
        "core_files": [file_entry(p, "core") for p in CORE_FILES],
        "source_markdown_files": [file_entry(p, "source_markdown") for p in source_files],
        "supplementary_material_files": [file_entry(p, "supplementary_material") for p in supplementary_files],
        "script_files": [file_entry(p, "script") for p in script_files],
    }

    files = []
    seen = set()
    for entries in sections.values():
        for entry in entries:
            if entry["path"] in seen:
                continue
            seen.add(entry["path"])
            files.append(entry)

    manifest = {
        "manifest_schema_version": "2.0",
        "dataset_name": "Leilan Dataset",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": sorted(files, key=lambda e: e["path"]),
        "sections": sections,
        "file_counts": {
            "total_files": len(files),
            "core_files": len(sections["core_files"]),
            "source_markdown_files": len(sections["source_markdown_files"]),
            "supplementary_material_files": len(sections["supplementary_material_files"]),
            "script_files": len(sections["script_files"]),
        },
        "dataset_counts": {
            "combined": combined_counts(),
            "gpt3_normalized": gpt3_normalized_counts(),
            "claude_family": claude_counts(),
            "gpt3_passages": passage_counts(),
            "source_tree": source_tree_counts(source_files, supplementary_files, script_files),
        },
        "notes": [
            "The canonical machine-facing entry point is combined_leilan_dataset_records.jsonl.",
            "Source Markdown and supplementary materials are included for auditability/provenance, not as additive training examples.",
            "GPT-4 base outputs are not included in this public release.",
        ],
    }

    Path("MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("Generated MANIFEST.json")
    print(f"Files indexed: {len(files)}")
    print(f"  core files:                  {len(sections['core_files'])}")
    print(f"  source Markdown files:        {len(sections['source_markdown_files'])}")
    print(f"  supplementary material files: {len(sections['supplementary_material_files'])}")
    print(f"  tracked script files:         {len(sections['script_files'])}")
    print("")
    print("Core files:")
    for entry in sections["core_files"]:
        print(f"  - {entry['path']} ({entry['bytes']} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
