"""Schema invariants come from the model, rules from the model only when needed.

Step C used to ask the small model for field facts already present in
`data_models.json`. These tests pin the mechanical set and the merge that keeps
the model's rules without duplicating a schema line.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import schema_invariants  # noqa: E402


DOCUMENTS = {
    "data_models": [{
        "name": "Budget",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True,
             "nullable": False, "unique": True},
            {"name": "category_id", "type": "int", "nullable": False,
             "foreign_key": {"target_entity": "Category",
                             "target_field": "id"}},
            {"name": "month", "type": "string", "nullable": False},
            {"name": "amount_limit_cents", "type": "int", "nullable": False},
            {"name": "note", "type": "string", "nullable": True},
        ],
    }],
}

REQUIREMENTS = (
    "A budget is unique for a category and month: "
    "UNIQUE(category_id, month). amount_limit_cents must be non-negative."
)


class SchemaInvariantTests(unittest.TestCase):
    def test_field_facts_are_rendered_once(self):
        entries = schema_invariants.schema_invariants(DOCUMENTS, REQUIREMENTS)
        texts = [entry["text"] for entry in entries]
        self.assertIn(
            "Budget.id must be an auto-incremented integer primary key "
            "with default value None", texts)
        self.assertIn("Budget.category_id must reference an existing Category.id",
                      texts)
        self.assertIn("Budget.month must not be null", texts)
        self.assertIn("Budget.note must be a string", texts)
        self.assertNotIn("Budget.note must not be null", texts)
        self.assertTrue(all(entry["kind"] == "schema" for entry in entries))
        self.assertEqual(len(texts), len(set(texts)))

    def test_composite_unique_and_numeric_bound_are_read_from_requirements(self):
        entries = schema_invariants.schema_invariants(DOCUMENTS, REQUIREMENTS)
        texts = [entry["text"] for entry in entries]
        self.assertIn(
            "Budget must have a unique constraint on (category_id, month)", texts)
        self.assertIn("Budget.amount_limit_cents must be non-negative", texts)

    def test_a_negated_positive_bound_is_not_inverted(self):
        self.assertIsNone(schema_invariants._numeric_bound(
            "Product", "price", "price must not be positive"))
        self.assertEqual(
            schema_invariants._numeric_bound(
                "Product", "price", "price must be positive"),
            ("positive", "1"))

    def test_a_slash_vocabulary_becomes_a_schema_invariant(self):
        documents = {"data_models": [{"name": "Expense", "fields": [
            {"name": "payment_method", "type": "string", "nullable": False}]}]}
        entries = schema_invariants.schema_invariants(
            documents, "payment_method (cash/card/transfer)")
        self.assertIn(
            "Expense.payment_method must be one of 'cash', 'card', 'transfer'",
            [entry["text"] for entry in entries])

    def test_merge_puts_schema_first_and_drops_exact_duplicates(self):
        schema = [{"text": "Budget.month must not be null", "kind": "schema"}]
        merged = schema_invariants.merge_invariants(schema, [
            {"text": "Budget.month must not be null", "kind": "rule"},
            {"text": "A budget may not exceed its limit", "kind": "rule"},
        ])
        self.assertEqual([item["kind"] for item in merged],
                         ["schema", "rule"])
        self.assertEqual(merged[0]["text"], "Budget.month must not be null")


if __name__ == "__main__":
    unittest.main()
