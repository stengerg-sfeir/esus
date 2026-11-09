"""Behavior acceptance for the inventory prompt.

The test drives the generated CLI for the prompt's command surface and calls
the domain service for the rules the CLI cannot reach (duplicate SKU, unknown
category, low-stock report, stock value).  All names and tables are discovered
from the generated package where the prompt leaves spelling open.

Run after extraction and generation::

    python3.12 tests/e2e_inventory_acceptance.py out/inventory_same_conditions
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(message):
    raise AssertionError(message)


def cli(cli_path, database, *args, expected=0):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, str(cli_path), "--db", str(database), *args],
        cwd=str(cli_path.parent), check=False, capture_output=True,
        text=True, env=env)
    if result.returncode != expected:
        fail(f"CLI {args!r} returned {result.returncode}, expected {expected}. "
             f"stdout={result.stdout!r}; stderr={result.stderr!r}")
    return result


def json_values(output):
    """Rows from either a JSON document or one JSON value per line."""
    text = (output or "").strip()
    if not text:
        return []
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    rows = []
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        rows.append(item)
    return rows


def table_with(connection, required_columns):
    for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"):
        escaped = name.replace('"', '""')
        columns = {row[1] for row in connection.execute(
            f'PRAGMA table_info("{escaped}")')}
        if set(required_columns) <= columns:
            return name
    fail(f"no generated table has columns {sorted(required_columns)}")


def rows_for(connection, table, **criteria):
    where = " AND ".join(f'"{key}" = ?' for key in criteria)
    query = f'SELECT * FROM "{table}"'
    params = ()
    if where:
        query += " WHERE " + where
        params = tuple(criteria.values())
    cursor = connection.execute(query, params)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def generated_deps(out_dir, database):
    sys.dont_write_bytecode = True
    generated = str(Path(out_dir) / "generated")
    if generated not in sys.path:
        sys.path.insert(0, generated)
    import cli as generated_cli
    built = generated_cli.build_cli(str(database))
    return built[1] if isinstance(built, tuple) else built


def find_service(services, method):
    for service in services.values():
        if callable(getattr(service, method, None)):
            return getattr(service, method)
    fail(f"no generated service exposes {method}")


def ids(records):
    return sorted(item.get("id") if isinstance(item, dict) else item.id
                  for item in records)


def main(argv):
    if len(argv) != 2:
        print("usage: e2e_inventory_acceptance.py OUT_DIR", file=sys.stderr)
        return 2
    out_dir = Path(argv[1]).resolve()
    cli_path = out_dir / "generated" / "cli.py"
    if not cli_path.is_file():
        fail(f"generated CLI is missing: {cli_path}")
    database = Path(tempfile.mkdtemp(prefix="inventory-e2e-",
                                     dir=out_dir)) / "acceptance.sqlite3"

    cli(cli_path, database, "category", "add", "--name", "Parts",
        "--description", "spare parts", "--threshold", "5")
    cli(cli_path, database, "category", "add", "--name", "Tools",
        "--description", "hand tools", "--threshold", "2")
    connection = sqlite3.connect(database)
    category_table = table_with(connection, {"id", "name",
                                              "reorder_threshold"})
    parts = rows_for(connection, category_table, name="Parts")[0]
    tools = rows_for(connection, category_table, name="Tools")[0]
    connection.close()

    for sku, name, category, price, stock in (
            ("P-1", "Bolt", parts["id"], "25", 2),
            ("T-1", "Hammer", tools["id"], "1250", 8),
            ("T-2", "Saw", tools["id"], "2000", 1)):
        cli(cli_path, database, "product", "add", "--sku", sku,
            "--name", name, "--category", str(category), "--price", price,
            "--stock", str(stock))
    connection = sqlite3.connect(database)
    product_table = table_with(connection, {"id", "sku", "price_cents",
                                             "stock_qty", "category_id"})
    rows = rows_for(connection, product_table)
    if {row["sku"] for row in rows} != {"P-1", "T-1", "T-2"}:
        fail(f"products were not stored: {rows}")
    if any(not isinstance(row["price_cents"], int) or row["price_cents"] <= 0
           for row in rows):
        fail(f"prices are not positive integer cents: {rows}")
    bolt = next(row for row in rows if row["sku"] == "P-1")
    saw = next(row for row in rows if row["sku"] == "T-2")
    connection.close()
    print("PASS  category and product creation with integer cents")

    listed = json_values(cli(cli_path, database, "product", "list").stdout)
    if {row.get("sku") for row in listed} != {"P-1", "T-1", "T-2"}:
        fail(f"product list did not return every product: {listed}")
    filtered = json_values(cli(cli_path, database, "product", "list",
                               "--category", str(tools["id"])).stdout)
    if {row.get("sku") for row in filtered} != {"T-1", "T-2"}:
        fail(f"product list --category did not filter: {filtered}")
    low = json_values(cli(cli_path, database, "product", "list",
                          "--low-only").stdout)
    if {row.get("sku") for row in low} != {"P-1", "T-2"}:
        fail(f"product list --low-only returned {low}")
    print("PASS  product filters by category and low stock")

    report = cli(cli_path, database, "product", "report", "low-stock")
    low_report = json_values(report.stdout)
    if {row.get("sku") for row in low_report} != {"P-1", "T-2"}:
        fail(f"product report low-stock returned {low_report!r}")
    value = cli(cli_path, database, "product", "report", "value")
    value_rows = json_values(value.stdout)
    if not value_rows:
        fail("product report value returned no result")
    print("PASS  low-stock and stock-value reports")

    cli(cli_path, database, "product", "restock", "--id", str(saw["id"]),
        "--qty", "4")
    connection = sqlite3.connect(database)
    if rows_for(connection, product_table, id=saw["id"])[0]["stock_qty"] != 5:
        fail("product restock did not add the requested quantity")
    connection.close()
    cli(cli_path, database, "product", "update", "--id", str(bolt["id"]),
        "--price", "50", "--name", "Long Bolt")
    connection = sqlite3.connect(database)
    updated = rows_for(connection, product_table, id=bolt["id"])[0]
    connection.close()
    if updated["name"] != "Long Bolt" or updated["price_cents"] <= 0:
        fail(f"product update did not persist: {updated}")
    print("PASS  restock and product update")

    deps = generated_deps(out_dir, database)
    repos, services = deps["repos"], deps["services"]
    add_product = find_service(services, "add_product")
    list_products = find_service(services, "list_products")
    low_stock = find_service(services, "low_stock_report")
    stock_value = find_service(services, "stock_value_by_category")
    try:
        add_product(sku="P-1", name="Duplicate", category_id=parts["id"],
                    price_cents=100, stock_qty=1)
    except Exception as error:  # noqa: BLE001
        if "Duplicate" not in type(error).__name__ and "Value" not in type(error).__name__:
            fail(f"duplicate SKU raised {type(error).__name__}, not a validation error")
    else:
        fail("add_product accepted a duplicate SKU")
    try:
        add_product(sku="ORPHAN", name="Orphan", category_id=999999,
                    price_cents=100, stock_qty=1)
    except Exception as error:  # noqa: BLE001
        if "NotFound" not in type(error).__name__ and "Value" not in type(error).__name__:
            fail(f"unknown category raised {type(error).__name__}, not a not-found error")
    else:
        fail("add_product accepted an unknown category")
    everything = list_products(None, None)
    if {item.sku for item in everything} != {"P-1", "T-1", "T-2"}:
        fail(f"list_products(None, None) returned {ids(everything)}")
    tools_low = list_products(tools["id"], True)
    if tools_low:
        fail(f"list_products(tools, low) should be empty after restock: "
             f"{[item.sku for item in tools_low]}")
    if {item.sku for item in low_stock()} != {"P-1"}:
        fail(f"low_stock_report returned {[item.sku for item in low_stock()]}")
    value = stock_value()
    if not value:
        fail("stock_value_by_category returned no values")
    print("PASS  InventoryService validation, filters, and aggregates")
    deps["store"].close()

    cli(cli_path, database, "product", "delete", "--id", str(saw["id"]))
    connection = sqlite3.connect(database)
    remaining = rows_for(connection, product_table)
    connection.close()
    if "T-2" in {row["sku"] for row in remaining}:
        fail("product delete did not remove the row")
    print("PASS  product delete")
    print("PASS  all inventory acceptance checks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
