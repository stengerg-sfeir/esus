"""Acceptance checks for the 2026-11-13 GPT-6 Luna inventory output."""

from __future__ import annotations

import sqlite3
import sys
from common import (
    Suite, equal, fetchall, main, raises, require, run_python, table_columns,
)


def make_env(suite: Suite, name: str):
    suite.import_from(suite.out, "inventory")
    from inventory import CategoryRepository, Database, InventoryService, ProductRepository
    database = Database(suite.db(name))
    service = InventoryService(CategoryRepository(database.connection),
                               ProductRepository(database.connection))
    return database, service


def make_category(service, name="Books", description="Printed books", threshold=3):
    return service.add_category(name, description, threshold)


def make_product(service, category_id, sku="BK-1", name="Novel", price=1200, stock=2):
    return service.add_product(sku, name, category_id, price, stock)


def run(suite: Suite) -> int:
    @suite.check("models default IDs to None")
    def models(_: Suite) -> str:
        suite.import_from(suite.out, "inventory")
        from inventory.models import Category, Product
        require(Category().id is None, "Category.id")
        require(Product().id is None, "Product.id")
        return "typed dataclasses"

    @suite.check("schema has unique names/SKUs, foreign keys and checks")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        database, _ = make_env(suite, "schema.sqlite3")
        database.close()
        categories = table_columns(db, "categories")
        products = table_columns(db, "products")
        require({"name", "description", "reorder_threshold"} <= set(categories), "category columns")
        require({"sku", "name", "category_id", "price_cents", "stock_qty", "low_active"}
                <= set(products), "product columns")
        sql = " ".join(row["sql"] or "" for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE type='table'"))
        require("UNIQUE" in sql.upper(), "no UNIQUE constraint")
        require("FOREIGN KEY" in sql.upper() or "REFERENCES" in sql.upper(), "no foreign key")
        require("CHECK" in sql.upper(), "no CHECK constraint")
        return "constraints present"

    @suite.check("category CRUD and duplicate-name rejection")
    def categories(_: Suite) -> str:
        database, service = make_env(suite, "categories.sqlite3")
        try:
            category = make_category(service)
            equal(category.name, "Books", "name")
            equal(category.reorder_threshold, 3, "threshold")
            updated = service.update_category(category.id, {"name": "Texts", "description": "Updated"})
            equal(updated.name, "Texts", "updated name")
            raises(Exception, lambda: make_category(service, name="Texts"), "duplicate name")
            raises(Exception, lambda: service.update_category(999, {"name": "Missing"}),
                   "unknown update")
            raises(Exception, lambda: service.delete_category(999), "unknown delete")
            service.delete_category(category.id)
            equal(service.list_categories(), [], "deleted")
            return "create/read/update/delete"
        finally:
            database.close()

    @suite.check("product creation stores cents and defaults low_active")
    def product_create(_: Suite) -> str:
        database, service = make_env(suite, "create.sqlite3")
        try:
            category = make_category(service)
            product = make_product(service, category.id, price=1299, stock=8)
            equal(product.price_cents, 1299, "price")
            equal(product.stock_qty, 8, "stock")
            equal(product.low_active, False, "low_active")
            equal(service.get_product_by_id(product.id).sku, "BK-1", "read")
            return "integer cents and defaults"
        finally:
            database.close()

    @suite.check("product validation rejects bad input")
    def product_validation(_: Suite) -> str:
        database, service = make_env(suite, "validation.sqlite3")
        try:
            category = make_category(service)
            make_product(service, category.id)
            raises(Exception, lambda: make_product(service, 999, sku="NO-CAT"), "unknown category")
            raises(Exception, lambda: make_product(service, category.id, sku="BK-1"), "duplicate SKU")
            raises(Exception, lambda: make_product(service, category.id, sku="NEG", price=-1),
                   "negative price")
            raises(Exception, lambda: make_product(service, category.id, sku="NEG-STOCK", stock=-1),
                   "negative stock")
            return "category, uniqueness, negatives"
        finally:
            database.close()

    @suite.check("product update covers fields and unknown rows")
    def product_update(_: Suite) -> str:
        database, service = make_env(suite, "update.sqlite3")
        try:
            first = make_category(service, name="First")
            second = make_category(service, name="Second", threshold=0)
            product = make_product(service, first.id)
            updated = service.update_product(product.id, {
                "name": "Updated", "price_cents": 1500,
                "category_id": second.id, "low_active": True,
            })
            equal((updated.name, updated.price_cents, updated.category_id, updated.low_active),
                  ("Updated", 1500, second.id, True), "fields")
            raises(Exception, lambda: service.update_product(999, {"name": "Missing"}), "unknown")
            raises(Exception, lambda: service.update_product(product.id, {"category_id": 999}),
                   "unknown category")
            return "field update"
        finally:
            database.close()

    @suite.check("product delete and category delete guard")
    def deletes(_: Suite) -> str:
        database, service = make_env(suite, "delete.sqlite3")
        try:
            category = make_category(service)
            product = make_product(service, category.id)
            raises(Exception, lambda: service.delete_category(category.id), "category with product")
            service.delete_product(product.id)
            raises(Exception, lambda: service.delete_product(product.id), "deleted product")
            service.delete_category(category.id)
            equal(service.list_categories(), [], "empty category deleted")
            return "delete guards"
        finally:
            database.close()

    @suite.check("filters by category and low stock")
    def filters(_: Suite) -> str:
        database, service = make_env(suite, "filters.sqlite3")
        try:
            books = make_category(service, name="Books", threshold=5)
            food = make_category(service, name="Food", threshold=2)
            low = make_product(service, books.id, sku="LOW", stock=2)
            high = make_product(service, books.id, sku="HIGH", stock=8)
            other = make_product(service, food.id, sku="FOOD", stock=9)
            equal({p.sku for p in service.list_products()}, {"LOW", "HIGH", "FOOD"}, "all")
            equal({p.sku for p in service.list_products(category_id=books.id)},
                  {"LOW", "HIGH"}, "category")
            equal({p.sku for p in service.list_products(low_only=True)}, {"LOW"}, "low only")
            equal({p.sku for p in service.list_products(category_id=food.id, low_only=True)},
                  set(), "combined")
            return "all/category/low-only"
        finally:
            database.close()

    @suite.check("low-stock report is strict and ignores missing thresholds")
    def low_stock(_: Suite) -> str:
        database, service = make_env(suite, "low-stock.sqlite3")
        try:
            strict = make_category(service, name="Strict", threshold=5)
            no_threshold = make_category(service, name="None", threshold=None)
            make_product(service, strict.id, sku="AT", stock=5)
            make_product(service, strict.id, sku="BELOW", stock=4)
            make_product(service, no_threshold.id, sku="NORULE", stock=0)
            equal({p.sku for p in service.low_stock_report()}, {"BELOW"}, "strict rows")
            return "strict below threshold"
        finally:
            database.close()

    @suite.check("stock value includes empty categories at zero")
    def stock_value(_: Suite) -> str:
        database, service = make_env(suite, "value.sqlite3")
        try:
            books = make_category(service, name="Books")
            empty = make_category(service, name="Empty")
            make_product(service, books.id, sku="A", price=125, stock=4)
            make_product(service, books.id, sku="B", price=200, stock=2)
            values = service.stock_value_by_category()
            equal(values[books.id], 900, "Books value")
            equal(values[empty.id], 0, "empty value")
            return "aggregate includes zero"
        finally:
            database.close()

    @suite.check("restock adds stock and rejects negative quantities")
    def restock(_: Suite) -> str:
        database, service = make_env(suite, "restock.sqlite3")
        try:
            category = make_category(service)
            product = make_product(service, category.id, stock=2)
            equal(service.restock(product.id, 3).stock_qty, 5, "restock")
            raises(Exception, lambda: service.restock(product.id, -1), "negative restock")
            return "increment only"
        finally:
            database.close()

    @suite.check("SQLite foreign keys and uniqueness hold")
    def constraints(_: Suite) -> str:
        db = suite.db("constraints.sqlite3")
        database, service = make_env(suite, "constraints.sqlite3")
        try:
            category = make_category(service)
            make_product(service, category.id, sku="UNIQUE")
            with sqlite3.connect(db) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                try:
                    connection.execute(
                        "INSERT INTO products(sku,name,category_id,price_cents,stock_qty) "
                        "VALUES ('UNIQUE','duplicate',?,1,1)", (category.id,))
                except sqlite3.IntegrityError:
                    pass
                else:
                    raise AssertionError("duplicate SKU was accepted")
                try:
                    connection.execute(
                        "INSERT INTO products(sku,name,category_id,price_cents,stock_qty) "
                        "VALUES ('ORPHAN','orphan',999,1,1)")
                except sqlite3.IntegrityError:
                    pass
                else:
                    raise AssertionError("orphan category was accepted")
            return "unique and FK"
        finally:
            database.close()

    @suite.check("Click CLI drives category, product and reports")
    def cli(_: Suite) -> str:
        db = suite.path("cli.sqlite3")
        category = run_python(suite.out, [
            "-m", "inventory", "--db", str(db), "category", "add",
            "--name", "Food", "--threshold", "4",
        ])
        require("Added category" in category.stdout, category.stdout)
        product = run_python(suite.out, [
            "-m", "inventory", "--db", str(db), "product", "add",
            "--sku", "FOOD-1", "--name", "Rice", "--category", "1",
            "--price", "125", "--stock", "2",
        ])
        require("Added product" in product.stdout, product.stdout)
        report = run_python(suite.out, [
            "-m", "inventory", "--db", str(db), "product", "report", "low-stock",
        ])
        require("FOOD-1" in report.stdout, report.stdout)
        value = run_python(suite.out, [
            "-m", "inventory", "--db", str(db), "product", "report", "value",
        ])
        require("250" in value.stdout, value.stdout)
        return "nested CLI"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("inventory", sys.argv[1] if len(sys.argv) > 1 else None, run))
