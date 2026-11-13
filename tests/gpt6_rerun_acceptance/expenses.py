"""Acceptance checks for the 2026-11-13 GPT-6 Luna expenses output."""

from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import date
from pathlib import Path

from common import Suite, equal, fetchall, main, raises, require, run_python


def make_env(suite: Suite, name: str):
    suite.import_from(suite.out, "expense_tracker")
    from expense_tracker import (
        BudgetRepository, CategoryRepository, Database, ExpenseRepository, ExpenseService,
    )
    db = suite.db(name)
    database = Database(db)
    categories = CategoryRepository(database)
    expenses = ExpenseRepository(database)
    budgets = BudgetRepository(database)
    service = ExpenseService(expenses, categories, budgets)
    return database, categories, expenses, budgets, service


def add_category(categories, name="Food", description="Groceries", budget=None):
    from expense_tracker import Category
    return categories.create(Category(name=name, description=description, monthly_budget=budget))


def add_expense(service, category_id, amount=1000, description="Lunch",
                expense_date="2024-01-15", method="card"):
    from expense_tracker import Expense
    return service.add_expense(Expense(
        amount_cents=amount, description=description, expense_date=expense_date,
        category_id=category_id, payment_method=method,
    ))


def run(suite: Suite) -> int:
    @suite.check("schema has table-level budget uniqueness and foreign keys")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        database, _, _, _, _ = make_env(suite, "schema.sqlite3")
        database.close()
        sql = " ".join(row["sql"] or "" for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE type='table'")).upper()
        require("UNIQUE" in sql, "no unique constraint")
        require("UNIQUE(CATEGORY_ID" in sql.replace(" ", "") or
                "UNIQUE (CATEGORY_ID" in sql, "budget uniqueness is not table-level")
        require("REFERENCES" in sql or "FOREIGN KEY" in sql, "no FK")
        require("CHECK" in sql, "no checks")
        return "schema constraints"

    @suite.check("category CRUD and duplicate names")
    def categories(_: Suite) -> str:
        database, categories, _, _, _ = make_env(suite, "categories.sqlite3")
        try:
            category = add_category(categories)
            equal(category.name, "Food", "name")
            equal(categories.get_by_name("Food").id, category.id, "lookup")
            updated = categories.update(category.id, name="Dining")
            equal(updated.name, "Dining", "update")
            raises(Exception, lambda: add_category(categories, name="Dining"), "duplicate")
            require(categories.delete(category.id), "delete")
            require(categories.get_by_id(category.id) is None, "deleted row")
            return "create/read/update/delete"
        finally:
            database.close()

    @suite.check("expense CRUD and optional filters")
    def expenses(_: Suite) -> str:
        database, categories, _, _, service = make_env(suite, "expenses.sqlite3")
        try:
            food = add_category(categories)
            travel = add_category(categories, name="Travel", description="Transit")
            first = add_expense(service, food.id, 1299, "Lunch", "2024-01-12", "card")
            second = add_expense(service, travel.id, 700, "Bus", "2024-02-02", "cash")
            equal(len(service.list_expenses()), 2, "all")
            equal([item.id for item in service.list_expenses(
                category_id=food.id, start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31), payment_method="card")], [first.id], "filters")
            updated = service.update_expense(first.id, {"description": "Dinner"})
            equal(updated.description, "Dinner", "update")
            service.delete_expense(second.id)
            raises(Exception, lambda: service.get_expense_by_id(second.id), "deleted")
            return "CRUD and filters"
        finally:
            database.close()

    @suite.check("expenses validate category existence")
    def foreign_key(_: Suite) -> str:
        database, _, _, _, service = make_env(suite, "fk.sqlite3")
        try:
            raises(Exception, lambda: add_expense(service, 999), "unknown category")
            return "category validation"
        finally:
            database.close()

    @suite.check("budget uniqueness and exceeded notification after insertion")
    def budget(_: Suite) -> str:
        database, categories, _, budgets, service = make_env(suite, "budget.sqlite3")
        try:
            food = add_category(categories)
            from expense_tracker import Budget
            budget = budgets.create(Budget(category_id=food.id, month="2024-01",
                                           amount_limit_cents=1000))
            require(budget.id is not None, "budget id")
            raises(sqlite3.IntegrityError, lambda: budgets.create(Budget(
                category_id=food.id, month="2024-01", amount_limit_cents=2000)), "duplicate")
            add_expense(service, food.id, 700)
            error = raises(Exception, lambda: add_expense(service, food.id, 400), "over budget")
            equal(getattr(error, "spent_cents", None), 1100, "reported spend")
            equal(len(service.list_expenses(category_id=food.id)), 2, "insert retained")
            return "unique budget and exceeded"
        finally:
            database.close()

    @suite.check("monthly report totals, breakdown and budget status")
    def monthly(_: Suite) -> str:
        database, categories, _, budgets, service = make_env(suite, "monthly.sqlite3")
        try:
            food = add_category(categories)
            from expense_tracker import Budget
            budgets.create(Budget(category_id=food.id, month="2024-01", amount_limit_cents=5000))
            add_expense(service, food.id, 4500, "Shopping", "2024-01-15")
            add_expense(service, food.id, 2500, "Trip", "2024-03-15")
            report = service.get_monthly_report("2024-01")
            equal(report["total_spent_cents"], 4500, "total")
            equal(report["budget_status"], "warning", "status")
            equal(report["categories"][0]["category_name"], "Food", "category")
            raises(ValueError, lambda: service.get_monthly_report("2024-13"), "bad month")
            return "monthly report"
        finally:
            database.close()

    @suite.check("yearly summary includes monthly totals, top categories and average")
    def yearly(_: Suite) -> str:
        database, categories, _, _, service = make_env(suite, "yearly.sqlite3")
        try:
            food = add_category(categories)
            travel = add_category(categories, name="Travel")
            add_expense(service, food.id, 4500, "Food", "2024-01-15")
            add_expense(service, travel.id, 2500, "Trip", "2024-03-15")
            summary = service.get_yearly_summary(2024)
            equal(summary["monthly_totals"]["2024-01"], 4500, "January")
            equal(summary["monthly_totals"]["2024-03"], 2500, "March")
            equal(summary["top_categories"][0]["category_id"], food.id, "top category")
            equal(summary["average_monthly_spend_cents"], 7000 / 12, "average")
            return "yearly summary"
        finally:
            database.close()

    @suite.check("category spending is filtered by date")
    def category_spending(_: Suite) -> str:
        database, categories, _, _, service = make_env(suite, "spending.sqlite3")
        try:
            food = add_category(categories)
            add_expense(service, food.id, 1200, "one", "2024-01-10")
            add_expense(service, food.id, 800, "two", "2024-02-10")
            equal(service.get_category_spending(food.id, date(2024, 1, 1), date(2024, 1, 31)),
                  1200, "January spending")
            return "category period aggregate"
        finally:
            database.close()

    @suite.check("CSV export writes filtered rows and decimal display")
    def export(_: Suite) -> str:
        database, categories, _, _, service = make_env(suite, "export.sqlite3")
        try:
            food = add_category(categories)
            add_expense(service, food.id, 1200, "Subscription", "2024-01-10")
            add_expense(service, food.id, 500, "Other", "2024-02-10")
            path = suite.path("expenses.csv")
            count = service.export_to_csv(path, date(2024, 1, 1), date(2024, 1, 31))
            equal(count, 1, "exported count")
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            equal(rows[0]["amount"], "12.00", "decimal amount")
            return "CSV export"
        finally:
            database.close()

    @suite.check("recurring detection marks consecutive-month matches")
    def recurring(_: Suite) -> str:
        database, categories, _, _, service = make_env(suite, "recurring.sqlite3")
        try:
            food = add_category(categories)
            for expense_date in ("2024-01-10", "2024-02-10", "2024-03-10"):
                add_expense(service, food.id, 1200, "Subscription", expense_date)
            add_expense(service, food.id, 1200, "Unrelated", "2024-06-10")
            marked = service.detect_recurring()
            equal(len(marked), 3, "marked rows")
            require(all(item.is_recurring for item in marked), "not marked")
            return "consecutive-month detection"
        finally:
            database.close()

    @suite.check("Click CLI drives categories, budgets, expenses and reports")
    def cli(_: Suite) -> str:
        db = suite.path("cli.sqlite3")
        env = {"EXPENSE_DB_PATH": str(db)}
        category = run_python(suite.out, [
            "-m", "expense_tracker", "category", "add",
            "--name", "Food", "--description", "Groceries",
        ], env=env)
        require("Created category" in category.stdout, category.stdout)
        budget = run_python(suite.out, [
            "-m", "expense_tracker", "budget", "add",
            "--category-id", "1", "--month", "2024-01", "--amount", "100.00",
        ], env=env)
        require("Created budget" in budget.stdout, budget.stdout)
        expense = run_python(suite.out, [
            "-m", "expense_tracker", "add",
            "--amount", "12.50", "--description", "Lunch",
            "--category", "1", "--expense-date", "2024-01-15",
        ], env=env)
        require("Created expense" in expense.stdout, expense.stdout)
        report = run_python(suite.out, [
            "-m", "expense_tracker", "report", "monthly", "--month", "2024-01",
        ], env=env)
        require("12.50" in report.stdout and "on_track" in report.stdout, report.stdout)
        return "nested CLI"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("expenses", sys.argv[1] if len(sys.argv) > 1 else None, run))
