"""Acceptance checks for the 2026-11-13 GPT-6 Luna wine GUI output."""

from __future__ import annotations

import sys

from common import Suite, fetchall, main, raises, require, table_columns


def make_env(suite: Suite, name: str):
    suite.import_from(suite.out, "domain")
    suite.import_from(suite.out, "repository")
    suite.import_from(suite.out, "service")
    from domain import StorageLocation
    from repository import SQLiteRepository
    from service import WineShopService
    db = suite.db(name)
    repository = SQLiteRepository(db)
    service = WineShopService(repository)
    location = service.save_location(StorageLocation(None, "Main Cellar", 1, 1, 12))
    return db, repository, service, location


def make_wine(service, location_id, name="Estate Cabernet", stock=5, **changes):
    from domain import Wine, WineType
    values = dict(
        id=None, name=name, vintage=2018, wine_type=WineType.RED, country="France",
        cost_price=20.0, selling_price=38.0, stock=stock, location_id=location_id,
    )
    values.update(changes)
    return service.save_wine(Wine(**values))


def run(suite: Suite) -> int:
    @suite.check("schema enforces unique wine names, prices and positive stock")
    def schema(_: Suite) -> str:
        db, _, _, _ = make_env(suite, "schema.sqlite3")
        wines = table_columns(db, "wines")
        locations = table_columns(db, "locations")
        require({"name", "vintage", "wine_type", "country", "cost_price",
                 "selling_price", "stock", "location_id"} <= set(wines), "wine columns")
        require({"zone_name", "row_number", "shelf_number", "max_capacity"}
                <= set(locations), "location columns")
        sql = " ".join(row["sql"] or "" for row in fetchall(
            db, "SELECT sql FROM sqlite_master WHERE type='table'")).upper()
        require("UNIQUE" in sql, "no unique name")
        require("REFERENCES" in sql or "FOREIGN KEY" in sql, "no location FK")
        require("CHECK" in sql, "no checks")
        return "schema constraints"

    @suite.check("selling price must be strictly greater than cost")
    def pricing(_: Suite) -> str:
        _, _, service, location = make_env(suite, "pricing.sqlite3")
        raises(Exception, lambda: make_wine(service, location.id, cost_price=40, selling_price=40),
               "equal prices")
        raises(Exception, lambda: make_wine(service, location.id, cost_price=40, selling_price=39),
               "lower selling price")
        return "pricing rule"

    @suite.check("stock cannot become negative")
    def stock(_: Suite) -> str:
        _, _, service, location = make_env(suite, "stock.sqlite3")
        wine = make_wine(service, location.id, stock=2)
        raises(Exception, lambda: service.adjust_stock(wine.id, -3), "negative stock")
        require(service.wines()[0].stock == 2, "stock changed after failure")
        return "nonnegative stock"

    @suite.check("wine names are unique case-insensitively")
    def names(_: Suite) -> str:
        _, _, service, location = make_env(suite, "names.sqlite3")
        make_wine(service, location.id, name="Estate Cabernet")
        raises(Exception, lambda: make_wine(service, location.id, name="estate cabernet"),
               "duplicate name")
        return "case-insensitive unique name"

    @suite.check("location capacity is shared across wines")
    def capacity(_: Suite) -> str:
        _, _, service, location = make_env(suite, "capacity.sqlite3")
        make_wine(service, location.id, stock=8)
        raises(Exception, lambda: make_wine(service, location.id, name="Chardonnay", stock=5),
               "capacity exceeded")
        raises(Exception, lambda: service.adjust_stock(service.wines()[0].id, 5),
               "adjust exceeds capacity")
        return "total assigned stock"

    @suite.check("location capacity cannot be lowered below current stock")
    def lower_capacity(_: Suite) -> str:
        _, _, service, location = make_env(suite, "lower.sqlite3")
        make_wine(service, location.id, stock=8)
        from domain import StorageLocation
        raises(Exception, lambda: service.save_location(
            StorageLocation(location.id, "Main Cellar", 1, 1, 7)), "lowered capacity")
        return "capacity floor"

    @suite.check("assigned location cannot be deleted, even at zero stock")
    def delete_location(_: Suite) -> str:
        _, _, service, location = make_env(suite, "delete.sqlite3")
        make_wine(service, location.id, stock=0)
        raises(Exception, lambda: service.delete_location(location.id), "location in use")
        return "delete guard"

    @suite.check("data persists across repository instances")
    def persistence(_: Suite) -> str:
        db, _, service, location = make_env(suite, "persist.sqlite3")
        saved = make_wine(service, location.id)
        suite.import_from(suite.out, "repository")
        from repository import SQLiteRepository
        reopened = type(service)(SQLiteRepository(db))
        equal = reopened.wines()[0]
        require(equal.id == saved.id and equal.name == saved.name, "wine not persisted")
        return "SQLite persistence"

    @suite.check("GUI entry is a real tkinter application with separate layers")
    def gui_structure(_: Suite) -> str:
        source = (suite.out / "main.py").read_text(encoding="utf-8")
        require("import tkinter" in source, "no tkinter import")
        require("class WineShopApp" in source, "no application class")
        require("ttk.Treeview" in source, "no tree view")
        require("service" in source and "repository" in source, "layers not wired")
        return "tkinter UI and layered wiring (not launched)"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("gui", sys.argv[1] if len(sys.argv) > 1 else None, run))
