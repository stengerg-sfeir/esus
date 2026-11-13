"""Acceptance checks for the 2026-11-13 GPT-6 Luna small-business output."""

from __future__ import annotations

import json
import sys

from common import Suite, equal, fetchall, main, raises, require, run_python


def make_env(suite: Suite, name: str):
    suite.import_from(suite.out, "shop")
    from shop.db import Database
    from shop.repository import Repository
    from shop.services import ShopService
    database = Database(suite.db(name))
    database.initialize()
    service = ShopService(Repository(database))
    return database, service


def setup(suite: Suite, name: str):
    database, service = make_env(suite, name)
    customer = service.add_customer("Avery Chen", "avery@example.com")
    category = service.add_category("Office")
    product = service.add_product(category["id"], "Notebook", "4.50", 30)
    return database, service, customer, category, product


def close_db(database) -> None:
    close = getattr(database, "close", None)
    if callable(close):
        close()


def run(suite: Suite) -> int:
    @suite.check("schema has expected tables, foreign keys, checks and statuses")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        database, _ = make_env(suite, "schema.sqlite3")
        database.initialize()
        tables = {row["name"] for row in fetchall(
            db, "SELECT name FROM sqlite_master WHERE type='table'")}
        require({"customers", "categories", "products", "orders", "order_items", "invoices"}
                <= tables, f"missing tables: {tables}")
        sql = " ".join(row["sql"] or "" for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE type='table'")).upper()
        require("REFERENCES" in sql or "FOREIGN KEY" in sql, "no foreign key")
        require("CHECK" in sql, "no check")
        require("UNIQUE" in sql, "no unique constraint")
        statuses = next(row["sql"] for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE name='orders'"))
        for status in ("pending", "confirmed", "shipped", "cancelled"):
            require(status in statuses, f"missing status {status}")
        return "tables and constraints"

    @suite.check("customers validate email and reject duplicates")
    def customers(_: Suite) -> str:
        database, service = make_env(suite, "customers.sqlite3")
        try:
            first = service.add_customer("Avery Chen", "avery@example.com")
            equal(service.search_orders(first["id"]), [], "new orders")
            raises(Exception, lambda: service.add_customer("Other", "avery@example.com"),
                   "duplicate email")
            raises(Exception, lambda: service.add_customer("Bad", "not an email"),
                   "invalid email")
            equal(len(service.list_customers()), 1, "customer list")
            return "email validation"
        finally:
            close_db(database)

    @suite.check("categories and products support CRUD and validation")
    def catalog(_: Suite) -> str:
        database, service = make_env(suite, "catalog.sqlite3")
        try:
            category = service.add_category("Office")
            renamed = service.update_category(category["id"], "Stationery")
            equal(renamed["name"], "Stationery", "rename")
            raises(Exception, lambda: service.add_category("Stationery"), "duplicate category")
            product = service.add_product(category["id"], "Notebook", "4.50", 30)
            equal(product["price_cents"], 450, "price cents")
            equal(product["stock_quantity"], 30, "stock")
            raises(Exception, lambda: service.add_product(category["id"], "Bad", "-1.00", 1),
                   "negative price")
            raises(Exception, lambda: service.add_product(category["id"], "Bad", "1.00", -1),
                   "negative stock")
            raises(Exception, lambda: service.add_product(999, "Bad", "1.00", 1),
                   "unknown category")
            raises(Exception, lambda: service.delete_category(category["id"]),
                   "category with product")
            return "catalog CRUD"
        finally:
            close_db(database)

    @suite.check("pending orders combine duplicate lines without reserving stock")
    def pending(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "pending.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 1), (product["id"], 2)])
            equal(order["status"], "pending", "status")
            equal(order["total_cents"], 1350, "total")
            equal(len(order["items"]), 1, "one line")
            equal(order["items"][0]["quantity"], 3, "combined quantity")
            equal(service.list_products()[0]["reserved_quantity"], 0, "reserved")
            return "pending and combined"
        finally:
            close_db(database)

    @suite.check("confirm reserves stock and creates one invoice")
    def confirm(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "confirm.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 3)])
            confirmed, invoice = service.confirm_order(order["id"])
            equal(confirmed["status"], "confirmed", "status")
            equal(invoice["total_cents"], 1350, "invoice total")
            equal(invoice["order_id"], order["id"], "invoice order")
            row = service.list_products()[0]
            equal((row["stock_quantity"], row["reserved_quantity"], row["available_quantity"]),
                  (30, 3, 27), "stock after confirm")
            equal(len(service.search_invoices(customer["id"])), 1, "invoice search")
            return "reservation and invoice"
        finally:
            close_db(database)

    @suite.check("cancelling a confirmed order releases stock and keeps invoice")
    def cancel_confirmed(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "cancel-confirmed.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 2)])
            _, invoice = service.confirm_order(order["id"])
            service.cancel_order(order["id"])
            row = service.list_products()[0]
            equal((row["stock_quantity"], row["reserved_quantity"], row["available_quantity"]),
                  (30, 0, 30), "released stock")
            equal(service.get_order(order["id"])["status"], "cancelled", "status")
            equal(service.get_invoice(invoice["id"])["order_id"], order["id"], "invoice retained")
            return "release and retain"
        finally:
            close_db(database)

    @suite.check("cancelling a pending order does not touch stock")
    def cancel_pending(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "cancel-pending.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 2)])
            service.cancel_order(order["id"])
            row = service.list_products()[0]
            equal((row["stock_quantity"], row["reserved_quantity"]), (30, 0), "stock unchanged")
            return "pending cancel"
        finally:
            close_db(database)

    @suite.check("shipping consumes reserved stock")
    def ship(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "ship.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 4)])
            service.confirm_order(order["id"])
            service.ship_order(order["id"])
            row = service.list_products()[0]
            equal((row["stock_quantity"], row["reserved_quantity"], row["available_quantity"]),
                  (26, 0, 26), "stock after ship")
            equal(service.get_order(order["id"])["status"], "shipped", "status")
            return "shipped"
        finally:
            close_db(database)

    @suite.check("invalid order transitions are refused")
    def transitions(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "transitions.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 1)])
            raises(Exception, lambda: service.ship_order(order["id"]), "ship pending")
            service.confirm_order(order["id"])
            raises(Exception, lambda: service.confirm_order(order["id"]), "confirm twice")
            service.cancel_order(order["id"])
            raises(Exception, lambda: service.cancel_order(order["id"]), "cancel twice")
            raises(Exception, lambda: service.ship_order(order["id"]), "ship cancelled")
            return "state machine"
        finally:
            close_db(database)

    @suite.check("insufficient stock fails atomically")
    def insufficient(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "insufficient.sqlite3")
        try:
            first = service.create_order(customer["id"], [(product["id"], 28)])
            second = service.create_order(customer["id"], [(product["id"], 3)])
            service.confirm_order(first["id"])
            raises(Exception, lambda: service.confirm_order(second["id"]), "second confirmation")
            equal(service.get_order(second["id"])["status"], "pending", "second pending")
            row = service.list_products()[0]
            equal(row["reserved_quantity"], 28, "first reservation only")
            return "all-or-nothing"
        finally:
            close_db(database)

    @suite.check("customer order and invoice searches are isolated")
    def searches(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "searches.sqlite3")
        try:
            other = service.add_customer("Other", "other@example.com")
            first = service.create_order(customer["id"], [(product["id"], 1)])
            second = service.create_order(other["id"], [(product["id"], 1)])
            invoice = service.confirm_order(first["id"])[1]
            equal([row["id"] for row in service.search_orders(customer["id"])], [first["id"]],
                  "own orders")
            equal([row["id"] for row in service.search_orders(other["id"])], [second["id"]],
                  "other orders")
            equal([row["id"] for row in service.search_invoices(customer["id"])],
                  [invoice["id"]], "own invoices")
            equal(service.search_invoices(other["id"]), [], "other invoices")
            return "search isolation"
        finally:
            close_db(database)

    @suite.check("product stock cannot be lowered below reservations")
    def stock_floor(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "stock-floor.sqlite3")
        try:
            order = service.create_order(customer["id"], [(product["id"], 5)])
            service.confirm_order(order["id"])
            raises(Exception, lambda: service.update_product(product["id"], stock=4),
                   "stock below reserved")
            updated = service.update_product(product["id"], stock=10)
            equal(updated["stock_quantity"], 10, "updated stock")
            return "reservation floor"
        finally:
            close_db(database)

    @suite.check("data persists across service instances")
    def persistence(_: Suite) -> str:
        database, service, customer, _, product = setup(suite, "persist.sqlite3")
        order = service.create_order(customer["id"], [(product["id"], 2)])
        service2 = type(service)(service.repo)
        equal(service2.get_order(order["id"])["customer_id"], customer["id"], "persisted order")
        return "SQLite persistence"

    @suite.check("CLI drives a complete customer/order/invoice lifecycle")
    def cli(_: Suite) -> str:
        db = suite.path("cli.sqlite3")
        base = ["main.py", "--db", str(db)]

        def call(*args: str):
            return run_python(suite.out, base + list(args))

        customer = call("customer", "add", "--name", "Avery Chen",
                        "--email", "avery@example.com")
        customer_id = json.loads(customer.stdout)["id"]
        category = call("category", "add", "--name", "Office")
        category_id = json.loads(category.stdout)["id"]
        product = call("product", "add", "--category-id", str(category_id),
                       "--name", "Notebook", "--price", "4.50", "--stock", "30")
        product_id = json.loads(product.stdout)["id"]
        order = call("order", "create", "--customer-id", str(customer_id),
                     "--item", f"{product_id}:2")
        order_id = json.loads(order.stdout)["id"]
        confirmed = call("order", "confirm", str(order_id))
        equal(json.loads(confirmed.stdout)["order"]["status"], "confirmed", "CLI confirm")
        invoices = call("invoice", "list", "--customer-id", str(customer_id))
        equal(len(json.loads(invoices.stdout)), 1, "CLI invoice")
        return "CLI lifecycle"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("60", sys.argv[1] if len(sys.argv) > 1 else None, run))
