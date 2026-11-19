"""Generic repairs for validation failures."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import repairs  # noqa: E402
from kernel.extraction.pipeline import (  # noqa: E402
    COMPONENTS, PERSISTENCE_PORTS, Pipeline,
)


class PersistenceRepairTests(unittest.TestCase):
    def test_none_technology_cannot_require_persistence(self):
        components = {"persistence": {"required": True, "technology": "none"}}
        repairs.repair_persistence_consistency(components)
        self.assertFalse(components["persistence"]["required"])

    def test_sqlite_requirement_is_left_alone(self):
        components = {"persistence": {"required": True, "technology": "sqlite"}}
        repairs.repair_persistence_consistency(components)
        self.assertTrue(components["persistence"]["required"])


class _Log:
    def write(self, text):
        pass


class PersistenceSkipTests(unittest.TestCase):
    def test_skipping_persistence_removes_a_null_ports_document(self):
        pipeline = Pipeline(None, log=_Log())
        pipeline.documents = {
            COMPONENTS: {"persistence": {"required": True,
                                         "technology": "none"}},
            PERSISTENCE_PORTS: None,
        }
        pipeline._step_persistence("")
        self.assertNotIn(PERSISTENCE_PORTS, pipeline.documents)


class UnknownRaiseTests(unittest.TestCase):
    def test_a_validation_raise_not_grounded_is_dropped(self):
        services = [{"service_name": "CategoryService", "methods": [{
            "name": "create_category", "raises": ["InvalidCategoryNameError"]}]}]
        errors, repaired = repairs.repair_unknown_raises(
            [], services, "Create a category.", None)
        self.assertEqual(errors, [])
        self.assertEqual(repaired[0]["methods"][0]["raises"], [])

    def test_a_validation_raise_grounded_by_requirements_is_registered(self):
        services = [{"service_name": "S", "methods": [{
            "name": "m", "raises": ["InvalidInputError"]}]}]
        errors, _ = repairs.repair_unknown_raises(
            [], services, "Reject invalid input.", None)
        self.assertEqual(errors[0]["name"], "InvalidInputError")
        self.assertEqual(errors[0]["base"], "ValueError")

    def test_a_state_raise_is_registered(self):
        services = [{"service_name": "OrderService", "methods": [{
            "name": "ship_order", "raises": ["OrderStateException"]}]}]
        errors, repaired = repairs.repair_unknown_raises(
            [], services, "Order transitions.", None)
        self.assertEqual(errors[0]["name"], "OrderStateException")
        self.assertEqual(errors[0]["base"], "RuntimeError")
        self.assertEqual(repaired[0]["methods"][0]["raises"], ["OrderStateException"])


class ForeignKeyNameTests(unittest.TestCase):
    def test_primary_key_named_relationship_becomes_entity_id(self):
        models = [{"name": "Loan", "fields": [
            {"name": "book_primary_key", "type": "int",
             "foreign_key": {"target_entity": "Book", "target_field": "id"}},
            {"name": "member_primary_key", "type": "int",
             "foreign_key": {"target_entity": "Member", "target_field": "id"}},
        ]}]
        repairs.repair_primary_key_foreign_key_names(models)
        self.assertEqual([field["name"] for field in models[0]["fields"]],
                         ["book_id", "member_id"])

    def test_an_existing_conventional_name_is_not_overwritten(self):
        models = [{"name": "Loan", "fields": [
            {"name": "book_id", "type": "int"},
            {"name": "book_primary_key", "type": "int",
             "foreign_key": {"target_entity": "Book", "target_field": "id"}},
        ]}]
        repairs.repair_primary_key_foreign_key_names(models)
        self.assertEqual(models[0]["fields"][1]["name"], "book_primary_key")


class GenericTypeTests(unittest.TestCase):
    def test_java_generics_become_python_annotations(self):
        services = [{"service_name": "S", "methods": [{
            "name": "list", "params": [{"name": "id", "type": "UUID"}],
            "return_type": "List<Book>"}]}]
        models = [{"name": "Book", "fields": []}]
        repairs.repair_generic_type_spellings(services, models)
        self.assertEqual(services[0]["methods"][0]["return_type"],
                         "list[models.Book]")
        self.assertEqual(services[0]["methods"][0]["params"][0]["type"], "UUID")

    def test_map_generics_use_dict(self):
        services = [{"service_name": "S", "methods": [{
            "name": "count", "params": [], "return_type": "Map<string, int>"}]}]
        repairs.repair_generic_type_spellings(services, [])
        self.assertEqual(services[0]["methods"][0]["return_type"],
                         "dict[str, int]")


class RequiredCreateFieldTests(unittest.TestCase):
    def test_required_fk_fields_are_added_to_a_plain_create(self):
        models = [{"name": "Loan", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "book_id", "type": "int", "nullable": False},
            {"name": "member_id", "type": "int", "nullable": False},
        ]}]
        ports = {"repositories": [{"entity": "Loan", "interface_name": "LoanRepository",
                                   "methods": [{"name": "create", "params": []}]}]}
        repairs.repair_required_create_fields(ports, models)
        self.assertEqual([p["name"] for p in ports["repositories"][0]["methods"][0]["params"]],
                         ["book_id", "member_id"])

    def test_mapping_create_is_left_alone(self):
        models = [{"name": "Loan", "fields": [
            {"name": "book_id", "type": "int", "nullable": False}]}]
        ports = {"repositories": [{"entity": "Loan", "methods": [{
            "name": "create", "params": [{"name": "data", "type": "LoanData"}]}]}]}
        repairs.repair_required_create_fields(ports, models)
        self.assertEqual(len(ports["repositories"][0]["methods"][0]["params"]), 1)

    def test_an_inferred_field_keeps_its_provenance_in_the_port(self):
        models = [{"name": "Loan", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "due_date", "type": "datetime", "nullable": False,
             "status": "inferred from prose"},
        ]}]
        ports = {"repositories": [{"entity": "Loan", "methods": [{
            "name": "create", "params": []}]}]}
        repairs.repair_required_create_fields(ports, models)
        param = ports["repositories"][0]["methods"][0]["params"][-1]
        self.assertEqual(param["name"], "due_date")
        self.assertEqual(param["status"], "inferred from prose")


class EmptyDomainTests(unittest.TestCase):
    def test_an_order_application_gets_an_inferred_model_and_crud(self):
        requirements = ("Create a Python 3.12 order application. When an order "
                        "is confirmed, send a notification.")
        models = repairs.repair_empty_domain([], requirements)
        self.assertEqual(models[0]["name"], "Order")
        self.assertEqual(models[0]["fields"][1]["name"], "status")
        self.assertEqual(models[0]["provenance"], "empty_domain_repair")
        self.assertTrue(models[0]["review_required"])
        components = {"persistence": {"required": False, "technology": "none"},
                      "crud_services": []}
        repairs.repair_empty_domain_components(components, models)
        self.assertEqual(components["crud_services"][0]["entity"], "Order")
        self.assertEqual(components["crud_services"][0]["provenance"],
                         "empty_domain_repair")
        self.assertTrue(components["crud_services"][0]["review_required"])
        self.assertTrue(components["persistence"]["required"])
        self.assertEqual(components["persistence"]["technology"], "sqlite")
        self.assertEqual(components["persistence"]["provenance"],
                         "empty_domain_repair")
        self.assertTrue(components["persistence"]["review_required"])

    def test_a_statement_without_an_application_noun_stays_empty(self):
        self.assertEqual(
            repairs.repair_empty_domain([], "Print hello world."), [])

    def test_an_article_before_the_word_application_is_not_a_domain(self):
        self.assertEqual(repairs.repair_empty_domain(
            [], "Create a Python application that prints Hello. Organize the "
                "application as a package."), [])


class ContractWriteProvenanceTests(unittest.TestCase):
    def test_an_added_update_keeps_its_contract_provenance(self):
        models = [{"name": "Order", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "status", "type": "string"}]}]
        repositories = [{"entity": "Order", "interface_name": "OrderRepository",
                         "methods": []}]
        contracts = [{"holder": "OrderService", "method": "cancel_order",
                      "effects": [{"target": "order.status", "op": "set",
                                   "write": "OrderRepository.update"}]}]
        repairs.repair_contract_write_methods(contracts, repositories, models)
        update = repositories[0]["methods"][0]
        self.assertEqual(update["provenance"], "contract_write")
        self.assertTrue(update["review_required"])

    def test_an_unrelated_entity_gets_no_update(self):
        models = [{"name": "Order", "fields": [
            {"name": "id", "type": "int", "primary_key": True}]},
                  {"name": "Product", "fields": [
            {"name": "id", "type": "int", "primary_key": True}]}]
        repositories = [{"entity": "Order", "interface_name": "OrderRepository",
                         "methods": []},
                        {"entity": "Product", "interface_name": "ProductRepository",
                         "methods": []}]
        contracts = [{"holder": "OrderService", "method": "cancel_order",
                      "effects": [{"target": "order.status", "op": "set",
                                   "write": "OrderRepository.update"}]}]
        repairs.repair_contract_write_methods(contracts, repositories, models)
        self.assertEqual(len(repositories[0]["methods"]), 1)
        self.assertEqual(repositories[1]["methods"], [])


class CapabilityAdapterTests(unittest.TestCase):
    def test_a_search_action_gets_a_filter_method_and_retargets(self):
        models = [{"name": "Product", "fields": [
            {"name": "category", "type": "string"}]}]
        services = [{"service_name": "ProductRepository", "methods": [
            {"name": "read_all", "params": [{"name": "category", "type": "str"}],
             "return_type": "list[Product]"}]}]
        adapters = [{"action_name": "search_products_by_category",
                     "target_service": "ProductRepository",
                     "target_method": "read_all",
                     "input_fields": [{"field_name": "category",
                                       "target_param": "category",
                                       "transform": "DIRECT",
                                       "required": True}]}]
        repairs.repair_capability_adapters(None, services, adapters, models, "")
        method = next(m for m in services[0]["methods"]
                      if m["name"] == "search_products_by_category")
        self.assertEqual(method["return_type"], "list[Product]")
        self.assertEqual(method["provenance"], "capability_adapter")
        self.assertTrue(method["review_required"])
        self.assertEqual(adapters[0]["target_method"],
                         "search_products_by_category")

    def test_export_and_prose_import_get_a_service_adapter_and_leaf(self):
        models = [{"name": "Contact", "fields": [
            {"name": "first_name", "type": "string"}]}]
        services = [{"service_name": "ContactRepository", "methods": [
            {"name": "read_all", "params": [], "return_type": "list[Contact]"}]}]
        adapters = [{"action_name": "export_contacts_to_csv",
                     "target_service": "ContactRepository",
                     "target_method": "read_all",
                     "input_fields": []}]
        components = {"facade": {"invocation": {"commands": [{
            "name": "Contact", "options": [], "subcommands": [
                {"name": "export", "options": []}]}]}}}
        requirements = ("Provide commands to export all contacts to CSV and "
                        "import contacts from CSV.")
        repairs.repair_capability_adapters(
            components, services, adapters, models, requirements)
        methods = {m["name"] for service in services
                   for m in service.get("methods") or []}
        self.assertIn("export_contacts_to_csv", methods)
        self.assertIn("import_contacts_from_csv", methods)
        imported = next(a for a in adapters
                        if a["action_name"] == "import_contacts_from_csv")
        self.assertEqual(imported["provenance"], "capability_adapter")
        self.assertTrue(imported["review_required"])
        self.assertIn("import", [sub["name"] for sub in
                                 components["facade"]["invocation"]
                                 ["commands"][0]["subcommands"]])
        # Idempotent: a second repair adds no duplicate method or leaf.
        before = len(adapters)
        repairs.repair_capability_adapters(
            components, services, adapters, models, requirements)
        self.assertEqual(len(adapters), before)


class CapabilityOwnershipTests(unittest.TestCase):
    def test_an_action_cannot_land_on_a_service_that_does_not_own_it(self):
        models = [{"name": "Order", "fields": []}]
        services = [{"service_name": "NotificationService", "methods": [
            {"name": "send_notification", "params": [], "return_type": "None"}]}]
        adapters = [{"action_name": "confirm_order",
                     "target_service": "NotificationService",
                     "target_method": "send_notification",
                     "input_fields": []}]
        repairs.repair_capability_adapters(
            None, services, adapters, models, "")
        self.assertFalse(any(m.get("name") == "confirm_order"
                             for m in services[0]["methods"]))
        self.assertEqual(adapters, [])


class DeterministicAdapterRepairTests(unittest.TestCase):
    def test_an_inferred_create_field_keeps_its_provenance_in_the_adapter(self):
        models = [{"name": "Loan", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "quantity", "type": "int", "nullable": False,
             "status": "inferred from prose"},
        ]}]
        services = [{"service_name": "LoanRepository", "methods": [{
            "name": "create_loan",
            "params": [{"name": "id", "type": "int"},
                       {"name": "quantity", "type": "int"}],
            "return_type": "Loan"}]}]
        adapters = [{"action_name": "loan_add",
                     "target_service": "LoanRepository",
                     "target_method": "create_loan",
                     "input_fields": []}]
        repairs.repair_create_adapter_fields(adapters, services, models)
        field = adapters[0]["input_fields"][-1]
        self.assertEqual(field["field_name"], "quantity")
        self.assertEqual(field["status"], "inferred from prose")

    def test_unknown_lookup_entity_resolves_from_method_name(self):
        adapters = [{"action_name": "product_delete",
                     "target_service": "InventoryService",
                     "target_method": "delete_product", "input_fields": [{
            "field_name": "id", "target_param": "id",
            "transform": "LOOKUP_ID", "lookup_entity": "Inventory",
            "required": True}]}]
        services = [{"service_name": "InventoryService", "methods": [{
            "name": "delete_product",
            "params": [{"name": "id", "type": "int"}]}]}]
        repositories = [{"interface_name": "ProductRepository",
                         "entity": "Product", "methods": []}]
        models = [{"name": "Product", "fields": [{"name": "id"}]}]
        repairs.repair_adapter_lookup_entities(
            adapters, services, repositories, models)
        self.assertEqual(adapters[0]["input_fields"][0]["lookup_entity"],
                         "Product")

    def test_capability_method_retargets_old_parameters(self):
        adapters = [{"action_name": "expenseexport",
                     "target_service": "ExpenseService",
                     "target_method": "expenseexport", "input_fields": [
            {"field_name": "from_date", "target_param": "start_date"},
            {"field_name": "to_date", "target_param": "end_date"},
            {"field_name": "output", "target_param": "file_path"}]}]
        services = [{"service_name": "ExpenseService", "methods": [{
            "name": "expenseexport", "params": [
                {"name": "from_date", "type": "str"},
                {"name": "to_date", "type": "str"},
                {"name": "output", "type": "str"}]}]}]
        repairs.repair_adapter_targets(adapters, services, None)
        self.assertEqual(
            [field["target_param"]
             for field in adapters[0]["input_fields"]],
            ["from_date", "to_date", "output"])

    def test_aggregate_create_falls_back_to_plain_create(self):
        models = [
            {"name": "Order", "fields": [
                {"name": "order_id", "primary_key": True},
                {"name": "status"}]},
            {"name": "OrderLine", "fields": [
                {"name": "order_line_id", "primary_key": True},
                {"name": "order_id"}, {"name": "product_id"},
                {"name": "quantity"}]},
        ]
        services = [{"service_name": "OrderService", "methods": [{
            "name": "create_order_with_lines",
            "params": [{"name": "order_data", "type": "OrderCreateRequest"},
                       {"name": "order_lines_data",
                        "type": "List[OrderLineCreateRequest]"}],
            "return_type": "models.Order"}]}]
        repositories = [{"interface_name": "OrderRepository",
                         "entity": "Order", "methods": [{
            "name": "create",
            "params": [{"name": "status", "type": "str"}]}]}]
        adapters = [{"action_name": "orderadd",
                     "target_service": "OrderService",
                     "target_method": "create_order_with_lines",
                     "input_fields": [
            {"field_name": "product_id", "target_param": "order_data"},
            {"field_name": "quantity", "target_param": "order_data"}]}]
        repairs.repair_aggregate_create_adapters(
            None, adapters, services, repositories, models)
        self.assertEqual(adapters[0]["target_service"], "OrderRepository")
        self.assertEqual(adapters[0]["target_method"], "create")
        self.assertEqual(adapters[0]["input_fields"], [])


class AdapterIdTransformTests(unittest.TestCase):
    def test_bare_id_derives_lookup_entity_from_repository(self):
        adapters = [{"action_name": "categorydelete",
                     "target_service": "CategoryRepository",
                     "target_method": "delete", "input_fields": [{
            "field_name": "id", "target_param": "id",
            "transform": "DIRECT", "lookup_entity": None, "required": True}]}]
        services = [{"service_name": "CategoryRepository", "methods": [{
            "name": "delete", "params": [{"name": "id", "type": "int"}]}]}]
        repairs.repair_adapter_id_transforms(adapters, services)
        field = adapters[0]["input_fields"][0]
        self.assertEqual(field["transform"], "LOOKUP_ID")
        self.assertEqual(field["lookup_entity"], "Category")

    def test_bare_id_derives_lookup_entity_from_target_param(self):
        adapters = [{"action_name": "categoryget",
                     "target_service": "ExpenseRepository",
                     "target_method": "read_one", "input_fields": [{
            "field_name": "id", "target_param": "category_id",
            "transform": "DIRECT", "lookup_entity": None, "required": True}]}]
        services = [{"service_name": "ExpenseRepository", "methods": [{
            "name": "read_one",
            "params": [{"name": "category_id", "type": "int"}]}]}]
        repairs.repair_adapter_id_transforms(adapters, services)
        self.assertEqual(adapters[0]["input_fields"][0]["lookup_entity"],
                         "Category")


class AdapterTransformTests(unittest.TestCase):
    def test_enum_lookup_on_a_bool_field_becomes_direct(self):
        adapters = [{"action_name": "add", "target_service": "BookRepository",
                     "target_method": "create", "input_fields": [{
            "field_name": "availability_status", "target_param": "availability_status",
            "transform": "ENUM_LOOKUP", "lookup_entity": None, "required": True}]}]
        services = [{"service_name": "BookRepository", "methods": [{
            "name": "create", "params": [{"name": "availability_status", "type": "bool"}]}]}]
        repairs.repair_adapter_transforms(adapters, None, services)
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")

    def test_bool_to_one_on_a_non_numeric_target_becomes_direct(self):
        adapters = [{"action_name": "create", "target_service": "OrderService",
                     "target_method": "create_order_with_lines", "input_fields": [{
            "field_name": "is_valid", "target_param": "order_data",
            "transform": "BOOL_TO_ONE", "lookup_entity": None, "required": True}]}]
        services = [{"service_name": "OrderService", "methods": [{
            "name": "create_order_with_lines", "params": [{
                "name": "order_data", "type": "OrderCreationData"}]}]}]
        repairs.repair_adapter_transforms(adapters, None, services)
        self.assertEqual(adapters[0]["input_fields"][0]["transform"], "DIRECT")


if __name__ == "__main__":
    unittest.main()
