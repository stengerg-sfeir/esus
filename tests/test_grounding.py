"""Grounding reports extras without mutating the extracted documents."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import grounding  # noqa: E402
from kernel import codegen  # noqa: E402
import generator  # noqa: E402


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
