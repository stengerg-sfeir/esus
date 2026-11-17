"""A criterion on a date column compares like with like.

Schema mode restores date columns to `datetime.date`, while criteria were
normalised to ISO text: `le`/`ge` raised `TypeError` and `eq` silently
matched nothing, so an overdue query could not run.
"""

import datetime
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def store_class():
    spec = importlib.util.spec_from_file_location(
        "esus_store_under_test", ROOT / "kernel" / "codegen_store_template.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.Store


def column(name, type_, primary_key=False, nullable=False):
    return {"name": name, "type": type_, "primary_key": primary_key,
            "nullable": nullable,
            "unique": primary_key, "foreign_key": None, "default": None}


SCHEMA = {"Loan": {"primary_key": "id", "fields": [
    column("id", "int", primary_key=True),
    column("due_date", "date"),
    column("return_date", "date", nullable=True)]}}


class StoreDateCriteriaTests(unittest.TestCase):
    def setUp(self):
        self.store = store_class()(schema=SCHEMA)
        self.today = datetime.date(2026, 11, 3)
        for due in (-3, 0, 5):
            self.store.add("Loan", "id", {
                "due_date": self.today + datetime.timedelta(days=due)}, [])

    def tearDown(self):
        self.store._db.close()

    def due(self, operator, value):
        return sorted(row["id"] for row in self.store.select(
            "Loan", [("due_date", operator, value)]))

    def test_le_against_a_date_object_does_not_raise(self):
        self.assertEqual(self.due("le", self.today), [1, 2])

    def test_ge_against_a_date_object_does_not_raise(self):
        self.assertEqual(self.due("ge", self.today), [2, 3])

    def test_eq_against_a_date_object_matches(self):
        self.assertEqual(self.due("eq", self.today), [2])

    def test_lt_is_strict_so_a_loan_due_today_is_not_before_today(self):
        self.assertEqual(self.due("lt", self.today), [1])

    def test_gt_is_strict(self):
        self.assertEqual(self.due("gt", self.today), [3])

    def test_a_null_criterion_still_matches_null_columns(self):
        self.assertEqual(sorted(row["id"] for row in self.store.select(
            "Loan", [("return_date", "eq", None)])), [1, 2, 3])

    def test_a_date_criterion_skips_null_columns_for_ordering(self):
        self.assertEqual(sorted(row["id"] for row in self.store.select(
            "Loan", [("return_date", "le", self.today)])), [])


if __name__ == "__main__":
    unittest.main()
