"""Mechanical repository completion and custom-method merging."""

import unittest

from kernel.extraction import interfaces, repository_contracts, vocabulary

DATA_MODELS = [
    {
        "name": "Category",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "name", "type": "string"},
        ],
    },
    {
        "name": "Expense",
        "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "amount_cents", "type": "int"},
            {"name": "category_id", "type": "int"},
        ],
    },
]
COMPONENTS = {
    "crud_services": [
        {"entity": "Category", "operations": ["create", "read_one", "read_all",
                                               "update", "delete"]},
        {"entity": "Expense", "operations": ["create", "read_one", "read_all",
                                              "update", "delete"]},
    ]
}
ERRORS = [{"name": "CategoryNotFoundError"}, {"name": "ExpenseNotFoundError"}]


def requirement(entity, operations=None):
    return vocabulary.CrudRequirement(
        entity, tuple(operations or ("create", "read_one", "read_all",
                                     "update", "delete")))


class CompleteTests(unittest.TestCase):
    def test_adds_one_repository_per_entity_with_required_methods(self):
        services = repository_contracts.complete(
            [], DATA_MODELS,
            [requirement("Category"), requirement("Expense")], ERRORS,
        )
        self.assertEqual(
            [service["service_name"] for service in services],
            ["CategoryRepository", "ExpenseRepository"],
        )
        for service in services:
            self.assertEqual(
                [method["name"] for method in service["methods"]],
                ["create", "read_one", "read_all", "update", "delete"],
            )
            self.assertEqual(service["methods"][-1]["return_type"], "None")

    def test_keeps_an_existing_repository_untouched(self):
        services = [{
            "service_name": "CategoryRepository",
            "methods": [{
                "name": "find_by_name",
                "description": "custom",
                "params": [],
                "return_type": "Category",
                "raises": [],
            }],
        }]
        result = repository_contracts.complete(
            services, DATA_MODELS, [requirement("Category")], ERRORS,
        )
        self.assertEqual(result, services)
        self.assertEqual(
            [method["name"] for method in result[0]["methods"]],
            ["find_by_name"],
        )

    def test_does_not_invent_repositories_without_crud_requirements(self):
        self.assertEqual(
            repository_contracts.complete([], DATA_MODELS, [], ERRORS),
            [],
        )


class MergeCustomMethodsTests(unittest.TestCase):
    def test_h_custom_methods_are_added_to_the_e_repository(self):
        services = [{
            "service_name": "CategoryRepository",
            "methods": [{"name": "create", "params": [], "return_type": "Category"}],
        }]
        ports = {
            "repositories": [{
                "entity": "Category",
                "interface_name": "CategoryRepository",
                "methods": [
                    {"name": "create", "params": [], "return_type": "Category"},
                    {"name": "find_expenses_by_category", "params": [],
                     "return_type": "list[Expense]"},
                ],
            }],
        }
        merged = interfaces.merge_repository_methods(services, ports)
        self.assertEqual(
            [method["name"] for method in merged[0]["methods"]],
            ["create", "find_expenses_by_category"],
        )
        self.assertEqual(len(ports["repositories"][0]["methods"]), 2)


if __name__ == "__main__":
    unittest.main()
