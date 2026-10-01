"""Tests for the repository-interface unification between steps E and H.

The behaviour under test: a repository declared in both `service_contracts` and
`persistence_ports` is one class, so it has one method set, and step E owns it.
"""

import unittest

from kernel.consistency.naming import normalize as checker_normalize
from kernel.extraction.interfaces import normalize, unify_repository_interfaces


def method(name, params=()):
    return {
        "name": name,
        "description": "does a thing",
        "params": [{"name": p, "type": "int"} for p in params],
        "return_type": "Result",
    }


def service(name, methods):
    return {"service_name": name, "methods": methods}


def port(name, entity, methods):
    return {"entity": entity, "interface_name": name, "methods": methods}


def ports(repositories, mappings=()):
    return {"repositories": list(repositories), "entity_mappings": list(mappings)}


class NormalizeAgreementTests(unittest.TestCase):
    """The extractor pairs the documents by the same key the checker does."""

    def test_matches_the_checker_for_the_names_that_occur(self):
        for name in (
            "WineRepository",
            "winerepository",
            "Wine_Repository",
            "CategoryRepository",
            "StorageLocationRepository",
            "BookRepository",
            "ExpenseRepository",
            "CategoryService",
            "OrderItemService",
        ):
            with self.subTest(name=name):
                self.assertEqual(normalize(name), checker_normalize(name))

    def test_a_service_is_not_confused_with_a_repository(self):
        self.assertNotEqual(normalize("WineService"), normalize("WineRepository"))


class UnifyRepositoryInterfacesTests(unittest.TestCase):
    """A doubly-declared repository adopts E's methods verbatim."""

    def test_adopts_e_methods_for_a_doubly_declared_repository(self):
        e_methods = [method("create_wine", ("name",)), method("delete_wine", ("wine_id",))]
        h_methods = [method("save_wine", ("name",)), method("update_wine_price", ("price",))]
        result = unify_repository_interfaces(
            ports([port("WineRepository", "Wine", h_methods)]),
            [service("WineRepository", e_methods)],
            None,
        )
        repository = result["repositories"][0]
        self.assertEqual([m["name"] for m in repository["methods"]], ["create_wine", "delete_wine"])
        self.assertEqual(repository["entity"], "Wine", "the mapping side is untouched")

    def test_adopts_e_spelling_of_the_interface_name(self):
        result = unify_repository_interfaces(
            ports([port("winerepository", "Wine", [method("save_wine")])]),
            [service("WineRepository", [method("create_wine", ("name",))])],
            None,
        )
        self.assertEqual(result["repositories"][0]["interface_name"], "WineRepository")

    def test_an_undeclared_repository_keeps_hs_own_methods(self):
        """60's repositories are a persistence-layer invention, so H owns them."""
        h_methods = [method("find_by_name", ("name",)), method("find_all")]
        result = unify_repository_interfaces(
            ports([port("CategoryRepository", "categories", h_methods)]),
            [service("CategoryService", [method("get_category_by_id", ("category_id",))])],
            None,
        )
        repository = result["repositories"][0]
        self.assertEqual([m["name"] for m in repository["methods"]], ["find_by_name", "find_all"])
        self.assertEqual(repository["interface_name"], "CategoryRepository")

    def test_domain_services_are_never_adopted_as_repositories(self):
        """`ExpenseService` methods are domain logic, not storage."""
        result = unify_repository_interfaces(
            ports([port("ExpenseRepository", "Expense", [method("save_expense", ("expense",))])]),
            [service("ExpenseService", [method("detect_recurring", ("repository",))])],
            None,
        )
        self.assertEqual(result["repositories"][0]["methods"][0]["name"], "save_expense")

    def test_entity_mappings_are_preserved(self):
        mapping = {"entity": "Wine", "table": "wines", "primary_key": "id", "indexes": ["name"]}
        result = unify_repository_interfaces(
            {
                "repositories": [port("WineRepository", "Wine", [method("save_wine")])],
                "entity_mappings": [mapping],
            },
            [service("WineRepository", [method("create_wine", ("name",))])],
            None,
        )
        self.assertEqual(result["entity_mappings"], [mapping])

    def test_missing_or_unusable_documents_are_returned_unchanged(self):
        document = ports([port("WineRepository", "Wine", [method("save_wine")])])
        for services in (None, [], "nonsense", [{"service_name": None, "methods": []}]):
            with self.subTest(services=services):
                self.assertIs(
                    unify_repository_interfaces(document, services, None),
                    document,
                    "nothing to adopt leaves the document identical",
                )

    def test_a_service_with_no_methods_declares_no_interface(self):
        result = unify_repository_interfaces(
            ports([port("WineRepository", "Wine", [method("save_wine")])]),
            [service("WineRepository", [])],
            None,
        )
        self.assertEqual(result["repositories"][0]["methods"][0]["name"], "save_wine")


if __name__ == "__main__":
    unittest.main()
