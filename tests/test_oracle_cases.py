"""Prompt-derived cases are validated before they can become behavior tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import cases  # noqa: E402


REQUIREMENTS = (
    "An order starts as pending. A pending order can be confirmed. "
    "Cancelling a confirmed order releases its reserved stock."
)


class OracleCaseTests(unittest.TestCase):
    def case(self, **overrides):
        value = {
            "id": "cancel_releases_stock",
            "source": "Cancelling a confirmed order releases its reserved stock.",
            "given": {"order": {"status": "confirmed"}},
            "when": {"action": "cancel_order", "args": ["order.id"]},
            "then": {"state": {"order.status": "cancelled"}},
            "status": "confirmed",
        }
        value.update(overrides)
        return value

    def test_a_valid_case_is_kept(self):
        valid, errors = cases.validate_cases([self.case()], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["id"], "cancel_releases_stock")

    def test_a_source_must_be_an_exact_prompt_span(self):
        valid, errors = cases.validate_cases(
            [self.case(source="The model invented this sentence.")],
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("source is not a prompt span", errors[0])

    def test_an_unknown_status_is_rejected(self):
        valid, errors = cases.validate_cases(
            [self.case(status="maybe")], REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("unknown status", errors[0])

    def test_opposite_outcomes_are_marked_contradictory(self):
        first = self.case()
        second = self.case(id="cancel_keeps_stock",
                           then={"state": {"order.status": "pending"}})
        valid, errors = cases.validate_cases([first, second], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual({case["status"] for case in valid},
                         {"contradictory"})
        self.assertTrue(all(case["ambiguities"] for case in valid))

    def test_assumptions_enter_the_review_queue(self):
        case = self.case(status="assumed", assumptions=["stock starts at 3"])
        valid, _errors = cases.validate_cases([case], REQUIREMENTS)
        self.assertEqual([item["id"] for item in cases.open_questions(valid)],
                         ["cancel_releases_stock"])


if __name__ == "__main__":
    unittest.main()
