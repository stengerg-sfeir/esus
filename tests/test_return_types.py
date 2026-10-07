"""The entity a generic return stands for.

A signature is a specification the generated body must honour, so a method that
declares `dict[str, object]` where the entity is known produces a repository whose
declared type contradicts what it operates on. These tests pin how the entity is
decided, and — as importantly — that an undecidable method is *left alone and
logged* rather than guessed at.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kernel.extraction import return_types  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message.strip())


def models(*names):
    return [{"name": name, "fields": []} for name in names]


def service(name, *methods):
    return {
        "service_name": name,
        "methods": [{"name": m, "return_type": "dict[str, object]"} for m in methods],
    }


def repository(entity, interface, *methods):
    return {
        "entity": entity,
        "interface_name": interface,
        "methods": [{"name": m, "return_type": "dict[str, object]"} for m in methods],
    }


class SpellingTests(unittest.TestCase):
    """Every generic spelling the corpus uses is rewritten, and nothing else is."""

    def test_each_generic_spelling_becomes_the_entity(self):
        for spelling, expected in (
            ("dict[str, object]", "Category"),
            ("list[dict[str, object]]", "list[Category]"),
            ("List[dict[str, object]]", "List[Category]"),
            ("dict[str, object] | None", "Category | None"),
            ("Optional[dict[str, object]]", "Optional[Category]"),
        ):
            with self.subTest(spelling=spelling):
                holder = service("CategoryRepository", "read_all_categories")
                holder["methods"][0]["return_type"] = spelling
                fixed = return_types.repair_contract_returns(
                    [holder], models("Category"), Log()
                )
                self.assertEqual(fixed[0]["methods"][0]["return_type"], expected)

    def test_an_entity_typed_return_is_left_alone(self):
        """`List[Book]` is already right; rewriting it would be the defect."""
        holder = service("BookRepository", "read_all_books")
        holder["methods"][0]["return_type"] = "List[Book]"
        fixed = return_types.repair_contract_returns([holder], models("Book"), Log())
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "List[Book]")

    def test_an_aggregate_return_is_left_alone(self):
        holder = service("ExpenseRepository", "spend_by_month")
        holder["methods"][0]["return_type"] = "Dict[str, int]"
        fixed = return_types.repair_contract_returns([holder], models("Expense"), Log())
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "Dict[str, int]")


class HolderTests(unittest.TestCase):
    """A repository names its entity, so its methods are decided by the holder."""

    def test_a_repository_method_takes_its_declared_entity(self):
        holder = repository("Category", "CategoryRepository", "read_all_categories")
        holder["methods"][0]["return_type"] = "list[dict[str, object]]"
        fixed = return_types.repair_port_returns(
            {"repositories": [holder]}, models("Category", "Product"), Log()
        )
        self.assertEqual(
            fixed["repositories"][0]["methods"][0]["return_type"], "list[Category]"
        )

    def test_a_contract_takes_the_entity_its_service_is_about(self):
        fixed = return_types.repair_contract_returns(
            [service("CategoryRepository", "read_all_categories")],
            models("Category", "Product"),
            Log(),
        )
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "Category")

    def test_a_holder_that_names_no_entity_is_left_alone_and_logged(self):
        """`InventoryService` is neither entity; its generic returns stay as they are."""
        log = Log()
        fixed = return_types.repair_contract_returns(
            [service("InventoryService", "restock")], models("Category", "Product"), log
        )
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "dict[str, object]")
        self.assertTrue(any("restock" in line for line in log.lines))

    def test_an_unresolvable_repository_entity_is_left_alone(self):
        fixed = return_types.repair_port_returns(
            {"repositories": [repository("Widget", "WidgetRepository", "read_all_widgets")]},
            models("Category"),
            Log(),
        )
        self.assertEqual(
            fixed["repositories"][0]["methods"][0]["return_type"], "dict[str, object]"
        )


class MethodNameTests(unittest.TestCase):
    """The method's own name decides when the holder cannot."""

    def test_a_service_named_for_nothing_uses_the_method_name(self):
        fixed = return_types.repair_contract_returns(
            [service("InventoryService", "add_product")], models("Category", "Product"), Log()
        )
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "Product")

    def test_the_object_is_read_before_the_by_filter(self):
        """**The wrong repair this rule was found by.**

        `get_products_by_category` returns products, not categories, so the
        `_by_` tail is a filter and the object is `get_products`. Without the cut
        the name mentions two entities, deferring to the holder answered
        `Category`, and the generated repository would have returned the wrong
        type.
        """
        self.assertEqual(return_types._object_part("get_products_by_category"), "get_products")
        self.assertEqual(return_types._object_part("read_all_categories"), "read_all_categories")

    def test_a_name_disagreeing_with_its_holder_is_repaired_and_logged(self):
        log = Log()
        fixed = return_types.repair_contract_returns(
            [service("CategoryRepository", "get_products_by_category")],
            models("Category", "Product"),
            log,
        )
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "Product")
        self.assertTrue(
            any("but its holder is Category" in line for line in log.lines),
            f"the conflict must be reported, got: {log.lines}",
        )

    def test_a_name_mentioning_two_entities_defers_to_the_holder(self):
        """No positional guess: two mentions hand the decision back."""
        fixed = return_types.repair_contract_returns(
            [service("CategoryRepository", "list_category_and_product")],
            models("Category", "Product"),
            Log(),
        )
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "Category")


class MalformedInputTests(unittest.TestCase):
    def test_a_missing_ports_object_is_returned_unchanged(self):
        self.assertIsNone(return_types.repair_port_returns(None, models("Category"), Log()))

    def test_ports_without_a_repository_list_are_returned_unchanged(self):
        ports = {"entity_mappings": []}
        self.assertIs(return_types.repair_port_returns(ports, models("Category"), Log()), ports)

    def test_no_models_means_nothing_to_resolve(self):
        holders = [service("CategoryRepository", "create_category")]
        fixed = return_types.repair_contract_returns(holders, [], Log())
        self.assertEqual(fixed[0]["methods"][0]["return_type"], "dict[str, object]")

    def test_a_method_that_is_not_an_object_is_left_in_place(self):
        holder = {"service_name": "CategoryRepository", "methods": ["broken"]}
        fixed = return_types.repair_contract_returns([holder], models("Category"), Log())
        self.assertEqual(fixed[0]["methods"], ["broken"])

    def test_a_holder_without_methods_is_left_in_place(self):
        holder = {"service_name": "CategoryRepository"}
        fixed = return_types.repair_contract_returns([holder], models("Category"), Log())
        self.assertEqual(fixed[0], holder)


if __name__ == "__main__":
    unittest.main(verbosity=2)
