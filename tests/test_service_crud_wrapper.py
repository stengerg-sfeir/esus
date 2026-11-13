"""Mechanical service CRUD wrappers and the low-stock filter."""

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


def method(name, params, returns="None", description=""):
    return {"name": name, "description": description, "return_type": returns,
            "params": [{"name": param, "type": type_} for param, type_ in params]}


class CrudWrapperTests(unittest.TestCase):
    def ctx(self):
        return {
            "entity_names": ["Customer", "Order"],
            "models": [
                model("Customer", field("customer_id", "int", primary_key=True),
                      field("name", "string"), field("email", "string")),
                model("Order", field("order_id", "int", primary_key=True),
                      field("status", "string")),
            ],
            "repositories": [
                repo("Customer", [method("create", [("name", "str"), ("email", "str")],
                                         "Customer"),
                                  method("update", [("customer_id", "int"),
                                                    ("name", "str"),
                                                    ("email", "str")], "Customer")]),
                repo("Order", [method("delete", [("order_id", "int"),
                                                 ("status", "str")], "None")]),
            ],
            "contracts": [],
            "method_repairs": {},
            "mappings": {},
        }

    def test_create_customer_delegates_to_the_repository(self):
        body = generator._service_crud_wrapper(
            self.ctx(), "CustomerService",
            method("create_customer", [("name", "str"), ("email", "str")],
                   description="Creates a new Customer."),
            [("name", "name", "str"), ("email", "email", "str")], "None")
        self.assertEqual(
            body[-1],
            "self._repos['CustomerRepository'].create(name=name, email=email)")
        self.assertIn("if name is None or email is None:", body[0])

    def test_update_wrapper_passes_optional_fields_as_none(self):
        body = generator._service_crud_wrapper(
            self.ctx(), "CustomerService",
            method("update_customer", [("customer_id", "int"), ("name", "str")],
                   description="Updates an existing Customer."),
            [("customer_id", "customer_id", "int"), ("name", "name", "str")],
            "None")
        self.assertIsNotNone(body)
        self.assertIn("CustomerRepository", body[0])
        self.assertIn("customer_id=customer_id", body[0])

    def test_a_description_with_a_business_rule_is_not_mechanical(self):
        body = generator._service_crud_wrapper(
            self.ctx(), "ExpenseService",
            method("update_expense", [("id", "int")],
                   description="Updates an expense and checks the budget."),
            [("id", "id", "int")], "None")
        self.assertIsNone(body)

    def test_a_method_with_a_repair_record_is_not_mechanical(self):
        ctx = self.ctx()
        ctx["method_repairs"] = {("CustomerService", "update_customer"): {}}
        body = generator._service_crud_wrapper(
            ctx, "CustomerService",
            method("update_customer", [("customer_id", "int")],
                   description="Updates an existing Customer."),
            [("customer_id", "customer_id", "int")], "None")
        self.assertIsNone(body)


class LowStockTests(unittest.TestCase):
    def ctx(self):
        return {
            "entity_names": ["Category", "Product"],
            "models": [
                model("Category", field("id", "int", primary_key=True),
                      field("name", "string"),
                      field("reorder_threshold", "int")),
                model("Product", field("id", "int", primary_key=True),
                      field("name", "string"),
                      field("category_id", "int",
                            foreign_key={"target_entity": "Category",
                                         "target_field": "id"}),
                      field("stock_qty", "int")),
            ],
            "repositories": [
                repo("Category", [method("read_all", [], "list[Category]")]),
                repo("Product", [method("read_all", [("category_id", "int")],
                                         "list[Product]")]),
            ],
            "mappings": {},
        }

    def test_list_products_branches_on_low_only(self):
        body = generator._service_low_stock_body(
            self.ctx(),
            method("list_products", [("category_id", "int"),
                                     ("low_only", "bool")], "list[Product]"),
            [("category_id", "category_id", "int"),
             ("low_only", "low_only", "bool")], "list[Product]")
        self.assertIsNotNone(body)
        text = "\n".join(body)
        self.assertIn("if low_only is not True:", text)
        self.assertIn("category_id=category_id", text)
        self.assertIn("stock_qty < threshold", text)


if __name__ == "__main__":
    unittest.main()
