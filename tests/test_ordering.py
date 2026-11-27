"""Deterministic document order and role-suffixed extraction names."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import (  # noqa: E402
    grammar_check,
    grammar_open,
    grammar_persistence,
    ordering,
    repairs,
    vocabulary,
    writer,
)


class CanonicalOrderTests(unittest.TestCase):
    def test_models_are_sorted_but_fields_keep_their_order(self):
        models = [
            {"name": "Zeta", "fields": [
                {"name": "zeta_id", "primary_key": True},
                {"name": "label"}]},
            {"name": "alpha", "fields": [
                {"name": "alpha_id", "primary_key": True},
                {"name": "label"}]},
        ]
        ordered = ordering.canonicalize("data_models", models)
        self.assertEqual([model["name"] for model in ordered],
                         ["alpha", "Zeta"])
        self.assertEqual([field["name"] for field in ordered[1]["fields"]],
                         ["zeta_id", "label"])

    def test_services_and_methods_are_sorted_but_params_keep_their_order(self):
        services = [
            {"service_name": "ZetaService", "methods": [
                {"name": "read_zeta",
                 "params": [{"name": "zeta_id"}, {"name": "mode"}]},
                {"name": "add_zeta", "params": []}]},
            {"service_name": "AlphaRepository", "methods": [
                {"name": "read_one", "params": [{"name": "alpha_id"}]}]},
        ]
        ordered = ordering.canonicalize("service_contracts", services)
        self.assertEqual([service["service_name"] for service in ordered],
                         ["AlphaRepository", "ZetaService"])
        self.assertEqual([method["name"] for method in ordered[1]["methods"]],
                         ["add_zeta", "read_zeta"])
        self.assertEqual(
            [param["name"] for param in ordered[1]["methods"][1]["params"]],
            ["zeta_id", "mode"])

    def test_errors_adapter_actions_and_crud_entities_are_sorted(self):
        errors = ordering.canonicalize(
            "errors", [{"name": "ZetaError"}, {"name": "AlphaError"}])
        self.assertEqual([error["name"] for error in errors],
                         ["AlphaError", "ZetaError"])
        adapters = ordering.canonicalize(
            "interaction_adapters",
            [{"action_name": "zeta"}, {"action_name": "alpha"}])
        self.assertEqual([adapter["action_name"] for adapter in adapters],
                         ["alpha", "zeta"])
        components = ordering.canonicalize("components", {
            "crud_services": [{"entity": "Zeta"}, {"entity": "Alpha"}]})
        self.assertEqual([item["entity"] for item in components["crud_services"]],
                         ["Alpha", "Zeta"])

    def test_a_missing_ports_section_is_not_invented(self):
        body = {"repositories": []}
        self.assertEqual(
            ordering.canonicalize("persistence_ports", body), body)

    def test_writing_the_same_facts_in_another_order_writes_the_same_bytes(self):
        first = {"data_models": [
            {"name": "Zeta", "fields": [{"name": "id", "primary_key": True}]},
            {"name": "Alpha", "fields": [{"name": "id", "primary_key": True}]},
        ]}
        second = {"data_models": list(reversed(first["data_models"]))}
        with tempfile.TemporaryDirectory() as directory:
            first_path = writer.write_documents(
                Path(directory) / "first", first)[0]
            second_path = writer.write_documents(
                Path(directory) / "second", second)[0]
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            text = first_path.read_text(encoding="utf-8")
            self.assertLess(text.index('"Alpha"'), text.index('"Zeta"'))


class VocabularyOrderTests(unittest.TestCase):
    def test_entities_services_and_errors_are_sorted_for_the_prompt(self):
        entities = vocabulary.entities_from([
            {"name": "Zeta", "fields": [{"name": "id", "primary_key": True}]},
            {"name": "Alpha", "fields": [{"name": "id", "primary_key": True}]},
        ])
        self.assertEqual([entity.name for entity in entities],
                         ["Alpha", "Zeta"])
        services = vocabulary.services_from([
            {"service_name": "ZetaService", "methods": [
                {"name": "read_zeta", "params": []}]},
            {"service_name": "AlphaService", "methods": [
                {"name": "read_alpha", "params": []}]},
        ])
        self.assertEqual([service.name for service in services],
                         ["AlphaService", "ZetaService"])
        block = vocabulary.Vocabulary(
            errors=({"name": "ZetaError"}, {"name": "AlphaError"})
        ).errors_block()
        self.assertLess(block.index("AlphaError"), block.index("ZetaError"))


class NamingGrammarTests(unittest.TestCase):
    def test_error_names_must_end_in_error_or_exception(self):
        text = grammar_open.errors()
        self.assertIn("error-name", text)
        self.assertIn('("Error" | "Exception")', text)
        self.assertEqual(grammar_check.check(text), [])

    def test_service_names_must_end_in_service_or_repository(self):
        text = grammar_open.service_contracts()
        self.assertIn("service-name", text)
        self.assertIn('("Service" | "Repository")', text)
        self.assertEqual(grammar_check.check(text), [])

    def test_persistence_interfaces_must_end_in_repository(self):
        text = grammar_open.persistence_ports()
        self.assertIn("repository-name", text)
        self.assertEqual(grammar_check.check(text), [])
        vocab = vocabulary.Vocabulary(
            entities=vocabulary.entities_from([
                {"name": "Book",
                 "fields": [{"name": "id", "primary_key": True}]}]),
            crud_entities=("Book",),
        )
        text = grammar_persistence.persistence_ports(vocab)
        self.assertIn("repository-name", text)
        self.assertEqual(grammar_check.check(text), [])


class HolderNameRepairTests(unittest.TestCase):
    def test_suffixes_and_every_reference_are_repaired_together(self):
        documents = {
            "service_contracts": [
                {"service_name": "Expense", "methods": [{
                    "name": "add_expense", "params": [],
                    "raises": ["BudgetExceeded"]}]},
                {"service_name": "BudgetRepo", "methods": []},
            ],
            "persistence_ports": {"repositories": [
                {"entity": "Expense", "interface_name": "Expense",
                 "methods": []},
            ]},
            "errors": [
                {"name": "BudgetExceeded", "base": "RuntimeError"},
            ],
            "interaction_adapters": [
                {"action_name": "add_expense", "target_service": "Expense",
                 "target_method": "add_expense"},
            ],
        }
        contracts = [{
            "holder": "Expense",
            "method": "add_expense",
            "bindings": [{"repository": "Expense", "method": "read_one"}],
            "creates": [{"call": "Expense.create"}],
        }]
        returned = repairs.repair_holder_names(documents, contracts)
        services = {
            service["service_name"]: service
            for service in documents["service_contracts"]}
        self.assertIn("ExpenseService", services)
        self.assertIn("BudgetRepository", services)
        self.assertEqual(
            services["ExpenseService"]["methods"][0]["raises"],
            ["BudgetExceededError"])
        self.assertEqual(documents["errors"][0]["name"], "BudgetExceededError")
        self.assertEqual(
            documents["persistence_ports"]["repositories"][0]["interface_name"],
            "ExpenseRepository")
        self.assertEqual(
            documents["interaction_adapters"][0]["target_service"],
            "ExpenseService")
        self.assertIs(returned, contracts)
        self.assertEqual(contracts[0]["holder"], "ExpenseService")
        self.assertEqual(
            contracts[0]["bindings"][0]["repository"], "ExpenseRepository")
        self.assertEqual(
            contracts[0]["creates"][0]["call"], "ExpenseRepository.create")

    def test_already_canonical_names_are_not_changed(self):
        documents = {
            "service_contracts": [
                {"service_name": "ExpenseService", "methods": [{
                    "name": "add_expense", "params": [],
                    "raises": ["BudgetExceededException"]}]},
            ],
            "persistence_ports": {"repositories": [
                {"entity": "Expense", "interface_name": "ExpenseRepository",
                 "methods": []},
            ]},
            "errors": [
                {"name": "BudgetExceededException", "base": "RuntimeError"},
            ],
            "interaction_adapters": [
                {"action_name": "add_expense",
                 "target_service": "ExpenseService",
                 "target_method": "add_expense"},
            ],
        }
        before = json.dumps(documents, sort_keys=True)
        repairs.repair_holder_names(documents, None)
        self.assertEqual(json.dumps(documents, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
