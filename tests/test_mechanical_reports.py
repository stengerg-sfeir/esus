"""Mechanical repository joins and service reports."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generator  # noqa: E402


def model(name, *fields):
    return {"name": name, "fields": list(fields)}


def field(name, type_, **extra):
    return {"name": name, "type": type_, **extra}


def repo(entity, methods):
    return {"entity": entity, "interface_name": f"{entity}Repository",
            "methods": methods}


def method(name, params, returns, description=""):
    return {"name": name, "description": description, "return_type": returns,
            "params": [{"name": p, "type": t} for p, t in params]}


def ctx():
    return {
        "entity_names": ["Customer", "Order", "Invoice", "Category", "Product"],
        "models": [
            model("Customer", field("customer_id", "int", primary_key=True),
                  field("name", "string")),
            model("Order", field("order_id", "int", primary_key=True),
                  field("customer_id", "int",
                        foreign_key={"target_entity": "Customer",
                                     "target_field": "customer_id"}),
                  field("status", "string")),
            model("Invoice", field("invoice_id", "int", primary_key=True),
                  field("order_id", "int",
                        foreign_key={"target_entity": "Order",
                                     "target_field": "order_id"})),
            model("Category", field("category_id", "int", primary_key=True),
                  field("name", "string"),
                  field("reorder_threshold", "int")),
            model("Product", field("product_id", "int", primary_key=True),
                  field("name", "string"),
                  field("category_id", "int",
                        foreign_key={"target_entity": "Category",
                                     "target_field": "category_id"}),
                  field("price", "decimal"),
                  field("stock_quantity", "int")),
        ],
        "repositories": [
            repo("Customer", [method("read_all", [], "list[Customer]")]),
            repo("Order", [method("read_all", [], "list[Order]")]),
            repo("Invoice", [method("read_all", [], "list[Invoice]")]),
            repo("Category", [method("read_all", [], "list[Category]")]),
            repo("Product", [method("read_all", [], "list[Product]"),
                             method("create", [("name", "str")], "Product")]),
        ],
        "mappings": {},
        "errors": [{"name": "CustomerNotFoundError"},
                   {"name": "CategoryNotFoundError"}],
        "invariants": [],
        "requirements": "Orders can be pending, confirmed, shipped or cancelled.",
    }


class RepositoryJoinTests(unittest.TestCase):
    def test_two_hop_filter_walks_customer_order_invoice(self):
        body = generator._repo_two_hop_filter_body(
            ctx(), "Customer", "models.Customer",
            method("find_invoices_by_customer_id",
                   [("customer_id", "int")], "list[Invoice]"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("self._store.select('Order'", text)
        self.assertIn("self._store.select('Invoice'", text)
        self.assertIn("middle_ids", text)

    def test_relation_lookup_reads_parent_then_product(self):
        body = generator._repo_relation_lookup_body(
            ctx(), "Product", "models.Product",
            method("get_product_by_category_and_name",
                   [("category_name", "str"), ("product_name", "str")],
                   "Product | None"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("self._store.select('Category'", text)
        self.assertIn("parent_rows[0]['category_id']", text)
        self.assertIn("criteria.append(('name', 'eq', product_name))", text)

    def test_relation_lookup_never_replaces_create(self):
        self.assertIsNone(generator._repo_relation_lookup_body(
            ctx(), "Product", "models.Product",
            method("create", [("category_id", "int")], "Product")))


class ReportTests(unittest.TestCase):
    def test_count_report_uses_the_documented_status_vocabulary(self):
        body = generator._service_count_report_body(
            ctx(), method("get_order_status_report", [], "dict[str, int]"), [],
            "dict[str, int]")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("'pending': 0", text)
        self.assertIn("OrderRepository", text)

    def test_stock_report_carries_every_field_and_the_category_name(self):
        body = generator._service_stock_report_body(
            ctx(), method("get_product_stock_report", [], "list[dict]"), [],
            "list[dict]")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("'category_name'", text)
        self.assertIn("'stock_quantity'", text)


class InventoryMechanicalTests(unittest.TestCase):
    def ctx(self):
        data = ctx()
        data["repositories"] = [
            repo("Category", [method("read_all", [], "list[Category]")]),
            repo("Product", [method("read_all", [], "list[Product]"),
                             method("update", [("id", "int"), ("name", "str"),
                                               ("price_cents", "int")],
                                    "Product")]),
        ]
        return data

    def test_low_stock_repository_scan_uses_the_category_threshold(self):
        body = generator._repo_low_stock_body(
            self.ctx(), "Product", "models.Product",
            method("find_low_stock_products", [], "list[Product]"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("thresholds", text)
        self.assertIn("stock_quantity", text)
        self.assertIn("_model_list", text)

    def test_stock_value_starts_every_category_at_zero(self):
        body = generator._repo_stock_value_body(
            self.ctx(), "Product", "models.Product",
            method("aggregate_stock_value_by_category", [], "dict[int, int]"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn(": 0 for row in parents", text)
        self.assertIn("price", text)
        self.assertIn("stock_quantity", text)

    def test_mapping_update_expands_only_declared_repository_parameters(self):
        body = generator._service_mapping_update_body(
            self.ctx(), "InventoryService",
            method("update_product", [("id", "int"), ("data", "dict")], "None"),
            [("id", "id", "int"), ("data", "data", "dict")])
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("data.get('name')", text)
        self.assertIn("data.get('price_cents')", text)


class ExpenseAggregateTests(unittest.TestCase):
    def ctx(self):
        data = ctx()
        data["entity_names"] += ["Expense", "Budget"]
        data["models"] += [
            model("Expense", field("id", "int", primary_key=True),
                  field("amount_cents", "int"),
                  field("expense_date", "date"),
                  field("category_id", "int",
                        foreign_key={"target_entity": "Category",
                                     "target_field": "category_id"}),
                  field("is_recurring", "boolean")),
            model("Budget", field("id", "int", primary_key=True),
                  field("category_id", "int",
                        foreign_key={"target_entity": "Category",
                                     "target_field": "category_id"}),
                  field("month", "string"),
                  field("amount_limit_cents", "int")),
        ]
        data["repositories"] += [
            repo("Expense", [method("read_all", [], "list[Expense]"),
                             method("update", [("id", "int"),
                                               ("is_recurring", "bool")],
                                    "Expense"),
                             method("get_monthly_spending_by_category",
                                    [("month", "str")], "dict[int, int]"),
                             method("get_yearly_spending_summary",
                                    [("year", "int")], "dict[str, int]"),
                             method("get_top_spending_categories",
                                    [("start_date", "date"), ("end_date", "date")],
                                    "list[tuple]"),
                             method("get_budget_status_for_category",
                                    [("category_id", "int"), ("month", "str")],
                                    "str")]),
            repo("Budget", [method("read_all", [], "list[Budget]")]),
        ]
        return data

    def test_monthly_spending_groups_by_category_and_month(self):
        body = generator._repo_period_sum_body(
            self.ctx(), "Expense",
            method("get_monthly_spending_by_category", [("month", "str")],
                   "dict[int, int]"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("startswith(str(month))", text)
        self.assertIn("category_id", text)

    def test_yearly_summary_groups_by_month(self):
        body = generator._repo_period_sum_body(
            self.ctx(), "Expense",
            method("get_yearly_spending_summary", [("year", "int")],
                   "dict[str, int]"))
        self.assertIsNotNone(body)
        self.assertIn("date[:7]", "\n".join(body))

    def test_top_categories_sorts_by_total(self):
        body = generator._repo_top_categories_body(
            self.ctx(), "Expense",
            method("get_top_spending_categories",
                   [("start_date", "date"), ("end_date", "date")],
                   "list[tuple]"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("sorted(", text)
        self.assertIn("names", text)


class LibraryGuiMechanicalTests(unittest.TestCase):
    def ctx(self):
        data = ctx()
        data["entity_names"] += ["Wine", "Loan", "StorageLocation"]
        data["models"] += [
            model("Wine", field("id", "int", primary_key=True),
                  field("name", "string"),
                  field("wine_type", "string"),
                  field("country_of_origin", "string"),
                  field("cost_price", "decimal"),
                  field("selling_price", "decimal"),
                  field("stock_quantity", "int"),
                  field("storage_location_id", "int",
                        foreign_key={"target_entity": "StorageLocation",
                                     "target_field": "id"})),
            model("Loan", field("id", "int", primary_key=True),
                  field("due_date", "date"),
                  field("return_date", "date"),
                  field("status", "string")),
            model("StorageLocation", field("id", "int", primary_key=True),
                  field("maximum_capacity", "int")),
        ]
        data["errors"] += [{"name": "NegativeStockError"},
                           {"name": "InvalidPricingException"},
                           {"name": "StorageLocationNotFoundError"}]
        data["repositories"] += [
            repo("Wine", [method("read_all", [("wine_type", "str")],
                                 "list[Wine]"),
                          method("search_by_name", [("query", "str")],
                                 "list[Wine]")]),
            repo("Loan", [method("read_all", [], "list[Loan]")]),
            repo("StorageLocation", [method("read_one", [("id", "int")],
                                           "StorageLocation")]),
        ]
        return data

    def test_count_by_type(self):
        body = generator._repo_count_by_field_body(
            self.ctx(), "Wine", method("get_wine_count_by_type", [],
                                       "dict[str, int]"))
        self.assertIsNotNone(body)
        self.assertIn("wine_type", "\n".join(body))

    def test_contained_name_filter(self):
        body = generator._repo_containment_filter_body(
            self.ctx(), "Wine", "models.Wine",
            method("get_wines_by_origin_country", [("country", "str")],
                   "list[Wine]"))
        self.assertIsNotNone(body)
        self.assertIn("country_of_origin", "\n".join(body))

    def test_plain_list_filter_delegates_to_read_all(self):
        body = generator._service_plain_list_filter_body(
            self.ctx(), method("list_wines_by_type", [("wine_type", "str")],
                               "list"),
            [("wine_type", "wine_type", "str")], "Any")
        self.assertIsNotNone(body)
        self.assertIn("read_all(wine_type=wine_type)", "\n".join(body))

    def test_search_delegate(self):
        body = generator._service_search_delegate_body(
            self.ctx(), method("search_wines_by_name", [("query", "str")],
                               "list[Wine]"),
            [("query", "query", "str")], "list[Wine]")
        self.assertIsNotNone(body)
        self.assertIn("search_by_name(query)", "\n".join(body))

    def test_notification_side_effect_is_logged(self):
        body = generator._service_notification_body(
            method("send_notification", [("recipient", "str"),
                                         ("message", "str")], "None",
                   description="Log a notification instead of sending it."),
            [("recipient", "recipient", "str"),
             ("message", "message", "str")], "None")
        self.assertIsNotNone(body)
        self.assertIn("Notification to", "\n".join(body))
        self.assertIn("print(message)", body)

    def test_capacity_guard_uses_child_stock_and_parent_capacity(self):
        body = generator._service_capacity_guard_body(
            self.ctx(), "WineInventoryService",
            method("check_storage_location_capacity",
                   [("location_id", "str"), ("wine_id", "int")], "bool",
                   description="Check storage location capacity."),
            [("location_id", "location_id", "str"),
             ("wine_id", "wine_id", "int")], "bool")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("maximum_capacity", text)
        self.assertIn("stock_quantity", text)
        self.assertIn("capacity exceeded", text)

    def test_negative_stock_guard(self):
        body = generator._service_negative_stock_body(
            self.ctx(), "WineInventoryService",
            method("update_wine_stock", [("wine_id", "str"),
                                         ("new_stock_quantity", "int")],
                   "bool", description="Ensures the new stock level is non-negative."),
            [("wine_id", "wine_id", "str"),
             ("new_stock_quantity", "new_stock_quantity", "int")], "bool")
        self.assertIsNotNone(body)
        self.assertIn("NegativeStockError", "\n".join(body))

    def test_price_guard_reads_the_comparison_from_the_description(self):
        body = generator._service_price_guard_body(
            self.ctx(), "WineInventoryService",
            method("validate_wine_pricing", [("cost_price", "float"),
                                             ("selling_price", "float")],
                   "bool", description="Selling price is strictly greater than cost price."),
            [("cost_price", "cost_price", "float"),
             ("selling_price", "selling_price", "float")], "bool")
        self.assertIsNotNone(body)
        self.assertIn("selling_price > cost_price", "\n".join(body))

    def test_a_negated_price_comparison_keeps_its_negation(self):
        body = generator._service_price_guard_body(
            self.ctx(), "WineInventoryService",
            method("validate_wine_pricing", [("cost_price", "float"),
                                             ("selling_price", "float")],
                   "bool", description="Selling price must not be greater than cost price."),
            [("cost_price", "cost_price", "float"),
             ("selling_price", "selling_price", "float")], "bool")
        self.assertIsNotNone(body)
        self.assertIn("selling_price <= cost_price", "\n".join(body))

    def test_repository_utilization_uses_capacity_and_children_stock(self):
        body = generator._repo_utilization_body(
            self.ctx(), "StorageLocation",
            method("get_location_utilization_rate", [("location_id", "int")],
                   "float"))
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("maximum_capacity", text)
        self.assertIn("stock_quantity", text)

    def test_overdue_read(self):
        body = generator._service_overdue_body(
            self.ctx(), method("get_overdue_loans", [], "list[Loan]"), [],
            "list[Loan]")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("due_date", text)
        self.assertIn("'overdue'", text)


if __name__ == "__main__":
    unittest.main()
