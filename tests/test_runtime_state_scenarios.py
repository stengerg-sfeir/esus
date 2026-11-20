"""Runtime contract checks derive state and invalid-precondition fixtures."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "runtime"))

import worker  # noqa: E402


DOCS = {
    "invariants": [{"text": "Order.status must be one of 'pending', "
                            "'confirmed', 'shipped', 'cancelled'"}],
    "requirements": "",
}


class StateStartTests(unittest.TestCase):
    def test_description_names_the_valid_starting_state(self):
        method = {"description": "Cancels a confirmed order."}
        self.assertEqual(
            worker._state_start_value(DOCS, "Order", "status", "cancelled", method),
            "confirmed")

    def test_an_alternative_documented_state_is_used_without_a_description(self):
        self.assertEqual(
            worker._state_start_value(DOCS, "Order", "status", "pending", {}),
            "confirmed")

    def test_no_documented_vocabulary_returns_none(self):
        self.assertIsNone(worker._state_start_value(
            {"invariants": []}, "Order", "status", "cancelled", {}))


class ReferenceResolutionTests(unittest.TestCase):
    def test_a_flat_alias_id_reference_resolves_to_its_pk(self):
        refs = {"order": {"order_id": 7}, "order.id": 7}
        self.assertEqual(worker._resolve({"ref": "order.id"}, refs), 7)


class FieldNameTests(unittest.TestCase):
    def test_state_and_status_are_the_same_fixture_field(self):
        model = {"fields": [{"name": "status", "type": "string"}]}
        self.assertEqual(worker._model_field_name(model, "state"), "status")
        self.assertEqual(worker._model_field_name(model, "status"), "status")


class InvalidPreconditionTests(unittest.TestCase):
    def test_equality_flips_according_to_raise_when(self):
        self.assertEqual(
            worker._invalid_precondition("order.status == 'confirmed'", "false"),
            ("order", "status", "not-confirmed"))
        self.assertEqual(
            worker._invalid_precondition("order.status == 'returned'", "true"),
            ("order", "status", "returned"))

    def test_nullability_and_ranges_have_an_invalid_value(self):
        self.assertEqual(
            worker._invalid_precondition("loan.return_date is not None", "true"),
            ("loan", "return_date", worker._NON_NULL))
        value = worker._invalid_precondition(
            "book.available_copies > 0", "false")
        self.assertEqual(value[:2], ("book", "available_copies"))
        self.assertEqual(value[2], 0)

    def test_valid_numeric_precondition_values_satisfy_the_comparison(self):
        contract = {"preconditions": [{
            "check": "book.available_copies > 0", "raise_when": "false"}]}
        values = worker._precondition_values(contract, "book")
        self.assertEqual(values["available_copies"], 1)

    def test_membership_uses_a_value_outside_the_documented_set(self):
        value = worker._invalid_precondition(
            "loan.status in ('active', 'returned')", "true")
        self.assertEqual(value[:2], ("loan", "status"))
        self.assertEqual(value[2], "__not_documented__")

    def test_prose_conditions_are_left_alone(self):
        self.assertIsNone(worker._invalid_precondition("user exists", "false"))


if __name__ == "__main__":
    unittest.main()
