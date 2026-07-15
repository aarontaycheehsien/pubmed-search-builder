"""Artifact contracts shared by legacy adapters and workflow-v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from pubmed_search_builder.core.diagnostics import Diagnostic
from pubmed_search_builder.core.io import load_json_object, sha256_file


ARTIFACT_ENVELOPE_VERSION = 2


def _required_fields(*names: str) -> Callable[[Mapping[str, Any]], list[Diagnostic]]:
    """Build a small structural validator without imposing a JSON schema dependency."""

    def validate(payload: Mapping[str, Any]) -> list[Diagnostic]:
        return [
            Diagnostic("artifact.field.missing", f"Artifact requires a non-empty {name!r} field.")
            for name in names
            if payload.get(name) in (None, "", [], {})
        ]

    return validate


def _present_fields(*names: str) -> Callable[[Mapping[str, Any]], list[Diagnostic]]:
    """Require fields that may legitimately contain zero or an empty list."""

    def validate(payload: Mapping[str, Any]) -> list[Diagnostic]:
        return [
            Diagnostic("artifact.field.missing", f"Artifact requires a {name!r} field.")
            for name in names
            if name not in payload or payload[name] is None
        ]

    return validate


@dataclass(frozen=True)
class ArtifactContract:
    artifact_type: str
    version: int = ARTIFACT_ENVELOPE_VERSION
    requires_scope_binding: bool = False
    validator: Callable[[Mapping[str, Any]], list[Diagnostic]] | None = None

    def validate(self, payload: Mapping[str, Any]) -> list[Diagnostic]:
        issues: list[Diagnostic] = []
        operation = payload.get("operation")
        hook = payload.get("hook")
        if not (
            isinstance(operation, str)
            and operation.strip()
            or isinstance(hook, str)
            and hook.strip()
        ):
            issues.append(Diagnostic("artifact.operation.missing", "Artifact has no operation."))
        ok = payload.get("ok")
        if ok is not None and not isinstance(ok, bool):
            issues.append(Diagnostic("artifact.ok.invalid", "Artifact field 'ok' must be boolean when present."))
        if self.requires_scope_binding:
            version = payload.get("scope_version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                issues.append(Diagnostic("artifact.scope_version.missing", "Artifact requires a positive scope_version."))
        if self.validator:
            issues.extend(self.validator(payload))
        return issues


@dataclass(frozen=True)
class ArtifactReference:
    role: str
    path: str
    sha256: str
    artifact_type: str
    artifact_version: int
    scope_version: int | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "role": self.role,
            "path": self.path,
            "sha256": self.sha256,
            "artifact_type": self.artifact_type,
            "artifact_version": self.artifact_version,
        }
        if self.scope_version is not None:
            result["scope_version"] = self.scope_version
        return result


CONTRACTS: dict[str, ArtifactContract] = {
    "protocol/receipt": ArtifactContract("protocol/receipt"),
    "protocol/derivative": ArtifactContract("protocol/derivative", requires_scope_binding=True),
    "concept-ledger": ArtifactContract("concept-ledger", requires_scope_binding=True),
    "candidate-ledger-template": ArtifactContract("candidate-ledger-template", requires_scope_binding=True),
    "candidate-ledger": ArtifactContract("candidate-ledger", requires_scope_binding=True),
    "block-registry": ArtifactContract("block-registry", requires_scope_binding=True),
    "critic-packet": ArtifactContract("critic-packet", requires_scope_binding=True),
    "audit-outline": ArtifactContract("audit-outline", requires_scope_binding=True),
    "discovery/evidence": ArtifactContract("discovery/evidence", requires_scope_binding=True),
    "pubmed/evidence": ArtifactContract("pubmed/evidence", requires_scope_binding=True),
    "mesh/evidence": ArtifactContract("mesh/evidence"),
    "strategy-analysis/evidence": ArtifactContract("strategy-analysis/evidence", requires_scope_binding=True),
    "qa/evidence": ArtifactContract("qa/evidence", requires_scope_binding=True),
    "registry/evidence": ArtifactContract("registry/evidence", requires_scope_binding=True),
    "review-retrieval/profile": ArtifactContract(
        "review-retrieval/profile",
        requires_scope_binding=True,
        validator=_required_fields("profile_id", "protocol_id", "eligible_types", "branches", "query", "profile_sha256"),
    ),
    "review-retrieval/sources": ArtifactContract("review-retrieval/sources"),
    "review-discovery/evidence": ArtifactContract(
        "review-discovery/evidence", requires_scope_binding=True, validator=_present_fields("profile_sha256", "topic_query", "records")
    ),
    "review-classification/evidence": ArtifactContract(
        "review-classification/evidence", requires_scope_binding=True, validator=_present_fields("profile_sha256", "records", "eligible_types")
    ),
    "review-filter/evaluation": ArtifactContract(
        "review-filter/evaluation", requires_scope_binding=True, validator=_present_fields("profile_sha256", "eligible_count", "retrieved_count")
    ),
    "prior-review-benchmark/evidence": ArtifactContract(
        "prior-review-benchmark/evidence", requires_scope_binding=True, validator=_required_fields("benchmark_kind", "source_tier_counts")
    ),
    "audit/evidence": ArtifactContract("audit/evidence", requires_scope_binding=True),
    "workflow/receipt": ArtifactContract("workflow/receipt"),
    "input/file": ArtifactContract("input/file"),
    "artifact/markdown": ArtifactContract("artifact/markdown"),
    "artifact/file": ArtifactContract("artifact/file"),
    "legacy/unknown": ArtifactContract("legacy/unknown"),
}


def artifact_type_for_operation(operation: str) -> str:
    """Map every legacy operation into a stable v2 namespace.

    New producers should write the explicit envelope.  This fallback lets old
    saved artifacts participate in v2 manifests without rewriting their bytes.
    """

    normalized = operation.strip().casefold()
    if normalized.startswith("review-retrieval-sources"):
        return "review-retrieval/sources"
    if normalized.startswith("review-retrieval-profile"):
        return "review-retrieval/profile"
    if normalized.startswith("review-discover"):
        return "review-discovery/evidence"
    if normalized.startswith("review-classif"):
        return "review-classification/evidence"
    if normalized.startswith("review-filter-eval"):
        return "review-filter/evaluation"
    if normalized.startswith("prior-review-benchmark"):
        return "prior-review-benchmark/evidence"
    if normalized.startswith("protocol-"):
        return "protocol/receipt"
    if normalized.startswith("candidate-ledger"):
        return "candidate-ledger/receipt"
    if normalized.startswith("orthogonal-pilot") or normalized.startswith("internal-convergence"):
        return "discovery/evidence"
    if normalized.startswith("registry-") or normalized == "external-pubmed-benchmark":
        return "registry/evidence"
    if normalized in {"concept-ablation", "fragility-score", "two-strand"} or normalized.startswith("screening-burden"):
        return "strategy-analysis/evidence"
    if normalized in {
        "revision-no-harm",
        "critic-artifact-validate",
        "critic-bundle-build",
        "critic-independent-run",
        "selftest",
    } or normalized.startswith("hooks-"):
        return "qa/evidence"
    if normalized.startswith("mesh-") or normalized in {"lookup", "details", "terms", "tree", "sweep", "sparql"}:
        return "mesh/evidence"
    if normalized in {"search", "fetch", "mine", "related", "study-family", "sample", "term-diff", "term-rank", "recall", "variants", "batch"}:
        return "pubmed/evidence"
    if normalized in {"audit-markdown", "audit-scaffold", "audit-workbook"}:
        return "audit/evidence"
    if normalized.startswith("workflow-"):
        return "workflow/receipt"
    if normalized.startswith("vocabulary-learning"):
        return "strategy-analysis/evidence"
    return "legacy/unknown"


def contract_for_payload(payload: Mapping[str, Any]) -> ArtifactContract:
    declared = payload.get("artifact_type")
    operation = str(payload.get("operation") or "")
    if not operation and isinstance(payload.get("hook"), str):
        operation = f"hooks-{payload['hook']}"
    artifact_type = str(declared) if isinstance(declared, str) and declared.strip() else artifact_type_for_operation(operation)
    return CONTRACTS.get(artifact_type, ArtifactContract(artifact_type=artifact_type))


def envelope(payload: Mapping[str, Any], *, producer: str, scope_version: int | None = None) -> dict[str, Any]:
    """Return an additive v2 artifact view without discarding legacy fields."""

    value = dict(payload)
    if not value.get("operation") and isinstance(value.get("hook"), str) and value["hook"].strip():
        value["operation"] = f"hooks-{value['hook']}"
    contract = contract_for_payload(value)
    value.setdefault("artifact_type", contract.artifact_type)
    value.setdefault("artifact_version", contract.version)
    value.setdefault("producer", producer)
    if scope_version is not None:
        value.setdefault("scope_version", scope_version)
    return value


def reference_from_path(role: str, path: Path, *, scope_version: int | None = None) -> tuple[ArtifactReference, list[Diagnostic]]:
    if path.suffix.casefold() != ".json":
        artifact_type = "artifact/markdown" if path.suffix.casefold() in {".md", ".markdown"} else "artifact/file"
        return (
            ArtifactReference(role, str(path), sha256_file(path), artifact_type, 1, scope_version),
            [],
        )
    payload = load_json_object(path)
    contract = contract_for_payload(payload)
    effective_scope = scope_version
    issues = contract.validate(payload)
    if effective_scope is None:
        raw_scope = payload.get("scope_version")
        if isinstance(raw_scope, int) and not isinstance(raw_scope, bool):
            effective_scope = raw_scope
    else:
        raw_scope = payload.get("scope_version")
        if isinstance(raw_scope, int) and not isinstance(raw_scope, bool) and raw_scope != effective_scope:
            issues.append(
                Diagnostic(
                    "artifact.scope_version.mismatch",
                    f"Artifact scope_version {raw_scope} does not match declared stage scope_version {effective_scope}.",
                    artifact=str(path),
                )
            )
    reference = ArtifactReference(
        role=role,
        path=str(path),
        sha256=sha256_file(path),
        artifact_type=contract.artifact_type,
        artifact_version=int(payload.get("artifact_version") or contract.version),
        scope_version=effective_scope,
    )
    return reference, issues
