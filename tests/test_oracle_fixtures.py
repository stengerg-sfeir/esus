"""The fixture planner supplies FK-complete setup without inventing outcomes."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import fixtures  # noqa: E402


def model(name, fields):
    return {"name": name, "fields": fields}


def field(name, type="string", *, pk=False, required=False, unique=False,
          fk=None, nullable=None):
    item = {"name": name, "type": type, "primary_key": pk,
            "unique": unique, "foreign_key": fk}
    if nullable is not None:
        item["nullable"] = nullable
    elif required:
        item["nullable"] = False
    return item


DOCS = {"models": [
    model("Customer", [
        field("id", "int", pk=True),
        field("name", required=True),
        field("email", required=True, unique=True),
        field("created_at", "datetime", required=True),
    ]),
    model("Order", [
        field("id", "int", pk=True),
        field("customer_id", "int", required=True,
              fk={"target_entity": "Customer", "target_field": "id"}),
        field("status", required=True),
    ]),
]}


def intent(**overrides):
    value = {
        "id": "cancel_order",
        "source": "Customers can cancel their orders.",
        "kind": "update",
        "entity": "Order",
        "action": "cancel_order",
        "setup_entities": [
            {"alias": "order", "entity": "Order", "role": "target"},
        ],
        "setup_values": {"order.status": "pending"},
        "lookup": ["order.id"],
        "changes": {"order.status": "cancelled"},
        "expect": {"state": {"order.status": "cancelled"}, "rows": {"Order": 1}},
        "status": "confirmed",
    }
    value.update(overrides)
    return value


class FixturePlannerTests(unittest.TestCase):
    def test_a_required_parent_is_created_before_the_child(self):
        plan = fixtures.plan_case(
            intent(), DOCS, "Customers can cancel their orders.")
        self.assertEqual(list(plan.case["given"]), ["customer", "order"])
        order = plan.case["given"]["order"]
        self.assertEqual(order["customer_id"], {"ref": "customer.id"})
        self.assertEqual(order["status"], "pending")
        customer = plan.case["given"]["customer"]
        self.assertEqual(customer["email"], "customer@example.test")
        self.assertNotIn("created_at", customer)
        self.assertEqual(len(plan.diagnostics["synthetic"]), 1)

    def test_an_explicit_parent_is_linked_not_duplicated(self):
        exercise = intent(setup_entities=[
            {"alias": "customer", "entity": "Customer", "role": "setup"},
            {"alias": "order", "entity": "Order", "role": "target"},
        ], setup_values={
            "customer.name": "Ada",
            "order.status": "pending",
        })
        plan = fixtures.plan_case(exercise, DOCS)
        self.assertEqual(list(plan.case["given"]), ["customer", "order"])
        self.assertEqual(plan.case["given"]["customer"]["name"], "Ada")
        self.assertEqual(plan.case["given"]["order"]["customer_id"],
                         {"ref": "customer.id"})
        self.assertEqual(plan.diagnostics["synthetic"], [])

    def test_a_nullable_foreign_key_is_not_auto_seeded(self):
        docs = {"models": [
            DOCS["models"][0],
            model("Order", [
                field("id", "int", pk=True),
                field("customer_id", "int", nullable=True,
                      fk={"target_entity": "Customer", "target_field": "id"}),
                field("status", required=True),
            ]),
        ]}
        plan = fixtures.plan_case(intent(), docs)
        self.assertNotIn("customer_id", plan.case["given"]["order"])
        self.assertNotIn("customer", plan.case["given"])

    def test_entity_aliases_are_resolved_to_extracted_names(self):
        docs = {"models": [
            model("Customer", [
                field("id", "int", pk=True),
                field("name", required=True),
            ]),
        ]}
        exercise = {
            "id": "rename_client",
            "source": "A client can change their name.",
            "kind": "update",
            "entity": "Client",
            "action": "update_customer",
            "setup_entities": [
                {"alias": "client", "entity": "Client", "role": "target"},
            ],
            "setup_values": {"client.name": "Ada"},
            "changes": {"client.name": "Grace"},
            "expect": {"state": {"client.name": "Grace"}},
            "status": "confirmed",
        }
        plan = fixtures.plan_case(
            exercise, docs, "A client can change their name.")
        self.assertEqual(list(plan.case["given"]), ["client"])
        self.assertEqual(plan.case["given"]["client"]["name"], "Ada")

    def test_an_unknown_field_is_rejected(self):
        with self.assertRaises(fixtures.PlanError):
            fixtures.plan_case(
                intent(setup_values={"order.missing": "x"}), DOCS)

    def test_an_unmentioned_auxiliary_lookup_is_replaced_by_the_key(self):
        docs = {"models": [
            model("Product", [field("id", "int", pk=True),
                              field("name", required=True)]),
        ]}
        exercise = {
            "id": "rename_product",
            "source": "A product can be renamed.",
            "kind": "update",
            "entity": "Product",
            "action": "rename_product",
            "setup_entities": [
                {"alias": "product", "entity": "Product", "role": "target"},
            ],
            "setup_values": {"product.name": "Old"},
            "lookup": ["product.sku"],
            "where": {"product.active": True},
            "args": ["product.sku"],
            "changes": {"product.name": "New"},
            "expect": {"state": {"product.name": "New"}},
            "status": "confirmed",
        }
        plan = fixtures.plan_case(
            exercise, docs, "A product can be renamed.")
        self.assertEqual(plan.case["when"]["args"], [{"ref": "product.id"}])
        self.assertNotIn("where", plan.case["when"])

    def test_a_prompt_named_missing_field_is_not_hidden(self):
        docs = {"models": [
            model("Product", [field("id", "int", pk=True),
                              field("name", required=True)]),
        ]}
        exercise = {
            "id": "unique_sku",
            "source": "SKUs must be unique.",
            "kind": "create",
            "entity": "Product",
            "action": "create_product",
            "setup_entities": [
                {"alias": "product", "entity": "Product", "role": "target"},
            ],
            "args": ["product.sku"],
            "expect": {"rows": {"Product": 1}},
            "status": "confirmed",
        }
        with self.assertRaises(fixtures.PlanError) as caught:
            fixtures.plan_case(exercise, docs, "SKUs must be unique.")
        self.assertIn("sku", str(caught.exception))

    def test_create_uses_prompt_values_for_asserted_fields(self):
        docs = {"models": [
            model("Product", [
                field("id", "int", pk=True),
                field("name", required=True),
                field("price", "number", required=True),
            ]),
        ]}
        create = {
            "id": "create_product",
            "source": "Create a product with a name and price.",
            "kind": "create",
            "entity": "Product",
            "action": "create_product",
            "setup_entities": [
                {"alias": "product", "entity": "Product", "role": "target"},
            ],
            "changes": {"product.name": "Widget"},
            "expect": {"state": {"product.price": 12.5},
                       "rows": {"Product": 1}},
            "status": "confirmed",
        }
        plan = fixtures.plan_case(
            create, docs, "Create a product with a name and price.")
        product = plan.case["given"]["product"]
        self.assertEqual(product["name"], "Widget")
        self.assertEqual(product["price"], 12.5)

    def test_a_method_parameter_entity_is_seeded_mechanically(self):
        docs = {
            "models": [
                model("Book", [field("id", "int", pk=True),
                               field("available_copies", "int", required=True)]),
                model("Member", [field("id", "int", pk=True),
                                 field("name", required=True)]),
            ],
            "services": [{"service_name": "LibraryService", "methods": [{
                "name": "borrow_book",
                "params": [{"name": "member_id"}, {"name": "book_id"}],
            }]}],
        }
        exercise = intent(
            entity="Book", action="borrow_book",
            setup_entities=[
                {"alias": "book", "entity": "Book", "role": "target"},
            ],
            setup_values={"book.available_copies": 1},
            args=["book.id", 1],
            changes={},
            expect={"state": {"book.available_copies": 0}},
        )
        plan = fixtures.plan_case(
            exercise, docs, "A member can borrow a book.")
        self.assertIn("member", plan.case["given"])
        self.assertEqual(plan.diagnostics["synthetic"][0]["entity"], "Member")

    def test_a_missing_row_expected_to_raise_is_not_auto_seeded(self):
        docs = {
            "models": [
                model("Book", [field("id", "int", pk=True),
                               field("available_copies", "int", required=True)]),
                model("Member", [field("id", "int", pk=True),
                                 field("name", required=True)]),
            ],
            "services": [{"service_name": "LibraryService", "methods": [{
                "name": "borrow_book",
                "params": [{"name": "member_id"}, {"name": "book_id"}],
            }]}],
        }
        exercise = intent(
            entity="Book", action="borrow_book",
            setup_entities=[
                {"alias": "book", "entity": "Book", "role": "target"},
            ],
            setup_values={"book.available_copies": 1},
            args=["book.id", 1],
            changes={},
            expect={"error": "MemberNotFoundError"},
        )
        plan = fixtures.plan_case(
            exercise, docs, "A member can borrow a book.")
        self.assertNotIn("member", plan.case["given"])

    def test_an_ungrounded_alias_is_renamed_to_the_extracted_entity(self):
        docs = {"models": [
            model("Customer", [field("id", "int", pk=True),
                               field("name", required=True)]),
        ]}
        exercise = {
            "id": "rename_customer",
            "source": "Customers can be renamed.",
            "kind": "update",
            "entity": "Customer",
            "action": "rename_customer",
            "setup_entities": [
                {"alias": "client", "entity": "Customer", "role": "target"},
            ],
            "setup_values": {"client.name": "Ada"},
            "changes": {},
            "args": ["client.id"],
            "expect": {"state": {"client.name": "Grace"}},
            "status": "confirmed",
        }
        plan = fixtures.plan_case(
            exercise, docs, "Customers can be renamed.")
        self.assertEqual(list(plan.case["given"]), ["customer"])
        self.assertEqual(plan.case["then"]["state"]["customer.name"], "Grace")
        self.assertEqual(plan.case["when"]["args"], [{"ref": "customer.id"}])

    def test_a_target_not_used_by_the_action_is_downgraded(self):
        docs = {
            "models": [
                model("Customer", [field("id", "int", pk=True)]),
                model("Product", [field("id", "int", pk=True),
                                  field("stock_quantity", "int", required=True)]),
                model("Order", [field("id", "int", pk=True),
                                field("customer_id", "int", required=True,
                                      fk={"target_entity": "Customer",
                                          "target_field": "id"})]),
            ],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "cancel_order",
                "params": [{"name": "order_id", "type": "int"}],
            }]}],
        }
        exercise = intent(
            entity="Product", action="cancel_order",
            setup_entities=[
                {"alias": "product", "entity": "Product", "role": "target"},
            ],
            setup_values={"product.stock_quantity": 5},
            changes={},
            expect={"state": {"product.stock_quantity": 5}},
        )
        plan = fixtures.plan_case(
            exercise, docs, "Customers can cancel their orders.")
        self.assertEqual(plan.case["status"], "assumed")
        self.assertTrue(any("not used by the action"
                            in item for item in plan.case["ambiguities"]))

    def test_a_list_expectation_replicates_enough_setup_rows(self):
        docs = {"models": [
            model("Customer", [field("id", "int", pk=True),
                               field("name", required=True),
                               field("email", required=True, unique=True)]),
        ]}
        exercise = {
            "id": "list_customers",
            "source": "Customers can be listed.",
            "kind": "list",
            "entity": "Customer",
            "action": "list_customers",
            "setup_entities": [
                {"alias": "customer", "entity": "Customer", "role": "target"},
            ],
            "setup_values": {"customer.name": "Ada"},
            "expect": {"rows": {"Customer": 3}},
            "status": "confirmed",
        }
        plan = fixtures.plan_case(
            exercise, docs, "Customers can be listed.")
        self.assertEqual(len(plan.case["given"]), 3)
        emails = [row["email"] for row in plan.case["given"].values()]
        self.assertEqual(len(set(emails)), 3)
        self.assertEqual(plan.case["given"]["customer"]["name"], "Ada")
        self.assertEqual(len(plan.diagnostics["replicated_rows"]), 2)
        self.assertEqual(plan.case["status"], "assumed")

    def test_a_primary_key_with_the_wrong_type_is_rejected(self):
        docs = {"models": [
            model("Customer", [field("id", "int", pk=True),
                               field("name", required=True)]),
        ]}
        exercise = {
            "id": "create_customer",
            "source": "Customers can be created.",
            "kind": "create",
            "entity": "Customer",
            "action": "create_customer",
            "setup_entities": [
                {"alias": "customer", "entity": "Customer", "role": "target"},
            ],
            "setup_values": {"customer.id": "C123",
                             "customer.name": "Ada"},
            "expect": {"state": {"customer.id": "C123"}},
            "status": "confirmed",
        }
        with self.assertRaises(fixtures.PlanError) as caught:
            fixtures.plan_case(exercise, docs, "Customers can be created.")
        self.assertIn("primary key", str(caught.exception))

    def test_pagination_without_page_parameters_is_rejected(self):
        docs = {
            "models": [model("Customer", [
                field("id", "int", pk=True), field("name", required=True)])],
            "services": [],
            "repos": [{"interface_name": "CustomerRepository", "methods": [
                {"name": "read_all",
                 "params": [{"name": "name", "type": "str"}]}]}],
        }
        exercise = {
            "id": "list_paged",
            "source": "The caller specifies page number and page size.",
            "kind": "list",
            "entity": "Customer",
            "action": "list_customers",
            "setup_entities": [
                {"alias": "customer", "entity": "Customer", "role": "target"},
            ],
            "setup_values": {"customer.name": "Ada"},
            "args": ["1", "10"],
            "expect": {"rows": {"Customer": 1}},
            "status": "confirmed",
        }
        with self.assertRaises(fixtures.PlanError) as caught:
            fixtures.plan_case(
                exercise, docs,
                "The caller specifies page number and page size.")
        self.assertIn("pagination", str(caught.exception))

    def test_app_intent_has_no_fixtures(self):
        app = {
            "id": "calculator",
            "source": "Run the calculator.",
            "kind": "app",
            "app": {"args": ["2", "+", "3"]},
            "expect": {"stdout_contains": "5", "exit_code": 0},
            "status": "assumed",
        }
        plan = fixtures.plan_case(app, {}, "Run the calculator.")
        self.assertEqual(plan.case["given"], {})
        self.assertTrue(plan.case["when"]["app"])
        self.assertEqual(plan.case["when"]["args"], ["2", "+", "3"])

    def test_custom_action_uses_args_not_update_changes(self):
        docs = {
            "models": DOCS["models"] + [
                model("Account", [
                    field("id", "int", pk=True),
                    field("customer_id", "int", required=True,
                          fk={"target_entity": "Customer",
                              "target_field": "id"}),
                    field("balance", "number", required=True),
                ]),
            ],
            "services": [{"service_name": "AccountService", "methods": [
                {"name": "deposit"},
                {"name": "withdraw"},
            ]}],
        }
        exercise = intent(
            entity="Account",
            setup_entities=[
                {"alias": "account", "entity": "Account", "role": "target"},
            ],
            setup_values={"account.balance": 100},
            kind="update", action="deposit",
            args=["account.account_id", 50],
            changes={"account.balance": 150},
            cli=["account", "deposit"],
            expect={"state": {"account.balance": 150}},
        )
        plan = fixtures.plan_case(
            exercise, docs, "Deposits increase the balance.")
        self.assertEqual(plan.case["when"]["args"],
                         [{"ref": "account.id"}, 50])

    def test_an_action_with_no_generated_method_is_rejected(self):
        docs = {
            "models": DOCS["models"],
            "repos": [{"interface_name": "AccountRepository", "methods": [
                {"name": "update"},
            ]}],
        }
        exercise = intent(action="reconcile",
                          source="Cancel an order.")
        with self.assertRaises(fixtures.PlanError) as caught:
            fixtures.plan_case(exercise, docs, "Cancel an order.")
        self.assertIn("invented", str(caught.exception))

    def test_a_prompt_named_missing_action_is_a_coverage_gap(self):
        docs = {
            "models": DOCS["models"],
            "repos": [{"interface_name": "AccountRepository", "methods": [
                {"name": "update"},
            ]}],
        }
        exercise = intent(action="withdraw",
                          source="Withdrawals decrease the balance.")
        with self.assertRaises(fixtures.PlanError) as caught:
            fixtures.plan_case(
                exercise, docs, "Withdrawals decrease the balance.")
        self.assertIn("coverage_gap", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
