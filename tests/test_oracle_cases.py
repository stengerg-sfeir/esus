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

    def test_backticks_and_terminal_punctuation_do_not_break_the_span(self):
        valid, errors = cases.validate_cases(
            [self.case(source="Cancelling a confirmed order releases its reserved stock")],
            REQUIREMENTS)
        self.assertEqual(errors, [])

    def test_a_source_must_be_an_exact_prompt_span(self):
        valid, errors = cases.validate_cases(
            [self.case(source="The model invented this sentence.")],
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("source is not a prompt span", errors[0])

    def test_an_app_case_may_have_no_domain_setup(self):
        requirements = "The calculator prints the result."
        valid, errors = cases.validate_cases([{
            "id": "adds", "source": "The calculator prints the result.",
            "given": {},
            "when": {"app": True, "args": ["2", "+", "3"]},
            "then": {"stdout_contains": "5", "exit_code": 0},
            "status": "confirmed",
        }], requirements)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["then"]["stdout_contains"], "5")

    def test_an_unknown_status_is_rejected(self):
        valid, errors = cases.validate_cases(
            [self.case(status="maybe")], REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("unknown status", errors[0])

    def test_a_plural_entity_name_covers_its_singular_alias(self):
        requirements = "Categories group products. Products can be listed."
        valid, errors = cases.validate_cases([{
            "id": "list_products",
            "source": "Products can be listed.",
            "given": {"category": {"name": "Tools"}},
            "when": {"action": "list_products", "args": []},
            "then": {"rows": {"Product": 1}},
            "status": "confirmed",
        }], requirements)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["given"]["category"]["name"], "Tools")

    def test_a_multiword_entity_name_covers_a_compact_alias(self):
        requirements = "A storage location holds wine. Wine can be listed."
        valid, errors = cases.validate_cases([{
            "id": "list_wine",
            "source": "Wine can be listed.",
            "given": {"storagelocation": {"zone_name": "Cellar"}},
            "when": {"action": "list_wine", "args": []},
            "then": {"rows": {"Wine": 1}},
            "status": "confirmed",
        }], requirements)
        self.assertEqual(errors, [])

    def test_a_stale_contradiction_can_clear_on_revalidation(self):
        first = self.case(status="contradictory", base_status="confirmed")
        second = self.case(id="other", status="contradictory",
                           base_status="assumed",
                           when={"action": "cancel_order", "args": ["other.id"]})
        valid, _errors = cases.validate_cases([first, second], REQUIREMENTS)
        self.assertEqual({case["status"] for case in valid},
                         {"confirmed", "assumed"})

    def test_different_arguments_are_not_a_contradiction(self):
        first = self.case()
        second = self.case(id="different_amount",
                           when={"action": "cancel_order",
                                 "args": ["order.id", 0]})
        valid, errors = cases.validate_cases([first, second], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual({case["status"] for case in valid}, {"confirmed"})

    def test_assumed_alternative_is_not_promoted_to_contradiction(self):
        first = self.case()
        second = self.case(id="alternative", status="assumed",
                           base_status="assumed",
                           then={"error": "DuplicateError"})
        valid, errors = cases.validate_cases([first, second], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual({case["status"] for case in valid},
                         {"confirmed", "assumed"})

    def test_opposite_outcomes_are_marked_contradictory(self):
        first = self.case()
        second = self.case(id="cancel_keeps_stock",
                           then={"state": {"order.status": "pending"}})
        valid, errors = cases.validate_cases([first, second], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual({case["status"] for case in valid},
                         {"contradictory"})
        self.assertTrue(all(case["ambiguities"] for case in valid))

    def test_nested_given_and_placeholders_are_rejected(self):
        valid, errors = cases.validate_cases(
            [self.case(given={"order": {"products": [{"quantity": 1}]}})],
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("flat value", errors[0])
        valid, errors = cases.validate_cases(
            [self.case(given={"order": {"status": "today"}})],
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("placeholder", errors[0])

    def test_a_cli_case_is_valid(self):
        valid, errors = cases.validate_cases(
            [self.case(when={"cli": ["order", "cancel", "--id=1"]})],
            REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["when"]["cli"][0], "order")

    def test_schema_error_placeholders_are_removed(self):
        case = self.case(then={"state": {"order.status": "cancelled"},
                               "error": "ErrorName or omit"})
        valid, errors = cases.validate_cases([case], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertNotIn("error", valid[0]["then"])

    def test_an_error_class_not_named_in_the_prompt_is_assumed(self):
        case = self.case(then={"state": {"order.status": "cancelled"},
                               "error": "InvalidOrderError"})
        valid, errors = cases.validate_cases([case], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["status"], "assumed")
        self.assertIn("not named", valid[0]["ambiguities"][0])

    def test_a_free_text_error_becomes_an_assumed_case(self):
        case = self.case(then={"state": {"order.status": "cancelled"},
                               "error": "order cannot be cancelled"})
        valid, errors = cases.validate_cases([case], REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["status"], "assumed")
        self.assertNotIn("error", valid[0]["then"])

    def test_assumptions_enter_the_review_queue(self):
        case = self.case(status="assumed", assumptions=["stock starts at 3"])
        valid, _errors = cases.validate_cases([case], REQUIREMENTS)
        self.assertEqual([item["id"] for item in cases.open_questions(valid)],
                         ["cancel_releases_stock"])


if __name__ == "__main__":
    unittest.main()
