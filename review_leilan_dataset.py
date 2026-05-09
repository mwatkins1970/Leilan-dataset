#!/usr/bin/env python3
"""
review_leilan_dataset.py

A small local Tkinter review/editing app for the rebuilt Leilan Claude-family
dataset JSON.

Default usage from the repo root:

    python3 review_leilan_dataset.py

or, explicitly:

    python3 review_leilan_dataset.py full_leilan_claude_dataset.json

No external packages are required.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText


APP_TITLE = "Leilan Dataset Q/A Reviewer v4"
DEFAULT_JSON = "full_leilan_claude_dataset.json"

STATUS_VALUES = [
    "unreviewed",
    "approved",
    "needs_fix",
    "exclude_from_training",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    """Write JSON atomically: temporary file in same directory, then replace."""
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


def make_backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.stem}.backup-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    return backup


def normalise_whitespace(s: str) -> str:
    return " ".join((s or "").split())


def preview(s: str, n: int = 120) -> str:
    s = normalise_whitespace(s or "")
    if len(s) > n:
        return s[: n - 1] + "…"
    return s


def list_pair_warnings(pair: Dict[str, Any]) -> List[str]:
    warnings = list(pair.get("warnings") or [])
    repair_notes = pair.get("repair_notes") or []
    if repair_notes:
        warnings.extend(f"repair:{note}" for note in repair_notes)
    return warnings


def response_has_issue(response: Dict[str, Any]) -> bool:
    if response.get("parse_warnings"):
        return True
    if response.get("review_status", {}).get("status") in {"needs_fix", "exclude_from_training"}:
        return True
    for pair in response.get("qa_pairs", []):
        if list_pair_warnings(pair):
            return True
        if not (pair.get("question") or "").strip():
            return True
        if not (pair.get("answer") or "").strip():
            return True
    return False


def transmission_issue_summary(transmission: Dict[str, Any]) -> List[str]:
    """Return human-readable issues that live at transmission level or below."""
    issues: List[str] = []

    build_warnings = transmission.get("build_warnings") or []
    for warning in build_warnings:
        if warning == "duplicate_model_responses_for_same_transmission":
            model_counts = Counter(r.get("model", "(unknown)") for r in transmission.get("responses", []))
            duplicates = [f"{model} x{count}" for model, count in sorted(model_counts.items()) if count > 1]
            if duplicates:
                issues.append("duplicate model responses: " + ", ".join(duplicates))
            else:
                issues.append(warning)
        else:
            issues.append(warning)

    response_issue_count = 0
    for response in transmission.get("responses", []):
        if response_has_issue(response):
            response_issue_count += 1

    if response_issue_count:
        issues.append(f"{response_issue_count} model response(s) contain response/Q-A warnings")

    return issues


def transmission_has_issue(transmission: Dict[str, Any]) -> bool:
    return bool(transmission_issue_summary(transmission))


def get_response_status(response: Dict[str, Any]) -> str:
    status = response.get("review_status", {}).get("status", "unreviewed")
    if status not in STATUS_VALUES:
        return "unreviewed"
    return status


def set_response_status(response: Dict[str, Any], status: str, notes: str = "") -> None:
    if status not in STATUS_VALUES:
        status = "unreviewed"

    response["review_status"] = {
        "status": status,
        "reviewed_utc": utc_now(),
        "notes": notes,
    }

    if status == "exclude_from_training":
        response["include_in_training"] = False
    elif status == "approved":
        response["include_in_training"] = True


def recompute_counts(data: Dict[str, Any]) -> None:
    transmissions = data.get("transmissions", [])
    response_count = 0
    qa_pair_count = 0
    model_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()

    for t in transmissions:
        responses = t.get("responses", [])
        response_count += len(responses)
        for r in responses:
            qa_pairs = r.get("qa_pairs", [])
            r["qa_pair_count"] = len(qa_pairs)
            qa_pair_count += len(qa_pairs)
            if r.get("model"):
                model_counter[r["model"]] += 1
            if r.get("source_directory"):
                source_counter[r["source_directory"]] += 1

            for idx, pair in enumerate(qa_pairs, start=1):
                pair["turn_index"] = idx
                pair["is_followup"] = idx > 1

    corpus = data.setdefault("corpus_info", {})
    corpus["transmission_count"] = len(transmissions)
    corpus["response_count"] = response_count
    corpus["qa_pair_count"] = qa_pair_count
    corpus["model_count"] = len(model_counter)
    corpus["model_counts"] = dict(sorted(model_counter.items()))
    corpus["source_directory_counts"] = dict(sorted(source_counter.items()))
    corpus["last_reviewed_or_edited_utc"] = utc_now()


def lightweight_validate_response(response: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    qa_pairs = response.get("qa_pairs", [])

    if not qa_pairs:
        issues.append("response_has_no_qa_pairs")

    for idx, pair in enumerate(qa_pairs, start=1):
        q = (pair.get("question") or "").strip()
        a = (pair.get("answer") or "").strip()
        if not q:
            issues.append(f"turn_{idx}_missing_question")
        if not a:
            issues.append(f"turn_{idx}_missing_answer")
        if len(a) < 20:
            issues.append(f"turn_{idx}_very_short_answer")
        if len(q) < 5:
            issues.append(f"turn_{idx}_very_short_question")

    return issues


def build_review_report(data: Dict[str, Any]) -> Dict[str, Any]:
    transmissions = data.get("transmissions", [])
    report: Dict[str, Any] = {
        "created_utc": utc_now(),
        "transmission_count": len(transmissions),
        "response_count": 0,
        "qa_pair_count": 0,
        "status_counts": {},
        "issue_counts": {},
        "responses_with_issues": [],
    }

    status_counter: Counter[str] = Counter()
    issue_counter: Counter[str] = Counter()

    for t in transmissions:
        tid = t.get("transmission_id", "")
        title = t.get("title", "")
        for r in t.get("responses", []):
            report["response_count"] += 1
            report["qa_pair_count"] += len(r.get("qa_pairs", []))
            status = get_response_status(r)
            status_counter[status] += 1

            issues: List[str] = []
            issues.extend(t.get("build_warnings") or [])
            issues.extend(r.get("parse_warnings") or [])
            issues.extend(lightweight_validate_response(r))
            for pair in r.get("qa_pairs", []):
                issues.extend(pair.get("warnings") or [])
                issues.extend(f"repair:{x}" for x in (pair.get("repair_notes") or []))

            if issues:
                for issue in issues:
                    issue_counter[issue] += 1
                report["responses_with_issues"].append(
                    {
                        "transmission_id": tid,
                        "title": title,
                        "model": r.get("model"),
                        "source_file": r.get("source_file"),
                        "status": status,
                        "issues": sorted(set(issues)),
                        "qa_pair_count": len(r.get("qa_pairs", [])),
                    }
                )

    report["status_counts"] = dict(sorted(status_counter.items()))
    report["issue_counts"] = dict(sorted(issue_counter.items()))
    return report


class ReviewApp:
    def __init__(self, root: tk.Tk, json_path: Path):
        self.root = root
        self.json_path = json_path
        self.data: Dict[str, Any] = {}
        self.transmissions: List[Dict[str, Any]] = []
        self.filtered_indices: List[int] = []

        self.current_t_index: Optional[int] = None
        self.current_response_index: Optional[int] = None
        self.current_pair_index: Optional[int] = None

        self.dirty = False
        self.loading = False

        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="all")
        self.status_var = tk.StringVar(value="unreviewed")
        self.notes_var = tk.StringVar()

        self._build_ui()
        self.load_file(json_path)

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        self.root.title(APP_TITLE)
        self.root.geometry("1280x820")
        self.root.minsize(1000, 650)

        self._build_menu()

        main = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=8)
        right = ttk.Frame(main, padding=8)
        main.add(left, weight=1)
        main.add(right, weight=3)

        self._build_left_panel(left)
        self._build_right_panel(right)

        self.status_bar = ttk.Label(self.root, anchor="w", relief=tk.SUNKEN)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open JSON…", command=self.open_json)
        file_menu.add_command(label="Save", command=self.save_json, accelerator="Cmd/Ctrl+S")
        file_menu.add_command(label="Save As…", command=self.save_as_json)
        file_menu.add_separator()
        file_menu.add_command(label="Export review report…", command=self.export_report)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menubar, tearoff=False)
        tools_menu.add_command(label="Validate current response", command=self.validate_current_response)
        tools_menu.add_command(label="Clear current response parser warnings", command=self.clear_response_warnings)
        tools_menu.add_command(label="Clear selected pair warnings", command=self.clear_pair_warnings)
        tools_menu.add_command(label="Recompute counts", command=self.recompute_and_refresh)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        self.root.config(menu=menubar)
        self.root.bind("<Control-s>", lambda event: self.save_json())
        self.root.bind("<Command-s>", lambda event: self.save_json())

    def _build_left_panel(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Transmissions", font=("TkDefaultFont", 13, "bold")).pack(anchor="w")

        controls = ttk.Frame(parent)
        controls.pack(fill=tk.X, pady=(6, 4))

        ttk.Label(controls, text="Filter").grid(row=0, column=0, sticky="w")
        filter_combo = ttk.Combobox(
            controls,
            textvariable=self.filter_var,
            values=["all", "needs_review", "approved", "unreviewed", "needs_fix", "excluded"],
            state="readonly",
            width=14,
        )
        filter_combo.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        filter_combo.bind("<<ComboboxSelected>>", lambda event: self.refresh_transmission_list())

        ttk.Label(controls, text="Search").grid(row=1, column=0, sticky="w", pady=(4, 0))
        search = ttk.Entry(controls, textvariable=self.search_var)
        search.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(4, 0))
        search.bind("<KeyRelease>", lambda event: self.refresh_transmission_list())
        controls.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.transmission_list = tk.Listbox(list_frame, exportselection=False)
        self.transmission_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.transmission_list.bind("<<ListboxSelect>>", self.on_transmission_selected)

        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.transmission_list.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.transmission_list.configure(yscrollcommand=scroll.set)

        self.left_info = ttk.Label(parent, text="", anchor="w", justify=tk.LEFT)
        self.left_info.pack(fill=tk.X, pady=(6, 0))

    def _build_right_panel(self, parent: ttk.Frame) -> None:
        top = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        top.pack(fill=tk.BOTH, expand=True)

        meta = ttk.Frame(top, padding=(0, 0, 0, 6))
        editor = ttk.Frame(top, padding=(0, 6, 0, 0))
        top.add(meta, weight=1)
        top.add(editor, weight=5)

        self._build_meta_panel(meta)
        self._build_editor_panel(editor)

    def _build_meta_panel(self, parent: ttk.Frame) -> None:
        """Top metadata area.

        v4 change: transmission details/issues are now in a wrapped, scrollable
        text box inside a horizontal paned layout. This prevents long
        transmission-level issue strings from forcing the model-response list
        off the right-hand side of the window.
        """
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        self.transmission_title = ttk.Label(
            parent,
            text="No file loaded",
            font=("TkDefaultFont", 13, "bold"),
            anchor="w",
        )
        self.transmission_title.grid(row=0, column=0, sticky="ew")

        meta_split = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        meta_split.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        details_frame = ttk.LabelFrame(meta_split, text="Transmission details / issues", padding=4)
        response_frame = ttk.LabelFrame(meta_split, text="Model responses", padding=4)

        meta_split.add(details_frame, weight=2)
        meta_split.add(response_frame, weight=3)

        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)

        self.transmission_meta = ScrolledText(
            details_frame,
            wrap=tk.WORD,
            height=6,
            width=48,
            undo=False,
            borderwidth=1,
            relief=tk.SUNKEN,
        )
        self.transmission_meta.grid(row=0, column=0, sticky="nsew")
        self.transmission_meta.configure(state=tk.DISABLED)

        response_frame.columnconfigure(0, weight=1)
        response_frame.rowconfigure(1, weight=1)

        response_header = ttk.Frame(response_frame)
        response_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        response_header.columnconfigure(0, weight=1)

        ttk.Label(response_header, text="").grid(row=0, column=0, sticky="w")
        ttk.Button(
            response_header,
            text="Delete selected model response",
            command=self.delete_current_response,
        ).grid(row=0, column=1, sticky="e")

        self.response_list = tk.Listbox(response_frame, height=6, exportselection=False)
        self.response_list.grid(row=1, column=0, sticky="nsew")
        self.response_list.bind("<<ListboxSelect>>", self.on_response_selected)

        rscroll = ttk.Scrollbar(response_frame, orient=tk.VERTICAL, command=self.response_list.yview)
        rscroll.grid(row=1, column=1, sticky="ns")
        self.response_list.configure(yscrollcommand=rscroll.set)

    def _build_editor_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)
        parent.rowconfigure(5, weight=3)

        status_frame = ttk.Frame(parent)
        status_frame.grid(row=0, column=0, sticky="ew")
        status_frame.columnconfigure(4, weight=1)

        ttk.Label(status_frame, text="Status").grid(row=0, column=0, sticky="w")
        status_combo = ttk.Combobox(status_frame, textvariable=self.status_var, values=STATUS_VALUES, state="readonly", width=22)
        status_combo.grid(row=0, column=1, sticky="w", padx=(6, 12))
        status_combo.bind("<<ComboboxSelected>>", lambda event: self.apply_status())

        ttk.Label(status_frame, text="Review notes").grid(row=0, column=2, sticky="w")
        notes_entry = ttk.Entry(status_frame, textvariable=self.notes_var)
        notes_entry.grid(row=0, column=3, columnspan=2, sticky="ew", padx=(6, 0))

        ttk.Button(status_frame, text="Mark approved", command=lambda: self.set_status("approved")).grid(row=0, column=5, padx=(8, 0))
        ttk.Button(status_frame, text="Needs fix", command=lambda: self.set_status("needs_fix")).grid(row=0, column=6, padx=(4, 0))
        ttk.Button(status_frame, text="Exclude", command=lambda: self.set_status("exclude_from_training")).grid(row=0, column=7, padx=(4, 0))

        self.response_warning_label = ttk.Label(parent, text="", foreground="#8a4b00", justify=tk.LEFT, wraplength=900)
        self.response_warning_label.grid(row=1, column=0, sticky="ew", pady=(6, 4))

        pair_top = ttk.Frame(parent)
        pair_top.grid(row=2, column=0, sticky="ew")
        pair_top.columnconfigure(0, weight=1)

        ttk.Label(pair_top, text="Q/A turns").grid(row=0, column=0, sticky="w")
        btns = ttk.Frame(pair_top)
        btns.grid(row=0, column=1, sticky="e")
        ttk.Button(btns, text="Apply edits", command=self.apply_pair_edits).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Add after", command=self.add_pair_after_current).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Delete", command=self.delete_current_pair).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Up", command=lambda: self.move_pair(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Down", command=lambda: self.move_pair(1)).pack(side=tk.LEFT, padx=2)

        pair_frame = ttk.Frame(parent)
        pair_frame.grid(row=3, column=0, sticky="nsew")
        pair_frame.columnconfigure(0, weight=1)
        pair_frame.rowconfigure(0, weight=1)

        self.pair_list = tk.Listbox(pair_frame, height=5, exportselection=False)
        self.pair_list.grid(row=0, column=0, sticky="nsew")
        self.pair_list.bind("<<ListboxSelect>>", self.on_pair_selected)

        pscroll = ttk.Scrollbar(pair_frame, orient=tk.VERTICAL, command=self.pair_list.yview)
        pscroll.grid(row=0, column=1, sticky="ns")
        self.pair_list.configure(yscrollcommand=pscroll.set)

        ttk.Label(parent, text="Question").grid(row=4, column=0, sticky="w", pady=(6, 0))
        self.question_text = ScrolledText(parent, wrap=tk.WORD, height=7, undo=True)
        self.question_text.grid(row=5, column=0, sticky="nsew")
        self.question_text.bind("<<Modified>>", self.on_text_modified)

        ttk.Label(parent, text="Answer").grid(row=6, column=0, sticky="w", pady=(6, 0))
        self.answer_text = ScrolledText(parent, wrap=tk.WORD, height=14, undo=True)
        self.answer_text.grid(row=7, column=0, sticky="nsew")
        self.answer_text.bind("<<Modified>>", self.on_text_modified)
        parent.rowconfigure(7, weight=4)

        self.pair_warning_label = ttk.Label(parent, text="", foreground="#8a4b00", justify=tk.LEFT, wraplength=900)
        self.pair_warning_label.grid(row=8, column=0, sticky="ew", pady=(6, 0))

    # ---------- Loading / saving ----------

    def load_file(self, path: Path) -> None:
        try:
            self.data = load_json(path)
        except Exception as e:
            messagebox.showerror("Could not load JSON", str(e))
            return

        self.json_path = path
        self.transmissions = self.data.get("transmissions", [])
        self.current_t_index = None
        self.current_response_index = None
        self.current_pair_index = None
        self.dirty = False
        self.refresh_transmission_list()
        self.update_status_bar()
        self.root.title(f"{APP_TITLE} — {self.json_path.name}")

    def open_json(self) -> None:
        if not self.confirm_discard_if_dirty():
            return
        path = filedialog.askopenfilename(
            title="Open Leilan dataset JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.load_file(Path(path))

    def save_json(self) -> None:
        if not self.data:
            return
        self.apply_pair_edits(silent=True)
        recompute_counts(self.data)

        try:
            backup = make_backup(self.json_path)
            write_json_atomic(self.json_path, self.data)
        except Exception as e:
            messagebox.showerror("Save failed", str(e))
            return

        self.dirty = False
        self.update_status_bar(f"Saved. Backup created: {backup.name}")

    def save_as_json(self) -> None:
        if not self.data:
            return
        path = filedialog.asksaveasfilename(
            title="Save dataset JSON as",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        self.apply_pair_edits(silent=True)
        recompute_counts(self.data)
        try:
            write_json_atomic(Path(path), self.data)
        except Exception as e:
            messagebox.showerror("Save As failed", str(e))
            return
        self.json_path = Path(path)
        self.dirty = False
        self.update_status_bar(f"Saved as {self.json_path.name}")

    def export_report(self) -> None:
        if not self.data:
            return
        self.apply_pair_edits(silent=True)
        report = build_review_report(self.data)
        default = self.json_path.with_name("leilan_dataset_review_report.json")
        path = filedialog.asksaveasfilename(
            title="Export review report",
            initialfile=default.name,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            write_json_atomic(Path(path), report)
        except Exception as e:
            messagebox.showerror("Export failed", str(e))
            return
        self.update_status_bar(f"Exported review report: {Path(path).name}")

    def confirm_discard_if_dirty(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved changes",
            "You have unsaved changes. Save before continuing?",
        )
        if answer is None:
            return False
        if answer:
            self.save_json()
            return not self.dirty
        return True

    def quit_app(self) -> None:
        if self.confirm_discard_if_dirty():
            self.root.destroy()

    # ---------- Selection and filtering ----------

    def refresh_transmission_list(self) -> None:
        self.apply_pair_edits(silent=True)
        self.transmission_list.delete(0, tk.END)
        self.filtered_indices = []

        search = self.search_var.get().strip().lower()
        mode = self.filter_var.get()

        for idx, t in enumerate(self.transmissions):
            if not self._passes_filter(t, mode):
                continue

            label = self._transmission_label(t)
            if search:
                haystack = " ".join(
                    [
                        str(t.get("transmission_id", "")),
                        str(t.get("title", "")),
                        str(t.get("slug", "")),
                        " ".join(r.get("model", "") for r in t.get("responses", [])),
                    ]
                ).lower()
                if search not in haystack:
                    continue

            self.filtered_indices.append(idx)
            self.transmission_list.insert(tk.END, label)

        if self.filtered_indices:
            self.transmission_list.selection_set(0)
            self.on_transmission_selected()
        else:
            self.clear_current_view()

        self.left_info.config(text=f"Showing {len(self.filtered_indices)} / {len(self.transmissions)} transmissions")

    def _passes_filter(self, t: Dict[str, Any], mode: str) -> bool:
        if mode == "all":
            return True
        if mode == "needs_review":
            return transmission_has_issue(t)

        responses = t.get("responses", [])
        if mode == "approved":
            return any(get_response_status(r) == "approved" for r in responses)
        if mode == "unreviewed":
            return any(get_response_status(r) == "unreviewed" for r in responses)
        if mode == "needs_fix":
            return any(get_response_status(r) == "needs_fix" for r in responses)
        if mode == "excluded":
            return any(get_response_status(r) == "exclude_from_training" for r in responses)

        return True

    def _transmission_label(self, t: Dict[str, Any]) -> str:
        tid = t.get("transmission_id", "")
        title = t.get("title", "")
        responses = len(t.get("responses", []))
        qas = sum(len(r.get("qa_pairs", [])) for r in t.get("responses", []))
        issue = "⚠ " if transmission_has_issue(t) else ""
        return f"{issue}{tid} — {title}  [{responses} voices / {qas} QAs]"

    def on_transmission_selected(self, event: Optional[tk.Event] = None) -> None:
        if self.loading:
            return
        selection = self.transmission_list.curselection()
        if not selection:
            return
        self.apply_pair_edits(silent=True)
        list_index = selection[0]
        self.current_t_index = self.filtered_indices[list_index]
        self.current_response_index = None
        self.current_pair_index = None
        self.load_current_transmission()

    def set_transmission_meta_text(self, text: str) -> None:
        """Set the wrapped/scrollable transmission metadata text safely."""
        self.transmission_meta.configure(state=tk.NORMAL)
        self.transmission_meta.delete("1.0", tk.END)
        self.transmission_meta.insert("1.0", text)
        self.transmission_meta.configure(state=tk.DISABLED)


    def load_current_transmission(self) -> None:
        t = self.current_transmission()
        if not t:
            self.clear_current_view()
            return

        self.transmission_title.config(text=f"{t.get('transmission_id', '')} — {t.get('title', '')}")
        transmission_issues = transmission_issue_summary(t)
        meta_lines = [
            f"Slug: {t.get('slug', '')}",
            f"Dates: {', '.join(t.get('dates') or [])}",
            f"Substack URL: {t.get('substack_url') or '(none)'}",
            "Transmission-level issues: " + ("; ".join(transmission_issues) if transmission_issues else "none"),
        ]
        self.set_transmission_meta_text("\n".join(meta_lines))

        self.response_list.delete(0, tk.END)
        for i, r in enumerate(t.get("responses", [])):
            self.response_list.insert(tk.END, self._response_label(r, i))

        if t.get("responses"):
            self.response_list.selection_set(0)
            self.on_response_selected()
        else:
            self.clear_response_view()

    def _response_label(self, r: Dict[str, Any], index: int) -> str:
        issue = "⚠ " if response_has_issue(r) else ""
        model = r.get("model", "(unknown model)")
        variant = r.get("response_variant_index_for_model", 1)
        variant_text = f" variant {variant}" if variant and variant > 1 else ""
        qas = len(r.get("qa_pairs", []))
        status = get_response_status(r)
        date = r.get("source_date", "")
        return f"{issue}{model}{variant_text} — {date} — {qas} QAs — {status}"

    def on_response_selected(self, event: Optional[tk.Event] = None) -> None:
        if self.loading:
            return
        selection = self.response_list.curselection()
        if not selection:
            return
        self.apply_pair_edits(silent=True)
        self.current_response_index = selection[0]
        self.current_pair_index = None
        self.load_current_response()

    def load_current_response(self) -> None:
        r = self.current_response()
        if not r:
            self.clear_response_view()
            return

        self.status_var.set(get_response_status(r))
        self.notes_var.set(r.get("review_status", {}).get("notes", ""))

        warnings = []
        warnings.extend(r.get("parse_warnings") or [])
        warnings.extend(lightweight_validate_response(r))

        # If the current transmission has duplicate responses for this model,
        # show it here too. This is technically a transmission-level issue, but
        # users expect to see it when clicking the affected response.
        t = self.current_transmission()
        if t:
            model_counts = Counter(resp.get("model", "(unknown)") for resp in t.get("responses", []))
            current_model = r.get("model", "(unknown)")
            if model_counts.get(current_model, 0) > 1:
                warnings.append(f"duplicate_model_response_for_this_transmission: {current_model} appears {model_counts[current_model]} times")

        self.response_warning_label.config(
            text="Response warnings: " + (", ".join(sorted(set(warnings))) if warnings else "none")
        )

        self.pair_list.delete(0, tk.END)
        for i, pair in enumerate(r.get("qa_pairs", [])):
            self.pair_list.insert(tk.END, self._pair_label(pair, i))

        if r.get("qa_pairs"):
            self.pair_list.selection_set(0)
            self.on_pair_selected()
        else:
            self.clear_pair_editor()

    def _pair_label(self, pair: Dict[str, Any], index: int) -> str:
        issue = "⚠ " if list_pair_warnings(pair) or not pair.get("question") or not pair.get("answer") else ""
        q_preview = preview(pair.get("question", ""), 80)
        return f"{issue}Turn {index + 1}: {q_preview}"

    def on_pair_selected(self, event: Optional[tk.Event] = None) -> None:
        if self.loading:
            return
        selection = self.pair_list.curselection()
        if not selection:
            return
        self.apply_pair_edits(silent=True)
        self.current_pair_index = selection[0]
        self.load_current_pair()

    def load_current_pair(self) -> None:
        pair = self.current_pair()
        if not pair:
            self.clear_pair_editor()
            return

        self.loading = True
        self.question_text.delete("1.0", tk.END)
        self.answer_text.delete("1.0", tk.END)
        self.question_text.insert("1.0", pair.get("question", ""))
        self.answer_text.insert("1.0", pair.get("answer", ""))
        self.question_text.edit_modified(False)
        self.answer_text.edit_modified(False)
        self.loading = False

        pair_warnings = list_pair_warnings(pair)
        extra = []
        if pair.get("split_method"):
            extra.append(f"split: {pair.get('split_method')}")
        if pair.get("split_confidence"):
            extra.append(f"confidence: {pair.get('split_confidence')}")
        if pair_warnings:
            extra.append("warnings: " + ", ".join(pair_warnings))
        self.pair_warning_label.config(text=" | ".join(extra) if extra else "Pair warnings: none")

    # ---------- Editing ----------

    def apply_pair_edits(self, silent: bool = False) -> None:
        pair = self.current_pair()
        if not pair or self.loading:
            return

        q = self.question_text.get("1.0", "end-1c")
        a = self.answer_text.get("1.0", "end-1c")

        if pair.get("question", "") != q or pair.get("answer", "") != a:
            pair["question"] = q
            pair["answer"] = a
            pair["edited_utc"] = utc_now()
            pair["edited_by"] = "review_leilan_dataset.py"
            self.mark_dirty()
            self.refresh_pair_list_labels()
            if not silent:
                self.update_status_bar("Applied edits to current Q/A pair.")

        self.question_text.edit_modified(False)
        self.answer_text.edit_modified(False)

    def on_text_modified(self, event: tk.Event) -> None:
        if self.loading:
            return
        widget = event.widget
        try:
            if widget.edit_modified():
                self.mark_dirty(status_message="Unsaved text edits")
                widget.edit_modified(False)
        except tk.TclError:
            pass

    def add_pair_after_current(self) -> None:
        r = self.current_response()
        if not r:
            return
        self.apply_pair_edits(silent=True)

        qa_pairs = r.setdefault("qa_pairs", [])
        insert_at = (self.current_pair_index + 1) if self.current_pair_index is not None else len(qa_pairs)
        new_pair = {
            "turn_index": insert_at + 1,
            "question": "",
            "answer": "",
            "is_followup": insert_at > 0,
            "split_method": "manual_added_in_review_app",
            "split_confidence": "manual",
            "source_character_start": None,
            "source_character_end": None,
            "warnings": ["manual_entry_needs_review"],
            "created_utc": utc_now(),
        }
        qa_pairs.insert(insert_at, new_pair)
        self.renumber_pairs(r)
        self.current_pair_index = insert_at
        self.mark_dirty("Added new Q/A pair.")
        self.load_current_response()
        self.pair_list.selection_clear(0, tk.END)
        self.pair_list.selection_set(insert_at)
        self.on_pair_selected()

    def delete_current_response(self) -> None:
        """Delete the selected model response from the current transmission."""
        t = self.current_transmission()
        if not t or self.current_response_index is None:
            return

        responses = t.get("responses", [])
        if not responses or self.current_response_index >= len(responses):
            return

        r = responses[self.current_response_index]
        model = r.get("model", "(unknown model)")
        date = r.get("source_date", "")
        source_file = r.get("source_file", "")

        confirm = messagebox.askyesno(
            "Delete model response",
            "Delete this entire model response from the dataset?\n\n"
            f"Model: {model}\n"
            f"Date: {date}\n"
            f"Source: {source_file}\n\n"
            "This removes the response and all its Q/A turns. A backup is made when you save.",
        )
        if not confirm:
            return

        del responses[self.current_response_index]

        # If deleting resolves duplicate-model warnings, clear that build warning.
        model_counts = Counter(resp.get("model", "(unknown)") for resp in responses)
        if all(count == 1 for count in model_counts.values()):
            t["build_warnings"] = [
                w for w in (t.get("build_warnings") or [])
                if w != "duplicate_model_responses_for_same_transmission"
            ]

        # Reassign per-model variant indices after deletion.
        variant_counts: Counter[str] = Counter()
        for response in responses:
            response_model = response.get("model", "(unknown)")
            variant_counts[response_model] += 1
            response["response_variant_index_for_model"] = variant_counts[response_model]

        t.setdefault("curator_notes", "")
        t["curator_notes"] = (t.get("curator_notes") or "") + (
            f"\n[review app {utc_now()}] Deleted duplicate/undesired model response: "
            f"{model} from {source_file}"
        )

        self.current_response_index = min(self.current_response_index, len(responses) - 1) if responses else None
        self.current_pair_index = None
        self.mark_dirty("Deleted model response. Save to write changes.")
        self.load_current_transmission()

        if self.current_response_index is not None:
            self.response_list.selection_clear(0, tk.END)
            self.response_list.selection_set(self.current_response_index)
            self.on_response_selected()


    def delete_current_pair(self) -> None:
        r = self.current_response()
        if not r or self.current_pair_index is None:
            return
        qa_pairs = r.get("qa_pairs", [])
        if not qa_pairs:
            return

        if not messagebox.askyesno("Delete Q/A pair", "Delete the selected Q/A pair?"):
            return

        del qa_pairs[self.current_pair_index]
        self.renumber_pairs(r)
        self.current_pair_index = min(self.current_pair_index, len(qa_pairs) - 1) if qa_pairs else None
        self.mark_dirty("Deleted Q/A pair.")
        self.load_current_response()
        if self.current_pair_index is not None:
            self.pair_list.selection_set(self.current_pair_index)
            self.on_pair_selected()

    def move_pair(self, delta: int) -> None:
        r = self.current_response()
        if not r or self.current_pair_index is None:
            return
        qa_pairs = r.get("qa_pairs", [])
        old = self.current_pair_index
        new = old + delta
        if new < 0 or new >= len(qa_pairs):
            return

        self.apply_pair_edits(silent=True)
        qa_pairs[old], qa_pairs[new] = qa_pairs[new], qa_pairs[old]
        self.renumber_pairs(r)
        self.current_pair_index = new
        self.mark_dirty("Moved Q/A pair.")
        self.load_current_response()
        self.pair_list.selection_clear(0, tk.END)
        self.pair_list.selection_set(new)
        self.on_pair_selected()

    def renumber_pairs(self, response: Dict[str, Any]) -> None:
        for idx, pair in enumerate(response.get("qa_pairs", []), start=1):
            pair["turn_index"] = idx
            pair["is_followup"] = idx > 1
        response["qa_pair_count"] = len(response.get("qa_pairs", []))

    def set_status(self, status: str) -> None:
        self.status_var.set(status)
        self.apply_status()

    def apply_status(self) -> None:
        r = self.current_response()
        if not r:
            return
        set_response_status(r, self.status_var.get(), self.notes_var.get())
        self.mark_dirty(f"Marked response as {self.status_var.get()}.")
        self.refresh_response_list_labels()

    def validate_current_response(self) -> None:
        r = self.current_response()
        if not r:
            return
        issues = lightweight_validate_response(r)
        if issues:
            messagebox.showwarning("Validation issues", "\n".join(issues))
        else:
            messagebox.showinfo("Validation", "No obvious validation issues found.")

    def clear_response_warnings(self) -> None:
        r = self.current_response()
        if not r:
            return
        if not messagebox.askyesno(
            "Clear parser warnings",
            "Clear parse_warnings on the current model response?\n\nThis does not alter the Q/A text.",
        ):
            return
        r["parse_warnings"] = []
        r["warnings_cleared_utc"] = utc_now()
        self.mark_dirty("Cleared response parser warnings.")
        self.load_current_response()
        self.refresh_response_list_labels()

    def clear_pair_warnings(self) -> None:
        pair = self.current_pair()
        if not pair:
            return
        if not messagebox.askyesno(
            "Clear pair warnings",
            "Clear warnings and repair_notes on the selected Q/A pair?",
        ):
            return
        pair["warnings"] = []
        pair["repair_notes"] = []
        pair["warnings_cleared_utc"] = utc_now()
        self.mark_dirty("Cleared pair warnings.")
        self.load_current_pair()
        self.refresh_pair_list_labels()

    def recompute_and_refresh(self) -> None:
        if not self.data:
            return
        self.apply_pair_edits(silent=True)
        recompute_counts(self.data)
        self.mark_dirty("Recomputed counts.")
        self.refresh_transmission_list()

    # ---------- Current object helpers ----------

    def current_transmission(self) -> Optional[Dict[str, Any]]:
        if self.current_t_index is None:
            return None
        if 0 <= self.current_t_index < len(self.transmissions):
            return self.transmissions[self.current_t_index]
        return None

    def current_response(self) -> Optional[Dict[str, Any]]:
        t = self.current_transmission()
        if not t or self.current_response_index is None:
            return None
        responses = t.get("responses", [])
        if 0 <= self.current_response_index < len(responses):
            return responses[self.current_response_index]
        return None

    def current_pair(self) -> Optional[Dict[str, Any]]:
        r = self.current_response()
        if not r or self.current_pair_index is None:
            return None
        pairs = r.get("qa_pairs", [])
        if 0 <= self.current_pair_index < len(pairs):
            return pairs[self.current_pair_index]
        return None

    # ---------- Refresh / clearing helpers ----------

    def refresh_response_list_labels(self) -> None:
        t = self.current_transmission()
        if not t:
            return
        selected = self.current_response_index
        self.response_list.delete(0, tk.END)
        for i, r in enumerate(t.get("responses", [])):
            self.response_list.insert(tk.END, self._response_label(r, i))
        if selected is not None and selected < self.response_list.size():
            self.response_list.selection_set(selected)

    def refresh_pair_list_labels(self) -> None:
        r = self.current_response()
        if not r:
            return
        selected = self.current_pair_index
        self.pair_list.delete(0, tk.END)
        for i, pair in enumerate(r.get("qa_pairs", [])):
            self.pair_list.insert(tk.END, self._pair_label(pair, i))
        if selected is not None and selected < self.pair_list.size():
            self.pair_list.selection_set(selected)

    def clear_current_view(self) -> None:
        self.transmission_title.config(text="No transmission selected")
        self.set_transmission_meta_text("")
        self.response_list.delete(0, tk.END)
        self.clear_response_view()

    def clear_response_view(self) -> None:
        self.response_warning_label.config(text="")
        self.pair_list.delete(0, tk.END)
        self.clear_pair_editor()

    def clear_pair_editor(self) -> None:
        self.loading = True
        self.question_text.delete("1.0", tk.END)
        self.answer_text.delete("1.0", tk.END)
        self.loading = False
        self.pair_warning_label.config(text="")

    def mark_dirty(self, status_message: str = "Unsaved changes") -> None:
        self.dirty = True
        self.update_status_bar(status_message)

    def update_status_bar(self, message: str = "") -> None:
        corpus = self.data.get("corpus_info", {}) if self.data else {}
        base = (
            f"{self.json_path} | "
            f"{corpus.get('transmission_count', len(self.transmissions))} transmissions | "
            f"{corpus.get('response_count', '?')} responses | "
            f"{corpus.get('qa_pair_count', '?')} Q/A pairs"
        )
        if self.dirty:
            base += " | UNSAVED"
        if message:
            base += f" | {message}"
        self.status_bar.config(text=base)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review/edit the Leilan Claude-family dataset JSON.")
    parser.add_argument(
        "json_file",
        nargs="?",
        default=DEFAULT_JSON,
        help=f"Dataset JSON file to open. Default: {DEFAULT_JSON}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    json_path = Path(args.json_file)

    if not json_path.exists():
        print(f"Could not find JSON file: {json_path}")
        print("Run this from the repo folder, or pass the JSON filename explicitly.")
        raise SystemExit(1)

    root = tk.Tk()
    app = ReviewApp(root, json_path)

    def on_close() -> None:
        app.quit_app()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
