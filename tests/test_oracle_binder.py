"""Case binding uses extraction only for invocation, never for expectations."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kernel.oracle import binder  # noqa: E402


DOCS = {
    "models": [
        {"name": "Order", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "status", "type": "string"}]},
        {"name": "Product", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "stock_quantity", "type": "int"}]},
    ],
    "services": [{"service_name": "OrderService", "methods": [{
        "name": "cancel_order",
        "params": [{"name": "order_id", "type": "int"}]}]}],
    "repos": [],
}


def case(**overrides):
    value = {
        "id": "cancel",
        "source": "Cancelling a confirmed order releases its stock.",
        "given": {"order": {"status": "confirmed"}},
        "when": {"action": "cancel_order", "args": ["order.id"]},
        "then": {"state": {"order.status": "cancelled"}},
        "status": "confirmed",
    }
    value.update(overrides)
    return value


class OracleBinderTests(unittest.TestCase):
    def test_a_service_case_becomes_the_existing_scenario_shape(self):
        scenario, reason = binder.bind_case(case(), DOCS)
        self.assertIsNone(reason)
        self.assertEqual(scenario["setup"][0]["entity"], "Order")
        self.assertEqual(scenario["when"]["service"], "OrderService")
        self.assertEqual(scenario["when"]["args"], {"order_id": {"ref": "order.id"}})
        self.assertEqual(scenario["expect"]["fields"],
                         {"order.status": "cancelled"})

    def test_named_service_args_become_kwargs(self):
        scenario, reason = binder.bind_case(
            case(when={"action": "cancel_order", "args": ["order_id=1"]}),
            DOCS)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"], {"order_id": 1})

    def test_a_cli_path_binds_to_the_generated_surface(self):
        docs = dict(DOCS)
        docs["components"] = {"facade": {"invocation": {"commands": [{
            "name": "order", "subcommands": [{"name": "cancel", "options": []}]
        }]}}}
        scenario, reason = binder.bind_case(
            case(when={"action": "order cancel", "args": ["--order-id=1"]}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["cli"],
                         ["order", "cancel", "--order-id=1"])

    def test_a_service_beats_a_repository_entry_in_the_contract_list(self):
        docs = dict(DOCS)
        docs["services"] = [
            {"service_name": "OrderService", "methods": [{
                "name": "cancel_order", "params": []}]},
            {"service_name": "OrderRepository", "methods": [{
                "name": "cancel_order", "params": []}]},
        ]
        docs["repos"] = [{"interface_name": "OrderRepository", "methods": [{
            "name": "cancel_order", "params": []}]}]
        scenario, reason = binder.bind_case(case(), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["service"], "OrderService")

    def test_missing_related_setup_is_unbound_for_a_success_case(self):
        docs = {
            "models": [
                {"name": "Customer", "fields": [
                    {"name": "id", "primary_key": True}]},
                {"name": "Order", "fields": [
                    {"name": "id", "primary_key": True},
                    {"name": "customer_id", "foreign_key": {
                        "target_entity": "Customer", "target_field": "id"}}]},
            ],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "create_order", "params": []}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "create_order"}, given={
                "order": {"status": "confirmed", "customer_id": 1}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("Customer row", reason)
        scenario, reason = binder.bind_case(
            case(when={"action": "create_order"}, given={
                "customer": {"id": 1},
                "order": {"status": "confirmed",
                          "customer_id": {"ref": "customer.id"}}},
                 then={"rows": {"Order": 1}}), docs)
        self.assertIsNone(reason)
        self.assertIsNotNone(scenario)

    def test_an_expected_error_may_use_a_missing_relation(self):
        docs = {
            "models": [
                {"name": "Customer", "fields": [
                    {"name": "id", "primary_key": True}]},
                {"name": "Order", "fields": [
                    {"name": "id", "primary_key": True},
                    {"name": "customer_id", "foreign_key": {
                        "target_entity": "Customer", "target_field": "id"}}]},
            ],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "cancel_order", "params": []}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(given={"order": {"status": "confirmed", "customer_id": 99}},
                 then={"error": "OrderNotFoundError"}), docs)
        self.assertIsNone(reason)
        self.assertIsNotNone(scenario)

    def test_a_create_uses_the_seeded_fields_as_kwargs(self):
        docs = {
            "models": [{"name": "Employee", "fields": [
                {"name": "employee_id", "primary_key": True},
                {"name": "name"}, {"name": "email"},
                {"name": "age"}, {"name": "salary"}]}],
            "services": [{"service_name": "EmployeeService", "methods": [{
                "name": "create_employee", "params": [
                    {"name": "name"}, {"name": "email"},
                    {"name": "age"}, {"name": "salary"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "create_employee",
                       "args": ["alice@example.com"]},
                 given={"employee": {"name": "Alice", "email": "alice@example.com",
                                     "age": 30, "salary": 1000}},
                 then={}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"], {
            "name": "Alice", "email": "alice@example.com",
            "age": 30, "salary": 1000})

    def test_an_update_with_a_key_reference_is_bound(self):
        docs = {
            "models": [{"name": "Contact", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "email"}, {"name": "phone"}]}],
            "services": [{"service_name": "ContactService", "methods": [{
                "name": "update", "params": [
                    {"name": "id"}, {"name": "email"}, {"name": "phone"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update", "args": ["contact.id"]},
                 given={"contact": {"email": "alice@example.com"}},
                 then={}), docs)
        self.assertIsNone(reason)
        self.assertIsNotNone(scenario)

    def test_relationship_ids_come_from_seeded_entities(self):
        docs = {
            "models": [
                {"name": "Book", "fields": [
                    {"name": "book_id", "primary_key": True},
                    {"name": "title"}]},
                {"name": "Member", "fields": [
                    {"name": "member_id", "primary_key": True}]},
            ],
            "services": [{"service_name": "BorrowService", "methods": [{
                "name": "borrow_book",
                "params": [{"name": "book_id"}, {"name": "member_id"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "borrow_book",
                       "args": ["book.title", "member.id"]},
                 given={"book": {"title": "Book"}, "member": {}},
                 then={}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"], {
            "book_id": {"ref": "book.id"},
            "member_id": {"ref": "member.id"},
        })

    def test_update_uses_setup_lookup_and_explicit_changes(self):
        docs = {
            "models": [{"name": "Contact", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "name"}, {"name": "email"}, {"name": "phone"}]}],
            "services": [{"service_name": "ContactService", "methods": [{
                "name": "update", "params": [
                    {"name": "id"}, {"name": "name"},
                    {"name": "email"}, {"name": "phone"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update",
                       "args": ["alice@example.com", "phone", "555-5678"]},
                 given={"contact": {"name": "Alice",
                                     "email": "alice@example.com",
                                     "phone": "555-1234"}},
                 then={}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"]["phone"], "555-5678")
        self.assertEqual(scenario["when"]["args"]["email"], "alice@example.com")
        self.assertEqual(scenario["when"]["args"]["id"], {"ref": "contact.id"})

    def test_flat_update_args_supply_changed_values(self):
        docs = {
            "models": [{"name": "Product", "fields": [
                {"name": "product_id", "primary_key": True},
                {"name": "name"}, {"name": "category"},
                {"name": "price"}, {"name": "quantity"}]}],
            "services": [],
            "repos": [{"interface_name": "ProductRepository", "methods": [{
                "name": "update", "params": [
                    {"name": "product_id"}, {"name": "name"},
                    {"name": "category"}, {"name": "price"},
                    {"name": "quantity"}]}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update_product",
                       "args": ["Mouse", "electronics", 25.0, 15]},
                 given={"product": {"name": "Mouse", "category": "electronics",
                                     "price": 25.0, "quantity": 5}},
                 then={"state": {"product.quantity": 15}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"]["quantity"], 15)
        self.assertEqual(scenario["when"]["args"]["product_id"],
                         {"ref": "product.id"})

    def test_a_create_without_its_target_row_is_checked_from_the_holder(self):
        docs = {
            "models": [
                {"name": "User", "fields": [
                    {"name": "user_id", "primary_key": True},
                    {"name": "role"}]},
                {"name": "Order", "fields": [
                    {"name": "order_id", "primary_key": True},
                    {"name": "user_id", "nullable": False},
                    {"name": "order_date", "nullable": False},
                    {"name": "status", "nullable": False}]},
            ],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "create_order", "params": [
                    {"name": "user_id"}, {"name": "order_date"},
                    {"name": "status"}], "return_type": "None"}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "create_order", "args": ["user.id"]},
                 given={"user": {"user_id": 1, "role": "normal_user"}},
                 then={"rows": {"Order": 1}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("Order.order_date", reason)

    def test_an_update_that_supplies_no_new_value_is_unbound(self):
        docs = {
            "models": [{"name": "Project", "fields": [
                {"name": "project_id", "primary_key": True},
                {"name": "description"}]}],
            "services": [],
            "repos": [{"interface_name": "ProjectRepository", "methods": [{
                "name": "update", "params": [
                    {"name": "project_id"}, {"name": "description"}]}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update_project",
                       "args": ["project.id", "project.description"]},
                 given={"project": {"description": "An existing project"}},
                 then={"state": {
                     "project.description": "An updated description"}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("supplies no new value", reason)

    def test_a_create_target_is_payload_not_an_existing_row(self):
        docs = {
            "models": [{"name": "Product", "fields": [
                {"name": "id", "primary_key": True}, {"name": "name"}]}],
            "services": [],
            "repos": [{"interface_name": "ProductRepository", "methods": [{
                "name": "create", "params": [{"name": "name"}]}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "create_product", "args": ["Mouse"]},
                 given={"product": {"name": "Mouse"}},
                 then={"rows": {"Product": 1}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["setup"][0]["seed"], False)
        self.assertEqual(scenario["result"],
                         {"alias": "product", "entity": "Product"})
        self.assertEqual(scenario["expect"]["rows"], {"Product": 1})

    def test_row_counts_are_deltas_and_entity_aliases_are_canonical(self):
        docs = {
            "models": [
                {"name": "Customer", "fields": [
                    {"name": "customer_id", "primary_key": True},
                    {"name": "email"}]},
                {"name": "AuditLog", "fields": [
                    {"name": "id", "primary_key": True}]},
            ],
            "services": [{"service_name": "CustomerService", "methods": [{
                "name": "update_customer", "params": [
                    {"name": "customer_id"}, {"name": "email"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update_customer",
                       "args": ["customer.id", "new@example.com"]},
                 given={"customer": {"email": "old@example.com"}},
                 then={"state": {"customer.id": 1},
                       "rows": {"Customer": 1, "Audit": 1}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["expect"]["rows"],
                         {"Customer": 0, "AuditLog": 1})
        self.assertEqual(scenario["expect"]["fields"],
                         {"customer.customer_id": 1})

    def test_an_undeclared_expected_field_is_unbound(self):
        docs = {
            "models": [{"name": "Product", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "stock_quantity"}]}],
            "services": [{"service_name": "ProductService", "methods": [{
                "name": "update", "params": [{"name": "id"}]}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "update", "args": ["product.id"]},
                 given={"product": {"stock_quantity": 5}},
                 then={"state": {"product.nonexistent": 7}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("not declared", reason)

    def test_a_plural_list_action_binds_to_read_all(self):
        docs = {
            "models": [{"name": "Project", "fields": [
                {"name": "project_id", "primary_key": True},
                {"name": "name"}]}],
            "services": [],
            "repos": [{"interface_name": "ProjectRepository", "methods": [{
                "name": "read_all", "params": [],
                "return_type": "List[Project]"}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "list_projects", "args": []},
                 given={"project": {"name": "P"}},
                 then={"rows": {"Project": 1}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["method"], "read_all")

    def test_a_list_without_a_mutation_cannot_expect_fewer_rows(self):
        docs = {
            "models": [{"name": "Project", "fields": [
                {"name": "project_id", "primary_key": True},
                {"name": "name"}]}],
            "services": [],
            "repos": [{"interface_name": "ProjectRepository", "methods": [{
                "name": "read_all", "params": [],
                "return_type": "List[Project]"}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "list_projects", "args": []},
                 given={"project": {"name": "P"}},
                 then={"rows": {"Project": 0}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("performs no delete or filter", reason)

    def test_a_list_rows_expectation_compares_the_returned_count(self):
        docs = {
            "models": [{"name": "Project", "fields": [
                {"name": "project_id", "primary_key": True},
                {"name": "name"}]}],
            "services": [],
            "repos": [{"interface_name": "ProjectRepository", "methods": [{
                "name": "read_all", "params": [],
                "return_type": "List[Project]"}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "list_projects", "args": []},
                 given={"project": {"name": "P"}},
                 then={"rows": {"Project": 1}}), docs)
        self.assertIsNone(reason)
        self.assertTrue(scenario["rows_as_result"])

    def test_a_bare_author_alias_becomes_the_foreign_key(self):
        docs = {
            "models": [
                {"name": "Author", "fields": [
                    {"name": "author_id", "primary_key": True},
                    {"name": "name"}]},
                {"name": "Book", "fields": [
                    {"name": "id", "primary_key": True},
                    {"name": "author_id"}]},
            ],
            "services": [],
            "repos": [{"interface_name": "BookRepository", "methods": [{
                "name": "read_all", "params": [
                    {"name": "author_id"}],
                "return_type": "List[Book]"}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "list_books", "args": ["author"]},
                 given={"author": {"name": "A"},
                        "book": {"title": "B"}},
                 then={"rows": {"Book": 1}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"],
                         {"author_id": {"ref": "author.id"}})

    def test_a_parameter_name_used_as_a_literal_is_unbound(self):
        docs = {
            "models": [{"name": "Book", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "title"}]}],
            "services": [{"service_name": "LibraryService", "methods": [{
                "name": "search_books",
                "params": [{"name": "query"}],
                "return_type": "List[Book]"}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "search_books", "args": ["query"]},
                 given={"book": {"title": "T"}},
                 then={"rows": {"Book": 1}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("parameter name 'query'", reason)

    def test_numeric_literal_arguments_follow_the_parameter_types(self):
        docs = {
            "models": [{"name": "Account", "fields": [
                {"name": "account_id", "primary_key": True}]},
                       {"name": "Customer", "fields": [
                {"name": "customer_id", "primary_key": True}]}],
            "services": [{"service_name": "AccountService", "methods": [{
                "name": "withdraw", "params": [
                    {"name": "amount", "type": "int"}],
                "return_type": "None"}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "withdraw", "args": ["5"]},
                 given={"customer": {"customer_id": 1}},
                 then={"rows": {"Account": 1}}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["when"]["args"], [5])

    def test_delete_state_on_a_hard_deleted_row_is_unbound(self):
        docs = {
            "models": [{"name": "Customer", "fields": [
                {"name": "customer_id", "primary_key": True},
                {"name": "name"}]}],
            "services": [],
            "repos": [{"interface_name": "CustomerRepository", "methods": [{
                "name": "delete", "params": [
                    {"name": "customer_id", "type": "int"}],
                "return_type": "None"}]}],
        }
        scenario, reason = binder.bind_case(
            case(when={"action": "delete_customer", "args": ["1"]},
                 given={"customer": {"customer_id": 1}},
                 then={"state": {"customer.name": "x"},
                       "rows": {"Customer": 0}}), docs)
        self.assertIsNone(scenario)
        self.assertIn("hard-deleted row", reason)

    def test_a_standalone_app_case_binds_with_empty_setup(self):
        docs = {"models": [], "services": [], "repos": []}
        scenario, reason = binder.bind_case(
            case(given={}, when={"app": True, "args": ["2", "+", "3"]},
                 then={"stdout_contains": "5", "exit_code": 0}), docs)
        self.assertIsNone(reason)
        self.assertEqual(scenario["setup"], [])
        self.assertEqual(scenario["when"]["args"], ["2", "+", "3"])
        self.assertEqual(scenario["expect"]["stdout_contains"], "5")

    def test_an_unknown_action_is_unbound(self):
        scenario, reason = binder.bind_case(
            case(when={"action": "invented_action"}), DOCS)
        self.assertIsNone(scenario)
        self.assertIn("no generated method", reason)

    def test_a_state_alias_binds_to_the_models_status_field(self):
        docs = {
            "models": [{"name": "Order", "fields": [
                {"name": "id", "primary_key": True},
                {"name": "status"}]}],
            "services": [{"service_name": "OrderService", "methods": [{
                "name": "cancel_order", "params": []}]}],
            "repos": [],
        }
        scenario, reason = binder.bind_case(
            case(given={"order": {"state": "confirmed"}},
                 then={"state": {"order.state": "cancelled"}}), docs)
        self.assertIsNone(reason)
        # The worker resolves state/status at execution time; the case keeps
        # the prompt's spelling and the binder does not rewrite the expectation.
        self.assertEqual(scenario["expect"]["fields"],
                         {"order.state": "cancelled"})


if __name__ == "__main__":
    unittest.main()
