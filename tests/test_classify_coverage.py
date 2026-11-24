"""Untested clauses are classified by available verifier evidence."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import classify_coverage  # noqa: E402


class CoverageClassifierTests(unittest.TestCase):
    def test_assumed_passes_and_plan_rejections_are_separated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "prompt_x"
            project.mkdir()
            coverage = {"projects": [{"project": "prompt_x", "rows": [
                {"status": "mapped_untested", "text": "A task can be listed."},
                {"status": "mapped_untested", "text": "Users can withdraw."},
            ]}]}
            (root / "coverage.json").write_text(
                json.dumps(coverage), encoding="utf-8")
            (project / "test_intents.json").write_text(json.dumps({
                "intents": [
                    {"id": "list", "source": "A task can be listed."},
                    {"id": "withdraw", "source": "Users can withdraw."},
                ]}), encoding="utf-8")
            (project / "oracle_cases_intents.json").write_text(json.dumps({
                "cases": [{
                    "id": "list", "source": "A task can be listed.",
                    "status": "assumed",
                }]}), encoding="utf-8")
            (project / "oracle_report_intents_all.json").write_text(json.dumps({
                "results": [{"case": "list", "status": "passed"}]}),
                encoding="utf-8")
            (project / "oracle_intent_plans.json").write_text(json.dumps({
                "rejected": [{"id": "withdraw",
                              "errors": ["action 'withdraw' is coverage_gap"]}]
            }), encoding="utf-8")
            result = classify_coverage.classify(root, root / "coverage.json")
        self.assertEqual(result["counts"]["assumed_pass"], 1)
        self.assertEqual(result["counts"]["missing_action"], 1)
        self.assertEqual(result["status_counts"]["assumed_only"], 1)
        self.assertEqual(result["status_counts"]["blocked_generation"], 1)
        by_source = {row["source"]: row["category"] for row in result["rows"]}
        self.assertEqual(by_source["A task can be listed."], "assumed_pass")
        self.assertEqual(by_source["Users can withdraw."], "missing_action")


if __name__ == "__main__":
    unittest.main()
