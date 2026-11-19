"""A plural parameter is not a creation contract by itself.

The collection entity must have a foreign key to the method's owning entity
and carry payload fields. This keeps `order_items` on `place_order` while
refusing a `tags` parameter whose model proves no parent relation.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import review_contracts  # noqa: E402


class CollectionCreationTests(unittest.TestCase):
    def ctx(self):
        return {
            "entity_names": ["Order", "OrderItem", "Tag"],
            "models": [
                {"name": "Order", "fields": [
                    {"name": "id", "type": "int", "primary_key": True}]},
                {"name": "OrderItem", "fields": [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "order_id", "type": "int", "foreign_key": {
                        "target_entity": "Order", "target_field": "id"}},
                    {"name": "product_id", "type": "int"},
                    {"name": "quantity", "type": "int"}]},
                {"name": "Tag", "fields": [
                    {"name": "id", "type": "int", "primary_key": True},
                    {"name": "name", "type": "string"}]},
            ],
            "repositories": [
                {"entity": "OrderItem", "interface_name": "OrderItemRepository",
                 "methods": [{"name": "create_order_item", "params": []}]},
            ],
        }

    def method(self, params, returns="models.Order"):
        return {"name": "place_order", "params": [
            {"name": name, "type": kind} for name, kind in params],
            "return_type": returns}

    def test_a_related_collection_with_payload_is_created(self):
        create = review_contracts._collection_create(
            self.ctx(),
            self.method([("customer_id", "int"), ("order_items", "array")]),
            "OrderManagementService")
        self.assertEqual(create, {
            "class": "OrderItem",
            "call": "OrderItemRepository.create_order_item",
        })

    def test_a_plural_name_without_a_parent_relation_is_refused(self):
        self.assertIsNone(review_contracts._collection_create(
            self.ctx(),
            self.method([("order_id", "int"), ("tags", "array")]),
            "OrderService"))

    def test_a_relation_without_payload_fields_is_refused(self):
        ctx = self.ctx()
        ctx["models"][1]["fields"] = [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "order_id", "type": "int", "foreign_key": {
                "target_entity": "Order", "target_field": "id"}},
        ]
        self.assertIsNone(review_contracts._collection_create(
            ctx,
            self.method([("order_id", "int"), ("order_items", "array")]),
            "OrderService"))

    def test_an_unknown_parent_is_refused(self):
        self.assertIsNone(review_contracts._collection_create(
            self.ctx(),
            self.method([("order_items", "array")], returns=""),
            "UnknownService"))


if __name__ == "__main__":
    unittest.main()
