"""Oracle findings are grouped by cause, not by project order."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import summarize_oracle  # noqa: E402


class OracleSummaryTests(unittest.TestCase):
    def report(self):
        return {"results": [{"prompt": "prompt_x", "results": [
            {"case": "a", "status": "passed"},
            {"case": "b", "status": "failed",
             "reason": "raised CustomerNotFoundError: missing"},
            {"case": "c", "status": "failed",
             "reason": "expected InvalidAgeError, no error was raised"},
            {"case": "d", "status": "unbound",
             "reason": "no generated method matches 'sell_product'"},
            {"case": "e", "status": "unbound",
             "reason": "ambiguous action binding: A.x, B.x"},
        ]}]}

    def test_categories_are_separated(self):
        counts, groups = summarize_oracle.summarize(self.report())
        self.assertEqual(counts["passed"], 1)
        self.assertEqual(counts["case_defect: setup"], 1)
        self.assertEqual(counts["behavior: expected error missing"], 1)
        self.assertEqual(counts["coverage_gap: missing action"], 1)
        self.assertEqual(counts["coverage_gap: ambiguous action"], 1)

    def test_markdown_names_each_finding(self):
        text = summarize_oracle.markdown(self.report())
        self.assertIn("prompt_x", text)
        self.assertIn("case_defect: setup", text)
        self.assertIn("sell_product", text)


if __name__ == "__main__":
    unittest.main()
