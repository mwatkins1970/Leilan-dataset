#!/usr/bin/env python3
"""
Surgically decapitalise word "Her" -> "her" in title/source-title metadata only.

Default targets: T077 and T181, as requested.
Earlier discussion mentioned T180; this script reports T180 title hits, and can patch
T180 too with --include-t180.

Dry run:
  python3 scripts/patch_title_decapitalisations.py
Write:
  python3 scripts/patch_title_decapitalisations.py --write
If needed:
  python3 scripts/patch_title_decapitalisations.py --include-t180 --write
Then:
  python3 scripts/generate_manifest.py
  python3 scripts/validate_dataset.py
"""
from __future__ import annotations

import argparse, json, os, re, shutil, tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

MD_ROOT = Path("post-gpt3_transmissions_by_model")
CLAUDE_JSON = Path("full_leilan_claude_dataset.json")
COMBINED_JSON = Path("combined_leilan_dataset.json")
COMBINED_JSONL = Path("combined_leilan_dataset_records.jsonl")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def load_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f: return json.load(f)

def write_json_atomic(p: Path, data: Any) -> None:
    fd, tmp = tempfile.mkstemp(prefix=p.name+".", suffix=".tmp", dir=str(p.parent or Path(".")), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2); f.write("\n")
        os.replace(tmp, p)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def write_jsonl_atomic(p: Path, records: List[Dict[str, Any]]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=p.name+".", suffix=".tmp", dir=str(p.parent or Path(".")), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for r in records: f.write(json.dumps(r, ensure_ascii=False, separators=(",",":"))+"\n")
        os.replace(tmp, p)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def backup(p: Path) -> None:
    shutil.copy2(p, p.with_name(f"{p.name}.backup-before-title-decap-{stamp()}"))

def split_fm(text: str):
    if not text.startswith("---\n"): return None
    end = text.find("\n---", 4)
    if end < 0: return None
    return text[:4], text[4:end], text[end:]

def fm_id(fm: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', fm)
    return m.group(1).strip() if m else None

def decap(v: Any) -> Any:
    return re.sub(r"\bHer\b", "her", v) if isinstance(v, str) else v

def patch_md_text(text: str, targets: set[str]) -> tuple[str, bool]:
    parts = split_fm(text)
    if not parts: return text, False
    start, fm, rest = parts
    if fm_id(fm) not in targets: return text, False
    changed = False
    def repl(m):
        nonlocal changed
        new = decap(m.group(2))
        if new != m.group(2): changed = True
        return m.group(1)+new+m.group(3)
    fm2 = re.sub(r'(?m)^(title:\s*["\'])(.*?)(["\']\s*)$', repl, fm)
    if fm2 == fm:
        def repl2(m):
            nonlocal changed
            new = decap(m.group(2))
            if new != m.group(2): changed = True
            return m.group(1)+new
        fm2 = re.sub(r'(?m)^(title:\s*)([^\n]+)$', repl2, fm)
    return (start+fm2+rest, True) if changed else (text, False)

def diagnostic(ids: set[str]) -> dict[str, list[Path]]:
    hits = {i: [] for i in ids}
    if not MD_ROOT.exists(): return hits
    for p in MD_ROOT.rglob("*.md"):
        if p.name == "README.md": continue
        txt = p.read_text(encoding="utf-8")
        parts = split_fm(txt)
        if not parts: continue
        tid = fm_id(parts[1])
        if tid in ids and re.search(r'(?m)^title:.*\bHer\b', parts[1]): hits[tid].append(p)
    return hits

def patch_markdown(targets: set[str], write: bool, actions: list[str]) -> int:
    n = 0
    for p in MD_ROOT.rglob("*.md"):
        if p.name == "README.md": continue
        old = p.read_text(encoding="utf-8"); new, changed = patch_md_text(old, targets)
        if changed:
            n += 1; actions.append(("would patch" if not write else "patched")+f" {p}")
            if write: p.write_text(new, encoding="utf-8")
    return n

def patch_claude(targets: set[str], write: bool, actions: list[str]) -> int:
    data = load_json(CLAUDE_JSON); n = 0
    for t in data.get("transmissions", []):
        if not isinstance(t, dict) or str(t.get("transmission_id", "")) not in targets: continue
        before = json.dumps(t, ensure_ascii=False, sort_keys=True)
        if "title" in t: t["title"] = decap(t["title"])
        for r in t.get("responses", []) if isinstance(t.get("responses"), list) else []:
            if isinstance(r, dict) and "source_title" in r: r["source_title"] = decap(r["source_title"])
        if json.dumps(t, ensure_ascii=False, sort_keys=True) != before: n += 1
    if n and write: backup(CLAUDE_JSON); write_json_atomic(CLAUDE_JSON, data)
    if n: actions.append(("would patch" if not write else "patched")+f" {n} Claude transmissions")
    return n

def patch_combined(targets: set[str], write: bool, actions: list[str]) -> int:
    data = load_json(COMBINED_JSON); records = data.get("records", []); n = 0
    for r in records:
        if not isinstance(r, dict) or str(r.get("transmission_id", "")) not in targets: continue
        before = json.dumps(r, ensure_ascii=False, sort_keys=True)
        for k in ["transmission_title", "source_title"]:
            if k in r: r[k] = decap(r[k])
        if json.dumps(r, ensure_ascii=False, sort_keys=True) != before: n += 1
    if n and write:
        backup(COMBINED_JSON); write_json_atomic(COMBINED_JSON, data); write_jsonl_atomic(COMBINED_JSONL, records)
    if n: actions.append(("would patch" if not write else "patched")+f" {n} combined records")
    return n

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--write", action="store_true"); ap.add_argument("--include-t180", action="store_true"); args = ap.parse_args()
    targets = {"077", "181"}
    if args.include_t180: targets.add("180")
    print("\nLeilan title decapitalisation patch\n-----------------------------------")
    print("Mode:", "WRITE" if args.write else "DRY RUN")
    print("Targets:", ", ".join(sorted(targets)))
    print("\nDiagnostic title hits containing word 'Her':")
    hits = diagnostic({"077", "180", "181"})
    anyhit = False
    for tid in ["077", "180", "181"]:
        if hits.get(tid):
            anyhit = True; print(f"  T{tid}:")
            for p in hits[tid]: print("    -", p)
    if not anyhit: print("  none")
    actions: list[str] = []
    md = patch_markdown(targets, args.write, actions); cj = patch_claude(targets, args.write, actions); cb = patch_combined(targets, args.write, actions)
    print(f"\nCounts:\n  Markdown files changed: {md}\n  Claude transmissions changed: {cj}\n  Combined records changed: {cb}")
    print("\nActions:"); [print("  -", a) for a in actions] if actions else print("  none")
    if not args.write:
        print("\nDry run only. To apply: python3 scripts/patch_title_decapitalisations.py --write")
        print("If diagnostic shows T180 is the relevant one: python3 scripts/patch_title_decapitalisations.py --include-t180 --write")
    else:
        print("\nNext: python3 scripts/generate_manifest.py && python3 scripts/validate_dataset.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
