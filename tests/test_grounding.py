"""Grounding reports extras without mutating the extracted documents."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import grounding  # noqa: E402
from kernel import codegen  # noqa: E402
import generator  # noqa: E402
import review_grounding  # noqa: E402


def service(name, *methods):
    return {"service_name": name, "methods": [
        {"name": method, "description": method,
         "params": [], "return_type": "None"} for method in methods
    ]}


class GroundingReportTests(unittest.TestCase):
    def test_an_export_service_is_reported_and_suggested_for_drop(self):
        services = [service("ExportService", "export_orders_to_csv",
                            "export_product_stock_to_csv")]
        report = grounding.report(
            "Customers can search orders and invoices.",
            ["Enable customers to search their orders and invoices"],
            services)
        self.assertEqual(
            [(item["holder"], item["method"]) for item in report["extra_methods"]],
            [("ExportService", "export_orders_to_csv"),
             ("ExportService", "export_product_stock_to_csv")])
        self.assertEqual(report["suggested_decisions"]["drop_services"],
                         ["ExportService"])
        self.assertEqual(report["suggested_decisions"]["drop_command_verbs"],
                         ["export"])

    def test_state_transitions_named_by_intentions_are_grounded(self):
        report = grounding.report(
            "Confirming reserves stock; cancelling releases it.",
            ["Reserve stock when confirming an order",
             "Release stock when cancelling a confirmed order"],
            [service("OrderService", "confirm_order", "cancel_order")])
        self.assertEqual(report["extra_methods"], [])
        self.assertEqual(report["missing_capabilities"], [])

    def test_a_standard_read_wrapper_is_exempt(self):
        report = grounding.report(
            "Customers place orders.",
            ["Allow customers to place orders"],
            [service("CustomerService", "read_customer_by_id")])
        self.assertEqual(report["extra_methods"], [])

    def test_missing_state_transition_is_reported(self):
        report = grounding.report(
            "Order status is tracked.",
            ["Reserve stock when confirming an order"],
            [service("OrderService", "update_order_status")])
        self.assertEqual(
            [item["expected"] for item in report["missing_capabilities"]],
            ["confirm"])


class AmbiguousAggregateTests(unittest.TestCase):
    def test_a_grouped_value_map_without_coverage_wording_is_reported(self):
        report = grounding.report(
            "Aggregate stock value by category.",
            ["Aggregate stock value by category"],
            [{"service_name": "InventoryService", "methods": [{
                "name": "stock_value_by_category",
                "description": "Returns a dictionary mapping each category "
                               "to the total value of products.",
                "params": [], "return_type": "dict[int: int]"}]}])
        self.assertEqual(
            [item["method"] for item in report["ambiguous_aggregate_groups"]],
            ["stock_value_by_category"])

    def test_explicit_each_category_wording_resolves_the_question(self):
        report = grounding.report(
            "Return the stock value for each category, including empty ones.",
            ["Return stock value for each category"],
            [{"service_name": "InventoryService", "methods": [{
                "name": "stock_value_by_category",
                "description": "Returns a dictionary mapping each category "
                               "to the total value of products.",
                "params": [], "return_type": "dict[int: int]"}]}])
        self.assertEqual(report["ambiguous_aggregate_groups"], [])

    def test_a_non_grouped_summary_is_not_flagged(self):
        report = grounding.report(
            "Summarize storage locations.",
            ["Summarize storage locations"],
            [{"service_name": "WineService", "methods": [{
                "name": "get_storage_location_summary",
                "description": "Returns a summary of all locations.",
                "params": [], "return_type": "dict[str, object]"}]}])
        self.assertEqual(report["ambiguous_aggregate_groups"], [])


class AggregateDecisionTests(unittest.TestCase):
    def test_repository_and_service_returns_use_the_reviewed_coverage(self):
        files = {
            "repositories.py": (
                "class ProductRepository:\n"
                "    def total(self):\n"
                "        result = {}\n"
                "        return result\n"
            ),
            "services.py": (
                "class InventoryService:\n"
                "    def total(self):\n"
                "        result = {}\n"
                "        return result\n"
            ),
        }
        decisions = [
            {"holder": "ProductRepository", "method": "total",
             "layer": "repository", "include_empty_groups": True,
             "parent_entity": "Category", "key_field": "id"},
            {"holder": "InventoryService", "method": "total",
             "layer": "service", "include_empty_groups": True,
             "parent_entity": "Category", "key_field": "id"},
        ]
        result, applied = generator.apply_aggregate_decisions(files, decisions)
        self.assertEqual(sorted(applied),
                         ["InventoryService.total", "ProductRepository.total"])
        self.assertIn("self._store.select('Category', [])",
                      result["repositories.py"])
        self.assertIn("self._repos['CategoryRepository'].read_all()",
                      result["services.py"])
        self.assertIn("def _include_empty_groups", result["repositories.py"])
        self.assertIn("def _include_empty_groups", result["services.py"])
        result, _applied = generator.apply_aggregate_decisions(result, decisions)
        self.assertEqual(
            result["repositories.py"].count("return _include_empty_groups("), 1)
        self.assertEqual(
            result["services.py"].count("return _include_empty_groups("), 1)
        compile(result["repositories.py"], "repositories.py", "exec")
        compile(result["services.py"], "services.py", "exec")


class ReviewGroundingTests(unittest.TestCase):
    def test_review_writes_drop_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "requirements.txt").write_text(
                "Customers can search orders and invoices.", encoding="utf-8")
            (out / "intentions.json").write_text(json.dumps({
                "intentions": ["Search orders and invoices"]}), encoding="utf-8")
            (out / "data_models.json").write_text(json.dumps({
                "data_models": []}), encoding="utf-8")
            (out / "service_contracts.json").write_text(json.dumps({
                "service_contracts": [
                    {"service_name": "ExportService", "methods": [
                        {"name": "export_orders_to_csv", "params": [],
                         "return_type": "None"}]}]}), encoding="utf-8")
            asked, answered = review_grounding.run_review(
                str(out), ask=lambda _prompt, _default: True,
                out_fn=lambda _line: None)
            self.assertEqual((asked, answered), (1, 1))
            data = json.loads(
                (out / "grounding_decisions.json").read_text(encoding="utf-8"))
            self.assertEqual(data["drop_services"], ["ExportService"])
            self.assertEqual(data["drop_command_verbs"], ["export"])


class RelatedPrimaryKeyRepairTests(unittest.TestCase):
    def test_a_related_lookup_does_not_reuse_the_current_repository_pk(self):
        ctx = {"mappings": {}, "models": [
            {"name": "Product", "fields": [
                {"name": "product_id", "type": "int", "primary_key": True}]},
            {"name": "Category", "fields": [
                {"name": "category_id", "type": "int", "primary_key": True}]},
        ]}
        files = {"repositories.py": (
            "class ProductRepository:\n"
            "    def find(self):\n"
            "        return self._store.get('Category', self.PK, 1)\n")}
        result, repaired = generator.repair_related_primary_keys(files, ctx)
        self.assertEqual(repaired, ["Category.category_id"])
        self.assertIn("'Category', 'category_id'", result["repositories.py"])
        self.assertNotIn("self.PK", result["repositories.py"])


class GroundingDecisionTests(unittest.TestCase):
    def test_decisions_drop_the_service_its_adapters_and_export_verb(self):
        services = [service("ExportService", "export_orders_to_csv"),
                    service("OrderService", "confirm_order")]
        adapters = [
            {"action_name": "export", "target_service": "ExportService",
             "target_method": "export_orders_to_csv"},
            {"action_name": "confirm", "target_service": "OrderService",
             "target_method": "confirm_order"},
        ]
        components = {"facade": {"invocation": {"commands": [
            {"name": "Order", "subcommands": [
                {"name": "confirm"}, {"name": "export"}]},
            {"name": "Product", "subcommands": [{"name": "export"}]},
        ]}}}
        routes = [{"kind": "route", "service": "ExportService",
                   "method": "export_orders_to_csv"}]
        result = generator.apply_grounding_decisions(
            services, adapters, components, routes, {
                "drop_services": ["ExportService"],
                "drop_command_verbs": ["export"],
            })
        kept_services, kept_adapters, kept_components, kept_routes = result
        self.assertEqual([item["service_name"] for item in kept_services],
                         ["OrderService"])
        self.assertEqual([item["action_name"] for item in kept_adapters],
                         ["confirm"])
        commands = kept_components["facade"]["invocation"]["commands"]
        self.assertEqual([(item["name"],
                           [sub["name"] for sub in item["subcommands"]])
                          for item in commands],
                         [("Order", ["confirm"]), ("Product", [])])
        self.assertEqual(kept_routes, [])
        self.assertIsNone(codegen.classify_crud("export_orders_to_csv"))


if __name__ == "__main__":
    unittest.main()
