"""Behavior acceptance for a freshly generated expenses package.

Run after real extraction and generation have populated ``OUT_DIR``::

    python3 tests/e2e_expenses_acceptance.py out/expenses

Every requirement of ``prompts/prompt_expenses.txt`` that can be run is checked
through the generated CLI in fresh processes, or through the package for the
service methods the CLI does not reach. Each check is independent and the whole
list is reported, because a program with several defects should show all of
them, not the first. Fixture rows are inserted with SQL where the thing under
test is not the insert; no generated module is ever edited.
"""

import ast
import csv
import datetime as dt
import inspect
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_library_acceptance as lib  # noqa: E402

TODAY = dt.date.today().isoformat()


class Fixture:
    """Paths and helpers for one generated package."""

    def __init__(self, out_dir):
        self.out = Path(out_dir).resolve()
        self.cli_path = self.out / "generated" / "cli.py"
        if not self.cli_path.is_file():
            raise SystemExit(f"generated CLI is missing: {self.cli_path}")
        self.scratch = Path(tempfile.mkdtemp(prefix="expenses-e2e-", dir=self.out))

    def database(self, name):
        return self.scratch / f"{name}.sqlite3"

    def cli(self, db, *args, expected=0):
        return lib.cli(self.cli_path, db, *args, expected=expected)

    def rows(self, db, table, **criteria):
        connection = sqlite3.connect(db)
        try:
            return lib.rows_for(connection, table, **criteria)
        finally:
            connection.close()

    def tables(self, db):
        """The category, expense and budget tables, found by their columns."""
        connection = sqlite3.connect(db)
        try:
            return {
                "category": lib.table_with(connection, {"id", "name", "description"})[0],
                "expense": lib.table_with(connection, {"id", "amount_cents", "category_id"})[0],
                "budget": lib.table_with(connection, {"id", "month", "amount_limit_cents"})[0],
            }
        finally:
            connection.close()

    def fresh(self, name):
        """A database with the tables created, by running a read-only command."""
        db = self.database(name)
        self.cli(db, "expense", "category", "list")
        return db

    def seeded(self, name):
        """A database with categories, budgets and expenses inserted by SQL."""
        db = self.fresh(name)
        tables = self.tables(db)
        connection = sqlite3.connect(db)
        connection.execute("PRAGMA foreign_keys=ON")
        q = lib.quoted
        connection.execute(
            f"INSERT INTO {q(tables['category'])} (name, description, monthly_budget) "
            "VALUES ('Food', 'Food', 10000), ('Travel', 'Trips', 1000)")
        connection.execute(
            f"INSERT INTO {q(tables['budget'])} (category_id, month, amount_limit_cents) "
            "VALUES (1, '2024-01', 10000), (2, '2024-01', 1000)")
        for amount, description, date, category, method, recurring in (
                (500, "lunch", "2024-01-10", 1, "card", 0),
                (1500, "train", "2024-01-20", 2, "cash", 0),
                (700, "dinner", "2024-02-05", 1, "card", 0),
                (999, "old", "2023-12-31", 1, "cash", 0)):
            connection.execute(
                f"INSERT INTO {q(tables['expense'])} (amount_cents, description, "
                "expense_date, category_id, payment_method, is_recurring) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (amount, description, date, category, method, recurring))
        connection.commit()
        connection.close()
        return db


def parse_value(text):
    """A report printed as a Python or JSON value."""
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        return ast.literal_eval(text)


def refused(result, name=None):
    text = result.stdout + result.stderr
    if not text.strip():
        lib.fail("a refused command printed no explanation")
    if name and name not in text:
        lib.fail(f"the refusal should name {name}: {text!r}")


# --------------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------------

def check_error_classes(fx):
    text = (fx.out / "generated" / "errors.py").read_text(encoding="utf-8")
    for name in ("CategoryNotFoundError", "ExpenseNotFoundError",
                 "BudgetExceededException"):
        if not re.search(rf"class {name}\b", text):
            lib.fail(f"the prompt names the exception {name}, which errors.py lacks")


def check_ids_are_optional_in_the_models(fx):
    tree = ast.parse((fx.out / "generated" / "models.py").read_text(encoding="utf-8"))
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
        ids = [n for n in cls.body if isinstance(n, ast.AnnAssign)
               and getattr(n.target, "id", None) == "id"]
        if not ids:
            continue
        default = ids[0].value
        if not (isinstance(default, ast.Constant) and default.value is None):
            lib.fail(f"{cls.name}.id must default to None")


def check_schema(fx):
    db = fx.fresh("schema")
    tables = fx.tables(db)
    connection = sqlite3.connect(db)
    try:
        for entity, table in tables.items():
            statement = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            if "AUTOINCREMENT" not in statement.upper():
                lib.fail(f"{entity} table does not auto-increment its id")
        budget = tables["budget"]
        uniques = []
        for index in connection.execute(f"PRAGMA index_list({lib.quoted(budget)})"):
            if index[2]:
                uniques.append([c[2] for c in connection.execute(
                    f"PRAGMA index_info({lib.quoted(index[1])})")])
        if ["category_id", "month"] not in uniques:
            lib.fail(f"budget needs a table-level UNIQUE(category_id, month): {uniques}")
        if ["month"] in uniques:
            lib.fail("month must not be unique on its own (inline `month TEXT UNIQUE`)")
        for entity in ("expense", "budget"):
            keys = [row[2].lower() for row in connection.execute(
                f"PRAGMA foreign_key_list({lib.quoted(tables[entity])})")]
            if tables["category"].lower() not in keys:
                lib.fail(f"{entity} must have a foreign key to category")
        name_unique = any(
            [c[2] for c in connection.execute(
                f"PRAGMA index_info({lib.quoted(i[1])})")] == ["name"]
            for i in connection.execute(
                f"PRAGMA index_list({lib.quoted(tables['category'])})") if i[2])
        if not name_unique:
            lib.fail("category name must be unique")
    finally:
        connection.close()


def check_category_commands(fx):
    db = fx.fresh("categories")
    fx.cli(db, "expense", "category", "add", "--name", "Food",
           "--description", "Food and drink", "--budget", "100", "--icon", "fork")
    fx.cli(db, "expense", "category", "add", "--name", "Travel",
           "--description", "Trips")
    tables = fx.tables(db)
    rows = fx.rows(db, tables["category"])
    if [r["name"] for r in rows] != ["Food", "Travel"]:
        lib.fail(f"category add did not store both categories: {rows}")
    connection = sqlite3.connect(db)
    kind = connection.execute(
        f"SELECT typeof(monthly_budget) FROM {lib.quoted(tables['category'])} "
        "WHERE name='Food'").fetchone()[0]
    connection.close()
    if kind != "integer":
        lib.fail(f"monthly_budget must be stored as integer cents, not {kind}")
    travel = next(r for r in rows if r["name"] == "Travel")
    if travel["monthly_budget"] is not None or travel.get("icon") is not None:
        lib.fail(f"an omitted --budget and --icon must stay NULL: {travel}")
    listed = lib.json_rows(fx.cli(db, "expense", "category", "list").stdout)
    if sorted(r.get("name") for r in listed) != ["Food", "Travel"]:
        lib.fail(f"category list should show both categories: {listed}")
    duplicate = fx.cli(db, "expense", "category", "add", "--name", "Food",
                       "--description", "again", expected=1)
    refused(duplicate)
    if len(fx.rows(db, tables["category"])) != 2:
        lib.fail("a duplicate category name stored a second row")
    fx.cli(db, "expense", "category", "update", "--id", "1", "--name", "Meals")
    if fx.rows(db, tables["category"], id=1)[0]["name"] != "Meals":
        lib.fail("category update --name did not change the name")
    fx.cli(db, "expense", "category", "delete", "--id", "2")
    if fx.rows(db, tables["category"], id=2):
        lib.fail("category delete did not remove the category")


def check_budget_commands(fx):
    db = fx.fresh("budgets")
    fx.cli(db, "expense", "category", "add", "--name", "Food", "--description", "f")
    fx.cli(db, "budget", "add", "--category-id", "1", "--month", "2024-01",
           "--amount", "50")
    fx.cli(db, "budget", "add", "--category-id", "1", "--month", "2024-02",
           "--amount", "60")
    table = fx.tables(db)["budget"]
    rows = fx.rows(db, table)
    if sorted(r["month"] for r in rows) != ["2024-01", "2024-02"]:
        lib.fail(f"budget add must keep the month as written (YYYY-MM): {rows}")
    listed = lib.json_rows(fx.cli(db, "budget", "list", "--category", "1",
                                  "--month", "2024-01").stdout)
    if [r.get("month") for r in listed] != ["2024-01"]:
        lib.fail(f"budget list --category --month should filter: {listed}")
    duplicate = fx.cli(db, "budget", "add", "--category-id", "1", "--month",
                       "2024-01", "--amount", "70", expected=1)
    refused(duplicate)
    if len(fx.rows(db, table)) != 2:
        lib.fail("UNIQUE(category_id, month) did not stop a duplicate budget")
    before = fx.rows(db, table, month="2024-01")[0]["amount_limit_cents"]
    fx.cli(db, "budget", "update", "--category-id", "1", "--month", "2024-01",
           "--amount", "80")
    after = fx.rows(db, table, month="2024-01")[0]["amount_limit_cents"]
    if after == before:
        lib.fail("budget update --amount did not change the limit")
    fx.cli(db, "budget", "delete", "--category-id", "1", "--month", "2024-02")
    if fx.rows(db, table, month="2024-02"):
        lib.fail("budget delete did not remove the budget")
    orphan = fx.cli(db, "budget", "add", "--category-id", "999", "--month",
                    "2024-03", "--amount", "5", expected=1)
    refused(orphan)


def check_expense_add(fx):
    db = fx.fresh("expense-add")
    fx.cli(db, "expense", "category", "add", "--name", "Food", "--description", "f")
    fx.cli(db, "expense", "add", "--amount", "12", "--description", "lunch",
           "--category", "1", "--expense-date", "2024-03-05", "--method", "card",
           "--recurring")
    fx.cli(db, "expense", "add", "--amount", "3", "--description", "coffee",
           "--category", "1")
    table = fx.tables(db)["expense"]
    rows = fx.rows(db, table)
    if len(rows) != 2:
        lib.fail(f"expense add should store two expenses, found {len(rows)}")
    connection = sqlite3.connect(db)
    kinds = {row[0] for row in connection.execute(
        f"SELECT typeof(amount_cents) FROM {lib.quoted(table)}")}
    connection.close()
    if kinds != {"integer"}:
        lib.fail(f"amounts must be stored as integer cents, found {kinds}")
    first = rows[0]
    if first["expense_date"] != "2024-03-05" or first["payment_method"] != "card" \
            or not first["is_recurring"]:
        lib.fail(f"expense add did not store its options: {first}")
    if str(rows[1]["expense_date"])[:10] != TODAY:
        lib.fail(f"an omitted --expense-date should default to today: {rows[1]}")
    unknown = fx.cli(db, "expense", "add", "--amount", "1", "--description", "x",
                     "--category", "999", expected=1)
    refused(unknown, "CategoryNotFoundError")
    if len(fx.rows(db, table)) != 2:
        lib.fail("an expense for an unknown category was stored")
    bad = fx.cli(db, "expense", "add", "--amount", "1", "--description", "x",
                 "--category", "1", "--method", "bitcoin", expected=1)
    refused(bad)


def check_budget_overage_is_stored_and_visible(fx):
    db = fx.fresh("overage")
    fx.cli(db, "expense", "category", "add", "--name", "Travel", "--description", "t")
    fx.cli(db, "budget", "add", "--category-id", "1", "--month", "2024-01",
           "--amount", "10")
    result = subprocess.run(
        [sys.executable, str(fx.cli_path), "--db", str(db), "expense", "add",
         "--amount", "15", "--description", "train", "--category", "1",
         "--expense-date", "2024-01-20"], capture_output=True, text=True)
    if len(fx.rows(db, fx.tables(db)["expense"])) != 1:
        lib.fail("an expense that exceeds its budget must still be stored "
                 "(the budget is checked after insertion): "
                 + (result.stdout + result.stderr).strip()[:200])
    report = fx.cli(db, "expense", "report", "monthly", "--month", "2024-01").stdout
    if "exceeded" not in report:
        lib.fail(f"the monthly report should show the budget as exceeded: {report!r}")


def check_expense_list(fx):
    db = fx.seeded("list")
    everything = lib.json_rows(fx.cli(db, "expense", "list").stdout)
    if len(everything) != 4:
        lib.fail(f"no filter must list every expense (4), got {len(everything)}")
    by_category = lib.json_rows(fx.cli(db, "expense", "list", "--category", "2").stdout)
    if [r["description"] for r in by_category] != ["train"]:
        lib.fail(f"--category filter: {by_category}")
    by_method = lib.json_rows(fx.cli(db, "expense", "list", "--method", "cash").stdout)
    if sorted(r["description"] for r in by_method) != ["old", "train"]:
        lib.fail(f"--method filter: {by_method}")
    by_dates = lib.json_rows(fx.cli(db, "expense", "list", "--from-date",
                                    "2024-01-01", "--to-date", "2024-01-31").stdout)
    if sorted(r["description"] for r in by_dates) != ["lunch", "train"]:
        lib.fail(f"--from-date/--to-date filter: {by_dates}")


def check_monthly_report(fx):
    db = fx.seeded("monthly")
    text = fx.cli(db, "expense", "report", "monthly", "--month", "2024-01").stdout
    report = parse_value(text)
    flat = json.dumps(report, default=str)
    if not re.search(r"\b(2000|20\.0+|20)\b", flat):
        lib.fail(f"the report should show the total spent for January (20.00): {flat}")
    if "on_track" not in flat or "exceeded" not in flat:
        lib.fail("Food (5.00 of 100.00) is on_track and Travel (15.00 of 10.00) "
                 f"is exceeded; the report shows: {flat}")
    for name in ("Food", "Travel"):
        if name not in flat and name.lower() not in flat and not re.search(r"\b[12]\b", flat):
            lib.fail(f"the per-category breakdown should name {name}: {flat}")


def check_yearly_summary(fx):
    db = fx.seeded("yearly")
    flat = json.dumps(parse_value(
        fx.cli(db, "expense", "report", "yearly", "--year", "2024").stdout),
        default=str)
    if "2024-01" not in flat or "2024-02" not in flat:
        lib.fail(f"the yearly summary needs monthly totals for 2024-01 and 2024-02: {flat}")
    if "average" not in flat.lower() or "top" not in flat.lower():
        lib.fail(f"the yearly summary needs top categories and an average: {flat}")


def check_export(fx):
    db = fx.seeded("export")
    target = fx.scratch / "out.csv"
    fx.cli(db, "expense", "export", "--from-date", "2024-01-01", "--to-date",
           "2024-12-31", "--output", str(target))
    if not target.is_file():
        lib.fail("expense export did not write the file")
    rows = list(csv.reader(target.read_text(encoding="utf-8").splitlines()))
    body = [row for row in rows[1:] if row]
    text = target.read_text(encoding="utf-8")
    if len(body) != 3 or "old" in text:
        lib.fail(f"the export should hold the 3 expenses of 2024 and not the 2023 one: {rows}")


def check_recurring_detect(fx):
    db = fx.fresh("recurring")
    fx.cli(db, "expense", "category", "add", "--name", "Rent", "--description", "r")
    table = fx.tables(db)["expense"]
    connection = sqlite3.connect(db)
    for month in ("2024-01-05", "2024-02-05", "2024-03-05"):
        connection.execute(
            f"INSERT INTO {lib.quoted(table)} (amount_cents, description, expense_date, "
            "category_id, payment_method, is_recurring) VALUES (50000, 'rent', ?, 1, 'transfer', 0)",
            (month,))
    connection.execute(
        f"INSERT INTO {lib.quoted(table)} (amount_cents, description, expense_date, "
        "category_id, payment_method, is_recurring) VALUES (999, 'once', '2024-02-09', 1, 'cash', 0)")
    connection.commit()
    connection.close()
    fx.cli(db, "expense", "recurring", "detect")
    rows = {r["description"]: bool(r["is_recurring"]) for r in fx.rows(db, table)}
    if not rows.get("rent") or rows.get("once"):
        lib.fail(f"detect should mark the three monthly rents and not the one-off: {rows}")


def check_service_methods(fx):
    db = fx.seeded("service")
    deps = lib.generated_deps(fx.out, db)
    try:
        service = deps["services"]["ExpenseService"]

        def call(name, *args):
            method = getattr(service, name, None)
            if not callable(method):
                lib.fail(f"the prompt names ExpenseService.{name}, which is missing")
            return method(*args)

        found = call("get_expense_by_id", 1)
        if getattr(found, "description", None) != "lunch":
            lib.fail(f"get_expense_by_id(1) should return the lunch expense: {found}")
        spending = call("get_category_spending", 1, dt.date(2024, 1, 1),
                        dt.date(2024, 12, 31))
        flat = json.dumps(spending, default=str)
        if not re.search(r"\b(1200|12\.0+|12)\b", flat):
            lib.fail(f"Food spending in 2024 is 5.00 + 7.00 = 12.00: {flat}")
        update = getattr(service, "update_expense", None)
        if not callable(update):
            lib.fail("the prompt names ExpenseService.update_expense, which is missing")
        parameters = list(inspect.signature(update).parameters)
        update(1, {"description": "brunch"}) if len(parameters) == 2 \
            else update(1, description="brunch")
        if fx.rows(db, fx.tables(db)["expense"], id=1)[0]["description"] != "brunch":
            lib.fail("update_expense did not change the expense")
        call("delete_expense", 4)
    finally:
        deps["store"].close()
    if fx.rows(db, fx.tables(db)["expense"], id=4):
        lib.fail("delete_expense did not remove the expense")


CHECKS = (
    ("error classes named by the prompt exist", check_error_classes),
    ("ids are optional (default None) in the models", check_ids_are_optional_in_the_models),
    ("schema: autoincrement, table-level UNIQUE(category_id, month), FKs, unique name", check_schema),
    ("category add/list/update/delete, integer cents, unique name", check_category_commands),
    ("budget add/list/update/delete, YYYY-MM months, UNIQUE, orphan rejected", check_budget_commands),
    ("expense add: cents, date default, options, unknown category, invalid method", check_expense_add),
    ("an expense over its budget is stored and the overage is visible", check_budget_overage_is_stored_and_visible),
    ("expense list: no filter lists all; category, method and date filters", check_expense_list),
    ("report monthly: total, breakdown, on_track/exceeded", check_monthly_report),
    ("report yearly: monthly totals, top categories, average", check_yearly_summary),
    ("export writes a CSV of the filtered expenses", check_export),
    ("recurring detect marks monthly repeats", check_recurring_detect),
    ("service methods the CLI does not reach", check_service_methods),
)


def run(out_dir):
    fx = Fixture(out_dir)
    results = []
    for name, check in CHECKS:
        try:
            check(fx)
        except AssertionError as error:
            results.append({"check": name, "status": "FAIL", "why": str(error)[:400]})
        except Exception as error:  # noqa: BLE001 - a crash is a failed check
            results.append({"check": name, "status": "FAIL",
                            "why": f"{type(error).__name__}: {str(error)[:300]}"})
        else:
            results.append({"check": name, "status": "PASS", "why": ""})
    passed = sum(1 for r in results if r["status"] == "PASS")
    for r in results:
        print(f"{r['status']}  {r['check']}")
        if r["why"]:
            print(f"      {r['why']}")
    print(f"\n{passed} of {len(results)} checks pass")
    (fx.out / "e2e_expenses_results.json").write_text(
        json.dumps({"passed": passed, "total": len(results), "results": results},
                   indent=2) + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} OUT_DIR", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1]))
