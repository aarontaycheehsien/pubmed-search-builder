#!/usr/bin/env python3
"""Custodian-held final evaluation, separate from iterative development validation.

A seal is a workflow boundary, not encryption. Keep the sealed file outside the
builder's workspace/context. The custodian attests non-exposure; hashes cannot
prove that a person or model has never seen a record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import candidate_ledger
import pubmed_tool


class FinalTestError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise FinalTestError("Expected a JSON object")
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": digest(path)}


def check_binding(value: dict[str, str]) -> Path:
    path = Path(value["path"])
    if digest(path) != value["sha256"]:
        raise FinalTestError("Frozen input changed; this evaluation cannot describe the revised build")
    return path


def write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def families(records: list[dict[str, Any]]) -> set[str]:
    return {str(row["study_family_id"]) for row in records if row.get("study_family_id")}


def seal(ledger_path: Path, protocol_path: Path, output: Path, receipt: Path,
         *, custodian: str, unseen_by_builder: bool) -> dict[str, Any]:
    if not unseen_by_builder or not custodian.strip():
        raise FinalTestError("An independent custodian must attest that these records were not exposed to the builder")
    if output.resolve() == receipt.resolve() or output.exists() or receipt.exists():
        raise FinalTestError("Seal and public receipt need distinct, unused paths")
    ledger = read(ledger_path)
    issues, summary = candidate_ledger.validate_ledger(ledger)
    records = ledger.get("records", [])
    if issues or not records or any(row.get("decision") != "include" for row in records):
        raise FinalTestError("Final test requires a valid ledger of screened-in records only")
    if summary.get("screening_provenance", {}).get("evidence_roles_without_screening_provenance"):
        raise FinalTestError("Final-test records require evidence-backed screening provenance")
    if any(row.get("use") not in candidate_ledger.EVIDENCE_USES for row in records):
        raise FinalTestError("Every final-test record must have passed evidence-role screening")
    # The supplied ledger is private custodian input, not the builder's development ledger.
    protocol = read(protocol_path)
    import protocol_tool
    protocol_issues = protocol_tool.validate_protocol(protocol, mode="lock")
    if protocol_issues:
        raise FinalTestError("Protocol must pass lock validation before sealing")
    if ledger.get("scope_version") != protocol.get("scope_version"):
        raise FinalTestError("Final-test screening scope does not match protocol")
    if {str(row["pmid"]) for row in records} & {str(row.get("pmid")) for row in protocol.get("seeds", {}).get("records", [])}:
        raise FinalTestError("Final-test PMIDs must not appear in the builder protocol seed list")
    expected = protocol_tool.canonical_sha256(protocol)
    if ledger.get("protocol_id") != protocol.get("protocol_id") or ledger.get("generated_from", {}).get("sha256") != expected:
        raise FinalTestError("Final-test ledger must be bound to the exact locked protocol")
    value = {
        "artifact_type": "final-test/sealed", "operation": "seal-final-test", "version": 1,
        "seal_id": secrets.token_hex(16), "sealed_at": now(), "custodian": custodian,
        "unseen_by_builder_attested": True, "protocol": binding(protocol_path),
        "scope_version": protocol["scope_version"], "source_ledger_sha256": digest(ledger_path),
        "records": [{"pmid": str(row["pmid"]), "study_family_id": row.get("study_family_id")} for row in records],
    }
    write_new(output, value)
    public = {
        "artifact_type": "final-test/receipt", "operation": "seal-final-test", "version": 1,
        "seal_id": value["seal_id"], "sealed_at": value["sealed_at"],
        "sealed_sha256": digest(output), "record_count": len(records),
        "scope_version": value["scope_version"], "protocol_sha256": value["protocol"]["sha256"],
        "custodian": custodian, "unseen_by_builder_attested": True,
        "status": "sealed", "independence_basis": "custodian attestation plus separation from development",
    }
    write_new(receipt, public)
    return public


def freeze(strategy: Path, protocol: Path, development_ledger: Path, receipt: Path,
           manifest: Path, output: Path) -> dict[str, Any]:
    import manifest_tool
    manifest_data = read(manifest)
    issues = manifest_tool.complete_loop_readiness(manifest_data, manifest)
    if issues:
        raise FinalTestError("Complete development, critic and QA before freezing: " + "; ".join(issues))
    public = read(receipt)
    if public.get("artifact_type") != "final-test/receipt" or public.get("status") != "sealed":
        raise FinalTestError("A sealed final-test receipt is required")
    if digest(protocol) != public.get("protocol_sha256"):
        raise FinalTestError("Protocol changed after test set was sealed; re-screen with the custodian")
    ledger = read(development_ledger)
    ledger_issues, _ = candidate_ledger.validate_ledger(ledger)
    if ledger_issues:
        raise FinalTestError("Development ledger is invalid")
    state = manifest_data.get("build_state", {})
    registered = state.get("candidate_screening", {}).get("artifact")
    if not registered or manifest_tool.resolve_artifact_path(registered, manifest).resolve() != development_ledger.resolve():
        raise FinalTestError("Freeze must use the manifest's active development ledger")
    # Ensure the named query really is the one in the successful development run.
    searches = [row for row in manifest_data.get("entries", []) if row.get("kind") == "search"]
    if not any(str(strategy.resolve()) == str(manifest_tool.resolve_artifact_path(p, manifest).resolve())
               and h == digest(strategy) for row in searches for p, h in (row.get("input_sha256") or {}).items()):
        raise FinalTestError("Frozen strategy must have a matching executed search input in the manifest")
    qa = [row for row in manifest_data.get("entries", []) if row.get("kind") == "qa" and "final-qa" in str(row.get("command", ""))]
    if not qa or not any(h == digest(strategy) and manifest_tool.resolve_artifact_path(p, manifest).resolve() == strategy.resolve()
                         for p, h in (qa[-1].get("input_sha256") or {}).items()):
        raise FinalTestError("Freeze must use the strategy from the latest final QA")
    if not strategy.read_text().strip():
        raise FinalTestError("Cannot freeze an empty strategy")
    value = {
        "artifact_type": "final-test/freeze", "operation": "freeze-final-strategy", "version": 1,
        "frozen_at": now(), "seal_id": public["seal_id"], "scope_version": public["scope_version"],
        "strategy": binding(strategy), "protocol": binding(protocol),
        "development_ledger": binding(development_ledger), "receipt": binding(receipt),
        "development_manifest": binding(manifest),
        "policy": "one evaluation; any result-informed revision requires a new untouched test set",
    }
    write_new(output, value)
    return value


def evaluate(sealed: Path, frozen: Path, output: Path, *, client=None) -> dict[str, Any]:
    if output.exists():
        raise FinalTestError("Evaluation output already exists")
    fixed = read(frozen)
    if fixed.get("artifact_type") != "final-test/freeze":
        raise FinalTestError("A frozen final strategy is required")
    paths = {key: check_binding(fixed[key]) for key in
             ("strategy", "protocol", "development_ledger", "receipt", "development_manifest")}
    public = read(paths["receipt"])
    if digest(sealed) != public.get("sealed_sha256"):
        raise FinalTestError("Sealed records changed")
    secret = read(sealed)
    if secret.get("artifact_type") != "final-test/sealed" or secret.get("seal_id") != fixed.get("seal_id"):
        raise FinalTestError("Final-test seal does not match the frozen build")
    development = read(paths["development_ledger"]).get("records", [])
    test_records = secret["records"]
    pmids = [row["pmid"] for row in test_records]
    if set(pmids) & {str(row.get("pmid")) for row in development}:
        raise FinalTestError("Final-test records overlap development exposure; independence is unavailable")
    if families(test_records) & families(development):
        raise FinalTestError("A study family crosses development and final test")
    query = paths["strategy"].read_text(encoding="utf-8-sig").strip()
    # Exclusive claim before any retrieval: failure also consumes the set conservatively.
    # This state is in the custodian's directory and must persist with the sealed file.
    used = sealed.with_name(sealed.name + ".used.json")
    claim = {"seal_id": fixed["seal_id"], "frozen_sha256": digest(frozen), "claimed_at": now(), "status": "consumed"}
    try:
        write_new(used, claim)
    except FileExistsError as exc:
        raise FinalTestError("Final test already consumed; do not retune and retest on this set") from exc
    client = client or pubmed_tool.NcbiClient()
    reachable: set[str] = set()
    retrieved: set[str] = set()
    # Save detailed requests only in the custodian directory. Public output has aggregates.
    requests = []
    try:
        for start in range(0, len(pmids), pubmed_tool.RECALL_UID_CHUNK):
            chunk = pmids[start:start + pubmed_tool.RECALL_UID_CHUNK]
            uid = " OR ".join(f"{pmid}[uid]" for pmid in chunk)
            for label, expression in (("reachable", uid), ("retrieved", f"({query}) AND ({uid})")):
                response = pubmed_tool.esearch(client, expression, len(chunk), 0, None)
                requests.append(response)
                if response.get("errors") or response.get("warnings"):
                    raise FinalTestError("Final-test retrieval returned warnings/errors; inspect private evidence")
                found = {str(p) for p in response.get("pmids", [])} & set(chunk)
                if label == "reachable":
                    reachable.update(found)
                else:
                    retrieved.update(found)
        retrieved &= reachable
        result = {
            "artifact_type": "final-test/result", "operation": "evaluate-final-test", "version": 1,
            "ok": True, "status": "evaluated", "evaluated_at": now(), "seal_id": fixed["seal_id"],
            "scope_version": fixed["scope_version"], "freeze": binding(frozen),
            "strategy": fixed["strategy"], "protocol": fixed["protocol"],
            "test_records": len(pmids), "reachable_records": len(reachable),
            "unreachable_records": len(pmids) - len(reachable), "retrieved_records": len(retrieved),
            "missed_records": len(reachable - retrieved),
            "recall": len(retrieved) / len(reachable) if reachable else None,
            "validation_stage": "sealed-final-test", "set_consumed": True,
            "independence_basis": public["independence_basis"],
            "study_family_check": "available-identifiers-only",
            "limitation": "Known-set recall, not absolute sensitivity; non-exposure is custodian-attested. Any later revision invalidates this as its final test.",
        }
        write_new(output, result)
        return result
    finally:
        write_new(sealed.with_name(sealed.name + ".evaluation-private.json"), {**claim, "requests": requests})


def verify(result_path: Path) -> dict[str, Any]:
    result = read(result_path)
    if result.get("artifact_type") != "final-test/result" or result.get("ok") is not True:
        raise FinalTestError("Not a successful final-test result")
    fixed = read(check_binding(result["freeze"]))
    for key in ("strategy", "protocol", "development_ledger", "receipt"):
        check_binding(fixed[key])
    if result.get("strategy") != fixed.get("strategy") or result.get("protocol") != fixed.get("protocol"):
        raise FinalTestError("Result does not match frozen inputs")
    return {"ok": True, "validation_stage": "sealed-final-test", "seal_id": result["seal_id"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seal", help="Custodian only: seal an unexposed, screened test ledger")
    for flag in ("candidate-ledger", "protocol", "output", "receipt", "custodian"):
        s.add_argument("--" + flag, required=True)
    s.add_argument("--unseen-by-builder", action="store_true", required=True)
    f = sub.add_parser("freeze", help="After development completion, freeze one authoritative strategy")
    for flag in ("strategy", "protocol", "development-ledger", "receipt", "manifest", "output"):
        f.add_argument("--" + flag, required=True)
    e = sub.add_parser("evaluate", help="Custodian only: evaluate once, returning aggregate results")
    for flag in ("sealed", "freeze", "output"):
        e.add_argument("--" + flag, required=True)
    v = sub.add_parser("verify", help="Reject a result whose frozen inputs changed")
    v.add_argument("result")
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            value = seal(Path(args.candidate_ledger), Path(args.protocol), Path(args.output), Path(args.receipt),
                         custodian=args.custodian, unseen_by_builder=args.unseen_by_builder)
        elif args.command == "freeze":
            value = freeze(Path(args.strategy), Path(args.protocol), Path(args.development_ledger),
                           Path(args.receipt), Path(args.manifest), Path(args.output))
        elif args.command == "evaluate":
            value = evaluate(Path(args.sealed), Path(args.freeze), Path(args.output))
        else:
            value = verify(Path(args.result))
        print(json.dumps({"ok": True, "operation": args.command, "output": getattr(args, "output", None),
                          "status": value.get("status", "complete")}))
        return 0
    except (FinalTestError, ValueError, OSError, pubmed_tool.PubMedError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
