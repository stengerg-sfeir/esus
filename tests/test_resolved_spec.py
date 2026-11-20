"""Only current, human-confirmed decisions enter the verifier prompt."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.extraction.decisions import requirements_sha  # noqa: E402
from kernel.oracle import resolved  # noqa: E402


class ResolvedSpecTests(unittest.TestCase):
    def project(self, directory):
        root = Path(directory)
        requirements = "A pending order may be cancelled."
        (root / "requirements.txt").write_text(requirements, encoding="utf-8")
        sha = requirements_sha(requirements)
        (root / "decisions.json").write_text(json.dumps({"decisions": [
            {"text": "pending may be cancelled", "chosen_pattern_id": "ALLOW",
             "decided_by": "user", "requirements_sha": sha},
            {"text": "stale", "chosen_pattern_id": "STALE",
             "decided_by": "user", "requirements_sha": "old"},
            {"text": "inferred", "chosen_pattern_id": "INFERRED",
             "decided_by": "inferred", "requirements_sha": sha},
        ]}), encoding="utf-8")
        (root / "method_contracts.json").write_text(json.dumps({
            "method_contracts": [{
                "holder": "OrderService", "method": "cancel_order",
                "decided_by": "user", "requirements_sha": sha,
                "effects": [{"target": "order.status", "op": "set",
                             "value": "'cancelled'"}]}]}), encoding="utf-8")
        return root, sha

    def test_only_current_user_decisions_are_included(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _sha = self.project(directory)
            decisions, _ = resolved.collect(root)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all("inferred" not in json.dumps(item)
                            for item in decisions))
        self.assertTrue(any(item["kind"] == "method_contract"
                            for item in decisions))

    def test_prompt_section_names_the_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _sha = self.project(directory)
            section = resolved.prompt_section(root)
        self.assertIn("CONFIRMED HUMAN DECISIONS", section)
        self.assertIn("cancel_order", section)
        self.assertIn("pending may be cancelled", section)
        self.assertNotIn("inferred", section)


if __name__ == "__main__":
    unittest.main()
