"""The components completion keeps a persisted child entity in CRUD."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import components_completion  # noqa: E402


def model(name, *fields):
    return {"name": name, "fields": list(fields)}


class CompleteTests(unittest.TestCase):
    def test_a_missing_dependent_entity_is_added(self):
        components = {
            "persistence": {"required": True},
            "crud_services": [{"entity": "Order",
                               "operations": ["create", "read_one", "read_all"]}],
        }
        components_completion.complete_crud_entities(components, [
            model("Order", {"name": "order_id", "type": "int",
                            "primary_key": True}),
            model("OrderItem",
                  {"name": "order_item_id", "type": "int",
                   "primary_key": True},
                  {"name": "order_id", "type": "int",
                   "foreign_key": {"target_entity": "Order"}}),
        ])
        self.assertEqual(
            [item["entity"] for item in components["crud_services"]],
            ["Order", "OrderItem"],
        )
        self.assertEqual(
            components["crud_services"][1]["operations"],
            ["create", "read_one", "read_all"],
        )

    def test_an_entity_without_a_foreign_key_is_not_invented(self):
        components = {"persistence": {"required": True}, "crud_services": []}
        components_completion.complete_crud_entities(components, [
            model("Report", {"name": "id", "type": "int"}),
        ])
        self.assertEqual(components["crud_services"], [])

    def test_no_persistence_means_no_completion(self):
        components = {"persistence": {"required": False}, "crud_services": []}
        components_completion.complete_crud_entities(components, [
            model("OrderItem",
                  {"name": "order_id", "type": "int",
                   "foreign_key": {"target_entity": "Order"}}),
        ])
        self.assertEqual(components["crud_services"], [])

    def test_an_entity_step_d_declared_is_untouched(self):
        components = {
            "persistence": {"required": True},
            "crud_services": [{"entity": "OrderItem",
                               "operations": ["create"]}],
        }
        components_completion.complete_crud_entities(components, [
            model("OrderItem",
                  {"name": "order_id", "type": "int",
                   "foreign_key": {"target_entity": "Order"}}),
        ])
        self.assertEqual(
            components["crud_services"],
            [{"entity": "OrderItem", "operations": ["create"]}],
        )


if __name__ == "__main__":
    unittest.main()
