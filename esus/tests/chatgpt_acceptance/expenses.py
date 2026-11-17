"""Independent acceptance checks for the direct GPT-6 Luna expense tracker.

The delivered package currently imports on Python 3.14 but not on Python 3.12
because of class-scope annotation shadowing.  Run this suite with 3.14 to
exercise the behavior; ``compat.py`` records the 3.12 import failure.
"""

from __future__ import annotations

import contextlib
import csv
import io
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

from common import (
    Suite, clean_error, equal, fetchall, main, raises, require,
)


def make_service(suite: Suite, db: Path):
    suite.import_from(suite.out / "src", "expense_tracker")
    from expense_tracker.database import Database
    from expense_tracker.services import ExpenseService
    return ExpenseService(Database(db))


def category(service, name="Food", description="Meals", budget=None, icon=None):
    return service.add_category(name, description, budget, icon)


def expense(service, category_id, amount=1000, when="2024-01-15",
            method="card", description="Lunch"):
    return service.add_expense(amount, description, category_id,
                               date.fromisoformat(when), method, False)


def cli_invoke(suite: Suite, db: Path, group: str, args: list[str]):
    suite.import_from(suite.out / "src", "expense_tracker")
    from click.testing import CliRunner
    from expense_tracker.cli import budget_cli, expense_cli
    old = os.environ.get("EXPENSE_DB_PATH")
    os.environ["EXPENSE_DB_PATH"] = str(db)
    try:
        result = CliRunner().invoke(expense_cli if group == "expense" else budget_cli, args)
    finally:
        if old is None:
            os.environ.pop("EXPENSE_DB_PATH", None)
        else:
            os.environ["EXPENSE_DB_PATH"] = old
    return result


def run(suite: Suite) -> int:
    @suite.check("schema has table-level UNIQUE(category_id, month) and FKs")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        make_service(suite, db)
        rows = fetchall(db, "SELECT name, sql FROM sqlite_master WHERE type='table'")
        text = " ".join(row["sql"] or "" for row in rows)
        require(re.search(r"UNIQUE\s*\(\s*category_id\s*,\s*month\s*\)", text, re.I),
                "missing table-level UNIQUE(category_id, month)")
        require("REFERENCES" in text.upper(), "missing foreign keys")
        require("CHECK" in text.upper(), "missing checks")
        return "table-level unique and FKs"

    @suite.check("category CRUD stores optional cents and icon")
    def categories(_: Suite) -> str:
        db = suite.db("categories.sqlite3")
        service = make_service(suite, db)
        item = category(service, budget=2500, icon="🍲")
        equal((item.name, item.monthly_budget, item.icon), ("Food", 2500, "🍲"),
              "category fields")
        equal(service.list_categories()[0].name, "Food", "category list")
        updated = service.update_category(item.id, {"name": "Dining", "monthly_budget": 3000})
        equal((updated.name, updated.monthly_budget), ("Dining", 3000), "updated category")
        raises(Exception, lambda: category(service, name="Dining"), "duplicate name")
        service.delete_category(item.id)
        equal(service.list_categories(), [], "deleted category")
        return "category CRUD"

    @suite.check("expense add/get/update/delete and validation")
    def expenses(_: Suite) -> str:
        db = suite.db("expenses.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        item = expense(service, food.id, amount=1250, when="2024-02-03")
        equal((item.amount_cents, item.expense_date), (1250, date(2024, 2, 3)),
              "expense fields")
        equal(service.get_expense_by_id(item.id).description, "Lunch", "get expense")
        updated = service.update_expense(item.id, {"amount_cents": 1500,
                                                   "description": "Dinner"})
        equal((updated.amount_cents, updated.description), (1500, "Dinner"), "update")
        service.delete_expense(item.id)
        raises(Exception, lambda: service.get_expense_by_id(item.id), "deleted expense")
        raises(Exception, lambda: service.add_expense(100, "No category", 999,
                                                      date(2024, 1, 1), "cash"),
               "unknown category")
        raises(Exception, lambda: service.add_expense(-1, "Negative", food.id,
                                                      date(2024, 1, 1), "cash"),
               "negative amount")
        raises(Exception, lambda: service.add_expense(100, "Bad method", food.id,
                                                      date(2024, 1, 1), "cheque"),
               "bad payment method")
        return "expense CRUD and validation"

    @suite.check("budget CRUD, uniqueness and month validation")
    def budgets(_: Suite) -> str:
        db = suite.db("budgets.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        budget = service.add_budget(food.id, "2024-01", 10000)
        equal(budget.month, "2024-01", "budget month")
        equal(service.budgets.list(category_id=food.id, month="2024-01")[0].amount_limit_cents,
              10000, "budget list")
        updated = service.budgets.update(food.id, "2024-01", 12000)
        equal(updated.amount_limit_cents, 12000, "budget update")
        raises(Exception, lambda: service.add_budget(food.id, "2024-01", 1),
               "duplicate category/month")
        raises(Exception, lambda: service.add_budget(food.id, "2024-13", 1),
               "invalid month")
        service.budgets.delete(food.id, "2024-01")
        equal(service.budgets.list(), [], "budget delete")
        return "budget CRUD"

    @suite.check("list filters by category, date and payment method")
    def filters(_: Suite) -> str:
        db = suite.db("filters.sqlite3")
        service = make_service(suite, db)
        food = category(service, name="Food")
        travel = category(service, name="Travel")
        expense(service, food.id, 100, "2024-01-01", "cash", "A")
        expense(service, food.id, 200, "2024-02-01", "card", "B")
        expense(service, travel.id, 300, "2024-02-02", "card", "C")
        equal(len(service.list_expenses()), 3, "no filters")
        equal([e.amount_cents for e in service.list_expenses(category_id=food.id)],
              [100, 200], "category filter")
        equal([e.amount_cents for e in service.list_expenses(
            start_date=date(2024, 2, 1), end_date=date(2024, 2, 2))],
              [200, 300], "date filter")
        equal([e.amount_cents for e in service.list_expenses(payment_method="cash")],
              [100], "method filter")
        raises(Exception, lambda: service.list_expenses(
            start_date=date(2024, 2, 1), end_date=date(2024, 1, 1)), "inverted dates")
        return "optional filters"

    @suite.check("monthly report totals, zero categories and budget statuses")
    def monthly_report(_: Suite) -> str:
        db = suite.db("monthly.sqlite3")
        service = make_service(suite, db)
        on_track = category(service, name="OnTrack")
        warning = category(service, name="Warning")
        exceeded = category(service, name="Exceeded")
        empty = category(service, name="Empty")
        service.add_budget(on_track.id, "2024-01", 1000)
        service.add_budget(warning.id, "2024-01", 1000)
        service.add_budget(exceeded.id, "2024-01", 1000)
        expense(service, on_track.id, 500, "2024-01-02")
        expense(service, warning.id, 800, "2024-01-03")
        raises(Exception, lambda: expense(service, exceeded.id, 1200, "2024-01-04"),
               "exceeded budget is reported")
        report = service.get_monthly_report("2024-01")
        equal(report["total_spent_cents"], 2500, "total")
        rows = {row["category"]: row for row in report["categories"]}
        equal(set(rows), {"OnTrack", "Warning", "Exceeded", "Empty"}, "zero category")
        equal(rows["OnTrack"]["budget_status"], "on_track", "on track")
        equal(rows["Warning"]["budget_status"], "warning", "warning")
        equal(rows["Exceeded"]["budget_status"], "exceeded", "exceeded")
        equal(rows["Empty"]["total_cents"], 0, "empty total")
        return "monthly statuses"

    @suite.check("monthly report works for February and December")
    def calendar(_: Suite) -> str:
        db = suite.db("calendar.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        expense(service, food.id, 100, "2024-02-29")
        expense(service, food.id, 200, "2024-12-31")
        equal(service.get_monthly_report("2024-02")["total_spent_cents"], 100, "February")
        equal(service.get_monthly_report("2024-12")["total_spent_cents"], 200, "December")
        return "calendar boundaries"

    @suite.check("yearly summary exposes months, top categories and average")
    def yearly(_: Suite) -> str:
        db = suite.db("yearly.sqlite3")
        service = make_service(suite, db)
        food = category(service, name="Food")
        travel = category(service, name="Travel")
        expense(service, food.id, 1000, "2024-01-10")
        expense(service, food.id, 2000, "2024-02-10")
        expense(service, travel.id, 500, "2024-02-11")
        summary = service.get_yearly_summary(2024)
        equal(summary["year"], 2024, "year")
        equal(summary["monthly_totals"],
              [{"month": "2024-01", "total_cents": 1000},
               {"month": "2024-02", "total_cents": 2500}], "monthly totals")
        equal(summary["top_categories"][0]["category"], "Food", "top category")
        equal(summary["total_spent_cents"], 3500, "total")
        require(summary["average_monthly_spend_cents"] > 0, "average")
        return "yearly report"

    @suite.check("category spending and category expense lookup")
    def category_spending(_: Suite) -> str:
        db = suite.db("category-spend.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        expense(service, food.id, 100, "2024-01-01")
        expense(service, food.id, 250, "2024-01-31")
        equal(service.get_category_spending(food.id, date(2024, 1, 1),
                                            date(2024, 1, 31)), 350, "spending")
        equal([item.amount_cents for item in service.categories.find_expenses(food.id)],
              [100, 250], "category expenses")
        return "category aggregation"

    @suite.check("CSV export is filtered and has the requested columns")
    def export(_: Suite) -> str:
        db = suite.db("export.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        expense(service, food.id, 1250, "2024-01-15", "card", "Lunch")
        expense(service, food.id, 999, "2024-02-15", "cash", "Dinner")
        target = suite.path("expenses.csv")
        count = service.export_to_csv(target, date(2024, 1, 1), date(2024, 1, 31))
        equal(count, 1, "export count")
        with target.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        equal(len(rows), 1, "CSV rows")
        equal(rows[0]["amount"], "12.50", "decimal amount")
        equal(rows[0]["description"], "Lunch", "description")
        require({"id", "date", "amount", "description", "category",
                 "payment_method", "is_recurring"} <= set(rows[0]), "CSV columns")
        return "filtered CSV"

    @suite.check("budget overage is stored and reported after insertion")
    def overage(_: Suite) -> str:
        db = suite.db("overage.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        service.add_budget(food.id, "2024-01", 1000)
        from expense_tracker.exceptions import BudgetExceededException
        error = raises(BudgetExceededException, lambda: expense(
            service, food.id, 1200, "2024-01-01"), "budget overage")
        require(error.expense_id is not None, "exception has no expense id")
        equal(len(service.list_expenses()), 1, "expense persisted")
        return "stored then raised"

    @suite.check("recurring detection marks matching amount/category months")
    def recurring(_: Suite) -> str:
        db = suite.db("recurring.sqlite3")
        service = make_service(suite, db)
        food = category(service)
        travel = category(service, name="Travel")
        expense(service, food.id, 1000, "2024-01-10", description="Rent")
        expense(service, food.id, 1000, "2024-02-10", description="Rent")
        expense(service, food.id, 1200, "2024-02-10", description="Other")
        expense(service, travel.id, 1000, "2024-02-10", description="Travel")
        marked = service.detect_recurring()
        equal(len(marked), 2, "marked rows")
        flags = {(item.amount_cents, item.category_id, item.description): item.is_recurring
                 for item in service.list_expenses()}
        equal(flags[(1000, food.id, "Rent")], True, "recurring flag")
        equal(flags[(1200, food.id, "Other")], False, "different amount")
        equal(flags[(1000, travel.id, "Travel")], False, "different category")
        return "monthly recurrence"

    @suite.check("CLI category/expense/budget commands work")
    def cli_expense(_: Suite) -> str:
        db = suite.db("cli.sqlite3")
        result = cli_invoke(suite, db, "expense",
                            ["category", "add", "--name", "Food",
                             "--description", "Meals", "--budget", "30.00"])
        require(result.exit_code == 0, f"category add failed: {result.output!r}")
        match = re.search(r"Created category (\d+)", result.output)
        require(match is not None, f"category id missing: {result.output!r}")
        category_id = match.group(1)
        result = cli_invoke(suite, db, "expense",
                            ["add", "--amount", "12.50", "--description", "Lunch",
                             "--category", category_id, "--method", "card"])
        require(result.exit_code == 0, f"expense add failed: {result.output!r}")
        result = cli_invoke(suite, db, "expense",
                            ["report", "monthly", "--month", "2024-01"])
        require(result.exit_code == 0, f"monthly report failed: {result.output!r}")
        result = cli_invoke(suite, db, "budget",
                            ["add", "--category-id", category_id, "--month", "2024-01",
                             "--amount", "30.00"])
        require(result.exit_code == 0, f"budget add failed: {result.output!r}")
        result = cli_invoke(suite, db, "budget", ["list", "--month", "2024-01"])
        require(result.exit_code == 0 and "30.00" in result.output,
                f"budget list failed: {result.output!r}")
        return "click groups"

    @suite.check("CLI domain error is clean and nonzero")
    def cli_error(_: Suite) -> str:
        db = suite.db("cli-error.sqlite3")
        result = cli_invoke(suite, db, "expense",
                            ["add", "--amount", "10", "--description", "Bad",
                             "--category", "999"])
        require(result.exit_code != 0, "missing category succeeded")
        clean_error(result, "missing category")
        return "clean click error"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("expenses", sys.argv[1] if len(sys.argv) > 1 else None, run))
