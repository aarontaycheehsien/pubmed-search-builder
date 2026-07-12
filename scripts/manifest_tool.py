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

Schema (manifest_version 1.1)::

    {
      "manifest_version": "1.1",
      "skill": "pubmed-search-builder",
      "skill_version": "2.0.0",
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
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = "1.1"
SKILL_NAME = "pubmed-search-builder"
DEFAULT_SKILL_VERSION = "2.0.0"

ENTRY_KINDS = (
    "scope",
    "candidate-screen",
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
    "critic",
    "revision",
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
CANONICAL_STAGE_NAMES = (
    "intake",
    "scope-lock",
    "candidate-discovery",
    "candidate-screening",
    "objective-evidence",
    "block-testing",
    "validation",
    "critic-review",
    "revision",
    "final-qa",
    "audit-output",
    "peer-review-handoff",
)
LEGACY_STAGE_NAMES = (
    "question-intake",
    "seed-intake",
    "limited-seed-evidence",
    "concept-gate",
    "pre-mesh-brainstorm",
    "mesh-exploration",
    "text-word-expansion",
)
STAGE_NAMES = CANONICAL_STAGE_NAMES + LEGACY_STAGE_NAMES
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_artifact_path(value: str, manifest_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    manifest_relative = manifest_path.parent / path
    if manifest_relative.exists():
        return manifest_relative
    return Path.cwd() / path


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
            recorded_hash = entry.get("output_sha256")
            if check_files and recorded_hash:
                resolved = resolve_artifact_path(out, manifest_path or Path("run_manifest.json"))
                if not resolved.is_file() or sha256_file(resolved) != recorded_hash:
                    issues.append(f"entry seq={seq} output artifact hash no longer matches: {out}")
        input_hashes = entry.get("input_sha256")
        if check_files and isinstance(input_hashes, dict):
            for input_path, recorded_hash in input_hashes.items():
                resolved = resolve_artifact_path(str(input_path), manifest_path or Path("run_manifest.json"))
                if not resolved.is_file():
                    issues.append(f"entry seq={seq} input artifact does not exist: {input_path}")
                elif sha256_file(resolved) != recorded_hash:
                    issues.append(f"entry seq={seq} input artifact hash no longer matches: {input_path}")
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
        "scope": {
            "version": 0,
            "status": "pending",
            "artifact": "",
            "lock_mode": "",
            "protocol_file": "",
            "protocol_sha256": "",
            "protocol_id": "",
            "dsl_version": "",
            "compile_receipt": "",
            "generated_paths": {},
            "generated_sha256": {},
            "reopened_reason": "",
            "history": [],
        },
        "candidate_screening": {
            "status": "pending",
            "artifact": "",
            "validation_artifact": "",
            "summary": {},
            "reason": "",
        },
        "critic_rounds": [],
        "revision_cycles": [],
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
    if not isinstance(state.get("scope"), dict):
        state["scope"] = base["scope"]
    else:
        for key, value in base["scope"].items():
            state["scope"].setdefault(key, value)
    if not isinstance(state.get("candidate_screening"), dict):
        state["candidate_screening"] = base["candidate_screening"]
    else:
        for key, value in base["candidate_screening"].items():
            state["candidate_screening"].setdefault(key, value)
    if not isinstance(state.get("critic_rounds"), list):
        state["critic_rounds"] = []
    if not isinstance(state.get("revision_cycles"), list):
        state["revision_cycles"] = []
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


def load_json_object(path_value: str, label: str) -> dict[str, object]:
    path = Path(path_value)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object: {path}")
    return value


def validate_scope_artifact(path_value: str) -> dict[str, object]:
    data = load_json_object(path_value, "retrieval-scope artifact")
    version = data.get("scope_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ManifestError("retrieval-scope artifact scope_version must be a positive integer")
    for field in ("review_question", "framework", "essential_blocks"):
        value = data.get(field)
        if value in (None, "", [], {}):
            raise ManifestError(f"retrieval-scope artifact requires non-empty {field}")
    if not isinstance(data.get("essential_blocks"), list):
        raise ManifestError("retrieval-scope artifact essential_blocks must be a list")
    ambiguities = data.get("unresolved_ambiguities", [])
    if not isinstance(ambiguities, list):
        raise ManifestError("retrieval-scope artifact unresolved_ambiguities must be a list")
    if ambiguities:
        raise ManifestError("retrieval scope cannot be locked while unresolved_ambiguities is non-empty")
    return {
        "version": version,
        "review_question": str(data.get("review_question")),
        "framework": data.get("framework"),
        "essential_block_count": len(data.get("essential_blocks", [])),
    }


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_sha256(data: object) -> str:
    """Hash JSON semantically, using the protocol compiler's canonical representation."""
    encoded = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _protocol_json(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"Could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a JSON object: {path}")
    return value


def _protocol_text(data: dict[str, object], key: str, label: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ManifestError(f"protocol requires non-empty {label}")
    return value


def _protocol_derived_state(protocol: dict[str, object]) -> dict[str, object]:
    """Extract the manifest-owned state from a protocol already validated by protocol_tool."""
    scope_version = protocol.get("scope_version")
    if not isinstance(scope_version, int) or isinstance(scope_version, bool) or scope_version < 1:
        raise ManifestError("protocol scope_version must be a positive integer")
    protocol_id = _protocol_text(protocol, "protocol_id", "protocol_id")
    dsl_version = protocol.get("dsl_version")
    if dsl_version != 1:
        raise ManifestError("protocol dsl_version must be integer 1")

    review = protocol.get("review")
    if not isinstance(review, dict):
        raise ManifestError("protocol review must be an object")
    framework = review.get("framework")
    if not isinstance(framework, dict):
        raise ManifestError("protocol review.framework must be an object")
    framework_name = str(framework.get("name") or "").strip()
    if not framework_name:
        raise ManifestError("protocol review.framework.name is required")

    searchable_scope = protocol.get("searchable_scope")
    if not isinstance(searchable_scope, dict):
        raise ManifestError("protocol searchable_scope must be an object")
    concepts = searchable_scope.get("concepts")
    if not isinstance(concepts, list):
        raise ManifestError("protocol searchable_scope.concepts must be a list")
    essential_blocks: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, concept in enumerate(concepts, start=1):
        if not isinstance(concept, dict) or concept.get("role") != "essential":
            continue
        concept_id = str(concept.get("id") or "").strip()
        label = str(concept.get("label") or "").strip()
        if not concept_id or not label:
            raise ManifestError(f"essential protocol concept {index} requires non-empty id and label")
        if concept_id in seen_ids:
            raise ManifestError(f"duplicate essential protocol concept id: {concept_id}")
        seen_ids.add(concept_id)
        essential_blocks.append({"id": concept_id, "label": label})
    if not essential_blocks:
        raise ManifestError("protocol must define at least one essential searchable-scope concept")

    seeds = protocol.get("seeds")
    if not isinstance(seeds, dict) or not isinstance(seeds.get("records"), list):
        raise ManifestError("protocol seeds.records must be a list")
    seed_gate = "provided" if seeds["records"] else "none"

    filters = protocol.get("filters_and_limits")
    if not isinstance(filters, dict) or not isinstance(filters.get("decisions"), list):
        raise ManifestError("protocol filters_and_limits.decisions must be a list")
    selected_filters = [
        item
        for item in filters["decisions"]
        if isinstance(item, dict) and item.get("status") == "selected"
    ]
    filter_gate = "selected" if selected_filters else "none"
    return {
        "scope_version": scope_version,
        "protocol_id": protocol_id,
        "dsl_version": dsl_version,
        "framework": framework_name,
        "seed_gate": seed_gate,
        "filter_gate": filter_gate,
        "essential_blocks": essential_blocks,
    }


def validate_protocol_compile(
    protocol_file: str,
    compile_receipt: str,
    manifest_path: Path,
) -> dict[str, object]:
    """Verify a protocol compile receipt and every generated artifact without importing its tool."""
    protocol_path = resolve_artifact_path(protocol_file, manifest_path)
    receipt_path = resolve_artifact_path(compile_receipt, manifest_path)
    protocol = _protocol_json(protocol_path, "protocol")
    derived = _protocol_derived_state(protocol)
    protocol_hash = canonical_json_sha256(protocol)

    receipt = _protocol_json(receipt_path, "protocol compile receipt")
    if receipt.get("operation") != "protocol-compile" or receipt.get("ok") is not True:
        raise ManifestError("protocol compile receipt must have operation='protocol-compile' and ok=true")
    if receipt.get("protocol_sha256") != protocol_hash:
        raise ManifestError("protocol compile receipt protocol_sha256 does not match the canonical protocol JSON")
    for field in ("protocol_id", "scope_version", "dsl_version"):
        expected = derived[field]
        if receipt.get(field) != expected:
            raise ManifestError(f"protocol compile receipt {field} does not match the protocol")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ManifestError("protocol compile receipt artifacts must be a non-empty list")
    generated_paths: dict[str, str] = {}
    generated_hashes: dict[str, str] = {}
    registry_essential_blocks: list[dict[str, str]] | None = None
    for index, artifact in enumerate(artifacts, start=1):
        if not isinstance(artifact, dict):
            raise ManifestError(f"protocol compile artifact {index} must be an object")
        artifact_type = str(artifact.get("artifact_type") or "").strip()
        artifact_value = str(artifact.get("path") or "").strip()
        artifact_hash = str(artifact.get("sha256") or "").strip().lower()
        if not artifact_type or not artifact_value or not SHA256_RE.fullmatch(artifact_hash):
            raise ManifestError(
                f"protocol compile artifact {index} requires artifact_type, path, and a lowercase SHA-256"
            )
        if artifact_type in generated_paths:
            raise ManifestError(f"protocol compile receipt repeats artifact_type: {artifact_type}")
        artifact_path = Path(artifact_value)
        if not artifact_path.is_absolute():
            artifact_path = (receipt_path.parent / artifact_path).resolve()
        if not artifact_path.is_file():
            raise ManifestError(f"generated protocol artifact does not exist: {artifact_value}")
        if sha256_file(artifact_path) != artifact_hash:
            raise ManifestError(f"generated protocol artifact hash mismatch: {artifact_value}")
        envelope = _protocol_json(artifact_path, f"generated {artifact_type} artifact")
        if envelope.get("artifact_type") != artifact_type or envelope.get("artifact_version") != 1:
            raise ManifestError(f"generated protocol artifact envelope is invalid: {artifact_value}")
        for field in ("protocol_id", "scope_version", "dsl_version"):
            if envelope.get(field) != derived[field]:
                raise ManifestError(f"generated protocol artifact {field} mismatch: {artifact_value}")
        generated_from = envelope.get("generated_from")
        if not isinstance(generated_from, dict) or generated_from.get("sha256") != protocol_hash:
            raise ManifestError(f"generated protocol artifact is not bound to the current protocol: {artifact_value}")
        if generated_from.get("path") != protocol_path.name:
            raise ManifestError(f"generated protocol artifact has stale generated_from.path: {artifact_value}")
        if artifact_type == "block-registry":
            raw_blocks = envelope.get("blocks")
            if not isinstance(raw_blocks, list):
                raise ManifestError("generated block-registry blocks must be a list")
            registry_essential_blocks = []
            seen_block_ids: set[str] = set()
            for block_index, block in enumerate(raw_blocks, start=1):
                if not isinstance(block, dict) or block.get("role") != "essential":
                    continue
                block_id = str(block.get("block_id") or "").strip()
                concept_id = str(block.get("concept_id") or "").strip()
                label = str(block.get("label") or "").strip()
                if not block_id or block_id != concept_id or not label:
                    raise ManifestError(
                        f"generated block-registry essential block {block_index} has invalid IDs or label"
                    )
                if block_id in seen_block_ids:
                    raise ManifestError(f"generated block-registry repeats essential block ID: {block_id}")
                seen_block_ids.add(block_id)
                registry_essential_blocks.append({"id": block_id, "label": label})
        generated_paths[artifact_type] = artifact_value
        generated_hashes[artifact_type] = artifact_hash

    required_types = {
        "concept-ledger",
        "candidate-ledger-template",
        "block-registry",
        "critic-packet",
        "audit-outline",
    }
    if set(generated_paths) != required_types:
        raise ManifestError("protocol compile receipt artifact types are incomplete or unexpected")
    protocol_blocks = {
        str(item["id"]): str(item["label"])
        for item in derived["essential_blocks"]
        if isinstance(item, dict)
    }
    registry_blocks = {
        str(item["id"]): str(item["label"])
        for item in (registry_essential_blocks or [])
        if isinstance(item, dict)
    }
    if registry_blocks != protocol_blocks:
        raise ManifestError("generated block-registry essential IDs/labels do not match the protocol")

    return {
        **derived,
        "essential_blocks": registry_essential_blocks or [],
        "protocol_file": protocol_file,
        "protocol_sha256": protocol_hash,
        "compile_receipt": compile_receipt,
        "generated_paths": generated_paths,
        "generated_sha256": generated_hashes,
    }


def reset_scope_dependent_state(state: dict[str, object]) -> None:
    """Invalidate state that cannot survive a protocol scope-version change."""
    fresh = new_build_state()
    state["candidate_screening"] = fresh["candidate_screening"]
    state["blocks"] = {}
    state["critic_rounds"] = []
    state["revision_cycles"] = []
    state["recall_offer"] = "pending"
    state["open_decisions"] = []
    completed = state.get("stages_completed")
    if isinstance(completed, list):
        state["stages_completed"] = [stage for stage in completed if stage == "intake"]


def protocol_scope_readiness(
    scope: dict[str, object],
    state: dict[str, object],
    manifest_path: Path,
) -> list[str]:
    """Revalidate a DSL-locked scope against its current protocol and compiled artifacts."""
    if scope.get("lock_mode") != "protocol":
        return []
    protocol_file = str(scope.get("protocol_file") or scope.get("artifact") or "")
    compile_receipt = str(scope.get("compile_receipt") or "")
    if not protocol_file or not compile_receipt:
        return ["DSL-locked scope lacks its protocol file or compile receipt"]
    try:
        current = validate_protocol_compile(protocol_file, compile_receipt, manifest_path)
    except ManifestError as exc:
        return [f"current protocol verification failed: {exc}"]

    issues: list[str] = []
    comparisons = (
        ("version", "scope_version"),
        ("protocol_id", "protocol_id"),
        ("dsl_version", "dsl_version"),
        ("protocol_sha256", "protocol_sha256"),
        ("generated_paths", "generated_paths"),
        ("generated_sha256", "generated_sha256"),
    )
    for state_key, current_key in comparisons:
        if scope.get(state_key) != current.get(current_key):
            issues.append(f"DSL-locked scope {state_key} is stale relative to the current protocol compile")
    if str(scope.get("artifact") or "") != protocol_file:
        issues.append("DSL-locked scope artifact is not the current protocol file")

    expected = {
        str(item["id"]): str(item["label"])
        for item in current.get("essential_blocks", [])
        if isinstance(item, dict) and item.get("id")
    }
    blocks = state.get("blocks") if isinstance(state.get("blocks"), dict) else {}
    if set(blocks) != set(expected):
        issues.append("registered essential blocks do not match the current protocol")
    for block_id, label in expected.items():
        spec = blocks.get(block_id)
        if not isinstance(spec, dict):
            continue
        if spec.get("scope_version") != current.get("scope_version"):
            issues.append(f"protocol block {block_id!r} has a stale scope version")
        if spec.get("protocol_sha256") != current.get("protocol_sha256"):
            issues.append(f"protocol block {block_id!r} has a stale protocol hash")
        if spec.get("display_label") != label:
            issues.append(f"protocol block {block_id!r} has a stale display label")
    return issues


def protocol_binding_issues(
    payload: object,
    scope: dict[str, object],
    label: str,
) -> list[str]:
    """Require a downstream JSON payload/summary to identify the current locked protocol."""
    if scope.get("lock_mode") != "protocol":
        return []
    if not isinstance(payload, dict):
        return [f"{label} lacks a protocol-bound JSON object"]
    generated_from = payload.get("generated_from")
    generated_hash = generated_from.get("sha256") if isinstance(generated_from, dict) else None
    actual_hash = payload.get("protocol_sha256") or generated_hash
    issues: list[str] = []
    if payload.get("protocol_id") != scope.get("protocol_id"):
        issues.append(f"{label} protocol_id does not match the current protocol")
    if payload.get("scope_version") != scope.get("version"):
        issues.append(f"{label} scope_version does not match the current protocol")
    if actual_hash != scope.get("protocol_sha256"):
        issues.append(f"{label} protocol_sha256 does not match the current protocol")
    return issues


def validated_receipt(path_value: str, expected_operation: str) -> dict[str, object]:
    data = load_json_object(path_value, "validation receipt")
    if data.get("operation") != expected_operation:
        raise ManifestError(
            f"validation receipt operation must be {expected_operation!r}, got {data.get('operation')!r}"
        )
    if data.get("ok") is not True:
        raise ManifestError(f"validation receipt did not pass: {path_value}")
    summary = data.get("summary")
    if not isinstance(summary, dict):
        raise ManifestError(f"validation receipt lacks a summary object: {path_value}")
    for key in ("artifact_sha256", "evidence_bundle_sha256"):
        if data.get(key):
            summary[key] = data[key]
    return summary


def validate_revision_artifact(path_value: str) -> dict[str, object]:
    revision_path = Path(path_value)
    data = load_json_object(path_value, "revision-cycle artifact")
    required = (
        "revision_round",
        "critic_round",
        "scope_version",
        "trigger_finding",
        "classification",
        "change",
        "evidence_files",
        "required_reprobe",
        "strategy_file",
        "disposition",
        "no_harm_file",
    )
    for field in required:
        if data.get(field) in (None, "", [], {}):
            raise ManifestError(f"revision-cycle artifact requires non-empty {field}")
    for field in ("revision_round", "critic_round", "scope_version"):
        value = data.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ManifestError(f"revision-cycle artifact {field} must be a positive integer")
    if data.get("classification") not in {"lexical", "structural", "scope", "filter", "syntax", "reporting"}:
        raise ManifestError("revision-cycle artifact classification is invalid")
    guard_path = Path(str(data.get("no_harm_file") or ""))
    if not guard_path.is_absolute():
        guard_path = revision_path.resolve().parent / guard_path
    guard = load_json_object(str(guard_path), "revision no-harm artifact")
    if guard.get("operation") != "revision-no-harm" or guard.get("ok") is not True:
        raise ManifestError("revision no-harm artifact must have operation='revision-no-harm' and ok=true")
    if guard.get("revision_kind") != "critic":
        raise ManifestError("critic revision cycles require revision_kind='critic' in the no-harm artifact")
    trigger = data.get("trigger_finding")
    trigger_id = str(trigger.get("finding_id") or trigger.get("id") or "") if isinstance(trigger, dict) else str(trigger)
    if str(guard.get("named_defect_id") or "") != trigger_id:
        raise ManifestError("revision no-harm named_defect_id does not match trigger_finding")
    disposition = str(data.get("disposition") or "").strip().casefold().replace("_", "-")
    expected_guard = {
        "accepted": "adopt",
        "adopted": "adopt",
        "reverted": "revert-to-baseline",
        "revert-to-baseline": "revert-to-baseline",
        "experimental": "experimental-only",
        "experimental-only": "experimental-only",
    }.get(disposition)
    if expected_guard is None or guard.get("disposition") != expected_guard:
        raise ManifestError("revision disposition does not match the no-harm guard disposition")
    if expected_guard == "adopt" and guard.get("no_harm_passed") is not True:
        raise ManifestError("an adopted revision must pass every no-harm check")
    checks = guard.get("checks") if isinstance(guard.get("checks"), list) else []
    check_names = {item.get("name") for item in checks if isinstance(item, dict)}
    required_checks = {
        "named-defect-fixed", "heldout-preserved", "required-blocks-justified",
        "syntax-translation-stable", "scope-unchanged-or-explicit", "workload-recorded",
        "no-narrowing-under-low-signal",
    }
    if check_names != required_checks:
        raise ManifestError("revision no-harm artifact does not contain the required no-harm checks")
    authoritative = Path(str(guard.get("authoritative_strategy_file") or ""))
    if not authoritative.is_absolute():
        authoritative = guard_path.parent / authoritative
    recorded_strategy = Path(str(data.get("strategy_file") or ""))
    if not recorded_strategy.is_absolute():
        recorded_strategy = revision_path.resolve().parent / recorded_strategy
    if authoritative.resolve() != recorded_strategy.resolve():
        raise ManifestError("revision strategy_file is not the no-harm guard's authoritative strategy")
    return {
        "revision_round": data["revision_round"],
        "critic_round": data["critic_round"],
        "scope_version": data["scope_version"],
        "classification": data["classification"],
        "trigger_finding": data["trigger_finding"],
        "change": data["change"],
        "strategy_file": data["strategy_file"],
        "disposition": data["disposition"],
        "no_harm_file": str(guard_path),
        "no_harm_sha256": sha256_file(guard_path),
        "no_harm_passed": guard.get("no_harm_passed"),
        "no_harm_disposition": guard.get("disposition"),
        "failed_no_harm_checks": guard.get("failed_checks", []),
        "workload_effect": guard.get("workload_effect"),
        "protocol_id": guard.get("protocol_id"),
        "protocol_sha256": guard.get("protocol_sha256"),
    }


def append_internal_entry(
    data: dict[str, object],
    *,
    now: str,
    kind: str,
    label: str,
    command: str,
    output_path: str,
    note: str = "",
) -> int:
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ManifestError("manifest entries is not a list")
    seq = len(entries) + 1
    entries.append(
        {
            "seq": seq,
            "timestamp_utc": now,
            "kind": kind,
            "label": label,
            "block": "",
            "command": command,
            "output_path": output_path,
            "count": None,
            "supersedes": None,
            "note": note,
            "open_decision": False,
        }
    )
    return seq


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


def complete_loop_readiness(data: dict[str, object], manifest_path: Path) -> list[str]:
    """Return all reasons a completed conceptual-objective-critic loop cannot be handed off."""
    issues: list[str] = []
    state = data.get("build_state")
    if not isinstance(state, dict):
        return ["build_state not initialized; the complete-loop gate requires tracked state"]
    state = ensure_build_state(data)
    issues.extend(build_state_readiness(state))

    gates = state.get("gates") if isinstance(state.get("gates"), dict) else {}
    for gate in GATE_NAMES:
        if not gate_resolved(gates.get(gate)):
            issues.append(f"{gate} gate is not resolved")

    scope = state.get("scope") if isinstance(state.get("scope"), dict) else {}
    scope_version = scope.get("version")
    if scope.get("status") != "locked" or not isinstance(scope_version, int) or scope_version < 1:
        issues.append("retrieval scope is not locked at a positive version")
    scope_artifact = str(scope.get("artifact") or "")
    if not scope_artifact:
        issues.append("retrieval-scope artifact is not recorded")
    elif not output_path_exists(scope_artifact, manifest_path=manifest_path, data=data):
        issues.append(f"retrieval-scope artifact does not exist: {scope_artifact}")
    issues.extend(protocol_scope_readiness(scope, state, manifest_path))

    screening = state.get("candidate_screening") if isinstance(state.get("candidate_screening"), dict) else {}
    screening_status = screening.get("status")
    if screening_status not in {"complete", "not-applicable"}:
        issues.append("candidate screening is not complete or explicitly not applicable")
    if screening_status == "complete":
        for key, label in (("artifact", "candidate ledger"), ("validation_artifact", "candidate-ledger validation")):
            path_value = str(screening.get(key) or "")
            if not path_value:
                issues.append(f"{label} artifact is not recorded")
            elif not output_path_exists(path_value, manifest_path=manifest_path, data=data):
                issues.append(f"{label} artifact does not exist: {path_value}")
        if scope.get("lock_mode") == "protocol":
            summary = screening.get("summary") if isinstance(screening.get("summary"), dict) else {}
            issues.extend(protocol_binding_issues(summary, scope, "candidate-screening summary"))
            ledger_payload = read_manifest_output_json(manifest_path, screening.get("artifact"))
            issues.extend(protocol_binding_issues(ledger_payload, scope, "candidate ledger"))
            validation_payload = read_manifest_output_json(manifest_path, screening.get("validation_artifact"))
            validation_summary = (
                validation_payload.get("summary")
                if isinstance(validation_payload, dict) and isinstance(validation_payload.get("summary"), dict)
                else {}
            )
            issues.extend(protocol_binding_issues(validation_summary, scope, "candidate-ledger validation summary"))
    if screening_status == "not-applicable" and not str(screening.get("reason") or "").strip():
        issues.append("candidate-screening not-applicable status lacks a reason")

    entries = data.get("entries", [])
    issues.extend(block_coverage_readiness(state, entries))
    issues.extend(gap_coverage_readiness(state, entries))
    blocks = state.get("blocks") if isinstance(state.get("blocks"), dict) else {}
    for label, spec in blocks.items():
        if not isinstance(spec, dict) or spec.get("scope_version") != scope_version:
            issues.append(f"block {label!r} is not registered against the current scope version")

    def operation_entries(operation: str) -> list[dict[str, object]]:
        found = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            output_value = str(entry.get("output_path") or "")
            if not output_value:
                continue
            payload = read_manifest_output_json(manifest_path, output_value)
            if isinstance(payload, dict) and payload.get("operation") == operation:
                found.append(entry)
        return sorted(found, key=lambda item: int(item.get("seq") or 0))

    if scope.get("lock_mode") == "protocol":
        for operation, label in (
            ("two-strand", "latest two-strand artifact"),
            ("screening-burden", "latest screening-burden artifact"),
        ):
            bound_entries = operation_entries(operation)
            if bound_entries:
                payload = read_manifest_output_json(
                    manifest_path,
                    str(bound_entries[-1].get("output_path") or ""),
                )
                issues.extend(protocol_binding_issues(payload, scope, label))

    analysis_sequences: list[int] = []
    if len(blocks) >= 2:
        ablation_entries = operation_entries("concept-ablation")
        if not ablation_entries:
            issues.append("no concept-ablation artifact covers the proposed AND blocks")
        else:
            ablation_entry = ablation_entries[-1]
            analysis_sequences.append(int(ablation_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(ablation_entry.get("output_path") or "")) or {}
            if payload.get("ok") is not True:
                issues.append("latest concept-ablation artifact did not complete successfully")
            if payload.get("scope_version") != scope_version:
                issues.append("latest concept-ablation artifact does not match the current retrieval-scope version")
            analyses = payload.get("analyses") if isinstance(payload.get("analyses"), list) else []
            analysed_labels = {
                normalize_block_key(item.get("label"))
                for item in analyses
                if isinstance(item, dict)
            }
            missing_labels = sorted(
                str(label) for label in blocks if normalize_block_key(label) not in analysed_labels
            )
            if missing_labels:
                issues.append("concept-ablation does not cover registered blocks: " + ", ".join(missing_labels))
            allowed = {
                "keep-as-required",
                "move-inside-another-or-block",
                "handle-at-screening",
                "focused-variant-only",
            }
            for item in analyses:
                if not isinstance(item, dict):
                    continue
                recommendation = item.get("recommendation") if isinstance(item.get("recommendation"), dict) else {}
                if recommendation.get("disposition") not in allowed:
                    issues.append(f"concept-ablation block {item.get('label')!r} lacks a valid recommendation")
                if not isinstance(item.get("development"), dict) or not isinstance(item.get("holdout"), dict):
                    issues.append(f"concept-ablation block {item.get('label')!r} lacks development/holdout evidence")
                if not isinstance(item.get("differential_sample"), dict) or not isinstance(item.get("workload_change"), dict):
                    issues.append(f"concept-ablation block {item.get('label')!r} lacks differential/workload evidence")

    if screening_status == "complete" and blocks:
        fragility_entries = operation_entries("fragility-score")
        if not fragility_entries:
            issues.append("no empirical fragility-score artifact covers the registered blocks")
        else:
            fragility_entry = fragility_entries[-1]
            analysis_sequences.append(int(fragility_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(fragility_entry.get("output_path") or "")) or {}
            if payload.get("ok") is not True or payload.get("scope_version") != scope_version:
                issues.append("latest fragility-score artifact failed or does not match the current scope version")
            concepts = payload.get("concepts") if isinstance(payload.get("concepts"), list) else []
            scored_labels = {
                normalize_block_key(item.get("label"))
                for item in concepts
                if isinstance(item, dict)
            }
            missing_labels = sorted(str(label) for label in blocks if normalize_block_key(label) not in scored_labels)
            if missing_labels:
                issues.append("fragility-score does not cover registered blocks: " + ", ".join(missing_labels))
            required_metrics = {
                "explicit_title_abstract_naming_percent",
                "mesh_coverage_percent",
                "exact_label_coverage_percent",
                "additional_descriptive_coverage_percent",
                "noise_added_by_safety_layer",
                "heldout_misses_attributable_to_block",
                "terminology_variation_across_eras",
            }
            for item in concepts:
                if not isinstance(item, dict):
                    continue
                metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                missing_metrics = sorted(required_metrics - set(metrics))
                if missing_metrics:
                    issues.append(f"fragility-score concept {item.get('label')!r} lacks metrics: {', '.join(missing_metrics)}")
                if item.get("final_recommendation") not in {"stable", "fragile", "very-fragile"}:
                    issues.append(f"fragility-score concept {item.get('label')!r} lacks a valid recommendation")
                if item.get("empirical_recommendation") not in {"stable", "fragile", "very-fragile"}:
                    issues.append(f"fragility-score concept {item.get('label')!r} lacks an empirical recommendation")
                dimensions = item.get("dimension_scores") if isinstance(item.get("dimension_scores"), dict) else {}
                required_dimensions = {
                    "terminology_stability",
                    "controlled_vocabulary_indexing",
                    "author_reporting_explicitness",
                    "retrieval_noise_behavior",
                    "validation_evidence",
                }
                if set(dimensions) != required_dimensions or any(value not in {0, 1, 2} for value in dimensions.values()):
                    issues.append(f"fragility-score concept {item.get('label')!r} has invalid dimension scores")
                if dimensions and item.get("total_score") != sum(dimensions.values()):
                    issues.append(f"fragility-score concept {item.get('label')!r} total does not match dimensions")
                if item.get("human_override") and not str(item.get("override_reason") or "").strip():
                    issues.append(f"fragility-score concept {item.get('label')!r} has an override without a reason")

        vocabulary_entries = operation_entries("vocabulary-learning")
        if not vocabulary_entries:
            issues.append("no active vocabulary-learning artifact follows candidate screening")
        else:
            vocabulary_entry = vocabulary_entries[-1]
            analysis_sequences.append(int(vocabulary_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(vocabulary_entry.get("output_path") or "")) or {}
            if payload.get("ok") is not True or payload.get("scope_version") != scope_version:
                issues.append("latest vocabulary-learning artifact failed or does not match the current scope version")
            if payload.get("scope_reentry_required") is not False:
                issues.append("vocabulary learning has an unresolved scope challenge requiring scope re-entry")
            if payload.get("assignment_required") is not False or payload.get("processing_blockers") not in ([], None):
                issues.append("vocabulary learning has unresolved record assignment/content blockers")
            excluded = payload.get("excluded_record_diagnosis") if isinstance(payload.get("excluded_record_diagnosis"), dict) else {}
            if excluded.get("used_for_proposals") is not False:
                issues.append("excluded-record terminology was not kept diagnostic-only")
            locked_concepts = {normalize_block_key(value) for value in payload.get("locked_concepts", [])}
            missing_locked = sorted(str(label) for label in blocks if normalize_block_key(label) not in locked_concepts)
            if missing_locked:
                issues.append("vocabulary learning does not preserve registered locked concepts: " + ", ".join(missing_locked))
            proposals = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
            accepted = [item for item in proposals if isinstance(item, dict) and item.get("decision") == "accepted"]
            adopted = [item for item in accepted if item.get("effective_decision") == "adopted"]
            experimental = [item for item in accepted if item.get("effective_decision") == "experimental-only"]
            reverted = [item for item in accepted if item.get("effective_decision") == "revert-to-baseline"]
            if (
                payload.get("accepted_term_count") != len(adopted)
                or payload.get("experimental_term_count") != len(experimental)
                or payload.get("reverted_term_count") != len(reverted)
                or payload.get("all_accepted_terms_retested") is not True
                or payload.get("no_harm_checks_complete") is not True
            ):
                issues.append("vocabulary learning does not confirm every accepted term was retested")
            for item in proposals:
                if not isinstance(item, dict):
                    issues.append("vocabulary-learning proposal must be an object")
                    continue
                if item.get("decision") not in {"accepted", "rejected", "deferred"} or not str(item.get("decision_reason") or "").strip():
                    issues.append(f"vocabulary proposal {item.get('proposal_id')!r} lacks a reasoned disposition")
                if item.get("decision") != "accepted":
                    continue
                if item.get("within_locked_concept_attested") is not True or normalize_block_key(item.get("concept")) not in locked_concepts:
                    issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} is not attested within a locked concept")
                retest = item.get("retest") if isinstance(item.get("retest"), dict) else {}
                holdout_test = retest.get("holdout_test") if isinstance(retest.get("holdout_test"), dict) else {}
                differential_sample = retest.get("differential_sample") if isinstance(retest.get("differential_sample"), dict) else {}
                if holdout_test.get("status") not in {"independent-holdout-tested", "unavailable-no-independent-holdout"}:
                    issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} lacks a held-out retest status")
                if not isinstance(differential_sample.get("count"), int) or not isinstance(differential_sample.get("records"), list):
                    issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} lacks a differential sample")
                guard = item.get("no_harm") if isinstance(item.get("no_harm"), dict) else {}
                checks = guard.get("checks") if isinstance(guard.get("checks"), list) else []
                expected_checks = {
                    "named-defect-fixed", "heldout-preserved", "required-blocks-justified",
                    "syntax-translation-stable", "scope-unchanged-or-explicit", "workload-recorded",
                    "no-narrowing-under-low-signal",
                }
                if {check.get("name") for check in checks if isinstance(check, dict)} != expected_checks:
                    issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} lacks all no-harm checks")
                disposition = guard.get("disposition")
                effective = item.get("effective_decision")
                if disposition == "adopt":
                    if guard.get("no_harm_passed") is not True or effective != "adopted":
                        issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} was adopted without passing no-harm checks")
                elif disposition == "experimental-only":
                    experimental_variant = guard.get("experimental_variant") if isinstance(guard.get("experimental_variant"), dict) else {}
                    if effective != "experimental-only" or not experimental_variant.get("variant_id") or not experimental_variant.get("label"):
                        issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} has an unlabelled experimental disposition")
                elif disposition == "revert-to-baseline":
                    if effective != "revert-to-baseline":
                        issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} did not revert after no-harm failure")
                else:
                    issues.append(f"accepted vocabulary proposal {item.get('proposal_id')!r} lacks a valid no-harm disposition")

    scope_payload = read_manifest_output_json(manifest_path, scope_artifact) if scope_artifact else None
    fragile = bool(isinstance(scope_payload, dict) and scope_payload.get("fragile_topic") is True)
    if isinstance(scope_payload, dict):
        fragility = str(scope_payload.get("topic_fragility") or "").strip().casefold()
        fragile = fragile or fragility in {"fragile", "very-fragile", "very fragile"}
        essential = scope_payload.get("essential_blocks")
        if isinstance(essential, list):
            fragile = fragile or any(
                isinstance(item, dict)
                and str(item.get("fragility") or "").strip().casefold() in {"fragile", "very-fragile", "very fragile"}
                for item in essential
            )
        searchable_scope = scope_payload.get("searchable_scope")
        protocol_concepts = searchable_scope.get("concepts") if isinstance(searchable_scope, dict) else None
        if isinstance(protocol_concepts, list):
            fragile = fragile or any(
                isinstance(item, dict)
                and item.get("role") == "essential"
                and str(item.get("provisional_fragility") or "").strip().casefold()
                in {"fragile", "very_fragile", "very-fragile", "very fragile"}
                for item in protocol_concepts
            )
    if fragile:
        strand_entries = operation_entries("two-strand")
        if not strand_entries:
            issues.append("fragile retrieval scope requires a two-strand deliverable")
        else:
            strand_entry = strand_entries[-1]
            analysis_sequences.append(int(strand_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(strand_entry.get("output_path") or "")) or {}
            if payload.get("ok") is not True or payload.get("scope_version") != scope_version:
                issues.append("latest two-strand artifact failed or does not match the current scope version")
            safeguards = payload.get("safeguards") if isinstance(payload.get("safeguards"), dict) else {}
            if safeguards.get("main_is_authoritative") is not True or safeguards.get("focused_cannot_replace_main") is not True:
                issues.append("two-strand artifact does not protect the recall-first main strategy")
            for key in ("main", "focused", "development", "holdout", "records_unique_to_main", "records_unique_to_focused", "estimated_screening_workload"):
                if not isinstance(payload.get(key), dict):
                    issues.append(f"two-strand artifact lacks {key}")
            narrowing = payload.get("narrowing_blocks") if isinstance(payload.get("narrowing_blocks"), list) else []
            if not narrowing or any(not str(item.get("rationale") or "").strip() for item in narrowing if isinstance(item, dict)):
                issues.append("two-strand artifact lacks reasoned narrowing blocks")

        burden_entries = operation_entries("screening-burden")
        if not burden_entries:
            issues.append("fragile multi-strand deliverable lacks labelled-sample screening-burden evidence")
        else:
            burden_entry = burden_entries[-1]
            analysis_sequences.append(int(burden_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(burden_entry.get("output_path") or "")) or {}
            if payload.get("ok") is not True or payload.get("scope_version") != scope_version:
                issues.append("latest screening-burden artifact failed or does not match the current scope version")
            if payload.get("labels_complete") is not True:
                issues.append("screening-burden sample labels are incomplete")
            minimum_recall = payload.get("minimum_heldout_recall")
            if not isinstance(minimum_recall, (int, float)) or isinstance(minimum_recall, bool) or not 0 <= minimum_recall <= 1:
                issues.append("screening-burden artifact lacks a valid held-out recall requirement")
            variants = payload.get("variants") if isinstance(payload.get("variants"), list) else []
            if len(variants) < 2:
                issues.append("screening-burden artifact must compare at least two variants")
            eligible_labels = set()
            eligible_rows = []
            for item in variants:
                if not isinstance(item, dict):
                    issues.append("screening-burden variant must be an object")
                    continue
                if not isinstance(item.get("precision_confidence_interval_95"), dict):
                    issues.append(f"screening-burden variant {item.get('label')!r} lacks a precision confidence interval")
                if "estimated_records_screened_per_relevant_report" not in item:
                    issues.append(f"screening-burden variant {item.get('label')!r} lacks records-per-relevant burden")
                recall_value = item.get("heldout_recall")
                if not isinstance(recall_value, (int, float)) or isinstance(recall_value, bool) or not isinstance(item.get("incremental_vs_baseline"), dict):
                    issues.append(f"screening-burden variant {item.get('label')!r} lacks held-out/incremental comparison")
                elif isinstance(minimum_recall, (int, float)) and not isinstance(minimum_recall, bool):
                    expected_qualified = recall_value >= minimum_recall
                    if item.get("recall_requirement_met") is not expected_qualified:
                        issues.append(f"screening-burden variant {item.get('label')!r} has an incorrect recall-gate result")
                if item.get("recall_requirement_met") is True and item.get("precision_estimate") is not None:
                    eligible_labels.add(str(item.get("label")))
                    eligible_rows.append(item)
            selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else {}
            recorded_eligible = {str(value) for value in selection.get("eligible_variant_labels", [])}
            if recorded_eligible != eligible_labels:
                issues.append("screening-burden eligible variants do not match recall-qualified variants")
            used = selection.get("burden_used_for_selection")
            recommended = selection.get("recommended_variant_label")
            if used is True:
                expected_recommended = None
                if len(eligible_rows) >= 2:
                    expected_recommended = min(
                        eligible_rows,
                        key=lambda row: (
                            float(row.get("estimated_records_screened_per_relevant_report") or float("inf")),
                            int(row.get("total_count") or 0),
                            str(row.get("label")),
                        ),
                    ).get("label")
                if len(eligible_labels) < 2 or str(recommended) not in eligible_labels or recommended != expected_recommended:
                    issues.append("screening burden was used to select a variant that did not meet the recall gate")
            elif used is not False or recommended is not None:
                issues.append("screening-burden selection must remain unused when fewer than two variants meet recall")

    if seed_gate_is_no_seed(state):
        issues.extend(recall_offer_readiness(state))
        discovery_entries = operation_entries("orthogonal-pilot-adjudication")
        if not discovery_entries:
            issues.append("no-seed build lacks orthogonal-pilot saturation evidence")
        else:
            discovery_entry = discovery_entries[-1]
            analysis_sequences.append(int(discovery_entry.get("seq") or 0))
            payload = read_manifest_output_json(manifest_path, str(discovery_entry.get("output_path") or "")) or {}
            required_pilots = {
                "mesh-led",
                "exact-phrase-led",
                "operational-description-led",
                "prior-review-led",
                "citation-registry-led",
                "historical-terminology-led",
            }
            pilot_types = {str(value) for value in payload.get("pilot_types", [])}
            if payload.get("ok") is not True or payload.get("scope_version") != scope_version:
                issues.append("orthogonal-pilot adjudication failed or does not match the current scope version")
            if payload.get("provenance_blinded") is not True:
                issues.append("orthogonal-pilot screening was not provenance blinded")
            if missing := sorted(required_pilots - pilot_types):
                issues.append("orthogonal-pilot evidence is missing pilot types: " + ", ".join(missing))
            if payload.get("safety_cap_reached_any") is True:
                issues.append("orthogonal-pilot safety cap was reached; saturation cannot be claimed")
            if payload.get("saturation_reached") is not True:
                issues.append("orthogonal-pilot discovery has not reached study-and-vocabulary saturation")
            required_rounds = payload.get("required_saturated_rounds")
            consecutive_rounds = payload.get("consecutive_saturated_rounds")
            if (
                not isinstance(required_rounds, int)
                or required_rounds < 2
                or not isinstance(consecutive_rounds, int)
                or consecutive_rounds < required_rounds
            ):
                issues.append("orthogonal-pilot saturation lacks the required repeated zero-novelty rounds")
            if payload.get("new_included_pmids") != [] or payload.get("new_vocabulary_term_count") != 0:
                issues.append("orthogonal-pilot final round still added relevant studies or vocabulary")
            if not str(payload.get("stopping_rule") or "").strip():
                issues.append("orthogonal-pilot artifact lacks its saturation stopping rule")
            if screening_status == "complete" and payload.get("ledger_frozen") is not True:
                issues.append("orthogonal-pilot holdout was not frozen before term mining")

    critics = state.get("critic_rounds") if isinstance(state.get("critic_rounds"), list) else []
    if not critics:
        issues.append("no PRESS-informed critic round is recorded")
        latest_critic_seq = 0
    else:
        for index, critic_summary in enumerate(critics, start=1):
            issues.extend(protocol_binding_issues(critic_summary, scope, f"critic round {index} summary"))
        latest = critics[-1] if isinstance(critics[-1], dict) else {}
        latest_critic_seq = int(latest.get("entry_seq") or 0)
        if latest.get("overall_status") != "pass":
            issues.append("latest critic round has not passed")
        if latest.get("open_actionable") not in (0, None):
            issues.append("latest critic round still has open actionable findings")
        if latest.get("scope_version") != scope_version:
            issues.append("latest critic round does not match the current retrieval-scope version")
        if analysis_sequences and latest_critic_seq <= max(analysis_sequences):
            issues.append("latest critic round was not run after the latest empirical analysis/discovery artifact")
        if latest.get("critic_version") != 2:
            issues.append("latest critic round does not use the evidence-backed critic_version 2 contract")
        for key, label in (("artifact", "critic"), ("validation_artifact", "critic validation")):
            path_value = str(latest.get(key) or "")
            if not path_value:
                issues.append(f"latest {label} artifact is not recorded")
            elif not output_path_exists(path_value, manifest_path=manifest_path, data=data):
                issues.append(f"latest {label} artifact does not exist: {path_value}")
        critic_artifact = str(latest.get("artifact") or "")
        bundle_value = str(latest.get("evidence_bundle") or "")
        if not bundle_value:
            issues.append("latest critic round lacks a hashed evidence bundle")
        elif critic_artifact:
            critic_path = resolve_artifact_path(critic_artifact, manifest_path)
            expected_critic_hash = str(latest.get("artifact_sha256") or "")
            if critic_path.is_file() and expected_critic_hash and sha256_file(critic_path) != expected_critic_hash:
                issues.append("latest critic artifact changed after validation")
            bundle_path = Path(bundle_value)
            if not bundle_path.is_absolute():
                bundle_path = critic_path.parent / bundle_path
            if not bundle_path.is_file():
                issues.append(f"latest critic evidence bundle does not exist: {bundle_path}")
            else:
                expected_bundle_hash = str(latest.get("evidence_bundle_sha256") or "")
                if expected_bundle_hash and sha256_file(bundle_path) != expected_bundle_hash:
                    issues.append("latest critic evidence bundle changed after validation")
                try:
                    bundle_payload = json.loads(bundle_path.read_text(encoding="utf-8"))
                    for item in bundle_payload.get("artifacts", []):
                        if not isinstance(item, dict):
                            continue
                        evidence_path = Path(str(item.get("path") or ""))
                        if not evidence_path.is_absolute():
                            evidence_path = bundle_path.parent / evidence_path
                        if not evidence_path.is_file() or sha256_file(evidence_path) != str(item.get("sha256") or ""):
                            issues.append(f"latest critic evidence changed after review: {item.get('role')}")
                except (OSError, json.JSONDecodeError, AttributeError):
                    issues.append("latest critic evidence bundle is not valid JSON")

    revisions = state.get("revision_cycles") if isinstance(state.get("revision_cycles"), list) else []
    revision_critic_rounds = {
        item.get("critic_round") for item in revisions if isinstance(item, dict)
    }
    for critic in critics:
        if isinstance(critic, dict) and critic.get("overall_status") == "revise":
            if critic.get("round") not in revision_critic_rounds:
                issues.append(f"critic round {critic.get('round')} required revision but no revision cycle is recorded")
    for revision in revisions:
        if not isinstance(revision, dict):
            issues.append("revision-cycle state contains a non-object entry")
            continue
        guard_value = str(revision.get("no_harm_file") or "")
        guard_path = Path(guard_value)
        if not guard_path.is_absolute():
            guard_path = manifest_path.parent / guard_path
        if not guard_path.is_file():
            issues.append(f"revision cycle {revision.get('revision_round')} lacks its no-harm artifact")
            continue
        if str(revision.get("no_harm_sha256") or "") != sha256_file(guard_path):
            issues.append(f"revision cycle {revision.get('revision_round')} no-harm artifact changed after recording")
            continue
        try:
            guard = json.loads(guard_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            issues.append(f"revision cycle {revision.get('revision_round')} no-harm artifact is invalid JSON")
            continue
        if guard.get("operation") != "revision-no-harm" or guard.get("disposition") != revision.get("no_harm_disposition"):
            issues.append(f"revision cycle {revision.get('revision_round')} no-harm disposition is stale")
        if guard.get("disposition") == "adopt" and guard.get("no_harm_passed") is not True:
            issues.append(f"revision cycle {revision.get('revision_round')} adopted a change that failed no-harm checks")
        issues.extend(protocol_binding_issues(guard, scope, f"revision cycle {revision.get('revision_round')} no-harm artifact"))

    screening_summary = screening.get("summary") if isinstance(screening.get("summary"), dict) else {}
    needs_validation = str(gates.get("seed") or "").strip().lower() in {"provided", "partial"}
    needs_validation = needs_validation or bool(screening_summary.get("independent_holdout_available"))
    validation_entries = [
        entry for entry in entries
        if isinstance(entry, dict) and entry.get("kind") in {"validate", "recall"}
    ]
    validation_entries.sort(key=lambda entry: int(entry.get("seq") or 0))
    if needs_validation and not validation_entries:
        issues.append("seed/holdout validation is required but no validate or recall artifact is recorded")
    elif needs_validation:
        latest_validation = validation_entries[-1]
        output_value = str(latest_validation.get("output_path") or "")
        if not output_value or not output_path_exists(output_value, manifest_path=manifest_path, data=data):
            issues.append("latest required validation lacks an existing output artifact")
        else:
            validation_payload = read_manifest_output_json(manifest_path, output_value)
            if validation_payload is None:
                issues.append("latest required validation output is not a valid JSON object")
            else:
                operation = validation_payload.get("operation")
                if operation not in {"validate", "recall"}:
                    issues.append("latest required validation output is not a validate/recall artifact")
                if validation_payload.get("ok") is not True:
                    issues.append("latest required validation output did not complete successfully")
                missed = validation_payload.get("missed_pmids")
                if not isinstance(missed, list):
                    issues.append("latest required validation output lacks a missed_pmids list")
                elif missed:
                    issues.append(
                        "latest required validation has unresolved missed PMIDs: "
                        + ", ".join(str(pmid) for pmid in missed[:20])
                    )
        if latest_validation.get("scope_version") not in (None, scope_version):
            issues.append("latest required validation does not match the current retrieval-scope version")
        revisions = state.get("revision_cycles") if isinstance(state.get("revision_cycles"), list) else []
        latest_revision_seq = max(
            (int(item.get("entry_seq") or 0) for item in revisions if isinstance(item, dict)),
            default=0,
        )
        if latest_revision_seq and int(latest_validation.get("seq") or 0) <= latest_revision_seq:
            issues.append("required validation was not rerun after the latest revision cycle")

    final_qa_entries = [
        entry for entry in entries
        if isinstance(entry, dict)
        and entry.get("kind") == "qa"
        and "final-qa" in str(entry.get("command") or "").casefold()
    ]
    final_qa_entries.sort(key=lambda entry: int(entry.get("seq") or 0))
    if not final_qa_entries:
        issues.append("no hooks_tool.py final-qa entry is recorded")
        final_qa_seq = 0
    else:
        final_qa = final_qa_entries[-1]
        final_qa_seq = int(final_qa.get("seq") or 0)
        if latest_critic_seq and final_qa_seq <= latest_critic_seq:
            issues.append("final QA was not rerun after the latest critic round")
        output_value = str(final_qa.get("output_path") or "")
        if not output_value or not output_path_exists(output_value, manifest_path=manifest_path, data=data):
            issues.append("latest final-qa entry lacks an existing output artifact")
        else:
            final_qa_payload = read_manifest_output_json(manifest_path, output_value)
            if final_qa_payload is None:
                issues.append("latest final-qa output is not a valid JSON object")
            elif final_qa_payload.get("hook") != "pre_final_strategy_qa":
                issues.append(
                    "latest final-qa output is not a pre_final_strategy_qa artifact"
                )
            elif final_qa_payload.get("ok") is not True:
                payload_issues = final_qa_payload.get("issues")
                if not isinstance(payload_issues, list):
                    payload_issues = []
                error_codes = [
                    str(item.get("code"))
                    for item in payload_issues
                    if isinstance(item, dict)
                    and item.get("severity") == "error"
                    and item.get("code")
                ]
                detail = f"; errors: {', '.join(error_codes)}" if error_codes else ""
                issues.append(f"latest final-qa output did not pass (ok is not true){detail}")

    final_topic_entries = [
        entry for entry in entries if isinstance(entry, dict) and looks_like_final_topic_search(entry)
    ]
    final_topic_entries.sort(key=lambda entry: int(entry.get("seq") or 0))
    if not final_topic_entries:
        issues.append("no final topic-only strategy count is recorded")
    else:
        if needs_validation and validation_entries:
            final_hashes = final_topic_entries[-1].get("input_sha256")
            validation_hashes = validation_entries[-1].get("input_sha256")
            if isinstance(final_hashes, dict) and final_hashes and isinstance(validation_hashes, dict) and validation_hashes:
                if set(final_hashes.values()).isdisjoint(set(validation_hashes.values())):
                    issues.append("final topic search and required validation are not bound to the same strategy input hash")
        issues.extend(low_count_review_readiness(data, manifest_path))

    if scope.get("lock_mode") == "protocol":
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            output_value = str(entry.get("output_path") or "")
            if not output_value.lower().endswith(".json"):
                continue
            payload = read_manifest_output_json(manifest_path, output_value)
            command = str(entry.get("command") or "").casefold()
            is_audit_json = "audit-scaffold" in command or (
                isinstance(payload, dict) and isinstance(payload.get("audit_outline"), dict)
            )
            if is_audit_json:
                issues.extend(protocol_binding_issues(payload, scope, f"audit JSON artifact {output_value}"))

    audit_entries = [
        entry for entry in entries
        if isinstance(entry, dict)
        and entry.get("kind") == "artifact"
        and str(entry.get("output_path") or "").lower().endswith(".md")
    ]
    audit_entries.sort(key=lambda entry: int(entry.get("seq") or 0))
    if not audit_entries:
        issues.append("no final audit Markdown artifact is recorded")
    else:
        audit = audit_entries[-1]
        if final_qa_seq and int(audit.get("seq") or 0) <= final_qa_seq:
            issues.append("audit Markdown was not rendered after final QA")
        output_value = str(audit.get("output_path") or "")
        if not output_path_exists(output_value, manifest_path=manifest_path, data=data):
            issues.append(f"audit Markdown artifact does not exist: {output_value}")

    return issues


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
    if action in ("show", "check-ready", "check-complete", "coverage"):
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
        elif action == "check-complete":
            issues = complete_loop_readiness(data, path)
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
        elif action == "lock-protocol":
            summary = validate_protocol_compile(args.protocol_file, args.compile_receipt, path)
            scope = state["scope"]
            current_version = int(scope.get("version") or 0)
            new_version = int(summary["scope_version"])
            same_lock = (
                current_version == new_version
                and scope.get("status") == "locked"
                and scope.get("lock_mode") == "protocol"
                and scope.get("protocol_sha256") == summary.get("protocol_sha256")
            )
            if current_version == 0:
                if new_version != 1:
                    raise ManifestError("the first locked protocol must use scope_version 1")
            elif not same_lock and new_version != current_version + 1:
                raise ManifestError(
                    f"protocol re-entry must increment scope_version by one: "
                    f"current={current_version}, supplied={new_version}"
                )

            history = scope.get("history") if isinstance(scope.get("history"), list) else []
            if not same_lock:
                reset_scope_dependent_state(state)
                entry_seq = append_internal_entry(
                    data,
                    now=now,
                    kind="scope",
                    label=f"protocol DSL scope v{new_version}",
                    command=(
                        f"manifest_tool.py state lock-protocol --protocol-file {args.protocol_file} "
                        f"--compile-receipt {args.compile_receipt}"
                    ),
                    output_path=args.protocol_file,
                    note="protocol DSL initial lock" if current_version == 0 else "protocol DSL scope re-entry",
                )
                entries = data.get("entries") if isinstance(data.get("entries"), list) else []
                if entries and isinstance(entries[-1], dict):
                    protocol_path = resolve_artifact_path(args.protocol_file, path)
                    receipt_path = resolve_artifact_path(args.compile_receipt, path)
                    entries[-1].update(
                        {
                            "output_sha256": sha256_file(protocol_path),
                            "input_sha256": {args.compile_receipt: sha256_file(receipt_path)},
                            "scope_version": new_version,
                            "protocol_sha256": summary["protocol_sha256"],
                            "returncode": 0,
                        }
                    )
                history.append(
                    {
                        "version": new_version,
                        "lock_mode": "protocol",
                        "protocol_id": summary["protocol_id"],
                        "dsl_version": summary["dsl_version"],
                        "protocol_file": args.protocol_file,
                        "protocol_sha256": summary["protocol_sha256"],
                        "compile_receipt": args.compile_receipt,
                        "generated_paths": summary["generated_paths"],
                        "generated_sha256": summary["generated_sha256"],
                        "essential_block_count": len(summary["essential_blocks"]),
                        "locked_utc": now,
                        "entry_seq": entry_seq,
                    }
                )

            scope.update(
                {
                    "version": new_version,
                    "status": "locked",
                    "artifact": args.protocol_file,
                    "lock_mode": "protocol",
                    "protocol_file": args.protocol_file,
                    "protocol_sha256": summary["protocol_sha256"],
                    "protocol_id": summary["protocol_id"],
                    "dsl_version": summary["dsl_version"],
                    "compile_receipt": args.compile_receipt,
                    "generated_paths": summary["generated_paths"],
                    "generated_sha256": summary["generated_sha256"],
                    "reopened_reason": "",
                    "history": history,
                }
            )
            if not same_lock:
                state["blocks"] = {
                    str(item["id"]): {
                        "waivers": {},
                        "scope_version": new_version,
                        "display_label": str(item["label"]),
                        "protocol_sha256": summary["protocol_sha256"],
                    }
                    for item in summary["essential_blocks"]
                    if isinstance(item, dict)
                }
            state["gates"].update(
                {
                    "framework": summary["framework"],
                    "seed": summary["seed_gate"],
                    "concept": f"resolved-v{new_version}",
                    "filter": summary["filter_gate"],
                }
            )
            state["current_stage"] = "scope-lock"
        elif action == "lock-scope":
            summary = validate_scope_artifact(args.scope_file)
            scope = state["scope"]
            current_version = int(scope.get("version") or 0)
            new_version = int(summary["version"])
            if current_version and scope.get("status") != "reopened":
                if new_version == current_version and scope.get("artifact") == args.scope_file:
                    pass
                else:
                    raise ManifestError("reopen the current scope before locking a new version")
            elif new_version != current_version + 1:
                raise ManifestError(
                    f"scope version must increment by one: current={current_version}, supplied={new_version}"
                )
            history = scope.get("history") if isinstance(scope.get("history"), list) else []
            existing = next((item for item in history if isinstance(item, dict) and item.get("version") == new_version), None)
            if existing is None:
                entry_seq = append_internal_entry(
                    data,
                    now=now,
                    kind="scope",
                    label=f"retrieval scope v{new_version}",
                    command=f"manifest_tool.py state lock-scope --scope-file {args.scope_file}",
                    output_path=args.scope_file,
                    note=str(scope.get("reopened_reason") or "initial conceptual scope lock"),
                )
                history.append(
                    {
                        **summary,
                        "artifact": args.scope_file,
                        "locked_utc": now,
                        "reason": str(scope.get("reopened_reason") or "initial conceptual scope lock"),
                        "entry_seq": entry_seq,
                    }
                )
            scope.update(
                {
                    "version": new_version,
                    "status": "locked",
                    "artifact": args.scope_file,
                    "lock_mode": "legacy",
                    "protocol_file": "",
                    "protocol_sha256": "",
                    "protocol_id": "",
                    "dsl_version": "",
                    "compile_receipt": "",
                    "generated_paths": {},
                    "generated_sha256": {},
                    "reopened_reason": "",
                    "history": history,
                }
            )
            state["gates"]["concept"] = f"resolved-v{new_version}"
            state["current_stage"] = "scope-lock"
        elif action == "reopen-scope":
            reason = str(args.reason or "").strip()
            if not reason:
                raise ManifestError("reopen-scope requires a non-empty reason")
            scope = state["scope"]
            if scope.get("status") != "locked" or int(scope.get("version") or 0) < 1:
                raise ManifestError("cannot reopen scope before an initial scope version is locked")
            scope["status"] = "reopened"
            scope["reopened_reason"] = reason
            state["gates"]["concept"] = "pending"
            state["candidate_screening"] = new_build_state()["candidate_screening"]
            state["blocks"] = {}
            state["current_stage"] = "revision"
        elif action == "record-candidate-screen":
            scope = state["scope"]
            if scope.get("status") != "locked":
                raise ManifestError("lock retrieval scope before recording candidate screening")
            summary = validated_receipt(args.validation_file, "candidate-ledger-validate")
            if summary.get("scope_version") != scope.get("version"):
                raise ManifestError("candidate ledger scope_version does not match the locked retrieval scope")
            binding_issues = protocol_binding_issues(summary, scope, "candidate-ledger validation summary")
            ledger_path = resolve_artifact_path(args.ledger_file, path)
            ledger_payload = _protocol_json(ledger_path, "candidate ledger")
            binding_issues.extend(protocol_binding_issues(ledger_payload, scope, "candidate ledger"))
            if binding_issues:
                raise ManifestError("; ".join(binding_issues))
            entry_seq = append_internal_entry(
                data,
                now=now,
                kind="candidate-screen",
                label=f"candidate screening for scope v{scope.get('version')}",
                command=(
                    f"candidate_ledger.py {args.ledger_file} --output {args.validation_file}; "
                    "manifest_tool.py state record-candidate-screen"
                ),
                output_path=args.ledger_file,
                note="validated candidate discovery/holdout roles",
            )
            state["candidate_screening"] = {
                "status": "complete",
                "artifact": args.ledger_file,
                "validation_artifact": args.validation_file,
                "summary": summary,
                "reason": "",
                "entry_seq": entry_seq,
                "completed_utc": now,
            }
            state["current_stage"] = "candidate-screening"
        elif action == "resolve-candidate-screening":
            reason = str(args.reason or "").strip()
            if args.value != "not-applicable":
                raise ManifestError("resolve-candidate-screening currently accepts only not-applicable")
            if not reason:
                raise ManifestError("candidate-screening not-applicable requires a reason")
            state["candidate_screening"] = {
                "status": "not-applicable",
                "artifact": "",
                "validation_artifact": "",
                "summary": {},
                "reason": reason,
                "completed_utc": now,
            }
        elif action == "record-critic":
            scope = state["scope"]
            if scope.get("status") != "locked":
                raise ManifestError("lock retrieval scope before recording a critic round")
            summary = validated_receipt(args.validation_file, "critic-artifact-validate")
            if summary.get("scope_version") != scope.get("version"):
                raise ManifestError("critic scope_version does not match the locked retrieval scope")
            binding_issues = protocol_binding_issues(summary, scope, "critic validation summary")
            if binding_issues:
                raise ManifestError("; ".join(binding_issues))
            if summary.get("critic_version") != 2:
                raise ManifestError("recorded critic rounds must use critic_version 2 with a hashed evidence bundle")
            rounds = state["critic_rounds"]
            expected_round = len(rounds) + 1
            if summary.get("round") != expected_round:
                raise ManifestError(f"critic round must be sequential: expected {expected_round}")
            if rounds:
                previous = rounds[-1] if isinstance(rounds[-1], dict) else {}
                previous_statuses = previous.get("finding_statuses") if isinstance(previous.get("finding_statuses"), dict) else {}
                current_statuses = summary.get("finding_statuses") if isinstance(summary.get("finding_statuses"), dict) else {}
                dropped = sorted(
                    finding_id
                    for finding_id, status in previous_statuses.items()
                    if status == "open" and finding_id not in current_statuses
                )
                if dropped:
                    raise ManifestError(
                        "critic finding continuity failed; previously open finding IDs were omitted: "
                        + ", ".join(dropped)
                    )
            entry_seq = append_internal_entry(
                data,
                now=now,
                kind="critic",
                label=f"PRESS-informed critic round {summary.get('round')}",
                command=(
                    f"critic_tool.py {args.critic_file} --output {args.validation_file}; "
                    "manifest_tool.py state record-critic"
                ),
                output_path=args.critic_file,
                note=f"overall_status={summary.get('overall_status')}",
            )
            rounds.append(
                {
                    **summary,
                    "artifact": args.critic_file,
                    "validation_artifact": args.validation_file,
                    "entry_seq": entry_seq,
                    "recorded_utc": now,
                }
            )
            state["current_stage"] = "critic-review"
        elif action == "record-revision":
            summary = validate_revision_artifact(args.revision_file)
            scope = state["scope"]
            if summary.get("scope_version") != scope.get("version"):
                raise ManifestError("revision-cycle scope_version does not match the current retrieval scope")
            binding_issues = protocol_binding_issues(summary, scope, "revision no-harm summary")
            if binding_issues:
                raise ManifestError("; ".join(binding_issues))
            expected_round = len(state["revision_cycles"]) + 1
            if summary.get("revision_round") != expected_round:
                raise ManifestError(f"revision round must be sequential: expected {expected_round}")
            critic_round = int(summary.get("critic_round") or 0)
            critics = state["critic_rounds"]
            if critic_round < 1 or critic_round > len(critics):
                raise ManifestError("revision-cycle critic_round does not reference a recorded critic round")
            entry_seq = append_internal_entry(
                data,
                now=now,
                kind="revision",
                label=f"revision cycle {summary.get('revision_round')}",
                command=f"manifest_tool.py state record-revision --revision-file {args.revision_file}",
                output_path=args.revision_file,
                note=str(summary.get("change") or ""),
            )
            state["revision_cycles"].append(
                {**summary, "artifact": args.revision_file, "entry_seq": entry_seq, "recorded_utc": now}
            )
            state["current_stage"] = "revision"
        elif action == "register-blocks":
            scope = state["scope"]
            blocks = state["blocks"]
            for label in load_block_labels(args.blocks_file):
                if label not in blocks:
                    blocks[label] = {"waivers": {}, "scope_version": scope.get("version")}
        elif action == "register-block":
            scope = state["scope"]
            blocks = state["blocks"]
            if args.label not in blocks:
                blocks[args.label] = {"waivers": {}, "scope_version": scope.get("version")}
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
    output_sha256 = None
    if output_path:
        resolved_output = resolve_artifact_path(output_path, path)
        if resolved_output.is_file():
            output_sha256 = sha256_file(resolved_output)
    input_sha256: dict[str, str] = {}
    for input_value in args.input or []:
        resolved_input = resolve_artifact_path(input_value, path)
        if not resolved_input.is_file():
            raise ManifestError(f"--input file does not exist: {input_value}")
        input_sha256[input_value] = sha256_file(resolved_input)

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
                "scope_version": args.scope_version,
                "returncode": args.returncode,
                "output_sha256": output_sha256,
                "input_sha256": input_sha256,
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
    require_complete_loop = getattr(args, "require_complete_loop", False)
    if (
        args.validate
        or args.check_files
        or require_ready
        or require_coverage
        or require_recall_offer
        or require_gap_analysis
        or require_low_count_review
        or require_complete_loop
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
        if require_complete_loop:
            issues.extend(f"complete-loop gap: {reason}" for reason in complete_loop_readiness(data, path))
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
            "scope": state.get("scope") if isinstance(state, dict) else None,
            "candidate_screening": state.get("candidate_screening") if isinstance(state, dict) else None,
            "critic_rounds": state.get("critic_rounds") if isinstance(state, dict) else [],
            "revision_cycles": state.get("revision_cycles") if isinstance(state, dict) else [],
            "complete_loop_issues": complete_loop_readiness(data, path) if isinstance(state, dict) else ["build_state not initialized"],
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
    add_parser.add_argument("--input", action="append", default=[], help="Input artifact path to hash and bind to this entry; repeatable.")
    add_parser.add_argument("--scope-version", type=int, help="Retrieval-scope version this evidence belongs to.")
    add_parser.add_argument("--returncode", type=int, default=0, help="Recorded process exit code (default: 0).")
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
    show_parser.add_argument(
        "--require-complete-loop",
        action="store_true",
        help="Combined final-handoff gate: require locked versioned scope, candidate-screening integrity, current block evidence, applicable validation, a passing critic round, final QA, final count/low-count handling, audit output, and no pending decision.",
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

    lock_protocol = add_state_action(
        "lock-protocol",
        "Lock the canonical protocol DSL and its verified compile artifacts; derives gates and essential blocks.",
    )
    lock_protocol.add_argument("--protocol-file", required=True, help="Canonical protocol_vN.json DSL file.")
    lock_protocol.add_argument(
        "--compile-receipt",
        required=True,
        help="Passing protocol_tool.py compile receipt whose artifact hashes will be verified.",
    )

    lock_scope = add_state_action(
        "lock-scope",
        "Legacy compatibility path: validate and lock a retrieval-scope JSON version. Prefer lock-protocol.",
    )
    lock_scope.add_argument("--scope-file", required=True, help="Versioned retrieval_scope_vN.json artifact.")

    reopen_scope = add_state_action(
        "reopen-scope", "Reopen the current scope after a structural/scope finding; clears block and candidate-screen state."
    )
    reopen_scope.add_argument("--reason", required=True, help="Evidence-backed reason for reopening scope.")

    record_candidate = add_state_action(
        "record-candidate-screen", "Record a candidate ledger that passed candidate_ledger.py validation."
    )
    record_candidate.add_argument("--ledger-file", required=True, help="Validated candidate_ledger.json path.")
    record_candidate.add_argument(
        "--validation-file", required=True, help="Passing candidate_ledger.py --output receipt path."
    )

    resolve_candidate = add_state_action(
        "resolve-candidate-screening", "Record candidate screening as not applicable with a reason."
    )
    resolve_candidate.add_argument("value", choices=["not-applicable"], help="Resolution value.")
    resolve_candidate.add_argument("--reason", required=True, help="Why no candidate screening was feasible/applicable.")

    record_critic = add_state_action(
        "record-critic", "Record the next PRESS-informed critic round after critic_tool.py validation."
    )
    record_critic.add_argument("--critic-file", required=True, help="critic_round_N.json path.")
    record_critic.add_argument(
        "--validation-file", required=True, help="Passing critic_tool.py --output receipt path."
    )

    record_revision = add_state_action(
        "record-revision", "Validate and record the next semantic revision-cycle JSON artifact."
    )
    record_revision.add_argument("--revision-file", required=True, help="revision_cycle_N.json path.")

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
        "check-complete", "Run the combined conceptual-objective-critic completion gate (read-only).", mutating=False
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
