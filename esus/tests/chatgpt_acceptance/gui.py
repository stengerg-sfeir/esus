"""Independent acceptance checks for the direct GPT-6 Luna wine GUI output."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from common import (
    Suite, equal, fetchall, main, raises, require,
)


def make_service(suite: Suite, db: Path):
    suite.import_from(suite.out, "wine_inventory")
    from wine_inventory.database import Database
    from wine_inventory.services import InventoryService
    return InventoryService(Database(db))


def add_location(service, zone="Main Cellar", row=1, shelf=3, capacity=5):
    return service.locations.save_location(
        zone_name=zone, row_number=row, shelf_number=shelf, max_capacity=capacity)


def add_wine(service, location_id, **overrides):
    values = dict(
        name="Estate Red", vintage_year=2019, wine_type="red", country="France",
        cost_price=20.0, selling_price=35.0, stock_quantity=2,
        location_id=location_id,
    )
    values.update(overrides)
    return service.wines.save_wine(**values)


def run(suite: Suite) -> int:
    @suite.check("models expose the requested wine and location fields")
    def models(_: Suite) -> str:
        suite.import_from(suite.out, "wine_inventory")
        from wine_inventory.models import StorageLocation, WineType
        equal([item.value for item in WineType], ["red", "white", "rosé", "sparkling"],
              "wine types")
        location = StorageLocation(1, "Main Cellar", 1, 3, 5, 0)
        require("Main Cellar" in location.display_name, "location display name")
        return "typed domain models"

    @suite.check("schema has unique wine names, capacity checks and foreign keys")
    def schema(_: Suite) -> str:
        db = suite.db("schema.sqlite3")
        make_service(suite, db)
        tables = {row["name"]: row for row in fetchall(
            db, "SELECT name, sql FROM sqlite_master WHERE type='table'")}
        require({"wines", "storage_locations"} <= set(tables), "missing tables")
        text = " ".join((row["sql"] or "") for row in tables.values()).upper()
        require("FOREIGN KEY" in text or "REFERENCES" in text, "no foreign key")
        require("UNIQUE" in text, "no unique constraint")
        require("CHECK" in text, "no check constraint")
        return "FK/unique/checks"

    @suite.check("storage locations create, list and persist")
    def locations(_: Suite) -> str:
        db = suite.db("locations.sqlite3")
        service = make_service(suite, db)
        location = add_location(service)
        equal(location.max_capacity, 5, "capacity")
        equal(service.locations.list_locations()[0].zone_name, "Main Cellar", "listed zone")
        raises(Exception, lambda: add_location(service, capacity=0), "zero capacity")
        raises(Exception, lambda: add_location(service, row=0), "zero row")
        raises(Exception, lambda: add_location(service, zone="main cellar", row=1, shelf=3),
               "duplicate location")
        service2 = make_service(suite, db)
        equal(len(service2.locations.list_locations()), 1, "persisted location")
        return "location CRUD"

    @suite.check("wines create, read and persist with one primary location")
    def wines(_: Suite) -> str:
        db = suite.db("wines.sqlite3")
        service = make_service(suite, db)
        location = add_location(service)
        wine = add_wine(service, location.id, stock_quantity=3)
        equal((wine.name, wine.vintage_year, wine.stock_quantity, wine.location_id),
              ("Estate Red", 2019, 3, location.id), "wine fields")
        rows = service.wines.list_wines()
        equal([row.name for row in rows], ["Estate Red"], "wine list")
        service2 = make_service(suite, db)
        equal(service2.wines.list_wines()[0].stock_quantity, 3, "persisted stock")
        return "wine persistence"

    @suite.check("wine names are unique case-insensitively")
    def unique_names(_: Suite) -> str:
        db = suite.db("unique.sqlite3")
        service = make_service(suite, db)
        location = add_location(service)
        add_wine(service, location.id)
        raises(Exception, lambda: add_wine(service, location.id, name="estate red"),
               "case-insensitive duplicate")
        other = add_wine(service, location.id, name="Estate White", stock_quantity=1)
        equal(other.name, "Estate White", "distinct wine")
        return "unique names"

    @suite.check("selling price must be strictly greater than cost")
    def pricing(_: Suite) -> str:
        db = suite.db("pricing.sqlite3")
        service = make_service(suite, db)
        location = add_location(service)
        raises(Exception, lambda: add_wine(service, location.id, cost_price=10, selling_price=10),
               "equal prices")
        raises(Exception, lambda: add_wine(service, location.id, cost_price=10, selling_price=9),
               "lower selling price")
        wine = add_wine(service, location.id, cost_price=10, selling_price=10.01)
        equal(wine.selling_price, 10.01, "valid margin")
        return "strict pricing"

    @suite.check("stock cannot be negative")
    def stock(_: Suite) -> str:
        db = suite.db("stock.sqlite3")
        service = make_service(suite, db)
        location = add_location(service)
        raises(Exception, lambda: add_wine(service, location.id, stock_quantity=-1),
               "negative stock")
        zero = add_wine(service, location.id, stock_quantity=0)
        equal(zero.stock_quantity, 0, "zero stock")
        return "non-negative stock"

    @suite.check("location capacity covers all assigned bottles")
    def capacity(_: Suite) -> str:
        db = suite.db("capacity.sqlite3")
        service = make_service(suite, db)
        location = add_location(service, capacity=5)
        add_wine(service, location.id, name="First", stock_quantity=3)
        add_wine(service, location.id, name="Second", stock_quantity=2)
        raises(Exception, lambda: add_wine(service, location.id, name="Third",
                                           stock_quantity=1), "over capacity")
        equal(service.locations.list_locations()[0].bottle_count, 5, "bottle count")
        return "capacity"

    @suite.check("a wine can be reassigned to another location")
    def reassignment(_: Suite) -> str:
        db = suite.db("move.sqlite3")
        service = make_service(suite, db)
        first = add_location(service, zone="Main", capacity=5)
        second = add_location(service, zone="Front", row=2, shelf=1, capacity=4)
        wine = add_wine(service, first.id, stock_quantity=2)
        moved = service.wines.save_wine(
            wine_id=wine.id, name=wine.name, vintage_year=wine.vintage_year,
            wine_type=wine.wine_type, country=wine.country,
            cost_price=wine.cost_price, selling_price=wine.selling_price,
            stock_quantity=3, location_id=second.id,
        )
        equal(moved.location_id, second.id, "new location")
        counts = {loc.zone_name: loc.bottle_count for loc in service.locations.list_locations()}
        equal(counts, {"Main": 0, "Front": 3}, "bottle counts")
        return "move wine"

    @suite.check("occupied locations cannot be removed")
    def remove_location(_: Suite) -> str:
        db = suite.db("remove.sqlite3")
        service = make_service(suite, db)
        occupied = add_location(service)
        empty = add_location(service, zone="Empty", row=2, shelf=1)
        add_wine(service, occupied.id)
        raises(Exception, lambda: service.locations.remove_location(occupied.id),
               "occupied location")
        service.locations.remove_location(empty.id)
        equal([loc.zone_name for loc in service.locations.list_locations()],
              ["Main Cellar"], "empty location removed")
        return "removal guard"

    @suite.check("capacity cannot shrink below assigned stock")
    def shrink(_: Suite) -> str:
        db = suite.db("shrink.sqlite3")
        service = make_service(suite, db)
        location = add_location(service, capacity=5)
        add_wine(service, location.id, stock_quantity=3)
        raises(Exception, lambda: service.locations.save_location(
            location_id=location.id, zone_name="Main Cellar", row_number=1,
            shelf_number=3, max_capacity=2), "shrink below stock")
        return "shrink guard"

    @suite.check("GUI module contains a real PyImgui/GLFW frame loop")
    def gui_structure(_: Suite) -> str:
        source = (suite.out / "wine_inventory" / "gui.py").read_text(encoding="utf-8")
        for needle in ("import imgui", "import glfw", "GlfwRenderer",
                       "while not glfw.window_should_close", "imgui.new_frame()",
                       "imgui.render()", "glfw.swap_buffers"):
            require(needle in source, f"missing GUI structure: {needle}")
        return "PyImgui/GLFW loop"

    @suite.check("real GUI launches for one frame")
    def real_launch(_: Suite) -> str:
        suite.import_from(suite.out, "wine_inventory")
        import glfw
        from wine_inventory import gui
        old_env = os.environ.get("WINE_INVENTORY_DB")
        os.environ["WINE_INVENTORY_DB"] = str(suite.db("gui.sqlite3"))
        old_close = glfw.window_should_close
        state = {"frames": 0, "terminated": False}
        old_terminate = glfw.terminate

        def should_close(_window):
            state["frames"] += 1
            return state["frames"] > 1

        def terminate():
            state["terminated"] = True

        glfw.window_should_close = should_close
        glfw.terminate = terminate
        try:
            gui.main()
        except BaseException as error:  # noqa: BLE001 - report the real failure
            raise AssertionError(f"gui.main() failed: {type(error).__name__}: {error}")
        finally:
            glfw.window_should_close = old_close
            glfw.terminate = old_terminate
            if old_env is None:
                os.environ.pop("WINE_INVENTORY_DB", None)
            else:
                os.environ["WINE_INVENTORY_DB"] = old_env
        require(state["frames"] >= 1, "no frame was rendered")
        require(state["terminated"], "glfw.terminate was not called")
        return f"{state['frames']} frame(s)"

    return suite.run()


if __name__ == "__main__":
    raise SystemExit(main("gui", sys.argv[1] if len(sys.argv) > 1 else None, run))
