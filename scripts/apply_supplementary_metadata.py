#!/usr/bin/env python3
"""
Surgically add external_sources / supplementary_materials metadata for selected
Leilan transmissions to Markdown frontmatter, full_leilan_claude_dataset.json,
combined_leilan_dataset.json, and combined_leilan_dataset_records.jsonl.

Dry run:
  python3 scripts/apply_supplementary_metadata.py
Write:
  python3 scripts/apply_supplementary_metadata.py --write
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

TARGET_IDS = ["015","032","051","060","061","069","076","080","083","109","145","295","307","309","326","353","356"]

M: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
"015":{"supplementary_materials":[{"id":"T015-image-001","type":"image","role":"query_context","title":"Leilan visualisation image","path":"supplementary_materials/015/t015-leilan-visualisation.png","license":"CC0","rights_note":"AI-generated image supplied by the dataset curator and released as part of the CC0 dataset.","note":"Image referenced by the query for Transmission 015."}]},
"032":{"external_sources":[{"id":"T032-source-001","type":"video","role":"query_context","title":"Terence McKenna lecture audio","url":"https://www.youtube.com/watch?v=JuvIgLVFoNg","rights_note":"Third-party audio/transcript; linked for context only and not included in the CC0 dataset."}]},
"051":{"external_sources":[{"id":"T051-source-001","type":"article","role":"query_context","title":"The Meat Eater Problem","authors":["Michael Plant"],"journal":"Journal of Controversial Ideas","doi":"10.35995/jci02020002","url":"https://doi.org/10.35995/jci02020002","license":"CC BY 4.0","note":"Article abstract was included in the query."}]},
"060":{"supplementary_materials":[{"id":"T060-diagram-001","type":"image","role":"response_context","title":"Mermaid diagram for Transmission 060, Sonnet 4.5 version","path":"supplementary_materials/060/t060-sonnet45-mermaid-diagram.png","associated_model":"claude-sonnet-4.5","license":"CC0","note":"Rendered diagram associated with the Sonnet 4.5 version."},{"id":"T060-diagram-002","type":"image","role":"response_context","title":"Mermaid diagram for Transmission 060, Opus 3 version","path":"supplementary_materials/060/t060-opus3-mermaid-diagram.png","associated_model":"claude-opus-3","license":"CC0","note":"Rendered diagram associated with the Opus 3 version."}]},
"061":{"supplementary_materials":[{"id":"T061-diagram-001","type":"image","role":"response_context","title":"Mermaid diagram for Transmission 061, Sonnet 4.5 version","path":"supplementary_materials/061/t061-sonnet45-mermaid-diagram.png","associated_model":"claude-sonnet-4.5","license":"CC0","note":"Rendered diagram associated with the Sonnet 4.5 version."},{"id":"T061-diagram-002","type":"image","role":"response_context","title":"Mermaid diagram for Transmission 061, Opus 3 version","path":"supplementary_materials/061/t061-opus3-mermaid-diagram.png","associated_model":"claude-opus-3","license":"CC0","note":"Rendered diagram associated with the Opus 3 version."}]},
"069":{"external_sources":[{"id":"T069-source-001","type":"webpage","role":"query_context","title":"Meditations on Moloch","url":"https://www.slatestarcodexabridged.com/Meditations-On-Moloch","rights_note":"Third-party text; linked for context only and not included in the CC0 dataset."}]},
"076":{"external_sources":[{"id":"T076-source-001","type":"webpage","role":"query_context","title":"The Alphabet Versus the Goddess","url":"https://en.wikipedia.org/wiki/The_Alphabet_Versus_the_Goddess","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."},{"id":"T076-source-002","type":"webpage","role":"query_context","title":"The Master and His Emissary","url":"https://en.wikipedia.org/wiki/The_Master_and_His_Emissary","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."}]},
"080":{"supplementary_materials":[{"id":"T080-playground-001","type":"image_with_transcription","role":"query_context","title":"GPT-3 Playground rollout screenshot 1","path":"supplementary_materials/080/t080-gpt3-playground-rollout-01.png","transcription_text_path":"supplementary_materials/080/t080-gpt3-playground-rollout-01.txt","transcription_json_path":"supplementary_materials/080/t080-gpt3-playground-rollout-01.json","rights_note":"Screenshot of curator-generated GPT-3 Playground output; included for provenance."},{"id":"T080-playground-002","type":"image_with_transcription","role":"query_context","title":"GPT-3 Playground rollout screenshot 2","path":"supplementary_materials/080/t080-gpt3-playground-rollout-02.png","transcription_text_path":"supplementary_materials/080/t080-gpt3-playground-rollout-02.txt","transcription_json_path":"supplementary_materials/080/t080-gpt3-playground-rollout-02.json","rights_note":"Screenshot of curator-generated GPT-3 Playground output; included for provenance."},{"id":"T080-playground-003","type":"image_with_transcription","role":"query_context","title":"GPT-3 Playground rollout screenshot 3","path":"supplementary_materials/080/t080-gpt3-playground-rollout-03.png","transcription_text_path":"supplementary_materials/080/t080-gpt3-playground-rollout-03.txt","transcription_json_path":"supplementary_materials/080/t080-gpt3-playground-rollout-03.json","rights_note":"Screenshot of curator-generated GPT-3 Playground output; included for provenance."},{"id":"T080-playground-004","type":"image_with_transcription","role":"query_context","title":"GPT-3 Playground rollout screenshot 4","path":"supplementary_materials/080/t080-gpt3-playground-rollout-04.png","transcription_text_path":"supplementary_materials/080/t080-gpt3-playground-rollout-04.txt","transcription_json_path":"supplementary_materials/080/t080-gpt3-playground-rollout-04.json","rights_note":"Screenshot of curator-generated GPT-3 Playground output; included for provenance."}]},
"083":{"external_sources":[{"id":"T083-source-001","type":"webpage","role":"query_context","title":"Roko's basilisk","url":"https://en.wikipedia.org/wiki/Roko%27s_basilisk","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."}]},
"109":{"external_sources":[{"id":"T109-source-001","type":"webpage","role":"query_context","title":"Cyborgism","url":"https://cyborgism.wiki/hypha/cyborgism","rights_note":"Linked for context only; licence not confirmed."},{"id":"T109-source-002","type":"webpage","role":"query_context","title":"Ascension Maze","url":"https://cyborgism.wiki/hypha/ascension_maze","rights_note":"Linked for context only; licence not confirmed."}]},
"145":{"external_sources":[{"id":"T145-source-001","type":"image","role":"query_context","title":"Puzzle & Dragons image reference 1","url":"https://static.wikia.nocookie.net/pad/images/4/4f/Pet1262.png","rights_note":"Third-party game artwork; linked for context only and not included in the CC0 dataset."},{"id":"T145-source-002","type":"image","role":"query_context","title":"Puzzle & Dragons image reference 2","url":"https://static.wikia.nocookie.net/pad/images/4/40/Pet1263.png","rights_note":"Third-party game artwork; linked for context only and not included in the CC0 dataset."}]},
"295":{"external_sources":[{"id":"T295-source-001","type":"profile","role":"query_context","title":"Deepfates Substack profile","url":"https://open.substack.com/users/74807290-deepfates?utm_source=mentions"},{"id":"T295-source-002","type":"social_post","role":"query_context","title":"Deepfates post on X","url":"https://x.com/deepfates/status/1850568913026977897","rights_note":"Third-party social-media post; linked for context only and not included in the CC0 dataset."}]},
"307":{"external_sources":[{"id":"T307-source-001","type":"image","role":"query_context","title":"Madonna and Child stamp image","url":"https://substack-post-media.s3.amazonaws.com/public/images/0e02d9d2-f380-4c6d-83d2-331c42f261dd_452x364.png","rights_note":"Photograph by curator of Royal Mail stamps containing third-party stamp artwork; linked for context only and not included in the CC0 dataset."}]},
"309":{"external_sources":[{"id":"T309-source-001","type":"article","role":"query_context","title":"The promise and warning of Truth Terminal","url":"https://techcrunch.com/2024/12/19/the-promise-and-warning-of-truth-terminal-the-ai-bot-that-secured-50000-in-bitcoin-from-marc-andreessen/","rights_note":"Third-party article; linked for context only."},{"id":"T309-source-002","type":"profile","role":"query_context","title":"Truth Terminal on X","url":"https://x.com/truth_terminal"},{"id":"T309-source-003","type":"social_post","role":"query_context","title":"Andy Ayrey post on X","url":"https://x.com/AndyAyrey/status/1873857912080392692","rights_note":"Third-party social-media post; linked for context only."}]},
"326":{"external_sources":[{"id":"T326-source-001","type":"webpage","role":"query_context","title":"Nick Land: Orthogonality / Pythia unbound","url":"https://www.lesswrong.com/posts/xuKH5fiE9NypySXqp/nick-land-orthogonality#Pythia_unbound"},{"id":"T326-source-002","type":"video","role":"query_context","title":"Referenced YouTube video","url":"https://www.youtube.com/watch?v=xzCe_tZTO-Q","rights_note":"Third-party video/transcript; linked for context only and not included in the CC0 dataset."}]},
"353":{"external_sources":[{"id":"T353-source-001","type":"webpage","role":"query_context","title":"Michael Levin (biologist)","url":"https://en.wikipedia.org/wiki/Michael_Levin_(biologist)","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."},{"id":"T353-source-002","type":"video","role":"query_context","title":"Referenced Michael Levin YouTube video","url":"https://www.youtube.com/watch?v=3IFL09i9LWQ","rights_note":"Third-party video/transcript; linked for context only."},{"id":"T353-source-003","type":"webpage","role":"query_context","title":"Algorithms Redux","url":"https://thoughtforms.life/algorithms-redux-finding-unexpected-properties-in-truly-minimal-systems/","rights_note":"Third-party webpage; linked for context only unless licence is confirmed."}]},
"356":{"external_sources":[{"id":"T356-source-001","type":"webpage","role":"query_context","title":"The Dawn of Everything","url":"https://en.wikipedia.org/wiki/The_Dawn_of_Everything","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."},{"id":"T356-source-002","type":"webpage","role":"query_context","title":"Minoan civilization","url":"https://en.wikipedia.org/wiki/Minoan_civilization","license_note":"Wikipedia text is generally CC BY-SA; linked only, not copied."},{"id":"T356-source-003","type":"book_passage","role":"query_context","title":"The Dawn of Everything, pp. 432–440","authors":["David Graeber","David Wengrow"],"note":"Referenced page range only; copyrighted book passage not included in the CC0 dataset."}]}
}


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
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, separators=(",",":"))+"\n")
        os.replace(tmp, p)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def backup(p: Path) -> None:
    shutil.copy2(p, p.with_name(f"{p.name}.backup-before-supplementary-{datetime.now().strftime('%Y%m%d-%H%M%S')}"))

def split_fm(text: str):
    if not text.startswith("---\n"): return None
    end = text.find("\n---", 4)
    if end < 0: return None
    return text[:4], text[4:end], text[end:]

def fm_id(fm: str) -> str | None:
    m = re.search(r'(?m)^id:\s*["\']?([^"\'\n]+)["\']?\s*$', fm)
    return m.group(1).strip() if m else None

def remove_block(fm: str, key: str) -> str:
    lines, out, i = fm.splitlines(), [], 0
    while i < len(lines):
        if lines[i].startswith(key + ":"):
            i += 1
            while i < len(lines) and (lines[i].startswith(" ") or not lines[i].strip()): i += 1
        else:
            out.append(lines[i]); i += 1
    return "\n".join(out).rstrip()+"\n"

def block(key: str, val: Any) -> str:
    s = json.dumps(val, ensure_ascii=False, indent=2)
    return key + ": |\n" + "\n".join("  "+line for line in s.splitlines())

def patch_md_text(text: str, meta: Dict[str, Any]) -> str:
    parts = split_fm(text)
    if not parts: return text
    start, fm, rest = parts
    for key in ["external_sources_json", "supplementary_materials_json"]:
        fm = remove_block(fm, key)
    adds = []
    if meta.get("external_sources"): adds.append(block("external_sources_json", meta["external_sources"]))
    if meta.get("supplementary_materials"): adds.append(block("supplementary_materials_json", meta["supplementary_materials"]))
    if adds: fm = fm.rstrip()+"\n"+"\n".join(adds)+"\n"
    return start+fm+rest

def find_md_by_id() -> Dict[str, List[Path]]:
    found = {tid: [] for tid in TARGET_IDS}
    for p in MD_ROOT.rglob("*.md"):
        if p.name == "README.md": continue
        txt = p.read_text(encoding="utf-8")
        parts = split_fm(txt)
        if not parts: continue
        tid = fm_id(parts[1])
        if tid in found: found[tid].append(p)
    return found

def make_t080_jsons(write: bool, warnings: List[str], actions: List[str]) -> None:
    folder = Path("supplementary_materials/080")
    for n in range(1,5):
        stem = f"t080-gpt3-playground-rollout-{n:02d}"
        txt, png, js = folder/f"{stem}.txt", folder/f"{stem}.png", folder/f"{stem}.json"
        if not txt.exists(): warnings.append(f"T080 transcription missing: {txt}"); continue
        if not png.exists(): warnings.append(f"T080 image missing: {png}")
        payload = {"id":f"T080-transcription-{n:03d}","type":"transcription","source_image_path":png.as_posix(),"source_text_path":txt.as_posix(),"text":txt.read_text(encoding="utf-8").strip(),"note":"Transcription of curator-generated GPT-3 Playground rollout screenshot."}
        actions.append(("would write" if not write else "wrote")+f" {js}")
        if write: write_json_atomic(js, payload)

def check_paths(warnings: List[str]) -> None:
    for tid, meta in M.items():
        for item in meta.get("supplementary_materials", []):
            for k in ["path", "transcription_text_path"]:
                if item.get(k) and not Path(item[k]).exists(): warnings.append(f"T{tid}: missing {k}: {item[k]}")

def patch_markdown(write: bool, actions: List[str], warnings: List[str]) -> int:
    found, n = find_md_by_id(), 0
    for tid in TARGET_IDS:
        if not found[tid]: warnings.append(f"T{tid}: no Markdown files found")
        for p in found[tid]:
            old = p.read_text(encoding="utf-8"); new = patch_md_text(old, M[tid])
            if new != old:
                n += 1; actions.append(("would patch" if not write else "patched")+f" {p}")
                if write: p.write_text(new, encoding="utf-8")
    return n

def patch_claude(write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(CLAUDE_JSON); n = 0; seen = set()
    for t in data.get("transmissions", []):
        if not isinstance(t, dict): continue
        tid = str(t.get("transmission_id", ""))
        if tid in M:
            seen.add(tid); meta = M[tid]
            if meta.get("external_sources"): t["external_sources"] = meta["external_sources"]
            if meta.get("supplementary_materials"): t["supplementary_materials"] = meta["supplementary_materials"]
            n += 1
    for tid in TARGET_IDS:
        if tid not in seen: warnings.append(f"T{tid}: not found in {CLAUDE_JSON}")
    if n and write: backup(CLAUDE_JSON); write_json_atomic(CLAUDE_JSON, data)
    actions.append(("would patch" if not write else "patched")+f" {n} Claude transmissions")
    return n

def patch_combined(write: bool, actions: List[str], warnings: List[str]) -> int:
    data = load_json(COMBINED_JSON); records = data.get("records", []); n = 0; per = {tid:0 for tid in TARGET_IDS}
    for r in records:
        if not isinstance(r, dict) or r.get("record_type") != "claude_qa_response": continue
        tid = str(r.get("transmission_id", ""))
        if tid in M:
            meta = M[tid]
            if meta.get("external_sources"): r["external_sources"] = meta["external_sources"]
            if meta.get("supplementary_materials"): r["supplementary_materials"] = meta["supplementary_materials"]
            n += 1; per[tid] += 1
    for tid, c in per.items():
        if c == 0: warnings.append(f"T{tid}: no combined records found")
    if n and write:
        backup(COMBINED_JSON); write_json_atomic(COMBINED_JSON, data); write_jsonl_atomic(COMBINED_JSONL, records)
    actions.append(("would patch" if not write else "patched")+f" {n} combined records")
    return n

def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("--write", action="store_true"); args = ap.parse_args()
    actions: List[str] = []; warnings: List[str] = []
    make_t080_jsons(args.write, warnings, actions); check_paths(warnings)
    md = patch_markdown(args.write, actions, warnings); cj = patch_claude(args.write, actions, warnings); cb = patch_combined(args.write, actions, warnings)
    print("\nLeilan supplementary metadata patch\n-----------------------------------")
    print("Mode:", "WRITE" if args.write else "DRY RUN")
    print(f"Markdown files: {md}\nClaude transmissions: {cj}\nCombined records: {cb}")
    print("\nActions:"); [print("  -", a) for a in actions] if actions else print("  none")
    print("\nWarnings:"); [print("  -", w) for w in warnings] if warnings else print("  none")
    if not args.write: print("\nDry run only. To apply: python3 scripts/apply_supplementary_metadata.py --write")
    else: print("\nNext: python3 scripts/generate_manifest.py && python3 scripts/validate_dataset.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
