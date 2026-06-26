"""Phase 0 refactor safety net.

Drives a single source-of-truth rule inventory (``tests/rule_inventory.json``) over the
skill's Markdown so that the Phase 1-4 deduplication can move prose between docs without
silently dropping a normative rule.

For every ``canonical`` rule the inventory asserts:
  * presence    -- each ``assertions`` substring appears in ``canonical_owner``
  * pointers    -- each ``pointer_locations`` doc mentions the owner's filename (links, not copies)
  * anti-dup    -- each ``forbidden_locations`` signature is absent outside the owner
  * cross-links -- each ``cross_links`` path appears in the named file
  * ordering    -- each ``ordering`` sequence appears in order within the named file
  * dedup meter -- a canonical signature must not have re-spread across docs

For ``duplicated-pending`` rules (Phase 1-4 targets) the test only RECORDS the duplication
that still exists; it does not fail on it. The commit that deduplicates a rule flips its
status to ``canonical`` and fills ``forbidden_locations``.

The suite stays standard-library only, matching the skill's no-dependencies policy.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path(__file__).resolve().parent / "rule_inventory.json"

# Docs scanned by the duplication meter: the loaded contract plus every reference doc.
SCANNED_DOCS = ["SKILL.md", "README.md"] + [
    str(p.relative_to(ROOT)).replace("\\", "/")
    for p in sorted((ROOT / "references").glob("*.md"))
]


def load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def read_lower(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8").lower()


def count_docs_containing(signature: str) -> list[str]:
    sig = signature.lower()
    return [doc for doc in SCANNED_DOCS if sig in read_lower(doc)]


class RuleInventoryStructureTests(unittest.TestCase):
    def test_inventory_is_well_formed(self):
        inv = load_inventory()
        self.assertIn("rules", inv)
        seen_ids: set[str] = set()
        for rule in inv["rules"]:
            rid = rule.get("id")
            self.assertTrue(rid, "every rule needs an id")
            self.assertNotIn(rid, seen_ids, f"duplicate rule id: {rid}")
            seen_ids.add(rid)
            self.assertIn(rule.get("status"), {"canonical", "duplicated-pending"}, rid)
            owner = rule.get("canonical_owner")
            self.assertTrue(owner and (ROOT / owner).exists(), f"{rid}: missing owner {owner}")
            self.assertTrue(rule.get("assertions"), f"{rid}: needs at least one assertion")

    def test_guarded_by_names_real_tests(self):
        """Every guarded_by (other than 'none') must name a live method in the doc test file."""
        source = (Path(__file__).resolve().parent / "test_concept_analysis_docs.py").read_text(encoding="utf-8")
        defined = set(re.findall(r"def (test_\w+)\(", source))
        for rule in load_inventory()["rules"]:
            guard = rule.get("guarded_by", "none")
            if guard == "none":
                continue
            self.assertIn(guard, defined, f"{rule['id']}: guarded_by names a missing test {guard!r}")

    def test_phase0_adds_coverage_for_previously_untested_clusters(self):
        """Phase 0's value-add: presence coverage for docs that had no doc-content test."""
        new_owners = {
            rule["canonical_owner"]
            for rule in load_inventory()["rules"]
            if rule.get("guarded_by") == "none"
        }
        for owner in [
            "references/wildcard-and-truncation.md",
            "references/validated-methodological-filters-and-hedges.md",
            "references/prisma-s-reporting.md",
            "references/examples.md",
        ]:
            self.assertIn(owner, new_owners, f"Phase 0 must add coverage for {owner}")


class CanonicalRuleTests(unittest.TestCase):
    def test_canonical_rules_hold(self):
        for rule in load_inventory()["rules"]:
            if rule.get("status") != "canonical":
                continue
            rid = rule["id"]
            with self.subTest(rule=rid, check="presence"):
                owner_text = read_lower(rule["canonical_owner"])
                for needle in rule["assertions"]:
                    self.assertIn(needle, owner_text, f"{rid}: missing in {rule['canonical_owner']}: {needle!r}")

            owner_basename = Path(rule["canonical_owner"]).name.lower()
            for pointer in rule.get("pointer_locations", []):
                with self.subTest(rule=rid, check="pointer", doc=pointer):
                    self.assertIn(owner_basename, read_lower(pointer), f"{rid}: {pointer} should link {owner_basename}")

            for block in rule.get("forbidden_locations", []):
                doc_text = read_lower(block["file"])
                for sig in block["signatures"]:
                    with self.subTest(rule=rid, check="anti-dup", doc=block["file"]):
                        self.assertNotIn(sig.lower(), doc_text, f"{rid}: {block['file']} must not restate {sig!r}")

            for block in rule.get("cross_links", []):
                doc_text = read_lower(block["file"])
                for path in block["must_contain"]:
                    with self.subTest(rule=rid, check="cross-link", doc=block["file"]):
                        self.assertIn(path.lower(), doc_text, f"{rid}: {block['file']} should reference {path}")

            for block in rule.get("ordering", []):
                doc_text = read_lower(block["file"])
                positions = [doc_text.find(s.lower()) for s in block["sequence"]]
                with self.subTest(rule=rid, check="ordering", doc=block["file"]):
                    self.assertNotIn(-1, positions, f"{rid}: ordering anchor missing in {block['file']}")
                    self.assertEqual(positions, sorted(positions), f"{rid}: out-of-order in {block['file']}")

    def test_canonical_signatures_have_not_respread(self):
        """A deduplicated rule must stay single-homed: its forbidden signatures live in one doc."""
        for rule in load_inventory()["rules"]:
            if rule.get("status") != "canonical":
                continue
            for block in rule.get("forbidden_locations", []):
                for sig in block["signatures"]:
                    holders = count_docs_containing(sig)
                    with self.subTest(rule=rule["id"], signature=sig):
                        self.assertLessEqual(
                            len(holders), 1,
                            f"{rule['id']}: signature {sig!r} reappeared in {holders}",
                        )


class PendingDedupTargetTests(unittest.TestCase):
    """Records (does not fail on) the duplication that Phase 1-4 will collapse."""

    def test_pending_targets_are_still_duplicated_and_tracked(self):
        pending = [r for r in load_inventory()["rules"] if r.get("status") == "duplicated-pending"]
        if not pending:
            print("\n[rule-inventory] no pending dedup targets remain; all clusters collapsed to canonical.")
            return
        report: list[str] = []
        for rule in pending:
            # The canonical owner must already state the rule (so dedup means deleting copies).
            owner_text = read_lower(rule["canonical_owner"])
            for needle in rule["assertions"]:
                self.assertIn(needle, owner_text, f"{rule['id']}: owner missing {needle!r}")
            sig = rule.get("dup_signature")
            if not sig:
                continue
            scope = rule.get("dup_scope")
            holders = (
                [d for d in count_docs_containing(sig) if d in scope] if scope
                else count_docs_containing(sig)
            )
            report.append(f"  {rule['id']}: {sig!r} currently in {len(holders)} doc(s) -> {holders}")
        if report:
            print("\n[rule-inventory] pending dedup metrics (lower is better after Phase 1-4):")
            print("\n".join(report))


if __name__ == "__main__":
    unittest.main()
