"""Test intents are structural, prompt-grounded and executor-neutral."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import intents  # noqa: E402


REQUIREMENTS = """Products have a SKU and a stock quantity.
Customers can create an order.
Orders start as pending.
Add stock to a product.
Users can withdraw money.
Run the calculator as a one-file program.
"""


def domain_intent(**overrides):
    intent = {
        "id": "add_stock",
        "source": "Add stock to a product.",
        "kind": "update",
        "entity": "Product",
        "action": "add_stock",
        "setup_entities": [
            {"alias": "product", "entity": "Product", "role": "target"},
        ],
        "setup_values": {"product.stock_qty": 5},
        "lookup": ["product.sku"],
        "args": ["product.sku", 3],
        "changes": {"product.stock_qty": 3},
        "expect": {
            "state": {"product.stock_qty": 8},
            "rows": {"Product": 1},
        },
        "status": "confirmed",
    }
    intent.update(overrides)
    return intent


class IntentValidationTests(unittest.TestCase):
    def test_a_complete_intent_is_accepted(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent()]}, REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["expect"]["state"]["product.stock_qty"], 8)
        self.assertEqual(valid[0]["setup_entities"][0]["entity"], "Product")

    def test_source_must_be_an_exact_prompt_span(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(source="Add inventory to a product.")]},
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("source is not a prompt span", errors[0])

    def test_unknown_kind_is_rejected(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(kind="browse")]}, REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("unknown kind", errors[0])

    def test_state_reference_needs_a_setup_alias(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(
                expect={"state": {"warehouse.stock_qty": 8}})]},
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("expect.state reference", errors[0])

    def test_placeholder_change_is_rejected(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(changes={"product.stock_qty": "unknown"})]},
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("is a placeholder", errors[0])

    def test_app_intent_is_accepted_without_entities(self):
        intent = {
            "id": "calculator_add",
            "source": "Run the calculator as a one-file program.",
            "kind": "app",
            "app": {"args": ["2", "+", "3"], "stdin": "", "files": {}},
            "expect": {"stdout_contains": "5", "exit_code": 0},
            "status": "assumed",
        }
        valid, errors = intents.validate_intents(
            {"intents": [intent]}, REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["kind"], "app")

    def test_app_intent_must_not_seed_entities(self):
        intent = {
            "id": "calculator_add",
            "source": "Run the calculator as a one-file program.",
            "kind": "app",
            "setup_entities": [
                {"alias": "calculator", "entity": "Calculator"},
            ],
            "app": {"args": ["2", "+", "3"]},
            "expect": {"stdout_contains": "5", "exit_code": 0},
            "status": "assumed",
        }
        valid, errors = intents.validate_intents(
            {"intents": [intent]}, REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("must not setup entities", errors[0])

    def test_observable_outcome_is_required(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(expect={})]}, REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("observable outcome", errors[0])

    def test_duplicate_ids_are_rejected(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(), domain_intent()]}, REQUIREMENTS)
        self.assertEqual(len(valid), 1)
        self.assertIn("duplicate id", errors[0])

    def test_unknown_setup_value_reference_is_rejected(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(
                setup_values={"warehouse.stock_qty": 5})]},
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("setup_values reference", errors[0])

    def test_a_sentence_error_is_not_an_exception_class(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(
                expect={"error": "withdrawal would make balance negative"})]},
            REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("exception class name", errors[0])

    def test_domain_intent_may_carry_ignored_cli_scaffolding(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(cli=["note", "create"])]},
            REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["kind"], "update")

    def test_domain_intent_may_carry_ignored_app_scaffolding(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(app={"args": ["2"]})]},
            REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["kind"], "update")

    def test_cli_intent_needs_a_command(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(kind="cli")]}, REQUIREMENTS)
        self.assertEqual(valid, [])
        self.assertIn("cli intent needs a cli command", errors[0])

    def test_cli_intent_accepts_a_command(self):
        valid, errors = intents.validate_intents(
            {"intents": [domain_intent(
                kind="cli", cli=["stock", "add", "ABC", "3"])]},
            REQUIREMENTS)
        self.assertEqual(errors, [])
        self.assertEqual(valid[0]["cli"], ["stock", "add", "ABC", "3"])


class IntentGroundingTests(unittest.TestCase):
    def test_an_error_class_from_another_clause_downgrades_to_assumed(self):
        value = domain_intent(
            source="Add stock to a product.",
            expect={"error": "AlreadyReturnedLoanError"})
        grounded = intents.ground_intents([value], REQUIREMENTS)
        self.assertEqual(grounded[0]["status"], "assumed")
        self.assertTrue(any("not stated in the target clause" in item
                            for item in grounded[0]["assumptions"]))

    def test_a_date_literal_absent_from_the_clause_downgrades_to_assumed(self):
        value = domain_intent(
            source="Add stock to a product.",
            expect={"state": {"product.stock_qty": 8,
                              "product.expires_at": "2023-10-01"}})
        grounded = intents.ground_intents([value], REQUIREMENTS)
        self.assertEqual(grounded[0]["status"], "assumed")
        self.assertTrue(any("expected date" in item
                            for item in grounded[0]["assumptions"]))

    def test_an_error_class_in_the_clause_stays_confirmed(self):
        value = domain_intent(
            source="Users can withdraw money or raise WithdrawError.",
            expect={"error": "WithdrawError"})
        grounded = intents.ground_intents([value], REQUIREMENTS)
        self.assertEqual(grounded[0]["status"], "confirmed")

    def test_an_app_with_unstated_arguments_is_assumed(self):
        value = {
            "id": "calculator",
            "source": "Run the calculator as a one-file program.",
            "kind": "app",
            "app": {"args": ["2", "+", "3"], "stdin": ""},
            "expect": {"stdout_contains": "5", "exit_code": 0},
            "status": "confirmed",
        }
        grounded = intents.ground_intents([value], REQUIREMENTS)
        self.assertEqual(grounded[0]["status"], "assumed")


if __name__ == "__main__":
    unittest.main()
