"""The expenses prompt's schema and date-filter defects, pinned.

`UNIQUE(category_id, month)` is a table-level constraint on the pair, not a
unique `month`; a filter over a date column compares the read dataclass's
`datetime.date` with a CLI ISO string.
"""

import datetime as dt
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402


def store_module():
    spec = importlib.util.spec_from_file_location(
        "esus_store_under_test", ROOT / "kernel" / "codegen_store_template.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def budget_ctx(**overrides):
    ctx = {
        "models": [{"name": "Budget", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "category_id", "type": "int"},
            {"name": "month", "type": "string", "unique": True},
            {"name": "amount_limit_cents", "type": "int"},
        ]}],
        "invariants": [{"text": "Budget must have a unique combination "
                                "of category_id and month"}],
        "requirements": "UNIQUE(category_id, month)",
        "errors": [], "repositories": [], "services": [], "adapters": [],
        "components": {}, "mappings": {}, "match_index": {},
        "entity_names": ["Budget"], "slots": {}, "contracts": [], "routes": [],
    }
    ctx.update(overrides)
    return ctx


class CompositeUniqueTests(unittest.TestCase):
    def test_the_pair_is_unique_and_month_is_not_unique_alone(self):
        ctx = budget_ctx()
        self.assertEqual(generator._unique_fields(ctx, "Budget"), [])
        self.assertEqual(generator._unique_groups(ctx, "Budget"),
                         [("category_id", "month")])
        namespace = {}
        exec(generator.emit_schema(ctx), namespace)  # noqa: S102
        schema = namespace["SCHEMA"]
        self.assertEqual(schema["Budget"]["unique_together"],
                         [["category_id", "month"]])
        month = next(field for field in schema["Budget"]["fields"]
                     if field["name"] == "month")
        self.assertFalse(month["unique"])

    def test_an_invariant_phrase_can_declare_the_pair(self):
        ctx = budget_ctx(requirements="",
                         invariants=[{"text": "Budget must have a unique "
                                              "constraint on (category_id, month)"}])
        self.assertEqual(generator._unique_groups(ctx, "Budget"),
                         [("category_id", "month")])

    def test_the_store_creates_a_table_level_unique_constraint(self):
        namespace = {}
        exec(generator.emit_schema(budget_ctx()), namespace)  # noqa: S102
        store = store_module().Store(":memory:", namespace["SCHEMA"])
        row = {"category_id": 1, "month": "2024-01", "amount_limit_cents": 5000}
        store.add("Budget", "id", row, [])
        store.add("Budget", "id", {**row, "category_id": 2}, [])
        with self.assertRaises(sqlite3.IntegrityError):
            store.add("Budget", "id", row, [])
        ddl = store._db.execute(
            "SELECT sql FROM sqlite_master WHERE name='Budget'").fetchone()[0]
        self.assertIn('UNIQUE ("category_id", "month")', ddl)
        store.close()

    def test_an_individual_unique_field_is_still_emitted(self):
        ctx = budget_ctx(invariants=[{"text": "Budget.month must be unique"}],
                         requirements="")
        self.assertEqual(generator._unique_fields(ctx, "Budget"), ["month"])
        self.assertEqual(generator._unique_groups(ctx, "Budget"), [])

    def test_a_library_like_context_has_no_composite_key(self):
        ctx = budget_ctx(
            models=[{"name": "Book", "fields": [
                {"name": "id", "type": "int", "primary_key": True},
                {"name": "isbn", "type": "string", "unique": True},
            ]}],
            invariants=[{"text": "Book.isbn must be unique"}],
            requirements="", entity_names=["Book"])
        self.assertEqual(generator._unique_groups(ctx, "Book"), [])
        self.assertEqual(generator._unique_fields(ctx, "Book"), ["isbn"])


def filter_ctx(params, field_type="date"):
    return {
        "models": [{"name": "Expense", "fields": [
            {"name": "id", "type": "int", "primary_key": True},
            {"name": "description", "type": "string"},
            {"name": "expense_date", "type": field_type},
            {"name": "payment_method", "type": "string"},
        ]}],
        "repositories": [{"entity": "Expense",
                          "interface_name": "ExpenseRepository",
                          "methods": [{"name": "read_all_expenses",
                                       "params": [],
                                       "return_type": "List[Expense]"}]}],
        "services": [{"service_name": "ExpenseService", "methods": [
            {"name": "list_expenses", "params": params,
             "return_type": "List[Expense]"}]}],
        "errors": [], "invariants": [], "requirements": "", "mappings": {},
        "match_index": {}, "entity_names": ["Expense"], "adapters": [],
        "components": {}, "slots": {}, "contracts": [], "routes": [],
    }


def service_text(ctx):
    stats = {"implemented": 0, "stubs": 0, "stub_reasons": []}
    return generator.emit_services(
        ctx, generator._repo_index(ctx), stats)


class DateFilterTests(unittest.TestCase):
    def test_a_date_criterion_normalises_both_sides(self):
        text = service_text(filter_ctx([
            {"name": "start_date", "type": "Optional[str]"},
            {"name": "end_date", "type": "Optional[str]"},
        ]))
        self.assertIn("def _filter_value(value):", text)
        self.assertIn("_holds(_filter_value(row.get(field)), operator,", text)
        self.assertIn("_filter_value(value))", text)
        compile(text, "services.py", "exec")

    def test_a_non_date_filter_does_not_grow_the_module(self):
        text = service_text(filter_ctx([
            {"name": "payment_method", "type": "Optional[str]"}]))
        self.assertNotIn("_filter_value", text)
        self.assertIn("_holds(row.get(field), operator, value)", text)

    def test_the_normaliser_matches_a_date_and_its_iso_text(self):
        namespace = {}
        text = service_text(filter_ctx([
            {"name": "start_date", "type": "Optional[str]"}]))
        # Execute only the helper, not the module's imports/classes.
        start = text.index("def _filter_value")
        end = text.index("class ExpenseService")
        exec(text[start:end], namespace)  # noqa: S102
        value = dt.date(2024, 1, 10)
        self.assertEqual(namespace["_filter_value"](value), "2024-01-10")
        self.assertEqual(namespace["_filter_value"]("2024-01-10"), "2024-01-10")
        self.assertIsNone(namespace["_filter_value"](None))


class PostWriteRaiseTests(unittest.TestCase):
    def test_after_insertion_permits_a_non_precondition_raise(self):
        self.assertTrue(generator._permits_post_write_raise(
            "add_expense: validates category exists, adds expense, checks if "
            "budget exceeded after insertion",
            {"preconditions": [{"error": "CategoryNotFoundError"}]},
            "BudgetExceededException"))

    def test_a_precondition_still_cannot_follow_the_create(self):
        self.assertFalse(generator._permits_post_write_raise(
            "add_expense: validates category exists, adds expense, checks "
            "after insertion",
            {"preconditions": [{"error": "CategoryNotFoundError"}]},
            "CategoryNotFoundError"))

    def test_without_after_insertion_the_generic_rule_stands(self):
        self.assertFalse(generator._permits_post_write_raise(
            "add_expense: validates category exists and adds the expense",
            {"preconditions": [{"error": "CategoryNotFoundError"}]},
            "BudgetExceededException"))


if __name__ == "__main__":
    unittest.main()
