#!/usr/bin/env python3
"""A common, prompt-derived behavior score for three expenses implementations.

The apps have different layouts and output formats, so this evaluator drives
each through its own CLI, inspects the SQLite database, and treats the prompt
as the contract. It does not use either app's own tests.

    python3 scripts/score_expenses_common.py
"""

import ast
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import e2e_library_acceptance as lib  # noqa: E402

TODAY = __import__("datetime").date.today().isoformat()
PY = sys.executable
ESUS = ROOT / "out" / "expenses_correct"
GPT = Path("/var/folders/kk/xjh_78x515g6lld88l0c_q2m0000gp/T/esus-big-expenses-raw")
GPT2 = Path("/var/folders/kk/xjh_78x515g6lld88l0c_q2m0000gp/T/esus-big-expenses-raw-2")
GEMINI = ROOT / "out" / "expenses_gemini"


class App:
    def __init__(self, name, root, kind):
        self.name = name
        self.root = Path(root)
        self.kind = kind
        self.scratch = Path(tempfile.mkdtemp(prefix=f"score-{name}-"))
        self.case = 0
        self.cwd = self.scratch
        self.db = self.scratch / "db.sqlite3"

    # -- command execution ------------------------------------------------
    def run(self, args, expect=0):
        if self.kind == "esus":
            cmd = [PY, str(self.root / "generated" / "cli.py"),
                   "--db", str(self.db), *args]
            cwd = str(self.cwd)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        elif self.kind == "gpt":
            if args and args[0] == "budget":
                cmd = [PY, "-m", "expense_tracker.budget_cli",
                       "--db", str(self.db), *args[1:]]
            else:
                cmd = [PY, "-m", "expense_tracker",
                       "--db", str(self.db), *args[1:]]
            cwd = str(self.cwd)
            env = dict(os.environ, PYTHONPATH=str(self.root),
                       PYTHONDONTWRITEBYTECODE="1")
        elif self.kind == "gpt2":
            mapped = args[1:] if args and args[0] == "expense" else args
            cmd = [PY, "-m", "expense_tracker", "--database", str(self.db),
                   *mapped]
            cwd = str(self.cwd)
            env = dict(os.environ, PYTHONPATH=str(self.root),
                       PYTHONDONTWRITEBYTECODE="1")
        elif self.kind == "gemini":
            mapped = args[1:] if args and args[0] == "expense" else args
            cmd = [PY, str(self.root / "cli.py"), *mapped]
            cwd = str(self.cwd)
            env = dict(os.environ, PYTHONPATH=str(self.root),
                       PYTHONDONTWRITEBYTECODE="1")
        else:
            raise ValueError(self.kind)
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                                text=True)
        if expect is None:
            return result
        if expect == "nonzero":
            if result.returncode == 0:
                raise AssertionError(
                    f"{args!r} returned 0, expected non-zero; "
                    f"stdout={result.stdout!r}; stderr={result.stderr!r}")
        elif result.returncode != expect:
            raise AssertionError(
                f"{args!r} returned {result.returncode}, expected {expect}; "
                f"stdout={result.stdout!r}; stderr={result.stderr!r}")
        return result

    def fresh(self):
        self.case += 1
        self.cwd = self.scratch / f"case{self.case}"
        self.cwd.mkdir(parents=True, exist_ok=True)
        self.db = self.cwd / (
            "expenses.db" if self.kind == "gemini" else "app.sqlite3")
        self.run(["expense", "category", "list"])
        return self.db

    def con(self):
        return sqlite3.connect(self.db)

    def tables(self):
        connection = self.con()
        try:
            return {
                "category": lib.table_with(
                    connection, {"id", "name", "description"})[0],
                "expense": lib.table_with(
                    connection, {"id", "amount_cents", "category_id"})[0],
                "budget": lib.table_with(
                    connection, {"id", "month", "amount_limit_cents"})[0],
            }
        finally:
            connection.close()

    def rows(self, table, **criteria):
        connection = self.con()
        try:
            return lib.rows_for(connection, table, **criteria)
        finally:
            connection.close()

    def text_rows(self, output):
        if self.kind == "esus":
            rows = []
            for line in output.splitlines():
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    rows.append(value)
            return rows
        rows = []
        for line in output.splitlines():
            if not line.strip():
                continue
            if self.kind in ("gpt", "gpt2"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    rows.append({"description": parts[-1]})
            else:
                match = re.search(r"\s-\s(.*)$", line)
                if match:
                    rows.append({"description": match.group(1)})
        return rows

    def source_files(self):
        if self.kind == "esus":
            directory = self.root / "generated"
        elif self.kind in ("gpt", "gpt2"):
            directory = self.root / "expense_tracker"
        else:
            directory = self.root
        return sorted(p for p in directory.glob("*.py") if p.is_file())


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def seed(app):
    app.fresh()
    tables = app.tables()
    connection = sqlite3.connect(app.db)
    try:
        q = quote
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            f"INSERT INTO {q(tables['category'])} (name, description, monthly_budget) "
            "VALUES ('Food', 'Food', 10000), ('Travel', 'Trips', 1000)")
        connection.execute(
            f"INSERT INTO {q(tables['budget'])} (category_id, month, amount_limit_cents) "
            "VALUES (1, '2024-01', 10000), (2, '2024-01', 1000)")
        for amount, description, when, category, method, recurring in (
                (500, "lunch", "2024-01-10", 1, "card", 0),
                (1500, "train", "2024-01-20", 2, "cash", 0),
                (700, "dinner", "2024-02-05", 1, "card", 0),
                (999, "old", "2023-12-31", 1, "cash", 0)):
            connection.execute(
                f"INSERT INTO {q(tables['expense'])} (amount_cents, description, "
                "expense_date, category_id, payment_method, is_recurring) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (amount, description, when, category, method, recurring))
        connection.commit()
    finally:
        connection.close()
    return tables


def check_schema(app):
    app.fresh()
    tables = app.tables()
    connection = sqlite3.connect(app.db)
    try:
        for entity, table in tables.items():
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)
            ).fetchone()[0]
            if "AUTOINCREMENT" not in sql.upper():
                raise AssertionError(f"{entity} table has no AUTOINCREMENT")
        budget = tables["budget"]
        uniques = []
        for index in connection.execute(f"PRAGMA index_list({quote(budget)})"):
            if index[2]:
                uniques.append([c[2] for c in connection.execute(
                    f"PRAGMA index_info({quote(index[1])})")])
        if ["category_id", "month"] not in uniques:
            raise AssertionError(f"budget missing composite unique: {uniques}")
        if ["month"] in uniques:
            raise AssertionError("month is unique on its own")
        for entity in ("expense", "budget"):
            keys = [row[2].lower() for row in connection.execute(
                f"PRAGMA foreign_key_list({quote(tables[entity])})")]
            if tables["category"].lower() not in keys:
                raise AssertionError(f"{entity} missing category FK")
        name_unique = any(
            [c[2] for c in connection.execute(
                f"PRAGMA index_info({quote(index[1])})")] == ["name"]
            for index in connection.execute(
                f"PRAGMA index_list({quote(tables['category'])})") if index[2])
        if not name_unique:
            raise AssertionError("category name is not unique")
    finally:
        connection.close()


def check_category(app):
    app.fresh()
    app.run(["expense", "category", "add", "--name", "Food",
             "--description", "Food and drink", "--budget", "100",
             "--icon", "fork"])
    app.run(["expense", "category", "add", "--name", "Travel",
             "--description", "Trips"])
    tables = app.tables()
    rows = app.rows(tables["category"])
    if [r["name"] for r in rows] != ["Food", "Travel"]:
        raise AssertionError(f"category add failed: {rows}")
    app.run(["expense", "category", "add", "--name", "Food",
             "--description", "again"], expect="nonzero")
    if len(app.rows(tables["category"])) != 2:
        raise AssertionError("duplicate category stored")
    app.run(["expense", "category", "update", "--id", "1", "--name", "Meals"])
    if app.rows(tables["category"], id=1)[0]["name"] != "Meals":
        raise AssertionError("category update did not change name")
    app.run(["expense", "category", "delete", "--id", "2"])
    if app.rows(tables["category"], id=2):
        raise AssertionError("category delete did not remove row")


def check_budget(app):
    app.fresh()
    app.run(["expense", "category", "add", "--name", "Food", "--description", "f"])
    app.run(["budget", "add", "--category-id", "1", "--month", "2024-01",
             "--amount", "50"])
    app.run(["budget", "add", "--category-id", "1", "--month", "2024-02",
             "--amount", "60"])
    tables = app.tables()
    rows = app.rows(tables["budget"])
    if sorted(r["month"] for r in rows) != ["2024-01", "2024-02"]:
        raise AssertionError(f"budget add failed: {rows}")
    app.run(["budget", "add", "--category-id", "1", "--month", "2024-01",
             "--amount", "70"], expect="nonzero")
    if len(app.rows(tables["budget"])) != 2:
        raise AssertionError("duplicate budget stored")
    before = app.rows(tables["budget"], month="2024-01")[0]["amount_limit_cents"]
    app.run(["budget", "update", "--category-id", "1", "--month", "2024-01",
             "--amount", "80"])
    after = app.rows(tables["budget"], month="2024-01")[0]["amount_limit_cents"]
    if after == before:
        raise AssertionError("budget update did not change limit")
    app.run(["budget", "delete", "--category-id", "1", "--month", "2024-02"])
    if app.rows(tables["budget"], month="2024-02"):
        raise AssertionError("budget delete did not remove row")
    app.run(["budget", "add", "--category-id", "999", "--month", "2024-03",
             "--amount", "5"], expect="nonzero")


def check_expense_add(app):
    app.fresh()
    app.run(["expense", "category", "add", "--name", "Food", "--description", "f"])
    app.run(["expense", "add", "--amount", "12", "--description", "lunch",
             "--category", "1", "--expense-date", "2024-03-05",
             "--method", "card", "--recurring"])
    app.run(["expense", "add", "--amount", "3", "--description", "coffee",
             "--category", "1"])
    tables = app.tables()
    rows = app.rows(tables["expense"])
    if len(rows) != 2:
        raise AssertionError(f"expense add stored {len(rows)} rows")
    first = rows[0]
    if str(first["expense_date"])[:10] != "2024-03-05" \
            or first["payment_method"] != "card" or not first["is_recurring"]:
        raise AssertionError(f"expense options lost: {first}")
    if str(rows[1]["expense_date"])[:10] != TODAY:
        raise AssertionError(f"expense date did not default to today: {rows[1]}")
    app.run(["expense", "add", "--amount", "1", "--description", "x",
             "--category", "999"], expect="nonzero")
    if len(app.rows(tables["expense"])) != 2:
        raise AssertionError("unknown-category expense stored")
    app.run(["expense", "add", "--amount", "1", "--description", "x",
             "--category", "1", "--method", "bitcoin"], expect="nonzero")


def check_overage(app):
    app.fresh()
    app.run(["expense", "category", "add", "--name", "Travel", "--description", "t"])
    app.run(["budget", "add", "--category-id", "1", "--month", "2024-01",
             "--amount", "10"])
    result = app.run(["expense", "add", "--amount", "15", "--description", "train",
                      "--category", "1", "--expense-date", "2024-01-20"],
                     expect=None)
    tables = app.tables()
    if len(app.rows(tables["expense"])) != 1:
        raise AssertionError("over-budget expense was not stored")
    report = app.run(["expense", "report", "monthly", "--month", "2024-01"])
    if "exceeded" not in (report.stdout + report.stderr).lower():
        raise AssertionError(f"report does not show exceeded: {report.stdout!r}")


def check_list(app):
    seed(app)
    all_rows = app.text_rows(app.run(["expense", "list"]).stdout)
    if len(all_rows) != 4:
        raise AssertionError(f"list without filters returned {len(all_rows)}")
    by_category = app.text_rows(
        app.run(["expense", "list", "--category", "2"]).stdout)
    if [r["description"] for r in by_category] != ["train"]:
        raise AssertionError(f"category filter: {by_category}")
    by_method = app.text_rows(
        app.run(["expense", "list", "--method", "cash"]).stdout)
    if sorted(r["description"] for r in by_method) != ["old", "train"]:
        raise AssertionError(f"method filter: {by_method}")
    by_dates = app.text_rows(
        app.run(["expense", "list", "--from-date", "2024-01-01",
                 "--to-date", "2024-01-31"]).stdout)
    if sorted(r["description"] for r in by_dates) != ["lunch", "train"]:
        raise AssertionError(f"date filter: {by_dates}")


def check_monthly(app):
    seed(app)
    report = app.run(["expense", "report", "monthly", "--month", "2024-01"]).stdout
    flat = report.lower()
    if not re.search(r"\b(2000|20\.00|20)\b", flat):
        raise AssertionError(f"monthly total missing: {report!r}")
    if "on_track" not in flat or "exceeded" not in flat:
        raise AssertionError(f"monthly statuses missing: {report!r}")


def check_yearly(app):
    seed(app)
    report = app.run(["expense", "report", "yearly", "--year", "2024"]).stdout
    flat = report.lower()
    for needle in ("2024-01", "2024-02", "average", "top"):
        if needle not in flat:
            raise AssertionError(f"yearly report missing {needle}: {report!r}")


def check_export(app):
    seed(app)
    target = app.cwd / "out.csv"
    app.run(["expense", "export", "--from-date", "2024-01-01",
             "--to-date", "2024-12-31", "--output", str(target)])
    if not target.is_file():
        raise AssertionError("export did not write a file")
    rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines()))
    body = [row for row in rows[1:] if row]
    if len(body) != 3 or "old" in target.read_text(encoding="utf-8"):
        raise AssertionError(f"export rows wrong: {rows}")


def check_recurring(app):
    app.fresh()
    app.run(["expense", "category", "add", "--name", "Rent", "--description", "r"])
    tables = app.tables()
    connection = sqlite3.connect(app.db)
    try:
        for when in ("2024-01-05", "2024-02-05", "2024-03-05"):
            connection.execute(
                f"INSERT INTO {quote(tables['expense'])} "
                "(amount_cents, description, expense_date, category_id, "
                "payment_method, is_recurring) VALUES (50000, 'rent', ?, 1, "
                "'transfer', 0)", (when,))
        connection.execute(
            f"INSERT INTO {quote(tables['expense'])} "
            "(amount_cents, description, expense_date, category_id, "
            "payment_method, is_recurring) VALUES (999, 'once', '2024-02-09', "
            "1, 'cash', 0)")
        connection.commit()
    finally:
        connection.close()
    app.run(["expense", "recurring", "detect"])
    rows = {r["description"]: bool(r["is_recurring"])
            for r in app.rows(tables["expense"])}
    if not rows.get("rent") or rows.get("once"):
        raise AssertionError(f"recurring flags: {rows}")


def static_source(app):
    return "\n".join(p.read_text(encoding="utf-8") for p in app.source_files())


def check_models_and_errors(app):
    source = static_source(app)
    for name in ("CategoryNotFoundError", "ExpenseNotFoundError",
                 "BudgetExceededException"):
        if f"class {name}" not in source:
            raise AssertionError(f"missing error class {name}")
    found = {}
    for path in app.source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) \
                            and isinstance(item.target, ast.Name) \
                            and item.target.id == "id":
                        found[node.name] = item.value
    for entity in ("Category", "Expense", "Budget"):
        if entity not in found:
            raise AssertionError(f"missing model {entity}")
        value = found[entity]
        if not (isinstance(value, ast.Constant) and value.value is None):
            raise AssertionError(f"{entity}.id must default to None")


def check_type_hints(app):
    missing = 0
    for path in app.source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.returns is None:
                missing += 1
            for arg in (*node.args.posonlyargs, *node.args.args,
                        *node.args.kwonlyargs):
                if arg.arg not in ("self", "cls") and arg.annotation is None:
                    missing += 1
    if missing:
        raise AssertionError(f"{missing} unannotated parameters/returns")


def check_service_methods(app):
    source = static_source(app)
    classes = ("CategoryRepository", "ExpenseRepository", "BudgetRepository",
               "ExpenseService")
    for name in classes:
        if f"class {name}" not in source:
            raise AssertionError(f"missing class {name}")
    for name in ("list_expenses", "get_expense_by_id", "add_expense",
                 "update_expense", "delete_expense", "get_monthly_report",
                 "get_yearly_summary", "get_category_spending",
                 "export_to_csv", "detect_recurring"):
        if f"def {name}" not in source:
            raise AssertionError(f"missing service method {name}")


CHECKS = (
    ("models and named errors", check_models_and_errors),
    ("type hints throughout", check_type_hints),
    ("schema: autoincrement, composite unique, FKs, unique name", check_schema),
    ("category CRUD, cents, unique name", check_category),
    ("budget CRUD, YYYY-MM, unique, orphan", check_budget),
    ("expense add, default date, options, refusals", check_expense_add),
    ("over-budget stored and visible", check_overage),
    ("list filters", check_list),
    ("monthly report", check_monthly),
    ("yearly report", check_yearly),
    ("CSV export", check_export),
    ("recurring detect", check_recurring),
    ("service classes and methods", check_service_methods),
)


def score(app):
    results = []
    for name, check in CHECKS:
        try:
            check(app)
        except Exception as error:  # noqa: BLE001
            results.append((name, False, str(error)[:300]))
        else:
            results.append((name, True, ""))
    return results


def main():
    apps = [App("ESUS", ESUS, "esus"), App("GPT-6 raw", GPT, "gpt"),
            App("GPT-6 rerun", GPT2, "gpt2"),
            App("Gemini", GEMINI, "gemini")]
    output = {}
    for app in apps:
        results = score(app)
        output[app.name] = results
        print(f"\n=== {app.name}: {sum(1 for _, ok, _ in results if ok)}"
              f"/{len(results)}")
        for name, ok, why in results:
            print(f"{'PASS' if ok else 'FAIL'}  {name}")
            if why:
                print(f"      {why}")
    path = ROOT / "out" / "expenses_common_score.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
