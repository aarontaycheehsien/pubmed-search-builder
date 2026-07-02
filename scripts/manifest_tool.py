#!/usr/bin/env python3
"""Maintain a canonical ``run_manifest.json`` provenance ledger for a strategy build.

The run manifest is an append-only record of a single PubMed strategy build: every
material command run, every output file produced, the date/time it happened, the PubMed
result count where relevant, and any file that was superseded (for example when an audit
file is re-rendered with a clear suffix instead of being overwritten silently).

Unlike the other bundled scripts, this tool performs no network access. The orchestrating
agent calls it to append entries as the build proceeds, because only the agent sees the
union of {commands run, counts returned, files written, supersessions}: the PubMed/MeSH
CLIs stream JSON to stdout and never see agent-written artifacts such as concept-block
``.txt`` files or ``audit_*.md``.

Schema (manifest_version 1.0)::

    {
      "manifest_version": "1.0",
      "skill": "pubmed-search-builder",
      "skill_version": "1.0.0",
      "topic_slug": "<slug or ''>",
      "created_utc": "2026-05-31T12:00:00Z",
      "updated_utc": "2026-05-31T12:40:00Z",
      "working_dir": "<cwd when first written>",
      "entries": [
        {"seq": 1, "timestamp_utc": "...Z", "kind": "search", "label": "main strategy",
         "block": "", "command": "python scripts/pubmed_tool.py search --query-file q.txt --retmax 0",
         "output_path": null, "count": 1234, "supersedes": null, "note": "topic-only count",
         "open_decision": false}
      ],
      "superseded": [
        {"path": "audit_demo.md", "superseded_by": "audit_demo_2.md",
         "seq": 12, "timestamp_utc": "...Z", "reason": "re-rendered after cleanup"}
      ]
    }

The five recorded facts map directly to each entry: command -> ``command`` (+ ``kind``),
output path -> ``output_path``, date -> ``timestamp_utc``, count -> ``count``, superseded
file -> ``supersedes`` plus the derived ``superseded`` index.

Usage::

    python scripts/manifest_tool.py init --manifest run_manifest.json --topic-slug demo
    python scripts/manifest_tool.py add  --manifest run_manifest.json --kind search \\
        --command "python scripts/pubmed_tool.py search --query-file q.txt --retmax 0" \\
        --count 1234 --note "topic-only count"
    python scripts/manifest_tool.py add  --manifest run_manifest.json --kind artifact \\
        --output audit_demo_2.md --supersedes audit_demo.md --note "re-render"
    python scripts/manifest_tool.py show --manifest run_manifest.json --validate --check-files
    python scripts/manifest_tool.py report --manifest run_manifest.json

Record material commands (count checks, block / full-strategy tests, validate, recall,
variants, audit render) and every artifact write or supersession. Exploratory throwaway
lookups may be summarized or omitted; never fabricate entries for commands that were not
run (mirrors the "summarize tool work performed from available outputs" guardrail in
``references/workflow.md``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = "1.0"
SKILL_NAME = "pubmed-search-builder"
DEFAULT_SKILL_VERSION = "1.0.0"

ENTRY_KINDS = (
    "search",
    "fetch",
    "related",
    "mine",
    "sample",
    "term-rank",
    "recall",
    "batch",
    "variants",
    "validate",
    "qa",
    "mesh",
    "artifact",
    "other",
)

RECORD_CONTENT_KINDS = {"fetch", "mine", "sample"}
RECORD_CONTENT_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:python(?:\.\w+)?\s+)?(?:\"[^\"]*pubmed_tool\.py\"|'[^']*pubmed_tool\.py'|\S*pubmed_tool\.py)\s+(fetch|mine|sample)\b",
    re.IGNORECASE,
)
OPTION_OUTPUT_RE = re.compile(r"(?:^|\s)--output(?:\s|=|$)")
OPTION_SUMMARY_RE = re.compile(r"(?:^|\s)--summary(?:\s|=|$)")

TOP_LEVEL_KEYS = (
    "manifest_version",
    "skill",
    "skill_version",
    "topic_slug",
    "created_utc",
    "updated_utc",
    "working_dir",
    "entries",
    "superseded",
)

REQUIRED_ENTRY_KEYS = ("seq", "timestamp_utc", "kind", "command")

# Live build-state block. Optional and lazily created the first time a `state` command runs,
# so manifests written only with init/add are byte-for-byte unchanged. It externalises the
# "where am I in the build" tracking that would otherwise be reconstructed from conversation
# prose each turn: the current workflow stage, which stages are done, gate decisions, and the
# one unresolved user question (if any).
STAGE_NAMES = (
    "question-intake",
    "seed-intake",
    "limited-seed-evidence",
    "concept-gate",
    "pre-mesh-brainstorm",
    "mesh-exploration",
    "text-word-expansion",
    "block-testing",
    "validation",
    "revision",
    "final-qa",
    "audit-output",
    "peer-review-handoff",
)
GATE_NAMES = ("framework", "seed", "concept", "filter")
UNRESOLVED_GATE_VALUES = {"", "pending"}

# Per-essential-block evidence requirements (Phase 1, opt-in via `state register-blocks` +
# `show --require-coverage`). Each registered block must, before final handoff, either have
# matching manifest evidence (a MeSH sweep and at least one block count test) or a reasoned
# waiver. This turns the workflow's "aggressive sweep + count-test per concept" prose into a
# machine-checked precondition instead of a model self-attestation.
BLOCK_REQUIREMENTS = ("mesh_sweep", "block_count")
MESH_SWEEP_COMMAND_RE = re.compile(r"mesh_tool\.py[\"']?\s+sweep\b", re.IGNORECASE)

# Bramer reciprocal gap analysis is a *conditional* per-block check (run when it aids term discovery;
# waive otherwise). It is tracked separately from the mandatory BLOCK_REQUIREMENTS and gated by its own
# opt-in flag `show --require-gap-analysis`, never folded into `--require-coverage`. Evidence is a
# `term-diff` run, a manual reciprocal gap query, or a reasoned waiver. See
# `references/bramer-reciprocal-gap-analysis.md`.
GAP_REQUIREMENT = "bramer_gap"
GAP_BLOCK_REQUIREMENTS = (GAP_REQUIREMENT,)
WAIVABLE_REQUIREMENTS = BLOCK_REQUIREMENTS + GAP_BLOCK_REQUIREMENTS
BRAMER_GAP_COMMAND_RE = re.compile(r"term-diff\b|bramer[_\-\s]?gap|_not_|\bNOT\s*\(", re.IGNORECASE)

# Low-count plausibility is a generic final-handoff check: when the final topic-only strategy
# count is below the threshold, require a recorded hooks_tool.py low-count-review artifact.
# See references/low-count-plausibility.md.
LOW_COUNT_THRESHOLD = 500
LOW_COUNT_HOOK_COMMAND_RE = re.compile(
    r"(?:^|\s)(?:python(?:\.\w+)?\s+)?(?:\"[^\"]*hooks_tool\.py\"|'[^']*hooks_tool\.py'|\S*hooks_tool\.py)\s+low-count-review\b",
    re.IGNORECASE,
)

# No-seed heuristic recall offer (opt-in via `state resolve-recall-offer` + `show --require-recall-offer`).
# On a no-seed build the optional heuristic recall check must be offered once at the Validation stage;
# this records whether the user was given the choice. `pending` means not yet offered/resolved. See
# `references/no-seed-recall-estimation.md`.
RECALL_OFFER_VALUES = ("declined", "done", "not-applicable")
RECALL_OFFER_RESOLVED = set(RECALL_OFFER_VALUES)

# Canonical seed-gate values. The seed gate stays free-form (like the other gates), but recording it
# as one of these lets the tool auto-detect a no-seed build and remind that the no-seed recall offer
# applies. Casefolded synonyms below are all treated as "no seeds supplied".
SEED_GATE_VALUES = ("provided", "none", "partial")
NO_SEED_GATE_VALUES = {"none", "no", "no-seed", "no-seeds", "no_seeds", "none-supplied", "noseed"}


class ManifestError(Exception):
    """Raised for invalid manifest operations or malformed manifest files."""


def utc_now() -> str:
    """UTC timestamp such as ``2026-05-31T12:40:00Z`` (matches the other bundled tools)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(data: dict[str, object]) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError, ValueError):
        pass
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    json.dump(data, sys.stdout, indent=2, ensure_ascii="utf" not in encoding)
    sys.stdout.write("\n")


def new_manifest(topic_slug: str, skill_version: str) -> dict[str, object]:
    now = utc_now()
    return {
        "manifest_version": MANIFEST_VERSION,
        "skill": SKILL_NAME,
        "skill_version": skill_version or DEFAULT_SKILL_VERSION,
        "topic_slug": topic_slug or "",
        "created_utc": now,
        "updated_utc": now,
        "working_dir": str(Path.cwd()),
        "entries": [],
        "superseded": [],
    }


def load_manifest(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Could not read manifest: {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest is not valid JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"Manifest root must be a JSON object: {path}")
    data.setdefault("entries", [])
    data.setdefault("superseded", [])
    if not isinstance(data["entries"], list) or not isinstance(data["superseded"], list):
        raise ManifestError(f"Manifest 'entries' and 'superseded' must be JSON arrays: {path}")
    return data


def save_manifest(path: Path, data: dict[str, object]) -> None:
    """Write the manifest atomically: a complete temp file then os.replace (atomic on Windows and
    POSIX). A concurrent or interrupted writer can never leave a half-written/torn JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def manifest_lock(path: Path, timeout: float = 10.0, stale: float = 60.0):
    """Serialize manifest read-modify-write across processes and threads with an O_EXCL lockfile.

    Concurrent ``add`` calls queue on the lock, so sequence numbers stay unique and no entry is
    lost. Waits up to ``timeout`` seconds, steals a lock left by a crashed writer after ``stale``
    seconds, and always releases in ``finally``.
    """
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {utc_now()}".encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            # Lock is held; steal it only if the holder looks crashed (stale mtime).
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    os.unlink(lock)
                    continue
            except OSError:
                pass
        except OSError:
            # Windows can raise PermissionError (errno 13) during a concurrent create/unlink
            # of the lockfile; treat it as transient contention and retry.
            pass
        if time.monotonic() > deadline:
            raise ManifestError(f"Could not acquire manifest lock: {lock} (held by another process?)")
        time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def resolve_existing_path(path: Path, if_exists: str) -> Path:
    # Mirrors scripts/audit_markdown.py resolve_existing_path so the suffix behaviour matches.
    if not path.exists() or if_exists == "overwrite":
        return path
    if if_exists == "fail":
        raise ManifestError(f"Manifest already exists: {path}")
    if if_exists != "suffix":
        raise ManifestError(f"Unsupported if_exists policy: {if_exists}")
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise ManifestError(f"Could not find an available suffix for manifest path: {path}")


def parse_count(value: str | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ManifestError(f"--count must be an integer, got {value!r}") from exc


def base_receipt(operation: str, path: Path, data: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "operation": operation,
        "manifest_path": str(path),
        "topic_slug": data.get("topic_slug", ""),
        "entry_count": len(data.get("entries", [])),
        "superseded_count": len(data.get("superseded", [])),
        "updated_utc": data.get("updated_utc", ""),
    }


def output_path_exists(value: str, *, manifest_path: Path | None, data: dict[str, object]) -> bool:
    path = Path(value)
    candidates = [path] if path.is_absolute() else []
    if manifest_path is not None and not path.is_absolute():
        candidates.append(manifest_path.parent / path)
    working_dir = data.get("working_dir")
    if isinstance(working_dir, str) and working_dir and not path.is_absolute():
        candidates.append(Path(working_dir) / path)
    if not candidates:
        candidates = [path]
    return any(candidate.exists() for candidate in candidates)


def validate_manifest(
    data: dict[str, object],
    *,
    check_files: bool = False,
    manifest_path: Path | None = None,
) -> list[str]:
    """Return a list of structural problems; empty list means the manifest is valid."""
    issues: list[str] = []
    for key in TOP_LEVEL_KEYS:
        if key not in data:
            issues.append(f"missing top-level key: {key}")

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return issues + ["'entries' is not a list"]

    seen_seq: set[object] = set()
    output_paths: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            issues.append(f"entry {index} is not a JSON object")
            continue
        for key in REQUIRED_ENTRY_KEYS:
            if key not in entry:
                issues.append(f"entry {index} missing required key: {key}")
        seq = entry.get("seq")
        if seq in seen_seq:
            issues.append(f"duplicate entry seq: {seq}")
        seen_seq.add(seq)
        count = entry.get("count")
        if count is not None and not isinstance(count, int):
            issues.append(f"entry seq={seq} count is not an integer or null: {count!r}")
        kind = entry.get("kind")
        if kind is not None and kind not in ENTRY_KINDS:
            issues.append(f"entry seq={seq} has unknown kind: {kind!r}")
        out = entry.get("output_path")
        if isinstance(out, str) and out:
            output_paths.add(out)
            if check_files and not output_path_exists(out, manifest_path=manifest_path, data=data):
                issues.append(f"entry seq={seq} output_path does not exist: {out}")
        command = str(entry.get("command", ""))
        command_match = RECORD_CONTENT_COMMAND_RE.search(command)
        command_kind = command_match.group(1).lower() if command_match else None
        is_record_content_entry = kind in RECORD_CONTENT_KINDS or command_kind is not None
        if is_record_content_entry and not (isinstance(out, str) and out.strip()):
            issues.append(
                f"entry seq={seq} records record-content command {kind or command_kind!r} without an output_path"
            )
        if is_record_content_entry and OPTION_SUMMARY_RE.search(command):
            issues.append(f"entry seq={seq} records record-content command with unsupported --summary")
        if command_kind is not None and not OPTION_OUTPUT_RE.search(command):
            issues.append(
                f"entry seq={seq} command for pubmed_tool.py {command_kind} is missing required --output"
            )

    superseded = data.get("superseded", [])
    if not isinstance(superseded, list):
        return issues + ["'superseded' is not a list"]
    for index, item in enumerate(superseded):
        if not isinstance(item, dict):
            issues.append(f"superseded {index} is not a JSON object")
            continue
        if not item.get("path"):
            issues.append(f"superseded {index} missing 'path'")
        replacement = item.get("superseded_by")
        # When a replacement is named it must actually have been produced as an output.
        if replacement and replacement not in output_paths:
            issues.append(
                f"superseded entry for {item.get('path')!r} names a replacement "
                f"{replacement!r} that is not recorded as any entry's output_path"
            )
    return issues


def new_build_state() -> dict[str, object]:
    return {
        "current_stage": None,
        "stages_completed": [],
        "gates": {gate: "pending" for gate in GATE_NAMES},
        "pending_user_question": "",
        "open_decisions": [],
        "blocks": {},
        "recall_offer": "pending",
        "updated_utc": utc_now(),
    }


def ensure_build_state(data: dict[str, object]) -> dict[str, object]:
    """Return the manifest's build_state, creating/backfilling it in memory if absent or partial."""
    state = data.get("build_state")
    if not isinstance(state, dict):
        state = new_build_state()
        data["build_state"] = state
        return state
    base = new_build_state()
    for key, value in base.items():
        state.setdefault(key, value)
    if not isinstance(state.get("gates"), dict):
        state["gates"] = base["gates"]
    else:
        for gate in GATE_NAMES:
            state["gates"].setdefault(gate, "pending")
    if not isinstance(state.get("blocks"), dict):
        state["blocks"] = {}
    return state


def gate_resolved(value: object) -> bool:
    return isinstance(value, str) and value not in UNRESOLVED_GATE_VALUES


def build_state_readiness(state: dict[str, object]) -> list[str]:
    """Return reasons the build is not ready for final handoff; empty list means ready."""
    issues: list[str] = []
    question = state.get("pending_user_question") or ""
    if str(question).strip():
        issues.append(f"unresolved user question pending: {question}")
    if not gate_resolved(state.get("gates", {}).get("concept")):
        issues.append("concept gate is not resolved")
    return issues


def recall_offer_readiness(state: dict[str, object]) -> list[str]:
    """Return reasons the no-seed recall offer is unresolved; empty list means resolved.

    Opt-in gate for no-seed builds: the optional heuristic recall check must have been offered and
    its outcome recorded (`done`/`declined`/`not-applicable`). `pending` means the user was never
    given the choice. See `references/no-seed-recall-estimation.md`."""
    value = state.get("recall_offer", "pending")
    if value in RECALL_OFFER_RESOLVED:
        return []
    return [
        "no-seed recall offer unresolved: offer the optional heuristic recall check, then record the "
        "outcome with `manifest_tool.py state resolve-recall-offer <done|declined|not-applicable>`"
    ]


def seed_gate_is_no_seed(state: dict[str, object]) -> bool:
    """True when the seed gate was resolved to a no-seed value (e.g. `none`)."""
    value = str((state.get("gates") or {}).get("seed", "")).strip().lower()
    return value in NO_SEED_GATE_VALUES


def build_state_reminders(state: dict[str, object]) -> list[str]:
    """Non-blocking nudges surfaced in read-only views. Currently: on a no-seed build whose recall
    offer is still pending, remind the agent to offer the heuristic recall check and gate handoff
    with `--require-recall-offer`. Reminders never affect exit codes."""
    reminders: list[str] = []
    if seed_gate_is_no_seed(state) and state.get("recall_offer", "pending") not in RECALL_OFFER_RESOLVED:
        reminders.append(
            "no-seed build: offer the optional heuristic recall check and run "
            "`show --require-recall-offer` at handoff (see references/no-seed-recall-estimation.md)"
        )
    return reminders


def normalize_block_key(value: object) -> str:
    """Casefold + collapse whitespace so block labels match regardless of case/spacing."""
    return " ".join(str(value or "").strip().casefold().split())


def entry_matches_block(entry: dict[str, object], block_key: str) -> bool:
    """An entry is evidence for a block if it carries an explicit matching ``block`` tag, or
    (when untagged) its free-text ``label`` contains the block key. Explicit tags are canonical;
    the label fallback keeps existing labelling habits working."""
    if not block_key:
        return False
    explicit = normalize_block_key(entry.get("block"))
    if explicit:
        return explicit == block_key
    label = normalize_block_key(entry.get("label"))
    return bool(label) and block_key in label


def requirement_satisfied(requirement: str, entries: list[object], block_key: str) -> bool:
    """True when at least one manifest entry supplies the given evidence for the block."""
    for entry in entries:
        if not isinstance(entry, dict) or not entry_matches_block(entry, block_key):
            continue
        kind = str(entry.get("kind", ""))
        command = str(entry.get("command", ""))
        if requirement == "mesh_sweep":
            if kind == "mesh" or MESH_SWEEP_COMMAND_RE.search(command):
                return True
        elif requirement == "block_count":
            if kind in ("search", "batch"):
                return True
        elif requirement == GAP_REQUIREMENT:
            if BRAMER_GAP_COMMAND_RE.search(command):
                return True
    return False


def derive_block_coverage(
    state: dict[str, object], entries: list[object], requirements: tuple[str, ...] = BLOCK_REQUIREMENTS
) -> dict[str, dict[str, dict[str, str]]]:
    """Compute per-block requirement status from registered blocks + recorded entries.

    Status per requirement is ``waived`` (an explicit reason was recorded), ``satisfied``
    (matching evidence exists), or ``pending`` (neither). Derived fresh each call so it never
    drifts from the actual manifest entries. ``requirements`` defaults to the mandatory
    BLOCK_REQUIREMENTS; pass GAP_BLOCK_REQUIREMENTS for the conditional Bramer gap-analysis view.
    """
    blocks = state.get("blocks") if isinstance(state.get("blocks"), dict) else {}
    coverage: dict[str, dict[str, dict[str, str]]] = {}
    for label, spec in blocks.items():
        block_key = normalize_block_key(label)
        spec = spec if isinstance(spec, dict) else {}
        waivers = spec.get("waivers") if isinstance(spec.get("waivers"), dict) else {}
        reqs: dict[str, dict[str, str]] = {}
        for requirement in requirements:
            waiver_reason = str(waivers.get(requirement, "")).strip()
            if waiver_reason:
                reqs[requirement] = {"status": "waived", "reason": waiver_reason}
            elif requirement_satisfied(requirement, entries, block_key):
                reqs[requirement] = {"status": "satisfied"}
            else:
                reqs[requirement] = {"status": "pending"}
        coverage[str(label)] = reqs
    return coverage


def block_coverage_readiness(state: dict[str, object], entries: list[object]) -> list[str]:
    """Return reasons block coverage is incomplete; empty list means every registered block has
    each requirement satisfied or waived. No registered blocks is itself an issue, because an
    explicit coverage check with nothing to check would be meaningless."""
    blocks = state.get("blocks") if isinstance(state.get("blocks"), dict) else {}
    if not blocks:
        return [
            "no essential blocks registered for coverage; run "
            "`manifest_tool.py state register-blocks --blocks-file <blocks.json>`"
        ]
    issues: list[str] = []
    for label, reqs in derive_block_coverage(state, entries).items():
        for requirement, info in reqs.items():
            if info["status"] == "pending":
                issues.append(f"block {label!r} missing evidence: {requirement}")
    return issues


def gap_coverage_readiness(state: dict[str, object], entries: list[object]) -> list[str]:
    """Return reasons the conditional Bramer reciprocal gap analysis is unresolved; empty means every
    registered block has a recorded gap analysis (`term-diff`/manual gap query) or a reasoned waiver.
    Opt-in via `show --require-gap-analysis`; never part of `--require-coverage`."""
    blocks = state.get("blocks") if isinstance(state.get("blocks"), dict) else {}
    if not blocks:
        return [
            "no essential blocks registered for gap analysis; run "
            "`manifest_tool.py state register-blocks --blocks-file <blocks.json>`"
        ]
    issues: list[str] = []
    for label, reqs in derive_block_coverage(state, entries, requirements=GAP_BLOCK_REQUIREMENTS).items():
        if reqs.get(GAP_REQUIREMENT, {}).get("status") == "pending":
            issues.append(
                f"block {label!r} missing Bramer reciprocal gap analysis (run `pubmed_tool.py term-diff` "
                "tagged to the block, or record a reasoned waiver)"
            )
    return issues


def looks_like_final_topic_search(entry: dict[str, object]) -> bool:
    """Heuristic for the final topic-only strategy count entry.

    The manifest is append-only and intentionally flexible, so this cannot rely on one exact label.
    Prefer labels/notes/commands that say final selected strategy/topic-only while excluding concept
    block, pairwise, pilot, and layer counts.
    """
    if entry.get("kind") != "search" or not isinstance(entry.get("count"), int):
        return False
    if str(entry.get("block") or "").strip():
        return False
    label_note = " ".join(str(entry.get(key) or "") for key in ("label", "note")).casefold()
    haystack = " ".join(
        str(entry.get(key) or "")
        for key in ("label", "note", "command", "output_path")
    ).casefold()
    if "final" not in haystack:
        return False
    if not any(token in haystack for token in ("strategy", "topic-only", "topic only", "selected")):
        return False
    excluded = (" block", "pairwise", "pilot", " layer", "mesh", "title/abstract")
    return not any(token in label_note for token in excluded)


def latest_final_topic_count(entries: list[object]) -> int | None:
    candidates = [entry for entry in entries if isinstance(entry, dict) and looks_like_final_topic_search(entry)]
    if not candidates:
        return None
    candidates.sort(key=lambda entry: int(entry.get("seq") or 0))
    count = candidates[-1].get("count")
    return count if isinstance(count, int) else None


def read_manifest_output_json(manifest_path: Path, output_path: object) -> dict[str, object] | None:
    if not output_path:
        return None
    path = Path(str(output_path))
    if not path.is_absolute():
        path = manifest_path.parent / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def low_count_review_entries(entries: list[object]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("kind") != "qa":
            continue
        command = str(entry.get("command") or "")
        label = str(entry.get("label") or "").casefold()
        if LOW_COUNT_HOOK_COMMAND_RE.search(command) or "low-count" in label or "low count" in label:
            found.append(entry)
    found.sort(key=lambda entry: int(entry.get("seq") or 0), reverse=True)
    return found


def low_count_review_readiness(data: dict[str, object], manifest_path: Path, threshold: int = LOW_COUNT_THRESHOLD) -> list[str]:
    entries = data.get("entries", [])
    final_count = latest_final_topic_count(entries)
    if final_count is None:
        return [
            "low-count review: no final topic-only strategy count found; record the final PubMed "
            "search count with a label containing 'final' and 'strategy' or 'topic-only'"
        ]
    if final_count >= threshold:
        return []

    review_entries = low_count_review_entries(entries)
    if not review_entries:
        return [
            f"low-count review: final topic-only count is {final_count} (<{threshold}); run "
            "`hooks_tool.py low-count-review`, record the QA output in the manifest, and rerun this gate"
        ]

    for entry in review_entries:
        payload = read_manifest_output_json(manifest_path, entry.get("output_path"))
        if not payload:
            continue
        if payload.get("hook") != "low_count_plausibility_review":
            continue
        if payload.get("final_count") != final_count:
            continue
        if payload.get("status") == "pass" and payload.get("ok") is True:
            return []

    return [
        f"low-count review: final topic-only count is {final_count} (<{threshold}), but no recorded "
        "low-count-review QA artifact has status='pass' for that final count"
    ]


def load_block_labels(path_str: str) -> list[str]:
    """Extract block labels from a ``--blocks-file`` (the same ``[{label, query}]`` list or
    ``{label: query}`` map used by ``recall``/``audit-scaffold``). Only labels are read, so the
    query values — and the PowerShell ``ConvertTo-Json`` blob pitfall — are irrelevant here."""
    path = Path(path_str)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Could not read blocks file: {path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Blocks file is not valid JSON: {path} ({exc})") from exc
    labels: list[str] = []
    if isinstance(data, dict):
        labels = [str(key) for key in data.keys()]
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("label"):
                labels.append(str(item["label"]))
            elif isinstance(item, str) and item.strip():
                labels.append(item.strip())
    else:
        raise ManifestError("Blocks file must be a list of {label, query} objects or a {label: query} map.")
    seen: set[str] = set()
    ordered: list[str] = []
    for label in labels:
        if label and label not in seen:
            seen.add(label)
            ordered.append(label)
    if not ordered:
        raise ManifestError("Blocks file contained no usable block labels.")
    return ordered


def cmd_state(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.manifest)
    action = args.state_action

    # Read-only actions never lock or write.
    if action in ("show", "check-ready", "coverage"):
        data = load_manifest(path)
        state = ensure_build_state(data)
        receipt = base_receipt(f"state-{action}", path, data)
        receipt["build_state"] = state
        reminders = build_state_reminders(state)
        if reminders:
            receipt["reminders"] = reminders
        if action == "check-ready":
            issues = build_state_readiness(state)
            receipt["ok"] = not issues
            receipt["issues"] = issues
        elif action == "coverage":
            entries = data.get("entries", [])
            receipt["coverage"] = derive_block_coverage(state, entries)
            receipt["gap_coverage"] = derive_block_coverage(state, entries, requirements=GAP_BLOCK_REQUIREMENTS)
            issues = block_coverage_readiness(state, entries)
            receipt["ok"] = not issues
            receipt["issues"] = issues
        return receipt

    # Mutating actions: serialize the whole read-modify-write under the manifest lock.
    with manifest_lock(path):
        data = (
            load_manifest(path)
            if path.exists()
            else new_manifest(getattr(args, "topic_slug", ""), getattr(args, "skill_version", DEFAULT_SKILL_VERSION))
        )
        state = ensure_build_state(data)
        now = utc_now()
        if action == "set-stage":
            if args.stage not in STAGE_NAMES:
                raise ManifestError(f"Unknown stage {args.stage!r}. Choose from: {', '.join(STAGE_NAMES)}.")
            state["current_stage"] = args.stage
        elif action == "complete-stage":
            if args.stage not in STAGE_NAMES:
                raise ManifestError(f"Unknown stage {args.stage!r}. Choose from: {', '.join(STAGE_NAMES)}.")
            if args.stage not in state["stages_completed"]:
                state["stages_completed"].append(args.stage)
        elif action == "resolve-gate":
            if args.gate not in GATE_NAMES:
                raise ManifestError(f"Unknown gate {args.gate!r}. Choose from: {', '.join(GATE_NAMES)}.")
            state["gates"][args.gate] = args.value
        elif action == "set-question":
            state["pending_user_question"] = args.text
        elif action == "clear-question":
            state["pending_user_question"] = ""
        elif action == "resolve-recall-offer":
            if args.value not in RECALL_OFFER_VALUES:
                raise ManifestError(
                    f"Unknown recall-offer value {args.value!r}. Choose from: {', '.join(RECALL_OFFER_VALUES)}."
                )
            state["recall_offer"] = args.value
        elif action == "register-blocks":
            blocks = state["blocks"]
            for label in load_block_labels(args.blocks_file):
                if label not in blocks:
                    blocks[label] = {"waivers": {}}
        elif action == "register-block":
            blocks = state["blocks"]
            if args.label not in blocks:
                blocks[args.label] = {"waivers": {}}
        elif action == "waive-requirement":
            if args.requirement not in WAIVABLE_REQUIREMENTS:
                raise ManifestError(
                    f"Unknown requirement {args.requirement!r}. Choose from: {', '.join(WAIVABLE_REQUIREMENTS)}."
                )
            reason = (args.reason or "").strip()
            if not reason:
                raise ManifestError("waive-requirement requires a non-empty reason (every skipped requirement must be justified).")
            blocks = state["blocks"]
            if args.label not in blocks:
                raise ManifestError(
                    f"Unknown block {args.label!r}; register it first with "
                    "`state register-block`/`register-blocks`."
                )
            block_spec = blocks[args.label]
            if not isinstance(block_spec, dict):
                block_spec = {}
                blocks[args.label] = block_spec
            waivers = block_spec.get("waivers")
            if not isinstance(waivers, dict):
                waivers = {}
                block_spec["waivers"] = waivers
            waivers[args.requirement] = reason
        else:  # pragma: no cover - argparse restricts choices
            raise ManifestError(f"Unknown state action: {action}")
        state["updated_utc"] = now
        data["updated_utc"] = now
        save_manifest(path, data)
        receipt = base_receipt(f"state-{action}", path, data)
        receipt["build_state"] = state
    return receipt


def cmd_init(args: argparse.Namespace) -> dict[str, object]:
    base = Path(args.manifest)
    with manifest_lock(base):
        path = resolve_existing_path(base, args.if_exists)
        data = new_manifest(args.topic_slug, args.skill_version)
        save_manifest(path, data)
        return base_receipt("manifest-init", path, data)


def cmd_add(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.manifest)
    # Validate before locking so a bad --kind/--count fails fast without touching the file.
    if args.kind not in ENTRY_KINDS:
        raise ManifestError(f"Unknown --kind {args.kind!r}. Choose from: {', '.join(ENTRY_KINDS)}.")
    count = parse_count(args.count)
    output_path = args.output or None
    supersedes = args.supersedes or None

    # The lock serializes the whole read-modify-write so concurrent adds get unique seqs.
    with manifest_lock(path):
        data = load_manifest(path) if path.exists() else new_manifest(args.topic_slug, args.skill_version)
        now = utc_now()
        entries = data["entries"]
        seq = len(entries) + 1
        entries.append(
            {
                "seq": seq,
                "timestamp_utc": now,
                "kind": args.kind,
                "label": args.label or "",
                "block": args.block or "",
                "command": args.command,
                "output_path": output_path,
                "count": count,
                "supersedes": supersedes,
                "note": args.note or "",
                "open_decision": bool(args.open_decision),
            }
        )
        if supersedes:
            data["superseded"].append(
                {
                    "path": supersedes,
                    "superseded_by": output_path,
                    "seq": seq,
                    "timestamp_utc": now,
                    "reason": args.note or "",
                }
            )
        data["updated_utc"] = now
        save_manifest(path, data)
        receipt = base_receipt("manifest-add", path, data)
        receipt["added_seq"] = seq
    return receipt


def cmd_show(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.manifest)
    data = load_manifest(path)
    receipt = base_receipt("manifest-show", path, data)
    state_for_reminders = data.get("build_state")
    if isinstance(state_for_reminders, dict):
        reminders = build_state_reminders(state_for_reminders)
        if reminders:
            receipt["reminders"] = reminders
    require_ready = getattr(args, "require_ready", False)
    require_coverage = getattr(args, "require_coverage", False)
    require_recall_offer = getattr(args, "require_recall_offer", False)
    require_gap_analysis = getattr(args, "require_gap_analysis", False)
    require_low_count_review = getattr(args, "require_low_count_review", False)
    if (
        args.validate
        or args.check_files
        or require_ready
        or require_coverage
        or require_recall_offer
        or require_gap_analysis
        or require_low_count_review
    ):
        issues = (
            validate_manifest(data, check_files=args.check_files, manifest_path=path)
            if (args.validate or args.check_files)
            else []
        )
        if require_ready:
            # Binding final-handoff gate: the concept gate must be resolved and no user
            # question may be pending. An absent build_state means the build never tracked
            # state, so readiness cannot be confirmed.
            state = data.get("build_state")
            if not isinstance(state, dict):
                issues.append(
                    "build_state not initialized: track stages and resolve the concept gate with "
                    "`manifest_tool.py state` before final handoff"
                )
            else:
                issues.extend(f"not ready for handoff: {reason}" for reason in build_state_readiness(state))
        if require_coverage:
            # Opt-in per-block evidence gate (Phase 1): every registered essential block must have
            # each requirement satisfied by recorded evidence or carry a reasoned waiver.
            state = data.get("build_state")
            if not isinstance(state, dict):
                issues.append(
                    "build_state not initialized: register essential blocks with "
                    "`manifest_tool.py state register-blocks` before the coverage check"
                )
            else:
                entries = data.get("entries", [])
                issues.extend(f"coverage gap: {reason}" for reason in block_coverage_readiness(state, entries))
        if require_recall_offer:
            # Opt-in no-seed gate: the optional heuristic recall check must have been offered and its
            # outcome recorded. Pass this flag only on no-seed builds at handoff.
            state = data.get("build_state")
            if not isinstance(state, dict):
                issues.append(
                    "build_state not initialized: offer the optional no-seed recall check and record it "
                    "with `manifest_tool.py state resolve-recall-offer` before the no-seed handoff check"
                )
            else:
                issues.extend(f"not ready for handoff: {reason}" for reason in recall_offer_readiness(state))
        if require_gap_analysis:
            # Opt-in conditional gate: every registered block must have a recorded Bramer reciprocal
            # gap analysis or a reasoned waiver. Separate from --require-coverage by design.
            state = data.get("build_state")
            if not isinstance(state, dict):
                issues.append(
                    "build_state not initialized: register essential blocks and run the Bramer gap "
                    "analysis (`term-diff`) or record a waiver before the gap-analysis check"
                )
            else:
                entries = data.get("entries", [])
                issues.extend(f"gap-analysis gap: {reason}" for reason in gap_coverage_readiness(state, entries))
        if require_low_count_review:
            issues.extend(low_count_review_readiness(data, path))
        receipt["ok"] = not issues
        receipt["issues"] = issues
    return receipt


def cmd_report(args: argparse.Namespace) -> dict[str, object]:
    """Read-only build dashboard: groups manifest entries by kind and surfaces the current audit
    path, superseded files, and open decisions. Never reruns searches; it only reads the manifest."""
    path = Path(args.manifest)
    data = load_manifest(path)
    entries = [e for e in data.get("entries", []) if isinstance(e, dict)]

    kind_counts: dict[str, int] = {}
    entries_by_kind: dict[str, list[dict[str, object]]] = {}
    open_decisions: list[dict[str, object]] = []
    audit_path: str | None = None
    for entry in entries:
        kind = str(entry.get("kind", "other"))
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        entries_by_kind.setdefault(kind, []).append(
            {
                "seq": entry.get("seq"),
                "label": entry.get("label", ""),
                "count": entry.get("count"),
                "output_path": entry.get("output_path"),
            }
        )
        if entry.get("open_decision"):
            open_decisions.append(
                {
                    "seq": entry.get("seq"),
                    "kind": kind,
                    "label": entry.get("label", ""),
                    "note": entry.get("note", ""),
                }
            )
        out = entry.get("output_path")
        if kind == "artifact" and isinstance(out, str) and out.endswith(".md"):
            audit_path = out  # the latest .md artifact is the current audit report

    superseded = [
        {"path": item.get("path"), "superseded_by": item.get("superseded_by")}
        for item in data.get("superseded", [])
        if isinstance(item, dict)
    ]

    state = data.get("build_state")
    block_coverage = derive_block_coverage(state, entries) if isinstance(state, dict) else {}
    gap_coverage = derive_block_coverage(state, entries, requirements=GAP_BLOCK_REQUIREMENTS) if isinstance(state, dict) else {}
    final_topic_count = latest_final_topic_count(entries)

    receipt = base_receipt("manifest-report", path, data)
    receipt.update(
        {
            "kind_counts": kind_counts,
            "entries_by_kind": entries_by_kind,
            "audit_path": audit_path,
            "open_decisions": open_decisions,
            "superseded": superseded,
            "block_coverage": block_coverage,
            "gap_coverage": gap_coverage,
            "final_topic_count": final_topic_count,
            "low_count_review_required": final_topic_count is not None and final_topic_count < LOW_COUNT_THRESHOLD,
        }
    )
    reminders = build_state_reminders(state) if isinstance(state, dict) else []
    if reminders:
        receipt["reminders"] = reminders
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Maintain a canonical run_manifest.json provenance ledger (no network access)."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    init_parser = subparsers.add_parser("init", help="Create a new run manifest with top-level metadata.")
    init_parser.add_argument("--manifest", default="run_manifest.json", help="Manifest path (default: %(default)s).")
    init_parser.add_argument("--topic-slug", default="", help="Short topic slug for this build.")
    init_parser.add_argument("--skill-version", default=DEFAULT_SKILL_VERSION, help="Skill version (default: %(default)s).")
    init_parser.add_argument(
        "--if-exists",
        choices=["fail", "suffix", "overwrite"],
        default="fail",
        help="How to handle an existing manifest. Default: fail.",
    )

    add_parser = subparsers.add_parser("add", help="Append one entry (auto-creates the manifest if missing).")
    add_parser.add_argument("--manifest", default="run_manifest.json", help="Manifest path (default: %(default)s).")
    add_parser.add_argument("--kind", required=True, help=f"Entry kind, one of: {', '.join(ENTRY_KINDS)}.")
    add_parser.add_argument("--command", required=True, help="The exact command or agent action this entry records.")
    add_parser.add_argument("--output", help="Output file path produced by this command, if any.")
    add_parser.add_argument("--count", help="PubMed result count, if any (integer).")
    add_parser.add_argument("--supersedes", help="Path of a file that this entry's output replaces.")
    add_parser.add_argument("--note", default="", help="Short free-text note.")
    add_parser.add_argument("--label", default="", help="Short human label for this entry (e.g. 'main strategy', 'robopet block').")
    add_parser.add_argument(
        "--block",
        default="",
        help="Essential-block label this entry supplies evidence for (links sweeps/counts to a registered block for the coverage gate).",
    )
    add_parser.add_argument("--open-decision", action="store_true", help="Flag this entry as an unresolved decision to surface in report.")
    add_parser.add_argument("--topic-slug", default="", help="Topic slug, used only when auto-creating the manifest.")
    add_parser.add_argument(
        "--skill-version", default=DEFAULT_SKILL_VERSION, help="Skill version, used only when auto-creating the manifest."
    )

    show_parser = subparsers.add_parser("show", help="Print a compact manifest receipt and optionally validate it.")
    show_parser.add_argument("--manifest", default="run_manifest.json", help="Manifest path (default: %(default)s).")
    show_parser.add_argument("--validate", action="store_true", help="Validate manifest structure and report issues.")
    show_parser.add_argument("--check-files", action="store_true", help="With validation, flag recorded output_path values that do not exist.")
    show_parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Final-handoff gate: also fail unless build_state shows the concept gate resolved and no user question pending.",
    )
    show_parser.add_argument(
        "--require-coverage",
        action="store_true",
        help="Per-block evidence gate (opt-in): also fail unless every registered essential block has a MeSH sweep and a block count, or a reasoned waiver.",
    )
    show_parser.add_argument(
        "--require-recall-offer",
        action="store_true",
        help="No-seed gate (opt-in): also fail unless the optional heuristic recall check was offered and its outcome recorded (resolve-recall-offer). Pass only on no-seed builds.",
    )
    show_parser.add_argument(
        "--require-gap-analysis",
        action="store_true",
        help="Conditional gap-analysis gate (opt-in): also fail unless every registered block has a recorded Bramer reciprocal gap analysis (term-diff/manual gap query) or a reasoned waiver. Separate from --require-coverage.",
    )
    show_parser.add_argument(
        "--require-low-count-review",
        action="store_true",
        help="Low-count gate (opt-in): if final topic-only count is below 500, also fail unless a passing hooks_tool.py low-count-review QA artifact is recorded.",
    )

    report_parser = subparsers.add_parser("report", help="Read-only build dashboard from the manifest (no reruns).")
    report_parser.add_argument("--manifest", default="run_manifest.json", help="Manifest path (default: %(default)s).")

    state_parser = subparsers.add_parser("state", help="Maintain the live build-state block inside the manifest.")
    state_sub = state_parser.add_subparsers(dest="state_action", required=True)

    def add_state_action(name: str, help_text: str, mutating: bool = True) -> argparse.ArgumentParser:
        sub = state_sub.add_parser(name, help=help_text)
        sub.add_argument("--manifest", default="run_manifest.json", help="Manifest path (default: %(default)s).")
        if mutating:
            sub.add_argument("--topic-slug", default="", help="Topic slug, used only when auto-creating the manifest.")
            sub.add_argument(
                "--skill-version", default=DEFAULT_SKILL_VERSION, help="Skill version, used only when auto-creating the manifest."
            )
        return sub

    set_stage = add_state_action("set-stage", f"Set the current workflow stage, one of: {', '.join(STAGE_NAMES)}.")
    set_stage.add_argument("stage", help="Stage name.")
    complete_stage = add_state_action("complete-stage", "Mark a workflow stage completed.")
    complete_stage.add_argument("stage", help="Stage name.")
    resolve_gate = add_state_action("resolve-gate", f"Record a gate decision, gate one of: {', '.join(GATE_NAMES)}.")
    resolve_gate.add_argument("gate", help="Gate name.")
    resolve_gate.add_argument(
        "value",
        help=f"Resolution value, e.g. a framework or 'resolved'. For the seed gate prefer {', '.join(SEED_GATE_VALUES)} "
        "so a no-seed build is auto-detected for the recall-offer reminder.",
    )
    set_question = add_state_action("set-question", "Record the one unresolved user/protocol question.")
    set_question.add_argument("text", help="The exact pending question.")
    add_state_action("clear-question", "Clear the pending user/protocol question.")

    resolve_recall_offer = add_state_action(
        "resolve-recall-offer",
        f"Record the no-seed heuristic recall-offer outcome, one of: {', '.join(RECALL_OFFER_VALUES)}.",
    )
    resolve_recall_offer.add_argument("value", help=f"Outcome, one of: {', '.join(RECALL_OFFER_VALUES)}.")

    register_blocks = add_state_action(
        "register-blocks", "Register essential blocks for the coverage gate from a --blocks-file."
    )
    register_blocks.add_argument(
        "--blocks-file",
        required=True,
        help="JSON list of {label, query} blocks (or a {label: query} map); only labels are read.",
    )
    register_block = add_state_action("register-block", "Register one essential block by label.")
    register_block.add_argument("label", help="Block label.")
    waive = add_state_action(
        "waive-requirement", "Waive one requirement for a registered block, with a mandatory reason."
    )
    waive.add_argument("label", help="Registered block label.")
    waive.add_argument("requirement", help=f"Requirement to waive, one of: {', '.join(WAIVABLE_REQUIREMENTS)}.")
    waive.add_argument("reason", help="Why this requirement does not apply (required, non-empty).")

    add_state_action("show", "Print the current build-state block (read-only).", mutating=False)
    add_state_action(
        "check-ready", "Report whether the build is ready for final handoff (read-only; exit 1 if not).", mutating=False
    )
    add_state_action(
        "coverage",
        "Report per-block evidence coverage (read-only; exit 1 if any registered block has a pending requirement).",
        mutating=False,
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {"init": cmd_init, "add": cmd_add, "show": cmd_show, "report": cmd_report, "state": cmd_state}
    try:
        receipt = handlers[args.subcommand](args)
    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_json(receipt)
    return 0 if receipt.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
