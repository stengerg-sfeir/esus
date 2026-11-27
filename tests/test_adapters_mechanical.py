"""The mechanical adapter pass derives only what the documents prove."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import adapters_mechanical  # noqa: E402


def components(*leaves):
    commands = []
    for name, sub, options in leaves:
        entry = next((item for item in commands if item["name"] == name), None)
        if entry is None:
            entry = {"name": name, "options": [], "subcommands": []}
            commands.append(entry)
        if sub is None:
            entry["options"] = options
        else:
            entry["subcommands"].append({"name": sub, "options": options})
    return {"facade": {"type": "cli", "technology": "argparse",
                       "invocation": {"commands": commands}}}


def option(name, type_="str", required=True):
    return {"name": "--" + name, "short": None, "type": type_,
            "required": required, "default": None}


def services(*entries):
    return [{"service_name": name, "methods": list(methods)}
            for name, methods in entries]


def method(name, *params):
    return {"name": name, "description": "", "return_type": "None",
            "params": [{"name": param, "type": type_}
                       for param, type_ in params]}


class DeriveTests(unittest.TestCase):
    def test_a_crud_leaf_maps_its_flags_to_the_create_parameters(self):
        models = [{"name": "Book", "fields": [
            {"name": "author_id", "type": "int",
             "foreign_key": {"target_entity": "Author"}},
            {"name": "title", "type": "string"},
            {"name": "price_cents", "type": "int"},
        ]}]
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("book", "add", [option("title"), option("author"),
                                        option("price", "int")])),
            services(("BookRepository", [
                method("create", ("title", "str"), ("author_id", "int"),
                       ("price_cents", "int")),
            ])),
            models,
            "Run `library book add --title --author --price`.",
        )
        self.assertIsNone(reason)
        fields = adapters[0]["input_fields"]
        by_name = {field["field_name"]: field for field in fields}
        self.assertEqual(by_name["author"]["target_param"], "author_id")
        self.assertEqual(by_name["author"]["transform"], "LOOKUP_ID")
        self.assertEqual(by_name["author"]["lookup_entity"], "Author")
        self.assertEqual(by_name["price"]["target_param"], "price_cents")
        self.assertEqual(by_name["price"]["transform"], "DECIMAL_TO_CENTS")

    def test_a_service_wrapper_wins_over_its_repository(self):
        adapters, _ = adapters_mechanical.derive_adapters(
            components(("product", "add", [option("sku")])),
            services(("ProductRepository", [method("create", ("sku", "str"))]),
                     ("InventoryService", [method("add_product", ("sku", "str"))])),
            [{"name": "Product", "fields": [{"name": "sku", "type": "string"}]}],
            "Run `product add --sku`.",
        )
        self.assertEqual(adapters[0]["target_service"], "InventoryService")
        self.assertEqual(adapters[0]["target_method"], "add_product")

    def test_a_wrong_bound_adapter_does_not_count_as_coverage(self):
        models = [{"name": "Budget", "fields": [
            {"name": "category_id", "type": "int"},
            {"name": "month", "type": "string"}]}]
        existing = {
            "action_name": "budgetdelete",
            "target_service": "ExpenseService",
            "target_method": "delete_expense",
            "input_fields": [{
                "field_name": "category_id", "target_param": "id",
                "transform": "DIRECT", "lookup_entity": None,
                "required": True}],
        }
        adapters = adapters_mechanical.complete_missing(
            components(("budget", "delete",
                        [option("category-id", "int"), option("month")])),
            services(("BudgetRepository", [
                         method("delete", ("category_id", "int"),
                                ("month", "str"))]),
                     ("ExpenseService", [
                         method("delete_expense", ("id", "int"))])),
            models,
            [existing],
            "Run `budget delete --category-id --month`.",
        )
        targets = {(item["target_service"], item["target_method"])
                   for item in adapters}
        self.assertIn(("BudgetRepository", "delete"), targets)

    def test_a_selector_flag_reaches_the_field_it_narrows(self):
        adapters, _ = adapters_mechanical.derive_adapters(
            components(("book", "list", [option("available-only", "bool",
                                                required=False)])),
            services(("BookRepository", [
                method("read_all", ("available_copies", "int"))])),
            [{"name": "Book", "fields": [
                {"name": "available_copies", "type": "int"}]}],
            "Run `book list [--available-only]`.",
        )
        field = adapters[0]["input_fields"][0]
        self.assertEqual(field["target_param"], "available_copies")
        self.assertEqual(field["transform"], "BOOL_TO_ONE")

    def test_one_residual_flag_and_parameter_are_paired(self):
        adapters, _ = adapters_mechanical.derive_adapters(
            components(("expense", "export", [option("output")])),
            services(("ExpenseService", [
                method("export_to_csv", ("file_path", "str"))])),
            [],
            "Run `expense export --output`.",
        )
        field = adapters[0]["input_fields"][0]
        self.assertEqual(field["field_name"], "output")
        self.assertEqual(field["target_param"], "file_path")

    def test_an_unresolved_flag_declines_instead_of_guessing(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("expense", "export", [option("output")])),
            services(("ExpenseService", [
                method("export_to_csv", ("file_path", "str"),
                       ("from_date", "date"), ("to_date", "date"))])),
            [],
            "Run `expense export --output`.",
        )
        self.assertIsNone(adapters)
        self.assertIn("maps to no parameter", reason)

    def test_a_flag_reaches_the_method_that_declares_it(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("order", "search", [option("customer-id", "int")])),
            services(("CustomerService", [
                         method("search_orders_by_customer", ("customer_id", "int"))]),
                     ("SearchService", [
                         method("search_orders_by_status", ("status", "str"))])),
            [{"name": "Order", "fields": [
                {"name": "customer_id", "type": "int",
                 "foreign_key": {"target_entity": "Customer"}}]}],
            "Run `order search --customer-id`.",
        )
        self.assertIsNone(reason)
        self.assertEqual(adapters[0]["target_service"], "CustomerService")
        self.assertEqual(adapters[0]["target_method"], "search_orders_by_customer")

    def test_an_unresolved_optional_flag_is_left_to_the_surface_review(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("overdue", None, [option("overdue", "bool",
                                                 required=False)])),
            services(("LibraryService", [method("get_overdue_loans")])),
            [],
            "Run `library overdue`.",
        )
        self.assertIsNone(reason)
        self.assertEqual(adapters[0]["target_method"], "get_overdue_loans")
        self.assertEqual(adapters[0]["input_fields"], [])

    def test_an_unresolved_required_flag_declines(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("overdue", None, [option("overdue", "bool")])),
            services(("LibraryService", [method("get_overdue_loans")])),
            [],
            "Run `library overdue`.",
        )
        self.assertIsNone(adapters)
        self.assertIn("maps to no parameter", reason)

    def test_a_tied_method_declines(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("report", None, [])),
            services(("ReportService", [method("build_report")]),
                     ("OtherService", [method("summary_report")])),
            [],
            "Run `system report`.",
        )
        self.assertIsNone(adapters)
        self.assertIn("ambiguous methods", reason)

    def test_prose_without_command_lines_declines(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("search", None, [])),
            services(("SearchService", [method("search")])),
            [],
            "Search orders by customer.",
        )
        self.assertIsNone(adapters)
        self.assertEqual(reason, "no explicit command lines")

    def test_a_prose_surface_can_still_get_mechanical_fields(self):
        adapters, reason = adapters_mechanical.derive_adapters(
            components(("order", "confirm", [option("order-id", "int")])),
            services(("OrderService", [
                method("confirm_order", ("order_id", "int"))])),
            [{"name": "Order", "fields": [{"name": "order_id", "type": "int"}]}],
            "Confirming an order reserves stock.",
            allow_prose=True,
        )
        self.assertIsNone(reason)
        self.assertEqual(adapters[0]["target_method"], "confirm_order")
        self.assertEqual(adapters[0]["input_fields"][0]["target_param"], "order_id")


if __name__ == "__main__":
    unittest.main()
