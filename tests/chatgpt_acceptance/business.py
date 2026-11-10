"""Independent acceptance checks for the direct GPT-6 Luna small-business output."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from common import (
    Suite, clean_error, equal, fetchall, main, raises, require, run_cli,
)


def imports(suite: Suite):
    suite.import_from(suite.out / "src", "shop")
    from shop.database import Database
    from shop.services import ShopService
    return Database, ShopService


def make_service(suite: Suite, db: Path):
    Database, ShopService = imports(suite)
    return ShopService(Database(db))


def setup(suite: Suite, db: Path):
    svc = make_service(suite, db)
    customer = svc.add_customer("Avery Chen", "avery@example.com")
    category = svc.add_category("Office")
    product = svc.add_product(category, "Notebook", "4.50", 30)
    return svc, customer, category, product


def cli(suite: Suite, db: Path, *args: str, expected: int = 0):
    return run_cli(
        suite.out,
        ["-m", "shop", "--db", str(db), *args],
        expected=expected,
        env={"PYTHONPATH": str(suite.out / "src")},
    )


def last_number(text: str) -> int:
    match = re.search(r"(\d+)(?!.*\d)", text)
    require(match is not None, f"no number in output: {text!r}")
    return int(match.group(1))


def run(suite: Suite) -> int:
    @suite.check("schema has the expected tables and constraints")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        make_service(suite, db)
        tables = {row["name"] for row in fetchall(
            db, "SELECT name FROM sqlite_master WHERE type='table'")}
        require({"customers", "categories", "products", "orders",
                 "order_items", "invoices"} <= tables, f"missing tables: {tables}")
        sql = " ".join((row["sql"] or "") for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE type='table'")).upper()
        require("FOREIGN KEY" in sql or "REFERENCES" in sql, "no foreign key")
        require("CHECK" in sql and "UNIQUE" in sql, "no check/unique constraint")
        statuses = fetchall(db, "SELECT sql FROM sqlite_master WHERE name='orders'")[0]["sql"]
        for status in ("pending", "confirmed", "shipped", "cancelled"):
            require(status in statuses, f"missing order status {status}")
        return "tables, FKs, checks and statuses"

    @suite.check("customers validate email and reject duplicates")
    def customers(_: Suite) -> str:
        db = suite.db("customers.sqlite3")
        svc = make_service(suite, db)
        first = svc.add_customer("Avery Chen", "avery@example.com")
        equal(svc.search_orders(first), [], "new customer orders")
        raises(Exception, lambda: svc.add_customer("Other", "avery@example.com"),
               "duplicate email")
        raises(Exception, lambda: svc.add_customer("Bad", "not an email"),
               "invalid email")
        equal(len(svc.list_customers()), 1, "customer list")
        return "email uniqueness and validation"

    @suite.check("categories and products support admin CRUD")
    def catalog(_: Suite) -> str:
        db = suite.db("catalog.sqlite3")
        svc = make_service(suite, db)
        category = svc.add_category("Office")
        svc.rename_category(category, "Stationery")
        equal(svc.list_categories()[0]["name"], "Stationery", "renamed category")
        raises(Exception, lambda: svc.add_category("Stationery"), "duplicate category")
        product = svc.add_product(category, "Notebook", "4.50", 30, "A5")
        equal(product, 1, "product id")
        row = svc.list_products()[0]
        equal((row["name"], row["price_cents"], row["stock_on_hand"]), ("Notebook", 450, 30),
              "product fields")
        raises(Exception, lambda: svc.add_product(category, "Bad", "0", 1), "zero price")
        raises(Exception, lambda: svc.add_product(category, "Bad", "1.00", -1), "negative stock")
        raises(Exception, lambda: svc.add_product(999, "Bad", "1.00", 1), "unknown category")
        return "category/product admin surface"

    @suite.check("an order with several products starts pending without reserving stock")
    def pending_order(_: Suite) -> str:
        db = suite.db("pending.sqlite3")
        svc, customer, category, product = setup(suite, db)
        second = svc.add_product(category, "Pen", "1.25", 10)
        order = svc.create_order(customer, [(product, 2), (second, 3)])
        details = svc.order_details(order)
        equal(details["order"]["status"], "pending", "order status")
        equal(details["total_cents"], 2 * 450 + 3 * 125, "order total")
        equal(svc.list_products()[0]["reserved_quantity"], 0, "reserved quantity")
        return "pending and unreserved"

    @suite.check("duplicate product lines are combined")
    def duplicate_lines(_: Suite) -> str:
        db = suite.db("duplicate-lines.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 1), (product, 2)])
        items = svc.order_details(order)["items"]
        equal(len(items), 1, "one order line")
        equal(items[0]["quantity"], 3, "combined quantity")
        return "quantities combined"

    @suite.check("confirm reserves stock, creates one invoice and fixes the total")
    def confirm(_: Suite) -> str:
        db = suite.db("confirm.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 3)])
        invoice = svc.confirm_order(order)
        row = svc.list_products()[0]
        equal((row["stock_on_hand"], row["reserved_quantity"], row["available"]),
              (30, 3, 27), "stock after confirm")
        details = svc.invoice_details(invoice)
        equal(details["invoice"]["total_cents"], 1350, "invoice total")
        equal(details["invoice"]["order_id"], order, "invoice order")
        equal(len(svc.search_invoices(customer)), 1, "invoice search")
        return "reservation and invoice"

    @suite.check("cancelling a confirmed order releases stock but keeps the invoice")
    def cancel_confirmed(_: Suite) -> str:
        db = suite.db("cancel-confirmed.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 2)])
        invoice = svc.confirm_order(order)
        svc.cancel_order(order)
        row = svc.list_products()[0]
        equal((row["stock_on_hand"], row["reserved_quantity"], row["available"]),
              (30, 0, 30), "released stock")
        equal(svc.order_details(order)["order"]["status"], "cancelled", "order status")
        equal(svc.invoice_details(invoice)["invoice"]["order_id"], order, "invoice retained")
        return "release, invoice retained"

    @suite.check("cancelling a pending order does not touch stock")
    def cancel_pending(_: Suite) -> str:
        db = suite.db("cancel-pending.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 2)])
        svc.cancel_order(order)
        row = svc.list_products()[0]
        equal((row["stock_on_hand"], row["reserved_quantity"]), (30, 0), "stock unchanged")
        return "pending cancel"

    @suite.check("shipping a confirmed order consumes reserved stock")
    def ship(_: Suite) -> str:
        db = suite.db("ship.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 4)])
        svc.confirm_order(order)
        svc.ship_order(order)
        row = svc.list_products()[0]
        equal((row["stock_on_hand"], row["reserved_quantity"], row["available"]),
              (26, 0, 26), "stock after ship")
        equal(svc.order_details(order)["order"]["status"], "shipped", "status")
        return "shipped"

    @suite.check("invalid order transitions are refused")
    def transitions(_: Suite) -> str:
        db = suite.db("transitions.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 1)])
        raises(Exception, lambda: svc.ship_order(order), "ship pending")
        svc.confirm_order(order)
        raises(Exception, lambda: svc.confirm_order(order), "confirm twice")
        svc.cancel_order(order)
        raises(Exception, lambda: svc.cancel_order(order), "cancel twice")
        raises(Exception, lambda: svc.ship_order(order), "ship cancelled")
        return "state machine"

    @suite.check("insufficient stock fails atomically")
    def insufficient(_: Suite) -> str:
        db = suite.db("insufficient.sqlite3")
        svc, customer, _, product = setup(suite, db)
        first = svc.create_order(customer, [(product, 28)])
        second = svc.create_order(customer, [(product, 3)])
        svc.confirm_order(first)
        raises(Exception, lambda: svc.confirm_order(second), "second confirmation")
        equal(svc.order_details(second)["order"]["status"], "pending", "second remains pending")
        row = svc.list_products()[0]
        equal(row["reserved_quantity"], 28, "first reservation only")
        return "all-or-nothing confirmation"

    @suite.check("customer order and invoice searches are isolated and filterable")
    def searches(_: Suite) -> str:
        db = suite.db("searches.sqlite3")
        svc, customer, _, product = setup(suite, db)
        other = svc.add_customer("Other", "other@example.com")
        first = svc.create_order(customer, [(product, 1)])
        second = svc.create_order(other, [(product, 1)])
        invoice = svc.confirm_order(first)
        equal([row["id"] for row in svc.search_orders(customer)], [first], "own orders")
        equal([row["id"] for row in svc.search_orders(other)], [second], "other orders")
        equal([row["id"] for row in svc.search_orders(customer, status="confirmed")],
              [first], "status filter")
        equal([row["id"] for row in svc.search_orders(customer, status="shipped")], [],
              "empty filter")
        equal([row["id"] for row in svc.search_invoices(customer, query=str(invoice))],
              [invoice], "invoice query")
        return "customer isolation and filters"

    @suite.check("product update respects reservations and active flag")
    def product_update(_: Suite) -> str:
        db = suite.db("product-update.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 5)])
        svc.confirm_order(order)
        raises(Exception, lambda: svc.update_product(product, stock=4),
               "stock below reserved")
        svc.update_product(product, stock=10, active=False)
        rows = svc.list_products()
        equal(rows, [], "active list excludes inactive")
        equal(len(svc.list_products(include_inactive=True)), 1, "inactive list")
        raises(Exception, lambda: svc.create_order(customer, [(product, 1)]),
               "inactive product order")
        return "reservation floor and deactivation"

    @suite.check("data persists across service instances")
    def persistence(_: Suite) -> str:
        db = suite.db("persist.sqlite3")
        svc, customer, _, product = setup(suite, db)
        order = svc.create_order(customer, [(product, 2)])
        svc2 = make_service(suite, db)
        equal(svc2.order_details(order)["order"]["customer_id"], customer,
              "persisted order")
        equal(svc2.list_products()[0]["sku"] if "sku" in svc2.list_products()[0].keys()
              else svc2.list_products()[0]["name"], "Notebook", "persisted product")
        return "SQLite persistence"

    @suite.check("CLI drives a complete customer/order/invoice lifecycle")
    def cli_lifecycle(_: Suite) -> str:
        db = suite.db("cli.sqlite3")
        customer = cli(suite, db, "customer", "add", "Avery Chen", "avery@example.com")
        customer_id = last_number(customer.stdout)
        category = cli(suite, db, "category", "add", "Office")
        category_id = last_number(category.stdout)
        product = cli(suite, db, "product", "add", str(category_id), "Notebook", "4.50", "30")
        product_id = last_number(product.stdout)
        order = cli(suite, db, "order", "create", str(customer_id),
                    "--item", f"{product_id}:2")
        order_id = last_number(order.stdout)
        confirmed = cli(suite, db, "order", "confirm", str(order_id))
        invoice_id = last_number(confirmed.stdout)
        orders = cli(suite, db, "customer", "orders", str(customer_id))
        require(f"Order {order_id}" in orders.stdout, f"order missing: {orders.stdout!r}")
        invoices = cli(suite, db, "customer", "invoices", str(customer_id))
        require(f"Invoice {invoice_id}" in invoices.stdout,
                f"invoice missing: {invoices.stdout!r}")
        details = cli(suite, db, "invoice", "show", str(invoice_id))
        require("Notebook x 2" in details.stdout and "9.00" in details.stdout,
                f"invoice detail wrong: {details.stdout!r}")
        return "CLI lifecycle"

    @suite.check("CLI validation errors are clean")
    def cli_errors(_: Suite) -> str:
        db = suite.db("cli-error.sqlite3")
        result = cli(suite, db, "customer", "add", "Bad", "not-an-email", expected=2)
        clean_error(result, "invalid email")
        result = cli(suite, db, "order", "show", "999", expected=2)
        clean_error(result, "unknown order")
        return "clean argparse/domain errors"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("60", sys.argv[1] if len(sys.argv) > 1 else None, run))
