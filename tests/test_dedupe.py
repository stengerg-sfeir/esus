"""Tests for the deterministic removal of exactly repeated names.

The first case is the real document that motivated the module: cli_tool's
ProductRepository, which cycled through the other entities of the names block
and never stopped. No model is needed here.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import dedupe  # noqa: E402

# The observed method list, verbatim: nine genuine methods, then a cycle.
CLI_TOOL_PRODUCT_METHODS = [
    "save", "findById", "findByName", "findAll", "update", "delete",
    "getProductStats", "getProductsByPriceRange", "getProductsByStockStatus",
    "orders", "getOrderStats", "order_items", "getOrderItemStats", "products",
    "getProductSales", "order_items", "getOrderItemSales", "orders",
    "getOrderStats", "getOrdersByDateRange", "products", "getProductSales",
    "order_items", "getOrderItemSales", "orders", "getOrderStats",
    "getOrdersByDateRange", "order_items", "getOrderItemSales", "products",
]


def method(name, params=()):
    return {
        "name": name,
        "description": f"{name} description",
        "params": [{"name": p, "type": "int"} for p in params],
        "return_type": "void",
    }


def ports(repositories, mappings=()):
    return {"repositories": repositories, "entity_mappings": list(mappings)}


def repository(entity, methods):
    return {"entity": entity, "interface_name": f"{entity}Repository", "methods": methods}


class RemovesTheObservedLoop(unittest.TestCase):
    def test_repeated_method_names_collapse_to_one_each(self):
        document = ports(
            [
                repository("products", [method(n) for n in CLI_TOOL_PRODUCT_METHODS]),
                repository("orders", [method("save"), method("findById")]),
            ]
        )
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)

        # 30 entries, 17 distinct names: save/findById/findByName/findAll/update/
        # delete, the three getProduct* queries, then the cycle over the other
        # entities. 13 repeats are removed.
        self.assertEqual(removed, 13, "30 methods held 17 distinct names")
        names = [m["name"] for m in cleaned["repositories"][0]["methods"]]
        self.assertEqual(len(names), len(set(names)), "no name may repeat")
        self.assertEqual(
            names[:9],
            CLI_TOOL_PRODUCT_METHODS[:9],
            "the genuine prefix survives untouched, in order",
        )

    def test_untouched_repository_is_not_modified(self):
        document = ports([repository("orders", [method("save"), method("findById")])])
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)

        self.assertEqual(removed, 0)
        self.assertEqual(
            [m["name"] for m in cleaned["repositories"][0]["methods"]], ["save", "findById"]
        )


class Properties(unittest.TestCase):
    def test_first_occurrence_is_the_one_kept(self):
        document = ports(
            [
                repository(
                    "products",
                    [method("save", ["id"]), method("save", ["other"]), method("findAll")],
                )
            ]
        )
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)

        self.assertEqual(removed, 1)
        kept = cleaned["repositories"][0]["methods"][0]
        self.assertEqual(kept["params"], [{"name": "id", "type": "int"}])

    def test_is_idempotent(self):
        document = ports([repository("products", [method(n) for n in CLI_TOOL_PRODUCT_METHODS])])
        once, _ = dedupe.deduplicate("persistence_ports", document)
        twice, removed = dedupe.deduplicate("persistence_ports", once)
        self.assertEqual(removed, 0)
        self.assertEqual(once, twice)

    def test_matching_ignores_case_and_padding(self):
        document = ports(
            [repository("products", [method("save"), method(" Save "), method("SAVE")])]
        )
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)
        self.assertEqual(removed, 2)
        self.assertEqual(cleaned["repositories"][0]["methods"][0]["name"], "save")

    def test_duplicate_parameters_are_removed_within_a_method(self):
        document = ports(
            [repository("products", [method("find", ["id", "id", "name"])])]
        )
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)
        self.assertEqual(removed, 1)
        self.assertEqual(
            [p["name"] for p in cleaned["repositories"][0]["methods"][0]["params"]],
            ["id", "name"],
        )

    def test_duplicate_indexes_are_removed(self):
        document = ports(
            [repository("products", [method("save")])],
            [{"entity": "products", "indexes": ["sku", "sku", "name"]}],
        )
        cleaned, removed = dedupe.deduplicate("persistence_ports", document)
        self.assertEqual(removed, 1)
        self.assertEqual(cleaned["entity_mappings"][0]["indexes"], ["sku", "name"])

    def test_service_contracts_are_handled_too(self):
        services = [
            {
                "service_name": "BookService",
                "methods": [method("add_book"), method("add_book"), method("find_book")],
            }
        ]
        cleaned, removed = dedupe.deduplicate("service_contracts", services)
        self.assertEqual(removed, 1)
        self.assertEqual(
            [m["name"] for m in cleaned[0]["methods"]], ["add_book", "find_book"]
        )

    def test_other_documents_pass_through(self):
        payload = ["a", "a"]
        cleaned, removed = dedupe.deduplicate("intentions", payload)
        self.assertEqual(removed, 0)
        self.assertIs(cleaned, payload)

    def test_missing_or_malformed_input_is_tolerated(self):
        for key, body in (
            ("persistence_ports", None),
            ("persistence_ports", []),
            ("persistence_ports", {}),
            ("service_contracts", None),
            ("service_contracts", {}),
        ):
            cleaned, removed = dedupe.deduplicate(key, body)
            self.assertEqual(removed, 0)
            self.assertEqual(cleaned, body)


def component_facade(commands):
    return {
        "facade": {
            "type": "cli",
            "technology": "click",
            "invocation": {"positional": [], "options": [], "commands": commands},
        }
    }


class RemovesRepeatedCliCommands(unittest.TestCase):
    """library listed `member` twice — the same defect as a method repeat, one level out."""

    def test_a_repeated_command_name_is_removed(self):
        body = component_facade(
            [
                {"name": "member", "options": [], "subcommands": [{"name": "add", "options": []}]},
                {"name": "member", "options": [], "subcommands": [{"name": "history", "options": []}]},
            ]
        )
        cleaned, removed = dedupe.deduplicate("components", body)
        self.assertEqual(removed, 1)
        commands = cleaned["facade"]["invocation"]["commands"]
        self.assertEqual([command["name"] for command in commands], ["member"])

    def test_a_repeated_subcommand_name_is_removed(self):
        body = component_facade(
            [
                {
                    "name": "product",
                    "options": [],
                    "subcommands": [
                        {"name": "list", "options": []},
                        {"name": "list", "options": []},
                    ],
                }
            ]
        )
        cleaned, removed = dedupe.deduplicate("components", body)
        self.assertEqual(removed, 1)
        subcommands = cleaned["facade"]["invocation"]["commands"][0]["subcommands"]
        self.assertEqual(len(subcommands), 1)

    def test_a_differently_cased_name_is_left_alone(self):
        """`member` and `Member` are a judgement about meaning; this module makes none."""
        body = component_facade(
            [
                {"name": "member", "options": [], "subcommands": []},
                {"name": "Member", "options": [], "subcommands": []},
            ]
        )
        cleaned, removed = dedupe.deduplicate("components", body)
        self.assertEqual(removed, 0)
        self.assertEqual(len(cleaned["facade"]["invocation"]["commands"]), 2)

    def test_a_null_invocation_is_untouched(self):
        body = {"facade": {"type": "gui", "technology": "pyimgui", "invocation": None}}
        cleaned, removed = dedupe.deduplicate("components", body)
        self.assertEqual((cleaned, removed), (body, 0))


class MergesServicesThatShareAName(unittest.TestCase):
    """60 emitted `CategoryRepository` twice and `OrderService` three times.

    That is one service whose methods were written in several entries, and a
    second registration of a name is what a program cannot have — so the entries
    are merged, and only then are repeated method names dropped.
    """

    def test_entries_sharing_a_name_become_one(self):
        services = [
            {"service_name": "OrderService", "methods": [method("create_order")]},
            {"service_name": "OrderService", "methods": [method("cancel_order")]},
            {"service_name": "OrderService", "methods": [method("confirm_order")]},
        ]
        cleaned, removed = dedupe.deduplicate("service_contracts", services)
        self.assertEqual(removed, 2, "two duplicate entries collapse")
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(
            [m["name"] for m in cleaned[0]["methods"]],
            ["create_order", "cancel_order", "confirm_order"],
            "methods keep the order they were written in",
        )

    def test_a_method_repeated_across_entries_is_dropped_once(self):
        services = [
            {"service_name": "ProductRepository", "methods": [method("read_all"), method("update")]},
            {"service_name": "ProductRepository", "methods": [method("update"), method("delete")]},
        ]
        cleaned, removed = dedupe.deduplicate("service_contracts", services)
        self.assertEqual(removed, 2, "one merged entry plus one repeated method")
        self.assertEqual(
            [m["name"] for m in cleaned[0]["methods"]], ["read_all", "update", "delete"]
        )

    def test_the_first_spelling_and_order_are_kept(self):
        services = [
            {"service_name": "BookService", "methods": [method("add_book")]},
            {"service_name": "CategoryService", "methods": [method("add_category")]},
            {"service_name": "bookservice", "methods": [method("find_book")]},
        ]
        cleaned, removed = dedupe.deduplicate("service_contracts", services)
        self.assertEqual(removed, 1)
        self.assertEqual([s["service_name"] for s in cleaned], ["BookService", "CategoryService"])
        self.assertEqual(
            [m["name"] for m in cleaned[0]["methods"]], ["add_book", "find_book"]
        )

    def test_distinct_services_are_untouched(self):
        services = [
            {"service_name": "BookService", "methods": [method("add_book")]},
            {"service_name": "AuthorService", "methods": [method("add_author")]},
        ]
        cleaned, removed = dedupe.deduplicate("service_contracts", services)
        self.assertEqual(removed, 0)
        self.assertEqual([s["service_name"] for s in cleaned], ["BookService", "AuthorService"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
