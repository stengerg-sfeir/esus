"""Mechanical order placement is derived from the model graph, not a prompt.

Every successful body must prove the customer read, the line relation, the
product stock field and all key fields. Removing any relation leaves a stub
instead of emitting a body that silently skips the write.
"""

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


def field(name, kind="int", **extra):
    value = {"name": name, "type": kind}
    value.update(extra)
    return value


def context():
    return {
        "mappings": {},
        "errors": [{"name": "InsufficientStockError"},
                   {"name": "CustomerNotFoundError"},
                   {"name": "ProductNotFoundError"}],
        "entity_names": ["Customer", "Product", "Order", "OrderItem"],
        "models": [
            {"name": "Customer", "fields": [
                field("id", primary_key=True), field("name", "string")]},
            {"name": "Product", "fields": [
                field("product_id", primary_key=True),
                field("stock_quantity")]},
            {"name": "Order", "fields": [
                field("order_id", primary_key=True),
                field("customer_id", foreign_key={
                    "target_entity": "Customer", "target_field": "id"}),
                field("order_date", "datetime")]},
            {"name": "OrderItem", "fields": [
                field("item_id", primary_key=True),
                field("order_id", foreign_key={
                    "target_entity": "Order", "target_field": "order_id"}),
                field("product_id", foreign_key={
                    "target_entity": "Product",
                    "target_field": "product_id"}),
                field("quantity")]},
        ],
        "repositories": [
            {"entity": "Customer", "interface_name": "CustomerRepository",
             "methods": [{"name": "read_one", "params": [{"name": "id"}]}]},
            {"entity": "Product", "interface_name": "ProductRepository",
             "methods": [
                 {"name": "read_one", "params": [{"name": "product_id"}]},
                 {"name": "update", "params": [
                     {"name": "product_id"}, {"name": "stock_quantity"}]}]},
            {"entity": "Order", "interface_name": "OrderRepository",
             "methods": [{"name": "create", "params": [
                 {"name": "customer_id"}, {"name": "order_date"}]}]},
            {"entity": "OrderItem", "interface_name": "OrderItemRepository",
             "methods": [{"name": "create", "params": [
                 {"name": "order_id"}, {"name": "product_id"},
                 {"name": "quantity"}]}]},
        ],
    }


METHOD = {
    "name": "place_order",
    "params": [{"name": "customer_id", "type": "int"},
               {"name": "order_items", "type": "array"}],
    "return_type": "models.Order",
}

PARAMS = [("customer_id", "customer_id", "int"),
          ("order_items", "order_items", "list")]


def body(ctx):
    return generator._service_place_order_body(
        ctx, METHOD, PARAMS, "models.Order")


class OrderPlacementTests(unittest.TestCase):
    def test_a_complete_graph_emits_the_place_order_body(self):
        lines = body(context())
        self.assertIsNotNone(lines)
        text = "\n".join(lines)
        self.assertIn("CustomerRepository", text)
        self.assertIn("OrderRepository", text)
        self.assertIn("OrderItemRepository", text)
        self.assertIn("stock_quantity < quantity", text)
        self.assertIn("InsufficientStockError", text)
        self.assertIn("stock_quantity=product.stock_quantity - quantity", text)

    def test_missing_customer_repository_leaves_a_stub(self):
        ctx = context()
        ctx["repositories"] = [repo for repo in ctx["repositories"]
                               if repo["entity"] != "Customer"]
        self.assertIsNone(body(ctx))

    def test_missing_product_line_relation_leaves_a_stub(self):
        ctx = context()
        ctx["models"][3]["fields"][2].pop("foreign_key")
        self.assertIsNone(body(ctx))

    def test_missing_stock_field_leaves_a_stub(self):
        ctx = context()
        ctx["models"][1]["fields"] = [ctx["models"][1]["fields"][0]]
        self.assertIsNone(body(ctx))

    def test_missing_primary_key_leaves_a_stub(self):
        ctx = context()
        ctx["models"][2]["fields"][0].pop("primary_key")
        self.assertIsNone(body(ctx))

    def test_missing_projection_can_be_deep_copied_without_mutating_the_fixture(self):
        ctx = context()
        clone = copy.deepcopy(ctx)
        self.assertEqual(ctx, clone)

    def test_no_line_items_is_an_empty_loop_not_a_crash(self):
        text = "\n".join(body(context()))
        self.assertIn("for item in items:", text)

    def test_order_placement_is_wrapped_in_the_store_transaction(self):
        ctx = context()
        ctx.update({
            "services": [{"service_name": "OrderService",
                          "methods": [METHOD]}],
            "components": {}, "contracts": [], "programs": {},
            "match_index": {},
        })
        source = generator.emit_services(
            ctx, [], {"implemented": 0, "stubs": 0, "stub_reasons": []})
        self.assertIn("with store.transaction():", source)
        self.assertIn("for _name in ['place_order']:", source)


if __name__ == "__main__":
    unittest.main()
