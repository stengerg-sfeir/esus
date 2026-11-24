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


if __name__ == "__main__":
    unittest.main()
