"""Independent acceptance checks for the direct GPT-6 Luna inventory output."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from common import (
    Suite, clean_error, equal, fetchall, main, raises, require, run_cli,
)


def service(suite: Suite, db: Path):
    inventory = suite.import_from(suite.out, "inventory")
    from inventory.database import Database
    from inventory.repositories.category_repository import CategoryRepository
    from inventory.repositories.product_repository import ProductRepository
    from inventory.services.inventory_service import InventoryService
    database = Database(db)
    return database, InventoryService(CategoryRepository(database), ProductRepository(database))


def make_category(svc, name="Books", threshold=3, description="Printed books"):
    return svc.add_category(name=name, description=description, reorder_threshold=threshold)


def make_product(svc, category_id, sku="BK-1", name="Novel", price=1200, stock=2):
    return svc.add_product(sku=sku, name=name, category_id=category_id,
                           price_cents=price, stock_qty=stock)


def cli(suite: Suite, db: Path, *args: str, expected: int = 0):
    return run_cli(suite.out, ["-m", "inventory", "--db-path", str(db), *args],
                   expected=expected)


def run(suite: Suite) -> int:
    @suite.check("package imports and models default IDs to None")
    def models(_: Suite) -> str:
        inventory = suite.import_from(suite.out, "inventory")
        from inventory.models import Category, Product
        require(Category().id is None, "Category.id does not default to None")
        require(Product().id is None, "Product.id does not default to None")
        return "typed dataclasses"

    @suite.check("schema has unique names/SKUs, foreign keys and checks")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        database, _ = service(suite, db)
        database.close()
        categories = {row["name"]: row for row in fetchall(
            db, "PRAGMA table_info(categories)")}
        products = {row["name"]: row for row in fetchall(
            db, "PRAGMA table_info(products)")}
        require("name" in categories and "reorder_threshold" in categories,
                "category columns missing")
        require({"sku", "name", "category_id", "price_cents", "stock_qty",
                 "low_active"} <= set(products), "product columns missing")
        sql = fetchall(db, "SELECT sql FROM sqlite_master WHERE type='table'")
        text = " ".join(row["sql"] or "" for row in sql).upper()
        require("UNIQUE" in text, "no UNIQUE constraint in schema")
        require("FOREIGN KEY" in text or "REFERENCES" in text,
                "no foreign key in schema")
        require("CHECK" in text, "no CHECK constraint in schema")
        return "schema constraints present"

    @suite.check("category CRUD and uniqueness")
    def category_crud(_: Suite) -> str:
        db = suite.db("categories.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            equal(category.name, "Books", "category name")
            equal(category.reorder_threshold, 3, "reorder threshold")
            equal(svc.list_categories()[0].id, category.id, "listed category")
            updated = svc.update_category(category.id, {"name": "Texts", "description": "Updated"})
            equal(updated.name, "Texts", "updated name")
            raises(ValueError, lambda: make_category(svc, name="Texts"), "duplicate name")
            raises(Exception, lambda: svc.update_category(999, {"name": "Missing"}),
                   "unknown category update")
            raises(Exception, lambda: svc.delete_category(999), "unknown category delete")
            svc.delete_category(category.id)
            equal(svc.list_categories(), [], "category deleted")
            return "create/read/update/delete"
        finally:
            database.close()

    @suite.check("product creation stores integer cents and defaults")
    def product_create(_: Suite) -> str:
        db = suite.db("create.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            product = make_product(svc, category.id, price=1299, stock=8)
            equal(product.price_cents, 1299, "price cents")
            equal(product.stock_qty, 8, "stock")
            equal(product.low_active, False, "low_active default")
            equal(svc.get_product_by_id(product.id).sku, "BK-1", "read by id")
            return "integer cents and defaults"
        finally:
            database.close()

    @suite.check("product validation rejects bad input")
    def product_validation(_: Suite) -> str:
        db = suite.db("validation.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            make_product(svc, category.id)
            raises(Exception, lambda: make_product(svc, 999, sku="NO-CAT"),
                   "unknown category")
            raises(ValueError, lambda: make_product(svc, category.id, sku="BK-1"),
                   "duplicate SKU")
            raises(ValueError, lambda: make_product(svc, category.id, sku="NEG", price=-1),
                   "negative price")
            raises(ValueError, lambda: make_product(svc, category.id, sku="NEG-STOCK", stock=-1),
                   "negative stock")
            return "unknown category, duplicate SKU, negatives"
        finally:
            database.close()

    @suite.check("product update covers name, price, category and low_active")
    def product_update(_: Suite) -> str:
        db = suite.db("update.sqlite3")
        database, svc = service(suite, db)
        try:
            first = make_category(svc, name="First")
            second = make_category(svc, name="Second", threshold=0)
            product = make_product(svc, first.id)
            updated = svc.update_product(product.id, {
                "name": "Updated", "price_cents": 1500,
                "category_id": second.id, "low_active": True,
            })
            equal((updated.name, updated.price_cents, updated.category_id, updated.low_active),
                  ("Updated", 1500, second.id, True), "updated fields")
            raises(Exception, lambda: svc.update_product(999, {"name": "Missing"}),
                   "unknown product")
            raises(Exception, lambda: svc.update_product(product.id, {"category_id": 999}),
                   "unknown category")
            return "field update"
        finally:
            database.close()

    @suite.check("product delete and category delete guard")
    def deletes(_: Suite) -> str:
        db = suite.db("delete.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            product = make_product(svc, category.id)
            raises(Exception, lambda: svc.delete_category(category.id),
                   "category with product")
            svc.delete_product(product.id)
            raises(Exception, lambda: svc.delete_product(product.id),
                   "deleted product")
            svc.delete_category(category.id)
            equal(svc.list_categories(), [], "empty category deleted")
            return "delete guards"
        finally:
            database.close()

    @suite.check("list filters by category and low stock")
    def filters(_: Suite) -> str:
        db = suite.db("filters.sqlite3")
        database, svc = service(suite, db)
        try:
            books = make_category(svc, name="Books", threshold=5)
            food = make_category(svc, name="Food", threshold=2)
            low = make_product(svc, books.id, sku="LOW", stock=2)
            high = make_product(svc, books.id, sku="HIGH", stock=8)
            other = make_product(svc, food.id, sku="FOOD", stock=9)
            equal({p.sku for p in svc.list_products()}, {"LOW", "HIGH", "FOOD"},
                  "unfiltered list")
            equal({p.sku for p in svc.list_products(category_id=books.id)},
                  {"LOW", "HIGH"}, "category filter")
            equal({p.sku for p in svc.list_products(low_only=True)}, {"LOW"},
                  "low-only filter")
            equal({p.sku for p in svc.list_products(category_id=food.id, low_only=True)},
                  set(), "combined filters")
            return "all/category/low-only"
        finally:
            database.close()

    @suite.check("low-stock report uses strict threshold and ignores null thresholds")
    def low_stock(_: Suite) -> str:
        db = suite.db("low-stock.sqlite3")
        database, svc = service(suite, db)
        try:
            strict = make_category(svc, name="Strict", threshold=5)
            no_threshold = make_category(svc, name="None", threshold=None)
            at_threshold = make_product(svc, strict.id, sku="AT", stock=5)
            below = make_product(svc, strict.id, sku="BELOW", stock=4)
            no_rule = make_product(svc, no_threshold.id, sku="NORULE", stock=0)
            equal({p.sku for p in svc.low_stock_report()}, {"BELOW"},
                  "low-stock rows")
            return "strict below threshold"
        finally:
            database.close()

    @suite.check("stock value includes empty categories at zero")
    def stock_value(_: Suite) -> str:
        db = suite.db("value.sqlite3")
        database, svc = service(suite, db)
        try:
            books = make_category(svc, name="Books")
            empty = make_category(svc, name="Empty")
            make_product(svc, books.id, sku="A", price=125, stock=4)
            make_product(svc, books.id, sku="B", price=200, stock=2)
            rows = {row["category_name"]: row for row in svc.stock_value_by_category()}
            equal(set(rows), {"Books", "Empty"}, "category rows")
            equal(rows["Books"]["total_value_cents"], 900, "Books value")
            equal(rows["Empty"]["total_value_cents"], 0, "empty category value")
            return "aggregate includes zero rows"
        finally:
            database.close()

    @suite.check("restock adds stock and rejects non-positive quantities")
    def restock(_: Suite) -> str:
        db = suite.db("restock.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            product = make_product(svc, category.id, stock=2)
            equal(svc.restock(product.id, 3).stock_qty, 5, "restock")
            raises(ValueError, lambda: svc.restock(product.id, 0), "zero restock")
            raises(ValueError, lambda: svc.restock(product.id, -1), "negative restock")
            return "increment only"
        finally:
            database.close()

    @suite.check("foreign keys and uniqueness hold in SQLite directly")
    def constraints(_: Suite) -> str:
        db = suite.db("constraints.sqlite3")
        database, svc = service(suite, db)
        try:
            category = make_category(svc)
            make_product(svc, category.id, sku="UNIQUE")
            with sqlite3.connect(db) as connection:
                connection.execute("PRAGMA foreign_keys = ON")
                raises(sqlite3.IntegrityError, lambda: connection.execute(
                    "INSERT INTO products(sku,name,category_id,price_cents,stock_qty) "
                    "VALUES('BAD-FK','Bad',999,1,1)"), "foreign key")
                raises(sqlite3.IntegrityError, lambda: connection.execute(
                    "INSERT INTO products(sku,name,category_id,price_cents,stock_qty) "
                    "VALUES('UNIQUE','Duplicate',?,1,1)", (category.id,)),
                    "unique SKU")
            return "FK and unique"
        finally:
            database.close()

    @suite.check("data persists across service instances")
    def persistence(_: Suite) -> str:
        db = suite.db("persist.sqlite3")
        database, svc = service(suite, db)
        category = make_category(svc)
        product = make_product(svc, category.id)
        database.close()
        database2, svc2 = service(suite, db)
        try:
            equal(svc2.get_product_by_id(product.id).sku, "BK-1", "persisted product")
            equal(svc2.list_categories()[0].name, "Books", "persisted category")
            return "file persistence"
        finally:
            database2.close()

    @suite.check("CLI creates, lists and reports through click")
    def cli_flow(_: Suite) -> str:
        db = suite.db("cli.sqlite3")
        category = json.loads(cli(suite, db, "category", "add", "--name", "Books",
                                  "--threshold", "3").stdout)
        product = json.loads(cli(suite, db, "product", "add", "--sku", "CLI-1",
                                  "--name", "Notebook", "--category", str(category["id"]),
                                  "--price", "1500", "--stock", "2").stdout)
        equal(product["price_cents"], 1500, "CLI price")
        listed = json.loads(cli(suite, db, "product", "list", "--category",
                                 str(category["id"])).stdout)
        equal([row["sku"] for row in listed], ["CLI-1"], "CLI list")
        low = json.loads(cli(suite, db, "product", "report", "low-stock").stdout)
        equal([row["sku"] for row in low], ["CLI-1"], "CLI low-stock")
        value = json.loads(cli(suite, db, "product", "report", "value").stdout)
        equal(value[0]["total_value_cents"], 3000, "CLI value")
        return "nested click commands"

    @suite.check("CLI errors are clean and nonzero")
    def cli_errors(_: Suite) -> str:
        db = suite.db("cli-error.sqlite3")
        result = cli(suite, db, "product", "add", "--sku", "MISSING", "--name", "No category",
                     "--category", "999", "--price", "100", "--stock", "1", expected=1)
        clean_error(result, "missing category")
        return "clean click error"

    @suite.check("CategoryRepository finds products for one category")
    def repository_query(_: Suite) -> str:
        db = suite.db("repo.sqlite3")
        database, svc = service(suite, db)
        try:
            from inventory.repositories.category_repository import CategoryRepository
            first = make_category(svc, name="First")
            second = make_category(svc, name="Second")
            make_product(svc, first.id, sku="FIRST")
            make_product(svc, second.id, sku="SECOND")
            rows = CategoryRepository(database).find_products_by_category(first.id)
            equal([row.sku for row in rows], ["FIRST"], "repository query")
            return "find_products_by_category"
        finally:
            database.close()

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("inventory", sys.argv[1] if len(sys.argv) > 1 else None, run))
