"""A human can confirm an assumed oracle case without editing JSON by hand."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import review_oracle  # noqa: E402


class OracleReviewTests(unittest.TestCase):
    def test_confirming_clears_assumptions_and_enables_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oracle_cases.json"
            path.write_text(json.dumps({"prompt_sha": "x", "cases": [{
                "id": "stock_case",
                "source": "stock is 3",
                "given": {"product": {"stock_quantity": 3}},
                "when": {"action": "cancel_order"},
                "then": {"state": {"product.stock_quantity": 5}},
                "status": "assumed",
                "assumptions": ["stock starts at 3"],
                "ambiguities": [],
            }]}), encoding="utf-8")
            asked, answered = review_oracle.run_review(directory,
                                                       input_fn=lambda _p: "c",
                                                       out_fn=lambda _l: None)
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((asked, answered), (1, 1))
        case = payload["cases"][0]
        self.assertEqual(case["status"], "confirmed")
        self.assertTrue(case["human_confirmed"])
        self.assertEqual(case["assumptions"], [])


if __name__ == "__main__":
    unittest.main()
