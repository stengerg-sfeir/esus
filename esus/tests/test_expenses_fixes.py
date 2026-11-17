"""The expenses prompt's schema and date-filter defects, pinned.

`UNIQUE(category_id, month)` is a table-level constraint on the pair, not a
unique `month`; a filter over a date column compares the read dataclass's
`datetime.date` with a CLI ISO string.
"""

import datetime as dt
import ast
import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generator  # noqa: E402
from kernel import codegen  # noqa: E402


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


class UpdateBodyTests(unittest.TestCase):
    def test_a_mapping_parameter_is_a_model_target(self):
        adapters = [{
            "action_name": "catupdate",
            "target_service": "CategoryRepository",
            "target_method": "update",
            "input_fields": [
                {"field_name": "id", "target_param": "id"},
                {"field_name": "name", "target_param": "data"},
            ],
        }]
        repositories = [{
            "entity": "Category",
            "interface_name": "CategoryRepository",
            "methods": [{"name": "update", "params": [
                {"name": "id", "type": "int"},
                {"name": "data", "type": "dict[str, any]"}]}],
        }]
        targets = codegen.action_targets(adapters, [], repositories, ["Category"])
        self.assertEqual(targets["catupdate"]["data"],
                         codegen.MAPPING_TARGET + "Category")

    def test_a_data_mapping_is_merged_into_the_patch(self):
        ctx = budget_ctx()
        ctx["entity_names"] = ["Category"]
        body = generator._update_body(
            ctx, {"name": "update"},
            [("id", "id", "int"), ("data", "data", "dict[str, any]")],
            "Category", "models.Category",
            ["id", "name", "description", "monthly_budget", "icon"],
            "errors.CategoryNotFoundError")
        text = "\n".join(body)
        self.assertIn("for key, value in data.items():", text)
        self.assertIn("patch[key] = value", text)
        self.assertNotIn("patch['data']", text)
        compile("def f(self, id=None, data=None):\n"
                + "\n".join("    " + line for line in body),
                "body.py", "exec")

    def test_a_composite_key_names_the_record_to_update(self):
        ctx = budget_ctx()
        ctx["entity_names"] = ["Budget"]
        body = generator._update_body(
            ctx, {"name": "update"},
            [("category_id", "category_id", "int"),
             ("month", "month", "str"),
             ("amount_limit_cents", "amount_limit_cents", "int")],
            "Budget", "models.Budget",
            ["id", "category_id", "month", "amount_limit_cents"],
            "errors.CategoryNotFoundError")
        text = "\n".join(body)
        self.assertIn("criteria.append(('category_id', 'eq', category_id))",
                      text)
        self.assertIn("criteria.append(('month', 'eq', month))", text)
        self.assertNotIn("criteria.append(('amount_limit_cents', 'eq'", text)
        self.assertIn("patch['amount_limit_cents'] = amount_limit_cents", text)


class BudgetCheckTests(unittest.TestCase):
    def body(self):
        ctx = budget_ctx()
        ctx["models"].append({"name": "Expense", "fields": [
            {"name": "amount_cents", "type": "int"},
            {"name": "category_id", "type": "int"},
            {"name": "expense_date", "type": "date"}]})
        method = {"name": "check_budget_exceeded", "return_type": "bool",
                  "params": [{"name": "category_id", "type": "int"},
                             {"name": "month", "type": "str"}]}
        return generator._repo_budget_check_body(
            ctx, "Budget", method, "check_budget_exceeded",
            {"spend_entity": "Expense", "limit_field": "amount_limit_cents",
             "target_field": "amount_cents", "date_field": "expense_date"})

    def check(self, budgets, expenses):
        body = self.body()
        code = ("class Self:\n"
                "    ENTITY = 'Budget'\n"
                "    def __init__(self, store):\n"
                "        self._store = store\n"
                "def f(self, category_id=None, month=None):\n"
                + "\n".join("    " + line for line in body))
        namespace = {}
        exec(code, namespace)  # noqa: S102

        class Store:
            def select(self, entity, criteria):
                return budgets if entity == "Budget" else expenses

        return namespace["f"](namespace["Self"](Store()), 1, "2024-01")

    def test_no_budget_means_not_exceeded(self):
        self.assertFalse(self.check([], []))

    def test_spending_above_the_limit_is_exceeded(self):
        self.assertTrue(self.check(
            [{"category_id": 1, "month": "2024-01",
              "amount_limit_cents": 1000}],
            [{"amount_cents": 1500, "category_id": 1,
              "expense_date": "2024-01-10"}]))

    def test_spending_below_the_limit_is_not_exceeded(self):
        self.assertFalse(self.check(
            [{"category_id": 1, "month": "2024-01",
              "amount_limit_cents": 1000}],
            [{"amount_cents": 500, "category_id": 1,
              "expense_date": "2024-01-10"}]))


class PromptPrefixTests(unittest.TestCase):
    def test_the_method_specific_part_comes_after_the_shared_module(self):
        module = "class S:\n    pass\n"
        first = generator.stub_prompt(
            "requirements", module,
            {"cls": "S", "def": "def a(self):", "reason": "one",
             "file": "services.py"},
            context="exact")
        second = generator.stub_prompt(
            "requirements", module,
            {"cls": "S", "def": "def b(self):", "reason": "two",
             "file": "services.py"},
            context="exact")
        self.assertGreater(first.index("- The method is "),
                           first.index("module (services.py):"))
        cut = first.index("- The method is ")
        self.assertEqual(first[:cut], second[:second.index("- The method is ")])


class ServiceMutationTests(unittest.TestCase):
    def test_an_unsaved_dataclass_mutation_is_refused(self):
        body = ["expenses = self._repos['ExpenseRepository'].read_all()",
                "for expense in expenses:",
                "    expense.is_recurring = True",
                "return expenses"]
        info = {"file": "services.py", "cls": "ExpenseService",
                "method": "detect_recurring",
                "def": "def detect_recurring(self) -> list[models.Expense]:",
                "docstring": '        """x"""'}
        module = ("import models\nclass ExpenseService:\n"
                  "    def detect_recurring(self) -> list[models.Expense]:\n"
                  "        raise NotImplementedError\n")
        complaints = generator._body_complaints(
            body, info, module, "", {"repositories.py": ""})
        self.assertTrue(any("never calls a repository update" in item
                            for item in complaints))


class PostWriteRaiseTests(unittest.TestCase):
    def test_a_colon_requirement_line_is_found(self):
        line = generator._requirements_line(
            "- add_expense: validates the category, adds the expense, "
            "checks after insertion", "add_expense")
        self.assertIn("after insertion", line)

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

    def test_an_unrelated_validation_error_stays_before_the_create(self):
        self.assertFalse(generator._permits_post_write_raise(
            "add_expense: adds expense, checks budget after insertion",
            {"preconditions": []}, "ValueError"))


class CreateReturnTests(unittest.TestCase):
    def test_a_quoted_vocabulary_is_read(self):
        ctx = budget_ctx(invariants=[{
            "text": "Expense.payment_method must be one of "
                    "'cash', 'card', 'transfer'"}])
        self.assertEqual(
            generator._field_vocabulary(ctx, "Expense", "payment_method"),
            ["cash", "card", "transfer"])

    def test_an_int_create_returns_the_new_key(self):
        ctx = budget_ctx()
        body = generator._create_body(
            ctx, {"name": "create", "return_type": "int"},
            [("name", "name", "str")], "Expense", "models.Expense",
            ["id", "name"], "[]")
        self.assertIn("return record[self.PK]", "\n".join(body))

    def test_an_entity_create_returns_the_model(self):
        ctx = budget_ctx()
        body = generator._create_body(
            ctx, {"name": "create", "return_type": "Expense"},
            [("name", "name", "str")], "Expense", "models.Expense",
            ["id", "name"], "[]")
        self.assertIn("return models.Expense(**record)", "\n".join(body))


class RepositoryCallTests(unittest.TestCase):
    REFERENCES = """class CategoryRepository:
    def find_expenses_by_category(self, category_id: int = None) -> list:
class ExpenseRepository:
    def read_all(self) -> list:
"""

    def test_a_method_on_the_wrong_repository_is_named(self):
        tree = ast.parse("def _wrapped(self):\n"
                         "    self._repos['ExpenseRepository']"
                         ".find_expenses_by_category(1)\n")
        complaints = generator._repository_call_complaints(
            tree, self.REFERENCES)
        self.assertEqual(len(complaints), 1)
        self.assertIn("ExpenseRepository", complaints[0])
        self.assertIn("CategoryRepository", complaints[0])

    def test_a_declared_repository_method_is_accepted(self):
        tree = ast.parse("def _wrapped(self):\n"
                         "    self._repos['ExpenseRepository'].read_all()\n")
        self.assertEqual(
            generator._repository_call_complaints(tree, self.REFERENCES), [])

    def test_a_field_dict_in_a_scalar_parameter_is_refused(self):
        references = """class ExpenseRepository:
    def update(self, id: int = None, amount_cents: int = None, is_recurring: bool = None) -> bool:
class CategoryRepository:
    def update(self, id: int = None, data: dict = None) -> object:
"""
        tree = ast.parse("def _wrapped(self):\n"
                         "    self._repos['ExpenseRepository']"
                         ".update(1, {'is_recurring': True})\n")
        complaints = generator._positional_dict_complaints(tree, references)
        self.assertEqual(len(complaints), 1)
        self.assertIn("amount_cents", complaints[0])
        allowed = ast.parse("def _wrapped(self):\n"
                            "    self._repos['CategoryRepository']"
                            ".update(1, {'name': 'x'})\n")
        self.assertEqual(
            generator._positional_dict_complaints(allowed, references), [])

    def test_an_int_create_result_read_as_a_record_is_refused(self):
        references = """class ExpenseRepository:
    def create(self, amount_cents: int = None) -> int:
    def read_one(self, id: int = None) -> object:
"""
        tree = ast.parse("def _wrapped(self):\n"
                         "    expense = self._repos['ExpenseRepository']"
                         ".create(amount_cents=1)\n"
                         "    return expense.expense_date\n")
        complaints = generator._scalar_return_complaints(tree, references)
        self.assertEqual(len(complaints), 1)
        self.assertIn("expense.expense_date", complaints[0])
        okay = ast.parse("def _wrapped(self):\n"
                         "    expense_id = self._repos['ExpenseRepository']"
                         ".create(amount_cents=1)\n"
                         "    return self._repos['ExpenseRepository']"
                         ".read_one(expense_id)\n")
        self.assertEqual(
            generator._scalar_return_complaints(okay, references), [])


if __name__ == "__main__":
    unittest.main()
