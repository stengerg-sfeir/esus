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


if __name__ == "__main__":
    unittest.main(verbosity=2)
