"""Verifier concepts are aligned before they are called defects."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import alignment  # noqa: E402


DOCS = {
    "models": [
        {"name": "Customer", "fields": [
            {"name": "customer_id", "primary_key": True},
            {"name": "name"}, {"name": "email"}, {"name": "phone_number"}]},
        {"name": "Order", "fields": [
            {"name": "order_id", "primary_key": True},
            {"name": "customer_id"}, {"name": "status"}]},
    ],
    "services": [{"service_name": "CustomerService", "methods": [
        {"name": "create_customer", "params": []}]}],
    "repos": [{"interface_name": "OrderRepository", "methods": [
        {"name": "read_all", "params": []},
        {"name": "create", "params": []}]}],
}


class EntityAlignmentTests(unittest.TestCase):
    def test_an_exact_entity_is_aligned(self):
        result = alignment.align_entity("Order", ["status"], "", "", DOCS)
        self.assertEqual(result.status, "aligned")
        self.assertEqual(result.canonical, "Order")

    def test_a_plural_is_an_alias(self):
        result = alignment.align_entity("Orders", ["status"], "", "", DOCS)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "Order")

    def test_a_different_name_with_matching_fields_is_an_alias(self):
        result = alignment.align_entity(
            "Client", ["name", "email"], "Clients have names.",
            "Clients have names.", DOCS)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "Customer")

    def test_a_prompt_named_missing_entity_is_a_coverage_gap(self):
        result = alignment.align_entity(
            "Invoice", ["total"], "Invoices have totals.",
            "Invoices have totals.", DOCS)
        self.assertEqual(result.status, "coverage_gap")

    def test_an_unmentioned_missing_entity_is_invented(self):
        result = alignment.align_entity(
            "Sale", ["amount"], "Orders have a status.",
            "Orders have a status.", DOCS)
        self.assertEqual(result.status, "invented")

    def test_equally_plausible_entities_are_ambiguous(self):
        docs = {"models": [
            {"name": "Customer", "fields": [{"name": "name"}, {"name": "email"}]},
            {"name": "User", "fields": [{"name": "name"}, {"name": "email"}]},
        ], "services": [], "repos": []}
        result = alignment.align_entity(
            "Client", ["name", "email"], "", "", docs)
        self.assertEqual(result.status, "ambiguous")

    def test_a_field_alias_can_identify_the_entity(self):
        docs = {"models": [
            {"name": "Wine", "fields": [{"name": "stock_quantity"}]},
        ], "services": [], "repos": []}
        result = alignment.align_entity(
            "Product", ["stock_qty"], "", "", docs)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "Wine")


class FieldAlignmentTests(unittest.TestCase):
    def test_an_exact_field_is_aligned(self):
        result = alignment.align_field(
            "Customer", "email", "", "", DOCS)
        self.assertEqual(result.status, "aligned")

    def test_a_phone_alias_maps_to_phone_number(self):
        result = alignment.align_field(
            "Customer", "phone", "", "", DOCS)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "phone_number")

    def test_a_prompt_named_missing_field_is_a_coverage_gap(self):
        result = alignment.align_field(
            "Order", "total", "Orders have a total.", "Orders have a total.", DOCS)
        self.assertEqual(result.status, "coverage_gap")


class ActionAlignmentTests(unittest.TestCase):
    def test_an_exact_method_is_aligned(self):
        result = alignment.align_action(
            "create_customer", "", "", DOCS)
        self.assertEqual(result.status, "aligned")

    def test_a_crud_alias_is_an_alias(self):
        result = alignment.align_action(
            "add_customer", "", "", DOCS)
        self.assertEqual(result.status, "alias")

    def test_a_prompt_named_missing_action_is_a_coverage_gap(self):
        result = alignment.align_action(
            "withdraw", "Users can withdraw money.",
            "Users can withdraw money.", DOCS)
        self.assertEqual(result.status, "coverage_gap")

    def test_an_unmentioned_missing_action_is_invented(self):
        result = alignment.align_action(
            "teleport", "Orders have a status.", "Orders have a status.", DOCS)
        self.assertEqual(result.status, "invented")

    def test_a_plural_operation_noun_maps_to_a_crud_read(self):
        docs = {
            "models": [],
            "services": [],
            "repos": [{"interface_name": "CustomerRepository", "methods": [
                {"name": "read_all"}]}],
        }
        result = alignment.align_action(
            "list_customers", "The caller specifies page number.", "", docs)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "CustomerRepository.read_all")

    def test_the_most_specific_method_name_wins(self):
        docs = {
            "models": [],
            "services": [{"service_name": "ProductRepository", "methods": [
                {"name": "create"}, {"name": "update"},
                {"name": "bulk_update_stock"}]}],
            "repos": [],
        }
        result = alignment.align_action(
            "bulk_update_product_stock", "", "", docs)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "ProductRepository.bulk_update_stock")

    def test_a_cancelled_action_matches_cancel_order(self):
        docs = {
            "models": [],
            "services": [{"service_name": "OrderService", "methods": [
                {"name": "confirm_order"}, {"name": "cancel_order"},
                {"name": "ship_order"}, {"name": "create_order"}]}],
            "repos": [],
        }
        result = alignment.align_action(
            "release_reserved_stock_on_cancelled_order", "", "", docs)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical, "OrderService.cancel_order")

    def test_domain_nouns_may_differ_when_the_operation_matches(self):
        docs = {
            "models": [],
            "services": [{"service_name": "WineInventoryService", "methods": [
                {"name": "assign_wine_to_location"},
                {"name": "check_storage_location_capacity"},
            ]}],
            "repos": [],
        }
        result = alignment.align_action(
            "assign_bottle_to_location", "", "", docs)
        self.assertEqual(result.status, "alias")
        self.assertEqual(result.canonical,
                         "WineInventoryService.assign_wine_to_location")

    def test_holder_entity_aliases_remain_ambiguous_when_equally_specific(self):
        docs = {
            "models": [],
            "services": [{"service_name": "OrderRepository", "methods": [
                {"name": "create"}]},
                {"service_name": "OrderItemRepository", "methods": [
                    {"name": "create"}]}],
            "repos": [],
        }
        result = alignment.align_action(
            "create_order", "Create an order.", "Create an order.", docs)
        self.assertEqual(result.status, "ambiguous")


if __name__ == "__main__":
    unittest.main()
