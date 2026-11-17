"""Mechanical persistence mappings."""

import unittest

from kernel.extraction import mappings

DATA_MODELS = [
    {
        "name": "Category",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "name", "type": "string", "unique": True},
        ],
    },
    {
        "name": "Expense",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "category_id", "type": "int",
             "foreign_key": {"target_entity": "Category"}},
            {"name": "expense_date", "type": "date"},
            {"name": "payment_method", "type": "string"},
        ],
    },
    {
        "name": "StorageLocation",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
        ],
    },
]


class MappingTests(unittest.TestCase):
    def test_plural_snake_case_tables(self):
        self.assertEqual(mappings.table_name("Category"), "categories")
        self.assertEqual(mappings.table_name("Expense"), "expenses")
        self.assertEqual(mappings.table_name("Budget"), "budgets")
        self.assertEqual(
            mappings.table_name("StorageLocation"), "storage_locations"
        )

    def test_mappings_follow_entities_and_fields(self):
        result = mappings.entity_mappings(
            DATA_MODELS, ["Category", "Expense", "StorageLocation"])
        self.assertEqual([item["entity"] for item in result],
                         ["Category", "Expense", "StorageLocation"])
        self.assertEqual(result[0]["table"], "categories")
        self.assertEqual(result[0]["primary_key"], "id")
        self.assertEqual(result[0]["indexes"], ["name"])
        self.assertIn("category_id", result[1]["indexes"])
        self.assertIn("expense_date", result[1]["indexes"])
        self.assertIn("payment_method", result[1]["indexes"])
        self.assertEqual(result[2]["indexes"], [])

    def test_missing_model_still_produces_a_valid_mapping(self):
        result = mappings.entity_mappings([], ["Budget"])
        self.assertEqual(result, [{
            "entity": "Budget",
            "table": "budgets",
            "primary_key": "id",
            "indexes": [],
        }])


if __name__ == "__main__":
    unittest.main()
