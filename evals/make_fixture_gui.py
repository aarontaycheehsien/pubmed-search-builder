#!/usr/bin/env python3
"""Standalone GUI to create new eval fixtures (no command line).

Richer than the "Create Fixture" tab in gui.py: it also exposes the full
**protocol** (the gate-resolving instructions the skill follows in Phase 2) as
editable fields, and previews the exact fixture JSON before writing.

It shells out to make_fixture.py (reusing its gold-set resolution: PMIDs, DOIs
via PubMed [AID], a PMIDs file, or a defining query) and passes the edited
protocol via --protocol-json, so nothing is reimplemented.

Launch by double-clicking ``make_fixture_gui.bat`` or run:
    python evals/make_fixture_gui.py
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
sys.path.insert(0, str(HERE))
from make_fixture import DEFAULT_PROTOCOL  # noqa: E402  (reuse the canonical defaults)

PROTOCOL_FIELDS = [
    ("seeds", "Seeds"),
    ("framework", "Framework"),
    ("essential_concepts", "Essential concepts"),
    ("optional_blocks", "Optional blocks"),
    ("methodological_filter", "Methodological filter"),
    ("limits", "Limits"),
    ("final_cleanup", "Final cleanup"),
    ("no_seed_recall", "No-seed recall check"),
]


class FixtureGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Create Eval Fixture")
        self.geometry("900x800")
        self.minsize(760, 680)
        self._q: queue.Queue[str | None] = queue.Queue()
        self._running = False
        self._build()
        self.after(100, self._drain)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 3}
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Topic id").grid(row=0, column=0, sticky="w")
        self.f_id = ttk.Entry(top, width=24)
        self.f_id.grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(top, text="Suite").grid(row=0, column=2, sticky="w")
        self.f_suite = ttk.Entry(top, width=18)
        self.f_suite.insert(0, "custom")
        self.f_suite.grid(row=0, column=3, sticky="w", **pad)
        self.f_force = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Overwrite if exists", variable=self.f_force).grid(row=0, column=4, sticky="w")

        ttk.Label(top, text="Question").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.f_question = tk.Text(top, width=78, height=3, wrap="word", font=("Segoe UI", 9))
        self.f_question.grid(row=1, column=1, columnspan=4, sticky="we", pady=(8, 0))
        top.columnconfigure(4, weight=1)

        # Gold source
        gold = ttk.LabelFrame(self, text="Gold relevant set (source)", padding=8)
        gold.pack(fill="x", padx=10, pady=6)
        self.src = tk.StringVar(value="pmids")
        for i, (val, label) in enumerate([
            ("pmids", "PMIDs (space-separated)"),
            ("dois", "DOIs file"),
            ("pmids_file", "PMIDs file"),
            ("query", "Defining query file"),
        ]):
            ttk.Radiobutton(gold, text=label, variable=self.src, value=val,
                            command=self._toggle_src).grid(row=i, column=0, sticky="w")
        self.g_input = ttk.Entry(gold, width=60)
        self.g_input.grid(row=0, column=1, rowspan=2, sticky="we", padx=6)
        self.g_browse = ttk.Button(gold, text="Browse...", command=self._browse)
        self.g_browse.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(gold, text="Query retmax").grid(row=3, column=0, sticky="w")
        self.g_retmax = ttk.Entry(gold, width=8)
        self.g_retmax.insert(0, "1000")
        self.g_retmax.grid(row=3, column=1, sticky="w", padx=6)
        gold.columnconfigure(1, weight=1)

        # Protocol (editable, pre-filled with defaults)
        proto = ttk.LabelFrame(self, text="Protocol (pre-resolves Phase 2 gates - edit per topic)", padding=8)
        proto.pack(fill="x", padx=10, pady=6)
        self.proto_widgets: dict[str, tk.Text] = {}
        for i, (key, label) in enumerate(PROTOCOL_FIELDS):
            ttk.Label(proto, text=label).grid(row=i, column=0, sticky="nw", pady=2)
            t = tk.Text(proto, width=78, height=2, wrap="word", font=("Segoe UI", 9))
            t.insert("1.0", DEFAULT_PROTOCOL.get(key, ""))
            t.grid(row=i, column=1, sticky="we", padx=6, pady=2)
            self.proto_widgets[key] = t
        proto.columnconfigure(1, weight=1)
        ttk.Button(proto, text="Reset protocol to defaults", command=self._reset_proto).grid(
            row=len(PROTOCOL_FIELDS), column=1, sticky="e", pady=(4, 0))

        # Actions
        actions = ttk.Frame(self, padding=(10, 4))
        actions.pack(fill="x")
        self.preview_btn = ttk.Button(actions, text="Preview JSON", command=self._preview)
        self.preview_btn.pack(side="left")
        self.create_btn = ttk.Button(actions, text="Create fixture", command=self._create)
        self.create_btn.pack(side="left", padx=8)
        self.status = ttk.Label(actions, text="ready", foreground="#555")
        self.status.pack(side="right")

        self.log = scrolledtext.ScrolledText(self, height=12, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log.configure(state="disabled")
        self._toggle_src()

    # ----- helpers ------------------------------------------------------
    def _toggle_src(self) -> None:
        is_file = self.src.get() in ("dois", "pmids_file", "query")
        self.g_browse.configure(state="normal" if is_file else "disabled")
        self.g_retmax.configure(state="normal" if self.src.get() == "query" else "disabled")

    def _browse(self) -> None:
        path = filedialog.askopenfilename(title="Select gold-source file",
                                          filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            self.g_input.delete(0, "end")
            self.g_input.insert(0, path)

    def _reset_proto(self) -> None:
        for key, t in self.proto_widgets.items():
            t.delete("1.0", "end")
            t.insert("1.0", DEFAULT_PROTOCOL.get(key, ""))

    def _protocol(self) -> dict:
        return {k: t.get("1.0", "end").strip() for k, t in self.proto_widgets.items()}

    def _collect(self) -> dict | None:
        fid = self.f_id.get().strip()
        question = self.f_question.get("1.0", "end").strip()
        value = self.g_input.get().strip()
        if not fid or "." in fid:
            messagebox.showwarning("Create", "Topic id is required and must not contain a dot.")
            return None
        if not question or not value:
            messagebox.showwarning("Create", "Question and a gold source are required.")
            return None
        return {"id": fid, "question": question, "value": value}

    def _preview(self) -> None:
        info = self._collect()
        if not info:
            return
        src = self.src.get()
        src_desc = {
            "pmids": f"PMIDs (CLI): {info['value']}",
            "dois": f"DOIs file: {info['value']} (resolved to PMIDs on create)",
            "pmids_file": f"PMIDs file: {info['value']}",
            "query": f"defining query: {info['value']} (retmax {self.g_retmax.get().strip()})",
        }[src]
        preview = {
            "id": info["id"],
            "suite": self.f_suite.get().strip() or "custom",
            "question": info["question"],
            "gold_relevant_pmids": "<resolved from gold source on create>",
            "gold_source": src_desc,
            "protocol": self._protocol(),
            "seed_pmids_given_to_skill": [],
        }
        self._log("\n--- fixture preview (gold resolves on create) ---\n")
        self._log(json.dumps(preview, indent=2) + "\n")

    def _create(self) -> None:
        info = self._collect()
        if not info or self._running:
            if self._running:
                messagebox.showinfo("Busy", "A job is already running.")
            return
        # write the edited protocol to a temp JSON and pass it through
        pj = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(self._protocol(), pj)
        pj.close()
        cmd = [sys.executable, "-u", str(HERE / "make_fixture.py"),
               "--id", info["id"], "--suite", self.f_suite.get().strip() or "custom",
               "--question", info["question"], "--protocol-json", pj.name]
        src = self.src.get()
        if src == "pmids":
            cmd += ["--gold-pmids", *info["value"].split()]
        elif src == "dois":
            cmd += ["--gold-dois-file", info["value"]]
        elif src == "pmids_file":
            cmd += ["--gold-pmids-file", info["value"]]
        else:
            cmd += ["--gold-query-file", info["value"], "--gold-retmax", self.g_retmax.get().strip() or "1000"]
        if self.f_force.get():
            cmd += ["--force"]
        self._launch(cmd)

    # ----- subprocess streaming ----------------------------------------
    def _launch(self, cmd: list[str]) -> None:
        self._running = True
        self.create_btn.configure(state="disabled")
        self.preview_btn.configure(state="disabled")
        self.status.configure(text="creating...")
        self._log(f"\n$ {' '.join(cmd)}\n")

        def worker() -> None:
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            try:
                proc = subprocess.Popen(
                    cmd, cwd=str(SKILL_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self._q.put(line)
                proc.wait()
                self._q.put(f"\n[done] exit code {proc.returncode}\n")
            except Exception as exc:  # pragma: no cover
                self._q.put(f"\n[error] {exc}\n")
            finally:
                self._q.put(None)

        threading.Thread(target=worker, daemon=True).start()

    def _drain(self) -> None:
        try:
            while True:
                item = self._q.get_nowait()
                if item is None:
                    self._running = False
                    self.create_btn.configure(state="normal")
                    self.preview_btn.configure(state="normal")
                    self.status.configure(text="ready")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    FixtureGUI().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
