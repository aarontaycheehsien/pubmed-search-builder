"""Guards that each canonical rule stays in its owning document, and stays linked.

``tests/rule_inventory.json`` names, for every normative rule, the one document that owns
it and the documents that must point at that owner. This test asserts:

  * presence  -- each ``assertions`` substring appears in ``canonical_owner``
  * pointers  -- each ``pointer_locations`` doc mentions the owner's filename (links, not copies)
  * guards    -- each ``guarded_by`` names a live test in the doc-contract suite

So prose can move between documents without silently dropping a normative rule, and a doc
cannot quietly stop linking the owner it delegates to.

The suite stays standard-library only, matching the skill's no-dependencies policy.
"""

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = Path(__file__).resolve().parent / "rule_inventory.json"


def load_inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def read_lower(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8").lower()


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


class CanonicalRuleTests(unittest.TestCase):
    def test_canonical_rules_hold(self):
        for rule in load_inventory()["rules"]:
            rid = rule["id"]
            with self.subTest(rule=rid, check="presence"):
                owner_text = read_lower(rule["canonical_owner"])
                for needle in rule["assertions"]:
                    self.assertIn(needle, owner_text, f"{rid}: missing in {rule['canonical_owner']}: {needle!r}")

            owner_basename = Path(rule["canonical_owner"]).name.lower()
            for pointer in rule.get("pointer_locations", []):
                with self.subTest(rule=rid, check="pointer", doc=pointer):
                    self.assertIn(owner_basename, read_lower(pointer), f"{rid}: {pointer} should link {owner_basename}")


if __name__ == "__main__":
    unittest.main()
