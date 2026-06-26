#!/usr/bin/env python3
"""Tkinter GUI for the eval harness - run everything without the command line.

Exposes the three CLI tools behind a window:
  * Run Eval     -> run_eval.py (score baseline, Phase 1) or generate.py (skill
                    builds the strategy, Phase 2)
  * Create Fixture -> make_fixture.py (from PMIDs, DOIs, a PMIDs file, or a
                    defining query)

It shells out to the same scripts (reusing all logic) and streams their output
live into a log pane. Long Phase 2 builds run on a worker thread so the window
stays responsive.

Launch by double-clicking ``eval_gui.bat`` (no console) or run:
    python evals/gui.py
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
DATASETS = HERE / "datasets"
sys.path.insert(0, str(HERE))
import run_eval  # noqa: E402  (resolve_fixture for baseline save)


def list_topics() -> list[str]:
    """All fixture topic ids (dotted auxiliary stems excluded)."""
    return sorted(f.stem for f in DATASETS.glob("**/*.json") if "." not in f.stem)


class EvalGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PubMed Search Builder - Eval")
        self.geometry("860x720")
        self.minsize(720, 600)
        self._q: queue.Queue[str | None] = queue.Queue()
        self._running = False
        self._build()
        self.after(100, self._drain_log)

    # ----- layout -------------------------------------------------------
    def _build(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="x", padx=10, pady=(10, 6))
        self._build_run_tab(nb)
        self._build_fixture_tab(nb)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10)
        self.open_btn = ttk.Button(bar, text="Open results folder", command=self._open_results)
        self.open_btn.pack(side="left")
        self.clear_btn = ttk.Button(bar, text="Clear log", command=self._clear_log)
        self.clear_btn.pack(side="left", padx=6)
        self.status = ttk.Label(bar, text="ready", foreground="#555")
        self.status.pack(side="right")

        ttk.Label(self, text="Output", foreground="#555").pack(anchor="w", padx=12, pady=(8, 0))
        self.log = scrolledtext.ScrolledText(self, height=18, wrap="word", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log.configure(state="disabled")
        self._toggle_phase2()  # set initial enabled/disabled state by mode

    def _build_run_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=12)
        nb.add(tab, text="Run Eval")

        ttk.Label(tab, text="Topic").grid(row=0, column=0, sticky="w")
        self.topic = ttk.Combobox(tab, values=list_topics(), width=24, state="readonly")
        if self.topic["values"]:
            self.topic.current(0)
        self.topic.grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Button(tab, text="Refresh", command=self._refresh_topics).grid(row=0, column=2, sticky="w")

        self.mode = tk.StringVar(value="generate")
        ttk.Label(tab, text="Mode").grid(row=1, column=0, sticky="w", pady=(8, 0))
        modes = ttk.Frame(tab)
        modes.grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Radiobutton(modes, text="Generate with skill (Phase 2)", variable=self.mode,
                        value="generate", command=self._toggle_phase2).pack(anchor="w")
        ttk.Radiobutton(modes, text="Score baseline strategy (Phase 1)", variable=self.mode,
                        value="score", command=self._toggle_phase2).pack(anchor="w")

        self.p2 = ttk.LabelFrame(tab, text="Phase 2 options", padding=8)
        self.p2.grid(row=2, column=0, columnspan=3, sticky="we", pady=10)
        ttk.Label(self.p2, text="Reasoning effort").grid(row=0, column=0, sticky="w")
        self.effort = ttk.Combobox(self.p2, values=["low", "medium", "high", "xhigh"], width=10, state="readonly")
        self.effort.set("medium")
        self.effort.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(self.p2, text="Timeout (s)").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.timeout = ttk.Entry(self.p2, width=8)
        self.timeout.insert(0, "1800")
        self.timeout.grid(row=0, column=3, sticky="w", padx=6)
        ttk.Label(self.p2, text="Model (optional)").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.model = ttk.Entry(self.p2, width=20)
        self.model.grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=(6, 0))

        # Baseline strategy (Score / Phase 1 mode)
        self.bl = ttk.LabelFrame(tab, text="Baseline strategy (Score mode)", padding=8)
        self.bl.grid(row=3, column=0, columnspan=3, sticky="we", pady=(0, 8))
        btns = ttk.Frame(self.bl)
        btns.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Button(btns, text="Load topic's current baseline", command=self._load_baseline).pack(side="left")
        ttk.Button(btns, text="Load from file...", command=self._load_strategy_file).pack(side="left", padx=6)
        self.strategy = scrolledtext.ScrolledText(self.bl, height=7, wrap="none", font=("Consolas", 9))
        self.strategy.grid(row=1, column=0, columnspan=3, sticky="we", pady=4)
        ttk.Label(self.bl, text="Concept blocks JSON (optional, for per-block diagnosis)").grid(
            row=2, column=0, sticky="w")
        self.blocks_path = ttk.Entry(self.bl, width=44)
        self.blocks_path.grid(row=3, column=0, sticky="we", padx=(0, 6))
        ttk.Button(self.bl, text="Browse...", command=self._browse_blocks).grid(row=3, column=1, sticky="w")
        self.save_baseline = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.bl, text="Save as this topic's baseline (persist to the fixture)",
                        variable=self.save_baseline).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(self.bl, text="Leave the strategy box empty to score the fixture's existing baseline.",
                  foreground="#888").grid(row=5, column=0, columnspan=3, sticky="w")
        self.bl.columnconfigure(0, weight=1)

        self.run_btn = ttk.Button(tab, text="Run", command=self._run_eval)
        self.run_btn.grid(row=4, column=0, sticky="w", pady=6)
        ttk.Label(tab, text="(Phase 2 is a full agentic build - minutes, real tokens)",
                  foreground="#888").grid(row=4, column=1, columnspan=2, sticky="w")

    def _build_fixture_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=12)
        nb.add(tab, text="Create Fixture")

        ttk.Label(tab, text="Topic id").grid(row=0, column=0, sticky="w")
        self.f_id = ttk.Entry(tab, width=24)
        self.f_id.grid(row=0, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(tab, text="Suite").grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.f_suite = ttk.Entry(tab, width=16)
        self.f_suite.insert(0, "custom")
        self.f_suite.grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(tab, text="Question").grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.f_question = tk.Text(tab, width=64, height=4, wrap="word", font=("Segoe UI", 9))
        self.f_question.grid(row=1, column=1, columnspan=3, sticky="we", padx=6, pady=(8, 0))

        gold = ttk.LabelFrame(tab, text="Gold relevant set (source)", padding=8)
        gold.grid(row=2, column=0, columnspan=4, sticky="we", pady=10)
        self.f_src = tk.StringVar(value="pmids")
        rows = [
            ("pmids", "PMIDs (space-separated)"),
            ("dois", "DOIs file"),
            ("pmids_file", "PMIDs file"),
            ("query", "Defining query file"),
        ]
        for i, (val, label) in enumerate(rows):
            ttk.Radiobutton(gold, text=label, variable=self.f_src, value=val,
                            command=self._toggle_src).grid(row=i, column=0, sticky="w")
        self.f_input = ttk.Entry(gold, width=46)
        self.f_input.grid(row=0, column=1, rowspan=2, sticky="we", padx=6)
        self.f_browse = ttk.Button(gold, text="Browse...", command=self._browse_gold)
        self.f_browse.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(gold, text="Query retmax").grid(row=3, column=0, sticky="w")
        self.f_retmax = ttk.Entry(gold, width=8)
        self.f_retmax.insert(0, "1000")
        self.f_retmax.grid(row=3, column=1, sticky="w", padx=6)
        gold.columnconfigure(1, weight=1)

        self.f_force = tk.BooleanVar(value=False)
        ttk.Checkbutton(tab, text="Overwrite if exists", variable=self.f_force).grid(row=3, column=0, sticky="w")
        self.make_btn = ttk.Button(tab, text="Create fixture", command=self._make_fixture)
        self.make_btn.grid(row=4, column=0, sticky="w", pady=6)
        self._toggle_src()

    # ----- helpers ------------------------------------------------------
    def _refresh_topics(self) -> None:
        self.topic["values"] = list_topics()
        if self.topic["values"] and not self.topic.get():
            self.topic.current(0)

    def _toggle_phase2(self) -> None:
        gen = self.mode.get() == "generate"
        for child in self.p2.winfo_children():
            try:
                child.configure(state="normal" if gen else "disabled")
            except tk.TclError:
                pass
        self._set_frame_state(self.bl, "disabled" if gen else "normal")

    @staticmethod
    def _set_frame_state(frame: ttk.LabelFrame, state: str) -> None:
        for child in frame.winfo_children():
            for w in (child, *child.winfo_children()):
                try:
                    w.configure(state=state)
                except tk.TclError:
                    pass

    def _load_strategy_file(self) -> None:
        path = filedialog.askopenfilename(title="Load strategy file",
                                          filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            self.strategy.delete("1.0", "end")
            self.strategy.insert("1.0", Path(path).read_text(encoding="utf-8-sig"))

    def _load_baseline(self) -> None:
        topic = self.topic.get().strip()
        if not topic:
            return
        try:
            fp = run_eval.resolve_fixture(topic)
            fx = json.loads(fp.read_text(encoding="utf-8"))
        except SystemExit as exc:
            messagebox.showwarning("Baseline", str(exc))
            return
        sfile = fx.get("strategy_file")
        if not sfile or not (fp.parent / sfile).exists():
            messagebox.showinfo("Baseline", f"Topic {topic} has no baseline strategy yet. Paste or load one.")
            return
        self.strategy.delete("1.0", "end")
        self.strategy.insert("1.0", (fp.parent / sfile).read_text(encoding="utf-8-sig"))
        bfile = fx.get("blocks_file")
        if bfile and (fp.parent / bfile).exists():
            self.blocks_path.delete(0, "end")
            self.blocks_path.insert(0, str(fp.parent / bfile))

    def _browse_blocks(self) -> None:
        path = filedialog.askopenfilename(title="Concept blocks JSON",
                                          filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if path:
            self.blocks_path.delete(0, "end")
            self.blocks_path.insert(0, path)

    def _save_topic_baseline(self, topic: str, strategy_text: str) -> Path:
        """Persist a strategy as the topic's baseline (writes <id>.strategy.txt and
        sets strategy_file in the fixture) so score-only works for it going forward."""
        fp = run_eval.resolve_fixture(topic)
        fx = json.loads(fp.read_text(encoding="utf-8"))
        sfile = f"{fx['id']}.strategy.txt"
        (fp.parent / sfile).write_text(strategy_text, encoding="utf-8")
        if fx.get("strategy_file") != sfile:
            fx["strategy_file"] = sfile
            fp.write_text(json.dumps(fx, indent=2), encoding="utf-8")
        return fp.parent / sfile

    def _toggle_src(self) -> None:
        is_file = self.f_src.get() in ("dois", "pmids_file", "query")
        self.f_browse.configure(state="normal" if is_file else "disabled")
        self.f_retmax.configure(state="normal" if self.f_src.get() == "query" else "disabled")

    def _browse_gold(self) -> None:
        path = filedialog.askopenfilename(title="Select gold-source file",
                                          filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            self.f_input.delete(0, "end")
            self.f_input.insert(0, path)

    def _open_results(self) -> None:
        (HERE / "results").mkdir(exist_ok=True)
        try:
            os.startfile(str(HERE / "results"))  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover
            messagebox.showinfo("Results", f"{HERE / 'results'}\n\n({exc})")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ----- actions ------------------------------------------------------
    def _run_eval(self) -> None:
        topic = self.topic.get().strip()
        if not topic:
            messagebox.showwarning("Run", "Select a topic first.")
            return
        if self.mode.get() == "generate":
            cmd = [sys.executable, "-u", str(HERE / "generate.py"), topic,
                   "--effort", self.effort.get(), "--timeout", self.timeout.get().strip() or "1800"]
            if self.model.get().strip():
                cmd += ["--model", self.model.get().strip()]
        else:
            cmd = [sys.executable, "-u", str(HERE / "run_eval.py"), topic,
                   "--output", str(HERE / "results" / f"{topic}.json")]
            strategy_text = self.strategy.get("1.0", "end").strip()
            if strategy_text:
                try:
                    if self.save_baseline.get():
                        sf = self._save_topic_baseline(topic, strategy_text + "\n")
                        self._refresh_topics()
                    else:
                        tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
                        tmp.write(strategy_text + "\n")
                        tmp.close()
                        sf = Path(tmp.name)
                except (SystemExit, OSError) as exc:
                    messagebox.showerror("Baseline", f"Could not save the strategy:\n{exc}")
                    return
                cmd += ["--strategy-file", str(sf)]
                blocks = self.blocks_path.get().strip()
                if blocks:
                    cmd += ["--blocks-file", blocks]
        self._launch(cmd, f"{self.mode.get()} {topic}")

    def _make_fixture(self) -> None:
        fid = self.f_id.get().strip()
        question = self.f_question.get("1.0", "end").strip()
        src = self.f_src.get()
        value = self.f_input.get().strip()
        if not fid or not question or not value:
            messagebox.showwarning("Create fixture", "Topic id, question, and a gold source are all required.")
            return
        cmd = [sys.executable, "-u", str(HERE / "make_fixture.py"),
               "--id", fid, "--suite", self.f_suite.get().strip() or "custom", "--question", question]
        if src == "pmids":
            cmd += ["--gold-pmids", *value.split()]
        elif src == "dois":
            cmd += ["--gold-dois-file", value]
        elif src == "pmids_file":
            cmd += ["--gold-pmids-file", value]
        else:
            cmd += ["--gold-query-file", value, "--gold-retmax", self.f_retmax.get().strip() or "1000"]
        if self.f_force.get():
            cmd += ["--force"]
        self._launch(cmd, f"make_fixture {fid}", on_done=self._refresh_topics)

    # ----- subprocess streaming ----------------------------------------
    def _launch(self, cmd: list[str], label: str, on_done=None) -> None:
        if self._running:
            messagebox.showinfo("Busy", "A job is already running. Wait for it to finish.")
            return
        self._running = True
        self._set_buttons("disabled")
        self.status.configure(text=f"running: {label}")
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
                self._q.put(None)  # sentinel
                if on_done:
                    self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()

    def _drain_log(self) -> None:
        try:
            while True:
                item = self._q.get_nowait()
                if item is None:
                    self._running = False
                    self._set_buttons("normal")
                    self.status.configure(text="ready")
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_buttons(self, state: str) -> None:
        for b in (self.run_btn, self.make_btn):
            b.configure(state=state)


def main() -> int:
    EvalGUI().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
