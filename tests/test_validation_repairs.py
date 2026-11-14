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


class EmptyDomainTests(unittest.TestCase):
    def test_an_order_application_gets_an_inferred_model_and_crud(self):
        requirements = ("Create a Python 3.12 order application. When an order "
                        "is confirmed, send a notification.")
        models = repairs.repair_empty_domain([], requirements)
        self.assertEqual(models[0]["name"], "Order")
        self.assertEqual(models[0]["fields"][1]["name"], "status")
        components = {"persistence": {"required": False, "technology": "none"},
                      "crud_services": []}
        repairs.repair_empty_domain_components(components, models)
        self.assertEqual(components["crud_services"][0]["entity"], "Order")
        self.assertTrue(components["persistence"]["required"])
        self.assertEqual(components["persistence"]["technology"], "sqlite")

    def test_a_statement_without_an_application_noun_stays_empty(self):
        self.assertEqual(
            repairs.repair_empty_domain([], "Print hello world."), [])


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
        self.assertTrue(any(a["action_name"] == "import_contacts_from_csv"
                            for a in adapters))
        self.assertIn("import", [sub["name"] for sub in
                                 components["facade"]["invocation"]
                                 ["commands"][0]["subcommands"]])
        # Idempotent: a second repair adds no duplicate method or leaf.
        before = len(adapters)
        repairs.repair_capability_adapters(
            components, services, adapters, models, requirements)
        self.assertEqual(len(adapters), before)


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
