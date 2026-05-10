#!/usr/bin/env python3
"""
patch_t080_substack_urls.py

Replace the four over-complicated Substack CDN image URLs in T080 material with
the simpler direct substack-post-media S3 URLs.

By default this is a dry run:

    python3 scripts/patch_t080_substack_urls.py

Apply changes:

    python3 scripts/patch_t080_substack_urls.py --write

After applying, regenerate the manifest and validate:

    python3 scripts/generate_manifest.py
    python3 scripts/validate_dataset.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List


URL_MAP: Dict[str, str] = {
    "https://substack-post-media.s3.amazonaws.com/public/images/16c4f3b7-5e0d-4bc9-a067-c6ea6f089e83_1373x496.png":
    "https://substack-post-media.s3.amazonaws.com/public/images/16c4f3b7-5e0d-4bc9-a067-c6ea6f089e83_1373x496.png",

    "https://substack-post-media.s3.amazonaws.com/public/images/e26f0648-9a67-4d6e-8dbb-4e5851716089_1368x444.png":
    "https://substack-post-media.s3.amazonaws.com/public/images/e26f0648-9a67-4d6e-8dbb-4e5851716089_1368x444.png",

    "https://substack-post-media.s3.amazonaws.com/public/images/46f80950-16d1-40ed-b33a-2574ea05787c_1371x464.png":
    "https://substack-post-media.s3.amazonaws.com/public/images/46f80950-16d1-40ed-b33a-2574ea05787c_1371x464.png",

    "https://substack-post-media.s3.amazonaws.com/public/images/469c6a62-17d7-4fdd-b062-fa62eb4ff60a_837x493.png":
    "https://substack-post-media.s3.amazonaws.com/public/images/469c6a62-17d7-4fdd-b062-fa62eb4ff60a_837x493.png",
}

TEXT_SUFFIXES = {
    ".md",
    ".json",
    ".jsonl",
    ".txt",
    ".py",
}

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "env",
}


def should_scan(path: Path) -> bool:
    if path.name.startswith(".") and path.name not in {".gitignore"}:
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix not in TEXT_SUFFIXES:
        return False
    # Avoid touching local backups if any remain.
    if ".backup-" in path.name or path.name.endswith(".bak"):
        return False
    return True


def replace_in_text(text: str) -> tuple[str, int]:
    count = 0
    for old, new in URL_MAP.items():
        occurrences = text.count(old)
        if occurrences:
            text = text.replace(old, new)
            count += occurrences
    return text, count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch T080 Substack CDN URLs to direct S3 URLs.")
    parser.add_argument("--write", action="store_true", help="Actually write changes. Default is dry run.")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()

    changed_files: List[tuple[Path, int]] = []
    total_replacements = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if not should_scan(rel):
            continue

        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        patched, replacements = replace_in_text(original)
        if replacements:
            changed_files.append((rel, replacements))
            total_replacements += replacements
            if args.write:
                path.write_text(patched, encoding="utf-8")

    print("\nT080 Substack URL patch")
    print("-----------------------")
    print("Mode: " + ("WRITE" if args.write else "DRY RUN"))
    print(f"Files changed:       {len(changed_files)}")
    print(f"Total replacements:  {total_replacements}")

    print("\nFiles:")
    if changed_files:
        for rel, count in changed_files:
            print(f"  - {rel} ({count})")
    else:
        print("  none")

    if not args.write:
        print("\nDry run only. If this looks right, run:")
        print("  python3 scripts/patch_t080_substack_urls.py --write")
    else:
        print("\nDone. Next run:")
        print("  python3 scripts/generate_manifest.py")
        print("  python3 scripts/validate_dataset.py")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
