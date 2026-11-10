"""Behavior acceptance for the small-business orders/invoices prompt.

Run only after real extraction and generation have populated ``OUT_DIR``::

    python3.12 tests/e2e_60_acceptance.py out/60_same_conditions

The prompt does not spell command, service, method or table names, so this
test discovers them from the generated package wherever it can.  It drives the
generated CLI through fresh processes for the user-facing setup and admin
surface, and calls the generated package in-process (``cli.build_cli``) for
the order state machine, stock reservation and invoice behaviour.  Money may
be stored as integer cents or as a decimal/float; totals are accepted in either
representation when the value is right.  Cancelling a confirmed order is
assumed to leave the invoice in place (the prompt only requires the stock to be
released), so the test does not require the invoice to be deleted.
"""

import argparse
import contextlib
import csv
import datetime as dt
import inspect
import json
import sqlite3
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_library_acceptance as lib  # noqa: E402

sys.dont_write_bytecode = True


# ---------------------------------------------------------------------------
# Names the prompt leaves open
# ---------------------------------------------------------------------------

CUSTOMER = ("customer", "customers", "client", "clients", "buyer", "buyers")
CATEGORY = ("category", "categories")
PRODUCT = ("product", "products", "article", "articles", "catalog")
ORDER = ("order", "orders", "purchase", "purchases")
INVOICE = ("invoice", "invoices", "bill", "bills")
ITEM = ("item", "items", "line", "lines", "entry", "entries")

CREATE_ACTIONS = ("create", "add", "new", "register", "place")
LIST_ACTIONS = ("list", "all", "browse", "show", "get", "read")
SEARCH_ACTIONS = ("search", "find", "query", "history", "mine")
UPDATE_ACTIONS = ("update", "edit", "change", "modify", "set")
DELETE_ACTIONS = ("delete", "remove", "destroy")
CONFIRM_ACTIONS = ("confirm", "approve", "checkout")
CANCEL_ACTIONS = ("cancel", "void")
SHIP_ACTIONS = ("ship", "dispatch", "deliver")
STATUS_ACTIONS = ("status",)

ORDER_LIST_NAMES = (
    "get_orders_by_customer", "get_customer_orders",
    "list_orders_by_customer", "list_customer_orders",
    "list_orders_for_customer", "get_orders_for_customer",
    "find_orders_by_customer", "search_orders", "get_order_history",
    "read_orders_by_customer", "list_my_orders", "list_orders",
    "read_all_orders", "get_orders",
)
INVOICE_LIST_NAMES = (
    "get_invoices_by_customer", "get_customer_invoices",
    "list_invoices_by_customer", "list_customer_invoices",
    "list_invoices_for_customer", "get_invoices_for_customer",
    "find_invoices_by_customer", "search_invoices",
    "read_invoices_by_customer", "list_my_invoices", "list_invoices",
    "read_all_invoices", "get_invoices",
)
UPDATE_STATUS_NAMES = (
    "update_order_status", "set_order_status", "change_order_status",
    "update_status", "set_status", "mark_status",
)
ACTION_EXACT = {
    "confirm": ("confirm_order", "approve_order", "checkout_order",
                "confirm_purchase"),
    "cancel": ("cancel_order", "void_order", "cancel_purchase"),
    "ship": ("ship_order", "dispatch_order", "deliver_order", "mark_shipped"),
}
ACTION_TARGET = {"confirm": "confirmed", "cancel": "cancelled",
                 "ship": "shipped"}
ACTION_LEAF_GROUPS = {
    "confirm": (CONFIRM_ACTIONS, STATUS_ACTIONS, UPDATE_ACTIONS),
    "cancel": (CANCEL_ACTIONS, STATUS_ACTIONS, UPDATE_ACTIONS),
    "ship": (SHIP_ACTIONS, STATUS_ACTIONS, UPDATE_ACTIONS),
}

SEMANTIC_OPTION_ALIASES = {
    "name": ("name",),
    "email": ("email",),
    "phone": ("phone", "telephone"),
    "address": ("address",),
    "description": ("description", "details"),
    "price": ("price", "unit_price", "price_cents", "unit_price_cents"),
    "stock_quantity": ("stock_quantity", "stock", "stock_qty", "quantity",
                       "initial_stock", "available_stock"),
    "category_id": ("category_id", "category", "categoryid"),
    "customer_id": ("customer_id", "customer", "customerid"),
    "order_id": ("order_id", "order", "orderid", "id"),
    "product_id": ("product_id", "product", "productid", "id"),
    "invoice_id": ("invoice_id", "invoice", "invoiceid", "id"),
    "quantity": ("quantity", "qty"),
    "status": ("status", "new_status", "order_status"),
    "id": ("id",),
}
PARAM_ALIASES = {
    "id": ("order_id", "customer_id", "product_id", "invoice_id",
           "category_id", "id"),
    "orderid": ("order_id", "orderid", "id", "order"),
    "customerid": ("customer_id", "customerid", "id", "customer"),
    "productid": ("product_id", "productid", "id", "product"),
    "invoiceid": ("invoice_id", "invoiceid", "id", "invoice"),
    "categoryid": ("category_id", "categoryid", "id", "category"),
    "quantity": ("quantity", "qty"),
    "unitprice": ("unit_price", "unitprice", "price"),
    "price": ("price", "unit_price", "price_cents", "unit_price_cents"),
    "status": ("status", "new_status", "order_status"),
}
OPTIONAL_FIELDS = {"email", "phone", "address", "description"}


def normalize(text):
    return "".join(character for character in str(text).lower()
                   if character.isalnum())


def word_hits(word, aliases):
    if not word:
        return False
    for alias in aliases:
        wanted = normalize(alias)
        if not wanted:
            continue
        if word == wanted or word.startswith(wanted) or wanted.startswith(word):
            return True
        if len(wanted) >= 4 and wanted in word:
            return True
    return False


# ---------------------------------------------------------------------------
# CLI discovery
# ---------------------------------------------------------------------------

class Leaf:
    """One runnable command path and the options it declares."""

    def __init__(self, path, options):
        self.path = tuple(str(part) for part in path)
        self.options = options

    def option(self, semantic):
        key = normalize(semantic)
        aliases = [normalize(alias)
                   for alias in SEMANTIC_OPTION_ALIASES.get(key, (semantic,))]
        for alias in aliases:
            for option in self.options:
                if normalize(option["dest"]) == alias:
                    return option
        for alias in aliases:
            for option in self.options:
                for flag in option["flags"]:
                    if normalize(flag) == alias:
                        return option
        for alias in aliases:
            if len(alias) < 3:
                continue
            matches = [
                option for option in self.options
                if normalize(option["dest"]).endswith(alias)
                or normalize(option["dest"]).startswith(alias)
                or alias in normalize(option["dest"])
            ]
            unique = {id(option): option for option in matches}
            if len(unique) == 1:
                return matches[0]
        return None

    def describe(self):
        return " ".join(self.path)

    def describe_options(self):
        return sorted(option["flags"][0] for option in self.options)


def option_value(semantic, value, option):
    key = normalize(semantic)
    if key == "price" and option.get("otype") == "int":
        try:
            return str(int((Decimal(str(value)) * 100).to_integral_value()))
        except Exception:  # noqa: BLE001 - an odd price is reported by the CLI
            return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


class CliSurface:
    """The generated command tree, read from click data or argparse."""

    def __init__(self, out_dir, cli_path, database):
        self.out = Path(out_dir).resolve()
        self.cli_path = Path(cli_path)
        self.database = Path(database)
        self.leaves = self._discover()
        if not self.leaves:
            lib.fail(f"no CLI commands could be discovered from {self.cli_path}")

    def _discover(self):
        generated = str(self.out / "generated")
        if generated not in sys.path:
            sys.path.insert(0, generated)
        import cli as generated_cli
        self.module = generated_cli

        commands = getattr(generated_cli, "COMMANDS", None)
        if isinstance(commands, dict) and commands:
            leaves = []
            self._walk_commands(commands, (), leaves)
            if leaves:
                return leaves

        build_parser = getattr(generated_cli, "build_parser", None)
        if callable(build_parser):
            try:
                parser = build_parser()
            except Exception:  # noqa: BLE001 - fall through to other shapes
                parser = None
            if parser is not None:
                leaves = []
                self._walk_argparse(parser, (), leaves)
                if leaves:
                    return leaves

        group = getattr(generated_cli, "cli", None)
        if group is not None and hasattr(group, "commands"):
            leaves = []
            self._walk_click(group, (), leaves)
            if leaves:
                return leaves
        return []

    def _walk_commands(self, tree, prefix, leaves):
        for name, spec in tree.items():
            if not isinstance(spec, dict):
                continue
            path = prefix + (str(name),)
            subs = spec.get("subcommands")
            plans = spec.get("plans") or []
            if isinstance(subs, dict) and subs:
                self._walk_commands(subs, path, leaves)
            if plans or "binding" in spec or not subs:
                leaves.append(Leaf(path, self._plan_options(plans)))

    @staticmethod
    def _plan_options(plans):
        options = []
        for plan in plans or []:
            if not isinstance(plan, dict):
                continue
            flags = [str(flag) for flag in plan.get("flags") or []
                     if str(flag).startswith("-")]
            if not flags:
                continue
            chosen = next((flag for flag in flags if flag.startswith("--")),
                          flags[0])
            otype = str(plan.get("otype") or "str")
            options.append({
                "dest": str(plan.get("dest") or ""),
                "flags": [chosen],
                "required": bool(plan.get("required")),
                "otype": otype,
                "is_flag": otype == "bool",
            })
        return options

    def _walk_argparse(self, parser, prefix, leaves):
        subparsers = [action for action in parser._actions
                      if isinstance(action, argparse._SubParsersAction)]
        if not subparsers:
            if prefix:
                leaves.append(Leaf(prefix, self._argparse_options(parser)))
            return
        for name, child in subparsers[0].choices.items():
            self._walk_argparse(child, prefix + (str(name),), leaves)

    @staticmethod
    def _argparse_options(parser):
        options = []
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                continue
            dest = getattr(action, "dest", None)
            if dest in (None, "help", "db", "_binding", "_parent_binding",
                        "command", "subcommand"):
                continue
            flags = [str(flag) for flag in getattr(action, "option_strings", [])
                     if str(flag).startswith("-")]
            if not flags:
                continue
            chosen = next((flag for flag in flags if flag.startswith("--")),
                          flags[0])
            kind = type(action).__name__
            is_flag = (kind in ("_StoreTrueAction", "_StoreFalseAction")
                       or getattr(action, "nargs", None) == 0)
            action_type = getattr(action, "type", None)
            if is_flag:
                otype = "bool"
            elif action_type is int:
                otype = "int"
            elif action_type is float:
                otype = "float"
            else:
                otype = "str"
            options.append({
                "dest": str(dest),
                "flags": [chosen],
                "required": bool(getattr(action, "required", False)),
                "otype": otype,
                "is_flag": is_flag,
            })
        return options

    def _walk_click(self, command, prefix, leaves):
        subcommands = getattr(command, "commands", None)
        if subcommands:
            for name, child in subcommands.items():
                self._walk_click(child, prefix + (str(name),), leaves)
            return
        options = []
        for parameter in getattr(command, "params", []):
            flags = [str(flag) for flag in getattr(parameter, "opts", [])
                     if str(flag).startswith("-")]
            if not flags:
                continue
            chosen = next((flag for flag in flags if flag.startswith("--")),
                          flags[0])
            is_flag = bool(getattr(parameter, "is_flag", False))
            type_name = type(getattr(parameter, "type", None)).__name__.lower()
            otype = "bool" if is_flag else (
                "int" if "int" in type_name
                else "float" if "float" in type_name else "str")
            options.append({
                "dest": str(getattr(parameter, "name", "")),
                "flags": [chosen],
                "required": bool(getattr(parameter, "required", False)),
                "otype": otype,
                "is_flag": is_flag,
            })
        leaves.append(Leaf(prefix, options))

    def find_leaf(self, entity_aliases, action_groups, required_fields=()):
        for action_aliases in action_groups:
            scored = []
            for leaf in self.leaves:
                words = [normalize(part) for part in leaf.path
                         if normalize(part)]
                entity_positions = [
                    index for index, word in enumerate(words)
                    if word_hits(word, entity_aliases)
                ]
                action_positions = [
                    index for index, word in enumerate(words)
                    if word_hits(word, action_aliases)
                ]
                if not entity_positions or not action_positions:
                    continue
                if required_fields and not all(
                        leaf.option(field) for field in required_fields):
                    continue
                score = 0
                if entity_positions[-1] == len(words) - 1:
                    score += 8
                if action_positions[-1] == len(words) - 1:
                    score += 8
                score += (3 * len(entity_positions)
                          + 3 * len(action_positions) - len(words))
                scored.append((score, leaf))
            if not scored:
                continue
            scored.sort(key=lambda pair: pair[0], reverse=True)
            top = scored[0][0]
            best = {leaf.path: leaf for score, leaf in scored if score == top}
            ordered = sorted(best.values(),
                             key=lambda leaf: (len(leaf.path), leaf.path))
            return ordered[0]
        return None

    def need_leaf(self, entity_aliases, action_groups, required_fields=(),
                  purpose=""):
        leaf = self.find_leaf(entity_aliases, action_groups, required_fields)
        if leaf is None:
            purpose = purpose or entity_aliases[0]
            lib.fail(f"no CLI command found for {purpose}; available: "
                     f"{self.describe()}")
        return leaf

    def describe(self):
        paths = sorted(" ".join(leaf.path) for leaf in self.leaves)
        shown = ", ".join(paths[:20])
        return shown + (" ..." if len(paths) > 20 else "")

    def run(self, leaf, expected=0, **kwargs):
        args = []
        used = set()
        for key, value in kwargs.items():
            if value is None:
                continue
            option = leaf.option(key)
            if option is None:
                if normalize(key) in {normalize(field)
                                      for field in OPTIONAL_FIELDS}:
                    continue
                lib.fail(f"CLI command {leaf.describe()!r} has no option for "
                         f"{key!r}; options: {leaf.describe_options()}")
            used.add(id(option))
            if option["is_flag"]:
                if value:
                    args.append(option["flags"][0])
            else:
                args.extend([option["flags"][0],
                             option_value(key, value, option)])
        missing = [option for option in leaf.options
                   if option["required"] and id(option) not in used]
        if missing:
            lib.fail(f"CLI command {leaf.describe()!r} still requires "
                     f"{[option['dest'] for option in missing]}; "
                     f"given {sorted(kwargs)}")
        return lib.cli(self.cli_path, self.database, *leaf.path, *args,
                       expected=expected)


# ---------------------------------------------------------------------------
# SQLite discovery
# ---------------------------------------------------------------------------

def table_names(connection):
    return [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'")]


def table_columns(connection, table):
    return [row[1] for row in connection.execute(
        f"PRAGMA table_info({lib.quoted(table)})")]


def find_table(connection, hint=None, required=()):
    required = set(required)
    candidates = []
    for table in table_names(connection):
        columns = set(table_columns(connection, table))
        if required and not required <= columns:
            continue
        score = 0
        if hint:
            wanted = normalize(hint)
            name = normalize(table)
            if name in (wanted, wanted + "s", wanted + "es"):
                score += 30
            elif wanted in name:
                score += 20
        candidates.append((score, table))
    if hint:
        hinted = [candidate for candidate in candidates if candidate[0] > 0]
        if hinted:
            candidates = hinted
    if not candidates:
        lib.fail(f"no SQLite table matches hint {hint!r} and columns "
                 f"{sorted(required)}")
    candidates.sort(key=lambda pair: (-pair[0], pair[1]))
    top = candidates[0][0]
    best = [table for score, table in candidates if score == top]
    if len(best) > 1:
        lib.fail(f"ambiguous SQLite tables for hint {hint!r}: {best}")
    return best[0]


def column_like(columns, *aliases):
    for alias in aliases:
        for column in columns:
            if normalize(column) == normalize(alias):
                return column
    for alias in aliases:
        for column in columns:
            if normalize(alias) in normalize(column):
                return column
    return None


def primary_key(connection, table):
    for row in connection.execute(f"PRAGMA table_info({lib.quoted(table)})"):
        if row[5]:
            return row[1]
    return "id"


def table_key(name):
    normal = normalize(name)
    if normal.endswith("ies"):
        return normal[:-3] + "y"
    if normal.endswith("s"):
        return normal[:-1]
    return normal


def has_reference(connection, table, source, target_table, target_column):
    for row in connection.execute(
            f"PRAGMA foreign_key_list({lib.quoted(table)})"):
        if row[3] != source:
            continue
        if table_key(row[2]) != table_key(target_table):
            continue
        if not row[4] or row[4] == target_column:
            return True
    return False


def assert_foreign_keys(connection):
    problems = connection.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        lib.fail(f"foreign-key violations after the scenario: {problems}")


# ---------------------------------------------------------------------------
# Service/model helpers
# ---------------------------------------------------------------------------

def service_items(deps):
    return [(name, service) for name, service in deps["services"].items()
            if normalize(name).endswith("service")]


def method_accepts(method, semantic):
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return True
    aliases = [normalize(alias)
               for alias in SEMANTIC_OPTION_ALIASES.get(normalize(semantic),
                                                        (semantic,))]
    for name, parameter in signature.parameters.items():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        normal = normalize(name)
        if any(normal == alias or normal.endswith(alias)
               for alias in aliases):
            return True
    return False


def service_methods(deps, exact=(), tokens=(), any_tokens=(), accepts=None):
    found = []
    seen = set()

    def add(method, label):
        if label in seen:
            return
        if accepts is not None and not method_accepts(method, accepts):
            return
        seen.add(label)
        found.append((method, label))

    for name, service in service_items(deps):
        for candidate in exact:
            method = getattr(service, candidate, None)
            if callable(method):
                add(method, f"{name}.{candidate}")
    for name, service in service_items(deps):
        for attribute in sorted(dir(service)):
            if attribute.startswith("_"):
                continue
            method = getattr(service, attribute)
            if not callable(method):
                continue
            normal = normalize(attribute)
            if tokens and not all(token in normal for token in tokens):
                continue
            if any_tokens and not any(token in normal
                                      for token in any_tokens):
                continue
            add(method, f"{name}.{attribute}")
    return found


def invoke(method, label, *, id_hint=None, **kwargs):
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return method(**kwargs)

    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD
           for parameter in parameters.values()):
        return method(**kwargs)

    sentinel = object()
    call_kwargs = {}
    missing = []
    for name, parameter in parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL,
                              inspect.Parameter.VAR_KEYWORD):
            continue
        if name in kwargs:
            call_kwargs[name] = kwargs[name]
            continue
        if normalize(name) == "id":
            # `id` is the record's own key only when a caller says which
            # semantic id it means; otherwise it must stay unset.
            aliases = (id_hint,) if id_hint else ("id",)
        else:
            aliases = PARAM_ALIASES.get(normalize(name),
                                        SEMANTIC_OPTION_ALIASES.get(
                                            normalize(name), (name,)))
        value = sentinel
        for alias in aliases:
            for key, candidate in kwargs.items():
                if normalize(key) == normalize(alias):
                    value = candidate
                    break
            if value is not sentinel:
                break
        if value is not sentinel:
            call_kwargs[name] = value
        elif parameter.default is inspect.Parameter.empty:
            missing.append(name)
    if missing:
        lib.fail(f"{label} requires {missing}; the test supplied "
                 f"{sorted(kwargs)}")
    return method(**call_kwargs)


def find_repo(deps, entity):
    wanted = normalize(entity) + "repository"
    for key, repo in deps["repos"].items():
        if normalize(key) == wanted:
            return repo
    for key, repo in deps["repos"].items():
        if wanted in normalize(key) or normalize(key) in wanted:
            return repo
    lib.fail(f"no repository for {entity}; have {sorted(deps['repos'])}")


def repo_create(repo, label, **values):
    method = lib.need(repo, "create", label)
    return invoke(method, label, **values)


def records_of(value):
    if value is None:
        return []
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, list):
                return list(item)
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def record_get(record, *names):
    for name in names:
        if isinstance(record, dict):
            if name in record:
                return record[name]
            for key, value in record.items():
                if normalize(key) == normalize(name):
                    return value
        elif hasattr(record, name):
            return getattr(record, name)
    return None


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return value


def record_id(record, pk):
    return as_int(record_get(record, pk, "id"))


def json_values(output):
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
        if isinstance(item, list):
            rows.extend(item)
        else:
            rows.append(item)
    return rows


def expect_error(label, call, markers=()):
    try:
        result = call()
    except Exception as error:  # noqa: BLE001 - the class name is the contract
        text = f"{type(error).__name__}: {error}"
        if markers and not any(marker.lower() in text.lower()
                               for marker in markers):
            lib.fail(f"{label} raised {type(error).__name__} ({error}), not "
                     f"one of {markers}")
        return error
    lib.fail(f"{label} unexpectedly succeeded with {result!r}")


def amount_matches(actual, expected):
    actual = Decimal(str(actual))
    expected = Decimal(str(expected))
    for candidate in (expected, expected / Decimal(100),
                      expected * Decimal(100)):
        if abs(actual - candidate) <= Decimal("0.01"):
            return True
    return False


# ---------------------------------------------------------------------------
# One generated package and its scenario state
# ---------------------------------------------------------------------------

class Fixture:
    def __init__(self, out_dir):
        self.out = Path(out_dir).resolve()
        self.cli_path = self.out / "generated" / "cli.py"
        if not self.cli_path.is_file():
            raise SystemExit(f"generated CLI is missing: {self.cli_path}")
        self.scratch = Path(tempfile.mkdtemp(prefix="orders-e2e-",
                                             dir=self.out))
        self.db = self.scratch / "acceptance.sqlite3"
        self.state = {}
        self._tables = None
        self._columns = {}
        self._pk = {}
        self._surface = None
        self._deps = None

    @property
    def surface(self):
        if self._surface is None:
            self._surface = CliSurface(self.out, self.cli_path, self.db)
        return self._surface

    def deps(self):
        if self._deps is None:
            self._deps = lib.generated_deps(self.out, self.db)
        return self._deps

    def close_deps(self):
        if self._deps is not None:
            try:
                self._deps["store"].close()
            finally:
                self._deps = None

    @contextlib.contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def tables(self):
        if self._tables is not None:
            return self._tables
        with self.connection() as connection:
            tables = {
                "customer": find_table(connection, "customer"),
                "category": find_table(connection, "categor"),
                "product": find_table(connection, "product"),
                "order": find_table(connection, "order"),
                "item": find_table(connection, "item",
                                   ("order_id", "product_id", "quantity")),
                "invoice": find_table(connection, "invoice"),
            }
            for entity, table in tables.items():
                self._columns[entity] = table_columns(connection, table)
                self._pk[entity] = primary_key(connection, table)
        self._tables = tables

        columns = self._columns
        state = self.state
        state["customer_pk"] = self._pk["customer"]
        state["customer_name_col"] = self.require_column("customer", "name")
        state["customer_email_col"] = column_like(columns["customer"],
                                                  "email")
        state["category_pk"] = self._pk["category"]
        state["category_name_col"] = self.require_column("category", "name")
        state["product_pk"] = self._pk["product"]
        state["product_name_col"] = self.require_column("product", "name")
        state["product_price_col"] = self.require_column(
            "product", "price", "unit_price", "price_cents",
            "unit_price_cents")
        state["product_stock_col"] = self.require_column(
            "product", "stock_quantity", "stock", "stock_qty", "quantity",
            "available_stock")
        state["product_category_col"] = self.require_column(
            "product", "category_id", "category", "product_category_id")
        state["order_pk"] = self._pk["order"]
        state["order_customer_col"] = self.require_column(
            "order", "customer_id", "customer")
        state["order_status_col"] = self.require_column(
            "order", "status", "order_status")
        state["item_pk"] = self._pk["item"]
        state["item_order_col"] = self.require_column(
            "item", "order_id", "order")
        state["item_product_col"] = self.require_column(
            "item", "product_id", "product")
        state["item_qty_col"] = self.require_column(
            "item", "quantity", "qty")
        # An order line may omit its own price (the invoice is then computed
        # from the product's current price, as the prompt's invariant says).
        state["item_price_col"] = column_like(
            columns["item"], "unit_price", "price", "unit_price_cents",
            "price_cents")
        state["invoice_pk"] = self._pk["invoice"]
        state["invoice_order_col"] = self.require_column(
            "invoice", "order_id", "order")
        state["invoice_customer_col"] = column_like(
            columns["invoice"], "customer_id", "customer")
        state["invoice_total_col"] = self.require_column(
            "invoice", "total_amount", "total", "amount", "total_cents",
            "amount_cents")
        state["invoice_number_col"] = column_like(
            columns["invoice"], "invoice_number", "number")
        return self._tables

    def require_column(self, entity, *aliases):
        column = column_like(self._columns[entity], *aliases)
        if column is None:
            lib.fail(f"{entity} table {self._tables[entity]!r} has no column "
                     f"like {aliases}; columns: {self._columns[entity]}")
        return column

    def rows(self, entity, **criteria):
        table = self._tables[entity] if entity in self._tables else entity
        with self.connection() as connection:
            return lib.rows_for(connection, table, **criteria)

    def one(self, entity, key_value):
        rows = self.rows(entity, **{self._pk[entity]: key_value})
        if not rows:
            lib.fail(f"{entity} {key_value!r} is missing from the database")
        return rows[0]

    def one_by(self, entity, column, value):
        rows = self.rows(entity, **{column: value})
        if len(rows) != 1:
            lib.fail(f"expected exactly one {entity} with {column}={value!r}, "
                     f"found {rows}")
        return rows[0]

    def count(self, entity):
        return len(self.rows(entity))

    def status(self, order_id):
        value = self.one("order", order_id)[self.state["order_status_col"]]
        return str(value).lower()

    def stock(self, product_id):
        return int(self.one("product", product_id)[
            self.state["product_stock_col"]])

    def order_items(self, order_id):
        return self.rows("item", **{self.state["item_order_col"]: order_id})

    def invoices_for(self, order_id):
        return self.rows("invoice", **{self.state["invoice_order_col"]:
                                      order_id})

    def product_prices(self, product):
        price_column = self.state["product_price_col"]
        value = Decimal(str(product[price_column]))
        if "cent" in normalize(price_column):
            cents = int(value.to_integral_value())
            return (value / Decimal(100)).quantize(Decimal("0.01")), cents
        return value, int((value * Decimal(100)).to_integral_value())

    def product_row(self, product_id):
        return self.one("product", product_id)

    # -- fixtures ---------------------------------------------------------

    def create_customer(self, name, email=None):
        leaf = self.surface.need_leaf(
            CUSTOMER, (CREATE_ACTIONS,), ("name",), "customer creation")
        self.surface.run(leaf, name=name, email=email,
                         phone="+1-555-0100", address="1 Test Way")
        self.tables()
        return self.one_by("customer", self.state["customer_name_col"], name)

    def create_category(self, name, description=""):
        leaf = self.surface.need_leaf(
            CATEGORY, (CREATE_ACTIONS,), ("name",), "category creation")
        self.surface.run(leaf, name=name, description=description)
        self.tables()
        return self.one_by("category", self.state["category_name_col"], name)

    def create_product(self, name, price, stock, category_id, description=""):
        leaf = self.surface.need_leaf(
            PRODUCT, (CREATE_ACTIONS,),
            ("name", "price", "stock_quantity", "category_id"),
            "product creation")
        self.surface.run(leaf, name=name, description=description, price=price,
                         stock_quantity=stock, category_id=category_id)
        self.tables()
        return self.one_by("product", self.state["product_name_col"], name)


# ---------------------------------------------------------------------------
# Order helpers
# ---------------------------------------------------------------------------

def create_order_with_items(fx, deps, customer_id, items):
    """An order and its lines, through the generated repositories.

    The prompt does not spell an item-flag syntax, so composing an order is
    done through the package on purpose; the confirmation/cancellation
    behaviour below is still the service's own code.
    """
    order_repo = find_repo(deps, "Order")
    item_repo = find_repo(deps, "OrderItem")
    now = dt.datetime.now()
    order_values = {
        "customer_id": customer_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "order_date": dt.date.today(),
        "date": dt.date.today(),
        "total_amount": 0.0,
        "total_amount_cents": 0,
        "total": 0.0,
        "total_cents": 0,
    }
    order = repo_create(order_repo, "OrderRepository.create", **order_values)
    order_id = (order if isinstance(order, int)
                else as_int(record_get(order, fx.state["order_pk"], "id")))
    if order_id is None:
        lib.fail(f"OrderRepository.create did not return a key: {order!r}")

    for product_id, quantity in items:
        product = fx.product_row(product_id)
        decimal_price, cents_price = fx.product_prices(product)
        # The store binds floats/ints, not Decimal objects; the generated
        # models accept either.  The cents variants keep integer money exact.
        unit_price = float(decimal_price)
        item_values = {
            "order_id": order_id,
            "product_id": product_id,
            "quantity": quantity,
            "unit_price": unit_price,
            "unit_price_cents": cents_price,
            "price": unit_price,
            "price_cents": cents_price,
            "total": unit_price * quantity,
            "total_cents": cents_price * quantity,
            "subtotal": unit_price * quantity,
            "subtotal_cents": cents_price * quantity,
        }
        repo_create(item_repo, "OrderItemRepository.create", **item_values)
    return order_id


def order_action(fx, deps, order_id, action):
    """Confirm/cancel/ship through the first generated implementation found.

    A stub (``NotImplementedError``) does not count as an implementation, so
    the search continues to the next service method and then to the CLI.
    """
    target = ACTION_TARGET[action]
    attempts = []
    for method, label in service_methods(deps, exact=ACTION_EXACT[action]):
        attempts.append((label, lambda method=method, label=label:
                         invoke(method, label, id_hint="order_id",
                                order_id=order_id)))
    for method, label in service_methods(deps, exact=UPDATE_STATUS_NAMES):
        attempts.append((label, lambda method=method, label=label:
                         invoke(method, label, id_hint="order_id",
                                order_id=order_id, status=target)))
    for method, label in service_methods(deps, exact=("update_order",),
                                         accepts="status"):
        attempts.append((label, lambda method=method, label=label:
                         invoke(method, label, id_hint="order_id",
                                order_id=order_id, status=target)))

    leaf = fx.surface.find_leaf(ORDER, ACTION_LEAF_GROUPS[action],
                                required_fields=("order_id",))
    if leaf is not None:
        kwargs = {"order_id": order_id}
        if leaf.option("status") is not None:
            kwargs["status"] = target
        attempts.append(("CLI " + leaf.describe(),
                         lambda leaf=leaf, kwargs=kwargs:
                         fx.surface.run(leaf, **kwargs)))
    if not attempts:
        lib.fail(f"no service method or CLI command can {action} order "
                 f"{order_id}")

    last_stub = None
    for label, call in attempts:
        try:
            call()
        except NotImplementedError as error:
            last_stub = (label, error)
            continue
        return label
    if last_stub is not None:
        raise last_stub[1]
    lib.fail(f"every implementation that could {action} order {order_id} "
             f"is a stub")


def list_for_customer(fx, deps, entity, customer_id):
    exact = ORDER_LIST_NAMES if entity == "order" else INVOICE_LIST_NAMES
    candidates = service_methods(deps, exact=exact, accepts="customer_id")
    candidates += service_methods(
        deps, tokens=(normalize(entity),),
        any_tokens=("list", "find", "search", "history", "bycustomer",
                    "forcustomer", "getcustomer", "customerorders",
                    "customerinvoices"),
        accepts="customer_id")
    seen = set()

    def aggregate(label):
        name = normalize(label.rsplit(".", 1)[-1])
        return any(word in name for word in
                   ("total", "count", "sum", "average", "aggregate",
                    "calculate", "report"))

    for method, label in candidates:
        flat = normalize(label.rsplit(".", 1)[-1])
        if label in seen or aggregate(label) or any(
                word in flat for word in
                ("create", "add", "new", "update", "delete", "remove",
                 "set", "confirm", "cancel", "ship")):
            # `create_order(customer_id, ...)` accepts the same parameter but
            # is a write, not a customer-scoped listing.
            continue
        seen.add(label)
        try:
            result = invoke(method, label, id_hint="customer_id",
                            customer_id=customer_id)
        except NotImplementedError:
            continue
        if not isinstance(result, (list, tuple, set, dict)):
            # `read_customer_by_id(customer_id)` accepts the same parameter
            # but returns one customer, not a customer's records.
            continue
        return records_of(result), label

    aliases = ORDER if entity == "order" else INVOICE
    leaf = fx.surface.find_leaf(aliases, (LIST_ACTIONS, SEARCH_ACTIONS),
                                required_fields=("customer_id",))
    if leaf is not None:
        result = fx.surface.run(leaf, customer_id=customer_id)
        return json_values(result.stdout), "CLI " + leaf.describe()
    lib.fail(f"no customer-scoped {entity} list method or CLI command")


def ids_of(records, pk):
    return {record_id(record, pk) for record in records}


def list_products(fx):
    """Product listing through the CLI, or through the package if absent."""
    leaf = fx.surface.find_leaf(PRODUCT, (LIST_ACTIONS, SEARCH_ACTIONS))
    # A search leaf may require a category; the prompt names no product-list
    # command and no mandatory filter, so only an argument-free leaf is a
    # valid drop-in for listing.
    if leaf is not None and not any(option["required"]
                                    for option in leaf.options):
        return json_values(fx.surface.run(leaf).stdout), "CLI " + leaf.describe()
    deps = lib.generated_deps(fx.out, fx.db)
    try:
        for method, label in service_methods(
                deps, exact=("read_all_products", "list_products",
                             "get_products", "all_products")):
            try:
                result = invoke(method, label)
            except NotImplementedError:
                continue
            return records_of(result), label
        repo = find_repo(deps, "Product")
        method = lib.need(repo, "read_all", "ProductRepository.read_all")
        records = records_of(invoke(method, "ProductRepository.read_all"))
        return records, type(repo).__name__ + ".read_all"
    finally:
        deps["store"].close()


def assert_invoice(fx, order_id, customer_id):
    state = fx.state
    invoice_rows = fx.invoices_for(order_id)
    if len(invoice_rows) != 1:
        lib.fail(f"confirming order {order_id} should create exactly one "
                 f"invoice, found {len(invoice_rows)}")
    invoice = invoice_rows[0]
    if state["invoice_customer_col"]:
        if as_int(invoice[state["invoice_customer_col"]]) != customer_id:
            lib.fail(f"invoice for order {order_id} names customer "
                     f"{invoice[state['invoice_customer_col']]!r}, expected "
                     f"{customer_id}")
    else:
        # An invoice may identify its customer only through its order.
        order = fx.one("order", order_id)
        if as_int(order[state["order_customer_col"]]) != customer_id:
            lib.fail(f"invoice for order {order_id} belongs to customer "
                     f"{order[state['order_customer_col']]!r}, expected "
                     f"{customer_id}")
    total = Decimal(str(invoice[state["invoice_total_col"]]))
    if total <= 0:
        lib.fail(f"invoice for order {order_id} has a non-positive total "
                 f"{total}")
    items = fx.order_items(order_id)
    if not items:
        lib.fail(f"order {order_id} has no items to invoice")
    if state["item_price_col"]:
        expected = sum(
            Decimal(str(item[state["item_price_col"]]))
            * int(item[state["item_qty_col"]])
            for item in items
        )
    else:
        expected = Decimal("0")
        for item in items:
            product = fx.product_row(as_int(
                item[state["item_product_col"]]))
            expected += (Decimal(str(product[state["product_price_col"]]))
                         * int(item[state["item_qty_col"]]))
    if not amount_matches(total, expected):
        lib.fail(f"invoice total {total} does not match the order lines "
                 f"({expected}); items={items}")
    number_column = state["invoice_number_col"]
    if number_column and not str(invoice[number_column] or "").strip():
        lib.fail(f"invoice for order {order_id} has an empty invoice number")
    return invoice


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def check_cli_master_data(fx):
    """Customers, categories and products are created through the CLI."""
    fx.create_customer("Ada Buyer", "ada@example.test")
    fx.create_customer("Bob Buyer", "bob@example.test")
    office = fx.create_category("Office", "desks and lamps")
    supplies = fx.create_category("Supplies", "paper and pens")
    fx.state["category_ids"] = {
        "Office": as_int(office[fx.state["category_pk"]]),
        "Supplies": as_int(supplies[fx.state["category_pk"]]),
    }
    fx.state["customer_ids"] = {
        row[fx.state["customer_name_col"]]:
            as_int(row[fx.state["customer_pk"]])
        for row in fx.rows("customer")
    }

    products = {
        "Standing Desk": ("120.00", 5, "Office"),
        "Desk Lamp": ("25.50", 3, "Office"),
        "Notebook": ("4.00", 1, "Supplies"),
        "Pen": ("1.50", 10, "Supplies"),
        "Shelf": ("40.00", 2, "Office"),
    }
    fx.state["product_ids"] = {}
    for name, (price, stock, category) in products.items():
        row = fx.create_product(name, price, stock,
                                fx.state["category_ids"][category],
                                f"{name} description")
        fx.state["product_ids"][name] = as_int(row[fx.state["product_pk"]])

    if fx.count("customer") != 2:
        lib.fail(f"expected 2 customers, found {fx.count('customer')}")
    if fx.count("category") != 2:
        lib.fail(f"expected 2 categories, found {fx.count('category')}")
    if fx.count("product") != 5:
        lib.fail(f"expected 5 products, found {fx.count('product')}")

    state = fx.state
    stock_column = state["product_stock_col"]
    price_column = state["product_price_col"]
    category_column = state["product_category_col"]
    for name, (price, stock, category) in products.items():
        row = fx.one("product", state["product_ids"][name])
        if int(row[stock_column]) != stock:
            lib.fail(f"product {name!r} stored stock "
                     f"{row[stock_column]!r}, expected {stock}")
        if Decimal(str(row[price_column])) <= 0:
            lib.fail(f"product {name!r} stored non-positive price "
                     f"{row[price_column]!r}")
        if as_int(row[category_column]) != state["category_ids"][category]:
            lib.fail(f"product {name!r} points at category "
                     f"{row[category_column]!r}, expected "
                     f"{state['category_ids'][category]}")

    listed, source = list_products(fx)
    names = {record_get(row, "name", "product_name") for row in listed}
    if not set(products) <= names:
        lib.fail(f"{source} did not return every product: {names}")

    with fx.connection() as connection:
        assert_foreign_keys(connection)
        references = (
            ("product", state["product_category_col"], "category",
             state["category_pk"]),
            ("order", state["order_customer_col"], "customer",
             state["customer_pk"]),
            ("item", state["item_order_col"], "order", state["order_pk"]),
            ("item", state["item_product_col"], "product",
             state["product_pk"]),
            ("invoice", state["invoice_order_col"], "order",
             state["order_pk"]),
        )
        if state["invoice_customer_col"]:
            references += (
                ("invoice", state["invoice_customer_col"], "customer",
                 state["customer_pk"]),
            )
        for entity, source, target, target_pk in references:
            if not has_reference(connection, fx.tables()[entity], source,
                                 fx.tables()[target], target_pk):
                lib.fail(f"{entity}.{source} is not a foreign key to "
                         f"{target}.{target_pk}")


def check_admin_and_validation(fx):
    """Product update/delete through admin operations, and bad input."""
    state = fx.state
    spare_id = state["product_ids"]["Shelf"]
    spare = fx.one("product", spare_id)
    old_price = Decimal(str(spare[state["product_price_col"]]))

    update_leaf = fx.surface.find_leaf(
        PRODUCT, (UPDATE_ACTIONS,), required_fields=("product_id",))
    cli_price = (update_leaf.option("price")
                 if update_leaf is not None else None)
    cli_stock = (update_leaf.option("stock_quantity")
                 if update_leaf is not None else None)
    if update_leaf is not None and (cli_price or cli_stock):
        kwargs = {"product_id": spare_id}
        if cli_price is not None:
            kwargs["price"] = "45.00"
        if cli_stock is not None:
            kwargs["stock_quantity"] = 4
        fx.surface.run(update_leaf, **kwargs)

    if cli_price is None or cli_stock is None:
        # The CLI may expose only part of the admin update; complete the
        # other field through the generated repository and verify both.
        deps = lib.generated_deps(fx.out, fx.db)
        try:
            repo = find_repo(deps, "Product")
            method = lib.need(repo, "update", "product update")
            decimal_price, cents_price = fx.product_prices(spare)
            new_price = float(decimal_price + Decimal("5.00"))
            invoke(method, type(repo).__name__ + ".update",
                   id_hint="product_id", product_id=spare_id,
                   price=new_price, price_cents=cents_price + 500,
                   unit_price=new_price,
                   unit_price_cents=cents_price + 500,
                   stock_quantity=4)
        finally:
            deps["store"].close()

    updated = fx.one("product", spare_id)
    if int(updated[state["product_stock_col"]]) != 4:
        lib.fail(f"product update did not persist stock 4: {updated}")
    if Decimal(str(updated[state["product_price_col"]])) == old_price:
        lib.fail(f"product update did not change the price: {updated}")

    delete_leaf = fx.surface.find_leaf(
        PRODUCT, (DELETE_ACTIONS,), required_fields=("product_id",))
    if delete_leaf is not None:
        fx.surface.run(delete_leaf, product_id=spare_id)
    else:
        deps = lib.generated_deps(fx.out, fx.db)
        try:
            repo = find_repo(deps, "Product")
            method = lib.need(repo, "delete", "product delete")
            invoke(method, type(repo).__name__ + ".delete",
                   id_hint="product_id", product_id=spare_id)
        finally:
            deps["store"].close()
    if fx.rows("product", **{state["product_pk"]: spare_id}):
        lib.fail("product delete did not remove the spare product")
    state["product_ids"].pop("Shelf", None)

    before = fx.count("product")
    create_leaf = fx.surface.need_leaf(
        PRODUCT, (CREATE_ACTIONS,),
        ("name", "price", "stock_quantity", "category_id"),
        "product creation")
    label, name = "unknown category", "Orphan Product"
    result = fx.surface.run(create_leaf, expected=1, name=name,
                            description=label, price="1.00",
                            stock_quantity=1, category_id=999999)
    message = (result.stdout + result.stderr).strip()
    if not message:
        lib.fail(f"{label} was refused without an error message")
    if fx.count("product") != before:
        lib.fail(f"{label} partially inserted a product")
    if fx.rows("product", **{state["product_name_col"]: name}):
        lib.fail(f"{label} stored the rejected product {name!r}")


def check_pending_order(fx):
    """An order with several products starts pending and keeps stock."""
    deps = fx.deps()
    state = fx.state
    customer_a = state["customer_ids"]["Ada Buyer"]
    customer_b = state["customer_ids"]["Bob Buyer"]
    product = state["product_ids"]
    before = {name: fx.stock(product_id)
              for name, product_id in product.items()}

    order_a = create_order_with_items(
        fx, deps, customer_a,
        [(product["Standing Desk"], 2), (product["Desk Lamp"], 1)])
    order_b = create_order_with_items(
        fx, deps, customer_b, [(product["Notebook"], 1)])
    state["order_ids"] = {"A": order_a, "B": order_b}

    for key, order_id, customer_id in (
            ("A", order_a, customer_a), ("B", order_b, customer_b)):
        order = fx.one("order", order_id)
        if str(order[state["order_status_col"]]).lower() != "pending":
            lib.fail(f"new order {key} should be pending, found "
                     f"{order[state['order_status_col']]!r}")
        if as_int(order[state["order_customer_col"]]) != customer_id:
            lib.fail(f"order {key} names customer "
                     f"{order[state['order_customer_col']]!r}, expected "
                     f"{customer_id}")

    items = fx.order_items(order_a)
    if len(items) != 2:
        lib.fail(f"order A should contain two lines, found {len(items)}")
    quantities = {as_int(item[state["item_product_col"]]):
                  int(item[state["item_qty_col"]]) for item in items}
    expected = {product["Standing Desk"]: 2, product["Desk Lamp"]: 1}
    if quantities != expected:
        lib.fail(f"order A lines are {quantities}, expected {expected}")

    after = {name: fx.stock(product_id)
             for name, product_id in product.items()}
    if after != before:
        lib.fail(f"creating a pending order must not reserve stock: "
                 f"{before} -> {after}")
    with fx.connection() as connection:
        assert_foreign_keys(connection)


def check_confirm_reserves_stock_and_invoices(fx):
    """Confirming reserves each product's stock and creates one invoice."""
    deps = fx.deps()
    state = fx.state
    product = state["product_ids"]
    customer_a = state["customer_ids"]["Ada Buyer"]
    customer_b = state["customer_ids"]["Bob Buyer"]
    order_a = state["order_ids"]["A"]
    order_b = state["order_ids"]["B"]

    order_action(fx, deps, order_a, "confirm")
    order_action(fx, deps, order_b, "confirm")

    for key, order_id in (("A", order_a), ("B", order_b)):
        if fx.status(order_id) != "confirmed":
            lib.fail(f"order {key} should be confirmed, found "
                     f"{fx.status(order_id)!r}")

    if fx.stock(product["Standing Desk"]) != 3:
        lib.fail(f"confirming order A should leave 3 standing desks, found "
                 f"{fx.stock(product['Standing Desk'])}")
    if fx.stock(product["Desk Lamp"]) != 2:
        lib.fail(f"confirming order A should leave 2 desk lamps, found "
                 f"{fx.stock(product['Desk Lamp'])}")
    if fx.stock(product["Notebook"]) != 0:
        lib.fail(f"confirming order B should leave 0 notebooks, found "
                 f"{fx.stock(product['Notebook'])}")

    invoice_a = assert_invoice(fx, order_a, customer_a)
    invoice_b = assert_invoice(fx, order_b, customer_b)
    state["invoice_ids"] = {
        "A": as_int(invoice_a[state["invoice_pk"]]),
        "B": as_int(invoice_b[state["invoice_pk"]]),
    }
    with fx.connection() as connection:
        assert_foreign_keys(connection)


def check_customer_lists(fx):
    """Each customer sees only their own orders and invoices."""
    deps = fx.deps()
    state = fx.state
    customer_a = state["customer_ids"]["Ada Buyer"]
    customer_b = state["customer_ids"]["Bob Buyer"]
    order_a = state["order_ids"]["A"]
    order_b = state["order_ids"]["B"]
    invoice_a = state["invoice_ids"]["A"]
    invoice_b = state["invoice_ids"]["B"]

    for entity, customer, expected, pk in (
            ("order", customer_a, {order_a}, state["order_pk"]),
            ("invoice", customer_a, {invoice_a}, state["invoice_pk"]),
            ("order", customer_b, {order_b}, state["order_pk"]),
            ("invoice", customer_b, {invoice_b}, state["invoice_pk"])):
        records, source = list_for_customer(fx, deps, entity, customer)
        found = ids_of(records, pk)
        if found != expected:
            lib.fail(f"{source} returned {entity} ids {found} for customer "
                     f"{customer}; expected {expected}")
    customer_repo = deps["repos"].get("CustomerRepository")
    if callable(getattr(customer_repo, "find_invoices_by_customer_id", None)):
        direct = customer_repo.find_invoices_by_customer_id(customer_a)
        found = ids_of(direct, state["invoice_pk"])
        if found != {invoice_a}:
            lib.fail(f"CustomerRepository.find_invoices_by_customer_id "
                     f"returned {found}; expected {{invoice_a}}")
    report_service = deps["services"].get("ReportService")
    if callable(getattr(report_service, "get_order_status_report", None)):
        report = report_service.get_order_status_report()
        orders = deps["repos"]["OrderRepository"].read_all()
        expected_counts = {"pending": 0, "confirmed": 0, "shipped": 0,
                           "cancelled": 0}
        for order in orders:
            if order.status in expected_counts:
                expected_counts[order.status] += 1
        for status, count in expected_counts.items():
            if report.get(status) != count:
                lib.fail(f"order status report must include {status!r} "
                         f"with count {count}: {report}")


def check_cancel_releases_stock(fx):
    """Cancelling a confirmed order restores the reserved stock."""
    deps = fx.deps()
    state = fx.state
    product = state["product_ids"]
    order_a = state["order_ids"]["A"]

    order_action(fx, deps, order_a, "cancel")
    if fx.status(order_a) != "cancelled":
        lib.fail(f"order A should be cancelled, found {fx.status(order_a)!r}")
    if fx.stock(product["Standing Desk"]) != 5:
        lib.fail(f"cancelling order A should restore 5 standing desks, found "
                 f"{fx.stock(product['Standing Desk'])}")
    if fx.stock(product["Desk Lamp"]) != 3:
        lib.fail(f"cancelling order A should restore 3 desk lamps, found "
                 f"{fx.stock(product['Desk Lamp'])}")
    if fx.stock(product["Notebook"]) != 0:
        lib.fail("cancelling order A must not touch order B's stock")
    with fx.connection() as connection:
        assert_foreign_keys(connection)


def check_refusals(fx):
    """Unknown customers and insufficient stock are refused atomically."""
    deps = fx.deps()
    state = fx.state
    product = state["product_ids"]
    customer_b = state["customer_ids"]["Bob Buyer"]

    orders_before = fx.count("order")
    items_before = fx.count("item")
    expect_error(
        "creating an order for an unknown customer",
        lambda: create_order_with_items(fx, deps, 999999,
                                        [(product["Pen"], 1)]),
        markers=("notfound", "customer", "foreign", "invalid", "value"))
    if fx.count("order") != orders_before \
            or fx.count("item") != items_before:
        lib.fail("an order for an unknown customer partially inserted rows")

    order_c = create_order_with_items(fx, deps, customer_b,
                                      [(product["Pen"], 11)])
    state["order_ids"]["C"] = order_c
    stocks_before = {name: fx.stock(product_id)
                     for name, product_id in product.items()}
    expect_error(
        f"confirming order C with only {stocks_before['Pen']} pens in stock",
        lambda: order_action(fx, deps, order_c, "confirm"),
        markers=("stock", "insufficient", "quantity", "invalid"))
    if fx.status(order_c) != "pending":
        lib.fail(f"a refused confirmation changed order C to "
                 f"{fx.status(order_c)!r}")
    stocks_after = {name: fx.stock(product_id)
                    for name, product_id in product.items()}
    if stocks_after != stocks_before:
        lib.fail(f"a refused confirmation changed stock: "
                 f"{stocks_before} -> {stocks_after}")
    if fx.invoices_for(order_c):
        lib.fail("a refused confirmation created an invoice for order C")
    with fx.connection() as connection:
        assert_foreign_keys(connection)


def check_shipping_and_state_validation(fx):
    """Shipping keeps stock reserved; a pending order cannot be shipped."""
    deps = fx.deps()
    state = fx.state
    product = state["product_ids"]
    order_b = state["order_ids"]["B"]
    order_c = state["order_ids"]["C"]

    order_action(fx, deps, order_b, "ship")
    if fx.status(order_b) != "shipped":
        lib.fail(f"order B should be shipped, found {fx.status(order_b)!r}")
    if fx.stock(product["Notebook"]) != 0:
        lib.fail("shipping must keep the reserved stock reserved")
    if len(fx.invoices_for(order_b)) != 1:
        lib.fail("shipping order B lost its invoice")

    expect_error(
        "shipping a pending order",
        lambda: order_action(fx, deps, order_c, "ship"),
        markers=("ship", "status", "state", "cannot", "invalid", "pending",
                 "confirmed"))
    if fx.status(order_c) != "pending":
        lib.fail(f"a refused shipment changed order C to "
                 f"{fx.status(order_c)!r}")
    if fx.stock(product["Pen"]) != 10:
        lib.fail("a refused shipment changed stock")
    with fx.connection() as connection:
        assert_foreign_keys(connection)


def check_persistence_and_foreign_keys(fx):
    """Everything survives a new connection and every reference resolves."""
    fx.close_deps()
    state = fx.state
    product = state["product_ids"]
    order = state["order_ids"]
    customer_a = state["customer_ids"]["Ada Buyer"]
    customer_b = state["customer_ids"]["Bob Buyer"]

    with fx.connection() as connection:
        assert_foreign_keys(connection)
        customer_ids = {row[state["customer_pk"]]
                        for row in fx.rows("customer")}
        category_ids = {row[state["category_pk"]]
                        for row in fx.rows("category")}
        product_rows = fx.rows("product")
        product_ids = {row[state["product_pk"]] for row in product_rows}
        order_rows = fx.rows("order")
        order_ids = {row[state["order_pk"]] for row in order_rows}
        item_rows = fx.rows("item")
        invoice_rows = fx.rows("invoice")

        if len(customer_ids) != 2 or len(category_ids) != 2:
            lib.fail(f"master data did not persist: customers="
                     f"{customer_ids}, categories={category_ids}")
        if len(product_rows) != 4:
            lib.fail(f"expected 4 products after the admin delete, found "
                     f"{len(product_rows)}")
        if len(order_rows) != 3:
            lib.fail(f"expected 3 orders, found {len(order_rows)}")
        if len(item_rows) != 4:
            lib.fail(f"expected 4 order lines, found {len(item_rows)}")
        if not invoice_rows:
            lib.fail("no invoices persisted")
        if not any(as_int(row[state["invoice_order_col"]]) == order["B"]
                   for row in invoice_rows):
            lib.fail("order B's invoice did not persist")

        for row in product_rows:
            if as_int(row[state["product_category_col"]]) not in category_ids:
                lib.fail(f"product points at a missing category: {row}")
        for row in order_rows:
            if as_int(row[state["order_customer_col"]]) not in customer_ids:
                lib.fail(f"order points at a missing customer: {row}")
        for row in item_rows:
            if as_int(row[state["item_order_col"]]) not in order_ids:
                lib.fail(f"order line points at a missing order: {row}")
            if as_int(row[state["item_product_col"]]) not in product_ids:
                lib.fail(f"order line points at a missing product: {row}")
        for row in invoice_rows:
            if as_int(row[state["invoice_order_col"]]) not in order_ids:
                lib.fail(f"invoice points at a missing order: {row}")
            if state["invoice_customer_col"] and as_int(
                    row[state["invoice_customer_col"]]) not in customer_ids:
                lib.fail(f"invoice points at a missing customer: {row}")

        statuses = {key: str(fx.one("order", order_id)[
            state["order_status_col"]]).lower()
            for key, order_id in order.items()}
        if statuses != {"A": "cancelled", "B": "shipped", "C": "pending"}:
            lib.fail(f"order statuses did not persist: {statuses}")
        if fx.stock(product["Standing Desk"]) != 5 \
                or fx.stock(product["Desk Lamp"]) != 3 \
                or fx.stock(product["Notebook"]) != 0 \
                or fx.stock(product["Pen"]) != 10:
            lib.fail("reserved/released stock counts did not persist")

    reopened = lib.generated_deps(fx.out, fx.db)
    try:
        order_repo = find_repo(reopened, "Order")
        orders = records_of(invoke(
            lib.need(order_repo, "read_all", "OrderRepository.read_all"),
            "OrderRepository.read_all"))
        if not {order["A"], order["B"], order["C"]} <= ids_of(
                orders, state["order_pk"]):
            lib.fail(f"reopened OrderRepository.read_all returned "
                     f"{ids_of(orders, state['order_pk'])}")
        invoice_repo = find_repo(reopened, "Invoice")
        invoices = records_of(invoke(
            lib.need(invoice_repo, "read_all",
                     "InvoiceRepository.read_all"),
            "InvoiceRepository.read_all"))
        if order["B"] not in {
                as_int(record_get(row, state["invoice_order_col"]))
                for row in invoices}:
            lib.fail("reopened InvoiceRepository.read_all lost order B's "
                     "invoice")
        product_repo = find_repo(reopened, "Product")
        desk = invoke(lib.need(product_repo, "read_one",
                               "ProductRepository.read_one"),
                      "ProductRepository.read_one",
                      id_hint="product_id",
                      product_id=product["Standing Desk"])
        if int(record_get(desk, state["product_stock_col"])) != 5:
            lib.fail(f"reopened product has stock "
                     f"{record_get(desk, state['product_stock_col'])!r}, "
                     f"expected 5")
    finally:
        reopened["store"].close()

    order_leaf = fx.surface.find_leaf(ORDER,
                                      (LIST_ACTIONS, SEARCH_ACTIONS))
    if order_leaf is not None and not any(
            option["required"] for option in order_leaf.options):
        listed = json_values(fx.surface.run(order_leaf).stdout)
        if not {order["A"], order["B"], order["C"]} <= ids_of(
                listed, state["order_pk"]):
            lib.fail("a fresh CLI process did not list the persisted orders")
    invoice_leaf = fx.surface.find_leaf(INVOICE,
                                        (LIST_ACTIONS, SEARCH_ACTIONS))
    if invoice_leaf is not None:
        invoice_kwargs = {}
        if invoice_leaf.option("customer_id") is not None:
            invoice_kwargs["customer_id"] = customer_b
        unrelated = [
            option for option in invoice_leaf.options
            if option["required"]
            and normalize(option["dest"]) != "customer_id"
        ]
        if not unrelated:
            listed = json_values(fx.surface.run(
                invoice_leaf, **invoice_kwargs).stdout)
            if order["B"] not in {
                    as_int(record_get(row, state["invoice_order_col"]))
                    for row in listed}:
                lib.fail("a fresh CLI process did not list order B's invoice")


def check_service_extras(fx):
    """Optional customer read and CSV exports fail cleanly."""
    deps = fx.deps()
    services = deps["services"]
    customer = services.get("CustomerService")
    if customer is not None and callable(getattr(customer, "read_customer_by_id", None)):
        if customer.read_customer_by_id(999999) is not None:
            lib.fail("read_customer_by_id must return None for an unknown id")
    export = services.get("ExportService")
    if export is not None:
        for name in ("export_orders_to_csv", "export_product_stock_to_csv"):
            method = getattr(export, name, None)
            if not callable(method):
                continue
            bad = fx.scratch / "missing" / f"{name}.csv"
            try:
                method(str(bad))
            except Exception as error:  # noqa: BLE001 - the error shape under test
                if "ValueError" not in type(error).__name__:
                    lib.fail(f"{name} path failure raised {type(error).__name__}, not ValueError")
            else:
                if not bad.is_file():
                    lib.fail(f"{name} path failure neither raised nor wrote a file")
            good = fx.scratch / f"{name}.csv"
            method(str(good))
            with good.open(encoding="utf-8", newline="") as handle:
                header = next(csv.reader(handle))
            expected = {
                "export_orders_to_csv": [
                    "order_id", "customer_id", "status", "created_at",
                    "confirmed_at", "shipped_at", "cancelled_at"],
                "export_product_stock_to_csv": [
                    "product_id", "name", "category_id", "price",
                    "stock_quantity"],
            }[name]
            if header != expected:
                lib.fail(f"{name} header is {header}, expected {expected}")


CHECKS = (
    ("CLI creates customers, categories and products; schema references",
     check_cli_master_data),
    ("admin product update/delete and rejected bad product input",
     check_admin_and_validation),
    ("an order with several products starts pending without reserving stock",
     check_pending_order),
    ("confirming reserves stock and creates one invoice with the order total",
     check_confirm_reserves_stock_and_invoices),
    ("each customer lists only their own orders and invoices",
     check_customer_lists),
    ("cancelling a confirmed order releases its reserved stock",
     check_cancel_releases_stock),
    ("unknown customers and insufficient stock are refused atomically",
     check_refusals),
    ("shipping keeps stock reserved and a pending order cannot ship",
     check_shipping_and_state_validation),
    ("data persists, foreign keys hold, and a fresh process reads it back",
     check_persistence_and_foreign_keys),
    ("optional customer read and CSV export errors are clean",
     check_service_extras),
)


def run(out_dir):
    fixture = Fixture(out_dir)
    results = []
    for name, check in CHECKS:
        try:
            check(fixture)
        except AssertionError as error:
            results.append({"check": name, "status": "FAIL",
                            "why": str(error)[:500]})
        except Exception as error:  # noqa: BLE001 - a crash is a failed check
            results.append({"check": name, "status": "FAIL",
                            "why": f"{type(error).__name__}: "
                                   f"{str(error)[:480]}"})
        else:
            results.append({"check": name, "status": "PASS", "why": ""})
    fixture.close_deps()

    passed = sum(1 for result in results if result["status"] == "PASS")
    for result in results:
        print(f"{result['status']}  {result['check']}")
        if result["why"]:
            print(f"      {result['why']}")
    print(f"\n{passed} of {len(results)} checks pass")

    result_path = fixture.out / "e2e_60_results.json"
    result_path.write_text(
        json.dumps({"passed": passed, "total": len(results),
                    "database": str(fixture.db), "results": results},
                   indent=2) + "\n", encoding="utf-8")
    print(f"database: {fixture.db}")
    print(f"results: {result_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} OUT_DIR", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1]))
