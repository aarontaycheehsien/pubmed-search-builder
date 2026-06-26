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
         "command": "python scripts/pubmed_tool.py search --query-file q.txt --retmax 0",
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
STAGE_REPORTS = {
    "question-intake": {
        "label": "Question intake",
        "level": "full",
        "references": ["SKILL.md", "references/workflow.md"],
        "doing_now": "Confirm an independently stated plain-language research/review question.",
        "allowed_now": "Clarify the research/review question and reject pasted Boolean syntax as build input.",
        "not_doing_yet": "Seed intake, MeSH/PubMed exploration, block construction, validation, final QA, and audit output.",
        "user_decision_needed": "plain-language research/review question if not already supplied",
    },
    "seed-intake": {
        "label": "Seed intake",
        "level": "full",
        "references": ["SKILL.md", "references/workflow.md"],
        "doing_now": "Ask once whether known relevant seed PMIDs are available.",
        "allowed_now": "Accept seed PMIDs, no-seed status, or an explicit proceed-without-seeds decision.",
        "not_doing_yet": "MeSH/PubMed exploration, concept gate, block testing, validation, variants, final QA, and audit output.",
        "user_decision_needed": "seed PMID status",
    },
    "limited-seed-evidence": {
        "label": "Limited seed evidence",
        "level": "marker",
        "references": [
            "references/workflow.md",
            "references/concept-analysis-and-gating.md",
            "references/seed-pmid-validation.md",
        ],
        "doing_now": "Fetch/mine usable seed PMIDs only to inform concept analysis.",
        "allowed_now": "Normalize seeds, document malformed or missing PMIDs, and inspect saved seed JSON for concept evidence.",
        "not_doing_yet": "Broad PubMed exploration, block testing, variants, validation, final QA, and audit output.",
        "user_decision_needed": "none unless a fetched seed is retracted or materially out of scope",
    },
    "concept-gate": {
        "label": "Concept gate",
        "level": "full",
        "references": [
            "references/framework-selection.md",
            "references/concept-analysis-and-gating.md",
            "references/anti-patterns.md",
        ],
        "doing_now": "Choose the framework and decide which candidate concepts may become required AND blocks.",
        "allowed_now": "Run formal concept analysis and ask only unresolved framework, optional-block, filter, or limit decisions.",
        "not_doing_yet": "MeSH/PubMed exploration, block construction, optional-block testing, variants, validation, final QA, and audit output.",
        "user_decision_needed": "none unless a sensitivity-dangerous concept, filter, limit, or framework ambiguity is unresolved",
    },
    "pre-mesh-brainstorm": {
        "label": "Pre-MeSH brainstorm",
        "level": "marker",
        "references": ["references/concept-analysis-and-gating.md", "references/tiab-expansion.md"],
        "doing_now": "Brainstorm vocabulary/domain frames for weak-MeSH or social-science concepts.",
        "allowed_now": "Accept, reject, or defer vocabulary families as within-block candidates.",
        "not_doing_yet": "MeSH lookup until any material domain-framing question is resolved.",
        "user_decision_needed": "none unless domain framing can materially change the strategy",
    },
    "mesh-exploration": {
        "label": "MeSH/PubMed exploration",
        "level": "marker",
        "references": ["references/mesh-and-pubmed-tools.md", "references/workflow.md"],
        "doing_now": "Run MeSH sweeps, tree/details checks, and PubMed ATM/count exploration for admitted concepts.",
        "allowed_now": "Explore controlled vocabulary and candidate terms for gate-authorized essential concepts.",
        "not_doing_yet": "Unauthorized optional-block tests, variants, final QA, and audit output.",
        "user_decision_needed": "none",
    },
    "text-word-expansion": {
        "label": "Text-word expansion",
        "level": "marker",
        "references": ["references/tiab-expansion.md", "references/wildcard-and-truncation.md"],
        "doing_now": "Generate and test title/abstract, proximity, acronym, spelling, and wildcard candidates.",
        "allowed_now": "Use seed, pilot, MeSH-entry, ATM, and sample evidence for within-block term candidates.",
        "not_doing_yet": "Final strategy handoff before block testing and QA.",
        "user_decision_needed": "none unless a term family should become a separate optional concept",
    },
    "block-testing": {
        "label": "Block testing",
        "level": "marker",
        "references": [
            "references/workflow.md",
            "references/concept-analysis-and-gating.md",
            "references/mesh-and-pubmed-tools.md",
        ],
        "doing_now": "Test concept blocks, pairwise blocks, full strategies, filters, and authorized variants.",
        "allowed_now": "Run count checks and authorized sensitivity/workload comparisons.",
        "not_doing_yet": "Promoting unauthorized optional blocks, filters, or focused variants.",
        "user_decision_needed": "none unless observed evidence creates a new material trade-off",
    },
    "validation": {
        "label": "Validation",
        "level": "marker",
        "references": ["references/seed-pmid-validation.md", "references/workflow.md"],
        "doing_now": "Validate known-item seed retrieval and optional relative recall.",
        "allowed_now": "Diagnose missed PMIDs and bottleneck blocks using saved outputs.",
        "not_doing_yet": "Final handoff before revisions and final QA are complete.",
        "user_decision_needed": "none unless a seed must be excluded, replaced, or retained specially",
    },
    "revision": {
        "label": "Revision",
        "level": "marker",
        "references": ["references/workflow.md"],
        "doing_now": "Revise weak blocks, noisy terms, missed-seed causes, or filter problems.",
        "allowed_now": "Change the draft strategy based on documented evidence and rerun affected checks.",
        "not_doing_yet": "Audit handoff until final QA and validation reflect the revised strategy.",
        "user_decision_needed": "none unless a revision would narrow recall beyond prior authorization",
    },
    "final-qa": {
        "label": "Final QA",
        "level": "marker",
        "references": ["references/workflow.md", "references/mesh-and-pubmed-tools.md"],
        "doing_now": "Run final parse, query-translation, duplicate, zero-hit, and recall-risk checks.",
        "allowed_now": "Fix errors, remove recall-neutral duplicates/zero-hit terms, and document remaining warnings.",
        "not_doing_yet": "Audit handoff before the final delivered query count is rerun.",
        "user_decision_needed": "none unless offer-only cleanup or recall-reducing changes need approval",
    },
    "audit-output": {
        "label": "Audit output",
        "level": "marker",
        "references": ["references/audit-template.md", "references/prisma-s-reporting.md"],
        "doing_now": "Render the audit Markdown, PRISMA-S appendix, and validated run manifest.",
        "allowed_now": "Assemble scaffold/overlay artifacts and validate the final handoff files.",
        "not_doing_yet": "Claiming PRESS peer review or non-PubMed coverage that was not performed.",
        "user_decision_needed": "none",
    },
    "peer-review-handoff": {
        "label": "Peer-review handoff",
        "level": "marker",
        "references": ["references/audit-template.md", "references/prisma-s-reporting.md"],
        "doing_now": "Hand off the draft strategy and audit for human PRESS peer review.",
        "allowed_now": "Report saved audit, appendix, manifest paths, and caveats.",
        "not_doing_yet": "Representing the strategy as final or peer-reviewed.",
        "user_decision_needed": "none",
    },
}


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


def stage_report(stage: str, *, level: str = "auto", decision_needed: str | None = None) -> dict[str, object]:
    if stage not in STAGE_REPORTS:
        raise ManifestError(f"Unknown stage {stage!r}. Choose from: {', '.join(STAGE_NAMES)}.")
    item = dict(STAGE_REPORTS[stage])
    if decision_needed is not None:
        item["user_decision_needed"] = decision_needed
    requested_level = item["level"] if level == "auto" else level
    if requested_level not in {"full", "marker"}:
        raise ManifestError("--level must be one of: auto, full, marker")
    if requested_level == "marker":
        text = f"Stage: {item['label']}. References in force: {', '.join(item['references'])}."
    else:
        text = "\n".join(
            [
                f"Stage: {item['label']}",
                f"Reference(s) in force: {', '.join(item['references'])}",
                f"Doing now: {item['doing_now']}",
                f"Allowed now: {item['allowed_now']}",
                f"Not doing yet: {item['not_doing_yet']}",
                f"User decision needed: {item['user_decision_needed']}",
            ]
        )
    return {
        "stage": stage,
        "stage_label": item["label"],
        "level": requested_level,
        "references": item["references"],
        "doing_now": item["doing_now"],
        "allowed_now": item["allowed_now"],
        "not_doing_yet": item["not_doing_yet"],
        "user_decision_needed": item["user_decision_needed"],
        "text": text,
    }


def cmd_state(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.manifest)
    action = args.state_action

    # Read-only actions never lock or write.
    if action == "banner":
        receipt = {
            "ok": True,
            "operation": "state-banner",
            "manifest_path": str(path),
        }
        receipt.update(stage_report(args.stage, level=args.level, decision_needed=args.decision_needed))
        return receipt
    if action in ("show", "check-ready"):
        data = load_manifest(path)
        state = ensure_build_state(data)
        receipt = base_receipt(f"state-{action}", path, data)
        receipt["build_state"] = state
        if action == "check-ready":
            issues = build_state_readiness(state)
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
    require_ready = getattr(args, "require_ready", False)
    if args.validate or args.check_files or require_ready:
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

    receipt = base_receipt("manifest-report", path, data)
    receipt.update(
        {
            "kind_counts": kind_counts,
            "entries_by_kind": entries_by_kind,
            "audit_path": audit_path,
            "open_decisions": open_decisions,
            "superseded": superseded,
        }
    )
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
    resolve_gate.add_argument("value", help="Resolution value, e.g. a framework or 'resolved'.")
    set_question = add_state_action("set-question", "Record the one unresolved user/protocol question.")
    set_question.add_argument("text", help="The exact pending question.")
    add_state_action("clear-question", "Clear the pending user/protocol question.")
    add_state_action("show", "Print the current build-state block (read-only).", mutating=False)
    add_state_action(
        "check-ready", "Report whether the build is ready for final handoff (read-only; exit 1 if not).", mutating=False
    )
    banner = add_state_action(
        "banner", "Print the canonical stage banner or marker text (read-only).", mutating=False
    )
    banner.add_argument("stage", help="Stage name.")
    banner.add_argument("--level", choices=["auto", "full", "marker"], default="auto")
    banner.add_argument("--decision-needed", help="Override the default User decision needed field.")

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
