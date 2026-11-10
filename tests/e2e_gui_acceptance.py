"""Behavior acceptance for a freshly generated wine-shop GUI package.

Run only after real extraction and generation have populated ``OUT_DIR``
(the run directory containing ``generated/``, or ``generated/`` itself)::

    python3.12 tests/e2e_gui_acceptance.py out/gui_same_conditions

The generated ``gui.py`` may require imgui/glfw and cannot be started
headless, so its structure is inspected statically.  Domain behavior is
driven through the generated package's own wiring (``cli.build_cli``) and,
where that is unavailable, by instantiating the generated store,
repositories and services directly.  Every check uses a fresh SQLite file so
one rejected write cannot hide the next check's defect.

The prompt names only a few exception classes and leaves most spellings
open.  Field and method names are therefore discovered from the generated
models and repositories.  When a dedicated custom exception class exists for
a violated rule, the rejection must actually use it; when no such class was
generated, any domain rejection satisfies the rule.
"""

import ast
import dataclasses
import importlib
import inspect
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------

def fail(message):
    raise AssertionError(message)


def norm(text):
    """A comparison key: case, underscores and punctuation do not matter."""
    return "".join(
        character for character in str(text or "").lower()
        if character.isalnum())


class SkipCall(Exception):
    """The method's signature does not fit the generated model's shape."""


def public_methods(owner):
    for name in dir(owner):
        if name.startswith("_"):
            continue
        try:
            value = getattr(owner, name)
        except Exception:  # noqa: BLE001 - a property may raise
            continue
        if callable(value):
            yield name, value


def as_record(value):
    """A generated dataclass, dict or object as a plain field mapping."""
    if isinstance(value, dict):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return None


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return [value]


def record_value(record, field):
    if record is None or field is None:
        return None
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, None)


def operation_of(name):
    """The CRUD operation a repository/service method name spells."""
    flat = norm(name)
    if not flat:
        return None
    if flat.startswith(("readall", "list", "getall", "all")):
        return "read_all"
    if flat.startswith(("create", "add", "new", "register", "insert")):
        return "create"
    if flat.startswith(("update", "edit", "modify", "change", "set")):
        return "update"
    if flat.startswith(("delete", "remove", "drop")):
        return "delete"
    if flat.startswith(("read", "get", "find", "fetch", "load")) \
            and ("byid" in flat or flat.endswith("id")
                 or flat.endswith("bypk")):
        return "read_one"
    return None


def verb_remainder(name, operation):
    flat = norm(name)
    prefixes = {
        "create": ("create", "add", "new", "register", "insert"),
        "read_all": ("readall", "getall", "list", "all"),
        "read_one": ("read", "get", "find", "fetch", "load"),
        "update": ("update", "edit", "modify", "change", "set"),
        "delete": ("delete", "remove", "drop"),
    }
    for prefix in prefixes.get(operation, ()):
        if flat.startswith(prefix):
            return flat[len(prefix):]
    return flat


def pick_field(fields, exact, tokens=(), exclude=()):
    for alias in exact:
        for field in fields:
            if norm(field) == norm(alias):
                return field
    for token in tokens:
        matches = [
            field for field in fields
            if token in norm(field)
            and not any(word in norm(field) for word in exclude)
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def model_field_names(model_cls):
    if dataclasses.is_dataclass(model_cls):
        return [field.name for field in dataclasses.fields(model_cls)]
    annotations = getattr(model_cls, "__annotations__", None)
    if isinstance(annotations, dict) and annotations:
        return list(annotations)
    try:
        signature = inspect.signature(model_cls)
    except (TypeError, ValueError):
        return []
    return [parameter.name for parameter in signature.parameters.values()
            if parameter.name != "self"]


# --------------------------------------------------------------------------
# generated package and its wiring
# --------------------------------------------------------------------------

class Package:
    """The generated modules, imported exactly once per run."""

    MODULE_NAMES = ("models", "errors", "schema", "store",
                    "repositories", "services", "cli")

    def __init__(self, out_dir):
        supplied = Path(out_dir).resolve()
        if (supplied / "generated").is_dir():
            self.out = supplied
            self.generated = supplied / "generated"
        elif supplied.name == "generated" or (supplied / "models.py").is_file():
            self.generated = supplied
            self.out = supplied.parent
        else:
            fail(f"generated package directory is missing: "
                 f"{supplied / 'generated'}")
        sys.dont_write_bytecode = True
        path = str(self.generated)
        if path not in sys.path:
            sys.path.insert(0, path)
        self.modules = {}
        self.import_errors = {}
        for name in self.MODULE_NAMES:
            try:
                self.modules[name] = importlib.import_module(name)
            except Exception as error:  # noqa: BLE001 - reported by the check
                self.import_errors[name] = error
        for required in ("models", "errors", "store", "repositories"):
            if required not in self.modules:
                fail(f"generated module {required}.py cannot be imported: "
                     f"{self.import_errors.get(required)}")
        self.error_classes = self._classes("errors", exceptions_only=True)

    def _classes(self, module_name, exceptions_only=False):
        module = self.modules.get(module_name)
        if module is None:
            return []
        classes = []
        for _, value in inspect.getmembers(module, inspect.isclass):
            if value.__module__ != module.__name__:
                continue
            if exceptions_only:
                if not issubclass(value, Exception) or value is Exception:
                    continue
            classes.append(value)
        return classes

    def entities(self):
        return {norm(cls.__name__): cls for cls in self._classes("models")}

    def scratch(self, name):
        directory = Path(tempfile.mkdtemp(
            prefix="gui-e2e-", dir=str(self.out)))
        return directory / f"{name}.sqlite3"

    def build_deps(self, database):
        """``cli.build_cli`` when it works, else the same wiring by hand."""
        cli = self.modules.get("cli")
        built = None
        if cli is not None and callable(getattr(cli, "build_cli", None)):
            try:
                built = cli.build_cli(str(database))
            except Exception:  # noqa: BLE001 - the direct wiring is the fallback
                built = None
        if isinstance(built, (tuple, list)) and len(built) == 2:
            built = built[1]
        if isinstance(built, dict) and "store" in built:
            return self._normalise_deps(built, database)
        return self._wire(database)

    def _normalise_deps(self, deps, database):
        result = dict(deps)
        repos = result.get("repos") or {}
        services = result.get("services") or {}
        if not isinstance(repos, dict):
            repos = {type(item).__name__: item for item in repos}
        if not isinstance(services, dict):
            services = {type(item).__name__: item for item in services}
        result["repos"] = repos
        result["services"] = services
        result.setdefault("entities", {})
        return result

    def _wire(self, database):
        """The standard generated wiring, for when ``cli`` cannot be used."""
        store_module = self.modules["store"]
        schema_module = self.modules.get("schema")
        schema = getattr(schema_module, "SCHEMA", {}) if schema_module else {}
        store_cls = getattr(store_module, "Store", None)
        if store_cls is None:
            fail("generated store.py does not define Store")
        try:
            store = store_cls(str(database), schema)
        except TypeError:
            store = store_cls(str(database))
        repos = {}
        for cls in self._classes("repositories"):
            try:
                repos[cls.__name__] = cls(store)
            except Exception as error:  # noqa: BLE001
                fail(f"cannot instantiate {cls.__name__}: {error}")
        services = {}
        for cls in self._classes("services"):
            try:
                services[cls.__name__] = cls(repos)
            except TypeError:
                try:
                    services[cls.__name__] = cls(store)
                except Exception as error:  # noqa: BLE001
                    fail(f"cannot instantiate {cls.__name__}: {error}")
            except Exception as error:  # noqa: BLE001
                fail(f"cannot instantiate {cls.__name__}: {error}")
        entities = self.entities()
        return {
            "store": store,
            "repos": repos,
            "services": {**repos, **services},
            "entities": entities,
        }


class Shape:
    """The field names a generated model uses for one domain concept."""

    def __init__(self, model_cls, kind):
        self.cls = model_cls
        self.kind = kind
        self.fields = model_field_names(model_cls)
        if not self.fields:
            fail(f"{model_cls.__name__} has no discoverable fields")
        if kind == "wine":
            self.id = pick_field(self.fields, (
                "wine_id", "wineid", "id"))
            self.name = pick_field(
                self.fields, ("name", "wine_name", "winename", "wine"),
                tokens=("winename", "name"))
            self.vintage = pick_field(
                self.fields, ("vintage_year", "vintage", "year"),
                tokens=("vintage", "year"))
            self.wine_type = pick_field(
                self.fields, ("wine_type", "winetype", "type", "varietal"),
                tokens=("winetype", "varietal", "variety", "style", "type"))
            self.country = pick_field(
                self.fields, ("country_of_origin", "country", "origin"),
                tokens=("country", "origin"))
            self.cost = pick_field(
                self.fields, ("cost_price", "cost", "purchase_price"),
                tokens=("cost", "purchase"))
            self.selling = pick_field(
                self.fields,
                ("selling_price", "sell_price", "selling", "price"),
                tokens=("selling", "sell", "retail", "price"),
                exclude=("cost", "purchase"))
            self.stock = pick_field(
                self.fields,
                ("stock_quantity", "stock_qty", "stock", "quantity",
                 "qty", "bottles", "bottle_count", "available_stock"),
                tokens=("stock", "quantity", "qty", "bottle"),
                exclude=("capacity", "location"))
            self.location = pick_field(
                self.fields,
                ("primary_location_id", "storage_location_id", "location_id",
                 "primary_location"),
                tokens=("locationid", "primarylocation", "location",
                        "storage"),
                exclude=("name", "zone", "row", "shelf", "capacity",
                         "description"))
            self.capacity = None
            self.zone = None
            self.row = None
            self.shelf = None
        else:
            self.id = pick_field(self.fields, (
                "location_id", "locationid", "storage_location_id", "id"))
            self.name = pick_field(
                self.fields,
                ("zone_name", "zonename", "zone", "location_name", "name"),
                tokens=("zone", "area", "locationname", "name"))
            self.zone = self.name
            self.row = pick_field(
                self.fields, ("row_number", "row_no", "row"),
                tokens=("rownumber", "row"))
            self.shelf = pick_field(
                self.fields, ("shelf_number", "shelf_no", "shelf"),
                tokens=("shelfnumber", "shelf"))
            self.capacity = pick_field(
                self.fields,
                ("max_bottle_capacity", "maximum_capacity", "max_capacity",
                 "capacity", "bottle_capacity"),
                tokens=("capacity", "bottlelimit", "maxbottles"))
            self.vintage = None
            self.wine_type = None
            self.country = None
            self.cost = None
            self.selling = None
            self.stock = None
            self.location = None
        if self.id is None:
            identifiers = [
                field for field in self.fields
                if norm(field) == "id" or norm(field).endswith("id")
            ]
            self.id = identifiers[0] if identifiers else self.fields[0]

    def aliases_for(self, field):
        """Parameter spellings that may carry this field's value."""
        aliases = {norm(field)}
        if self.kind == "wine":
            id_aliases = ("id", "wine_id", "wineid", "wineno", "wine_number",
                          "pk")
        else:
            id_aliases = ("id", "location_id", "locationid", "storage_id",
                          "storagelocationid", "pk")
        groups = (
            (self.id, id_aliases),
            (self.name, ("name", "wine_name", "winename", "zone_name",
                         "zonename", "zone", "area", "location_name",
                         "locationname")),
            (self.vintage, ("vintage_year", "vintageyear", "vintage", "year")),
            (self.wine_type, ("wine_type", "winetype", "type", "varietal",
                              "variety", "style")),
            (self.country, ("country_of_origin", "countryoforigin", "country",
                            "origin")),
            (self.cost, ("cost_price", "costprice", "cost",
                         "purchase_price")),
            (self.selling, ("selling_price", "sellingprice", "sell_price",
                            "sellprice", "selling", "price")),
            (self.stock, ("stock_quantity", "stockquantity", "stock_qty",
                          "stockqty", "stock", "quantity", "qty", "bottles",
                          "bottle_count", "available_stock")),
            (self.location, ("primary_location_id", "primarylocationid",
                             "storage_location_id", "storagelocationid",
                             "location_id", "locationid", "location")),
            (self.row, ("row_number", "rownumber", "row_no", "rowno", "row")),
            (self.shelf, ("shelf_number", "shelfnumber", "shelf_no",
                          "shelfno", "shelf")),
            (self.capacity, ("max_bottle_capacity", "maxbottlecapacity",
                             "maximum_capacity", "maximumcapacity",
                             "max_capacity", "maxcapacity", "capacity",
                             "bottle_capacity", "bottlecapacity")),
        )
        for slot, names in groups:
            if slot is not None and field == slot:
                aliases.update(norm(name) for name in names)
        return aliases


def _annotation_is_dict(annotation):
    return "dict" in str(annotation).lower() \
        or "mapping" in str(annotation).lower()


def _is_entity_parameter(parameter, shape):
    annotation = parameter.annotation
    if annotation is not inspect.Parameter.empty:
        if annotation is shape.cls:
            return True
        text = str(annotation)
        if shape.cls.__name__ in text:
            return True
        if _annotation_is_dict(annotation):
            return False
        flat_annotation = norm(annotation)
        if annotation in (int, float, str, bool) \
                or flat_annotation in (
                    "int", "integer", "float", "str", "string", "bool",
                    "boolean"):
            return False
    names = {
        "wine": {"wine", "winedata", "winerecord", "winemodel"},
        "location": {"location", "storagelocation", "locationdata",
                     "locationrecord", "locationmodel"},
    }[shape.kind]
    flat = norm(parameter.name)
    return flat in names | {"record", "entity", "model", "data"}


def call_with_values(method, shape, values):
    """Call a generated method, mapping its parameters onto model fields."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError) as error:
        raise SkipCall(f"signature unavailable: {error}") from error
    remaining = dict(values)
    positional = []
    keyword = {}
    for parameter in signature.parameters.values():
        if parameter.name in ("self", "cls"):
            continue
        if parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            for key, value in remaining.items():
                keyword.setdefault(key, value)
            continue
        matched = None
        for key in remaining:
            aliases = shape.aliases_for(key)
            if norm(parameter.name) == norm(key) \
                    or norm(parameter.name) in aliases:
                matched = key
                break
        if matched is not None:
            value = remaining[matched]
        elif _is_entity_parameter(parameter, shape):
            entity_values = {
                key: value for key, value in remaining.items()
                if key in shape.fields
            }
            if _annotation_is_dict(parameter.annotation):
                value = dict(entity_values)
            else:
                try:
                    value = shape.cls(**entity_values)
                except TypeError as error:
                    raise SkipCall(
                        f"cannot build {shape.cls.__name__}: {error}") from error
        elif parameter.default is not inspect.Parameter.empty:
            continue
        else:
            raise SkipCall(
                f"parameter {parameter.name!r} has no matching model field")
        if parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            positional.append(value)
        else:
            keyword[parameter.name] = value
    return method(*positional, **keyword)


def key_of(value, shape):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    record = as_record(value)
    if record is not None:
        key = record.get(shape.id) if shape.id else None
        if key is None:
            key = record.get("id")
        if key is not None:
            return key
    return None


class App:
    """One generated dependency graph over one SQLite file."""

    def __init__(self, package, database):
        self.package = package
        self.deps = package.build_deps(database)
        self.store = self.deps.get("store")
        if self.store is None:
            fail("generated dependencies contain no store")
        self.repos = self.deps.get("repos") or {}
        self.services = self.deps.get("services") or {}
        if not isinstance(self.repos, dict):
            self.repos = {type(item).__name__: item for item in self.repos}
        if not isinstance(self.services, dict):
            self.services = {
                type(item).__name__: item for item in self.services}
        if not self.repos:
            self.repos = {
                name: item for name, item in self.services.items()
                if hasattr(item, "ENTITY")
            }
        self.repo_objects = list(self.repos.values())
        repo_ids = {id(item) for item in self.repo_objects}
        self.service_objects = [
            item for item in self.services.values()
            if id(item) not in repo_ids
        ]
        entities = dict(self.deps.get("entities") or {})
        for name, cls in package.entities().items():
            entities.setdefault(name, cls)
        self.entities = entities
        self.wine = Shape(self._model("Wine"), "wine")
        self.location = Shape(self._model("StorageLocation"), "location")

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 - closing must not mask the check
            pass
        return False

    def _model(self, wanted):
        exact = norm(wanted)
        for key, cls in self.entities.items():
            if not inspect.isclass(cls):
                continue
            if norm(key) == exact or norm(cls.__name__) == exact:
                return cls
        for cls in self.entities.values():
            if not inspect.isclass(cls):
                continue
            name = norm(cls.__name__)
            if wanted == "Wine":
                if "wine" in name and "location" not in name:
                    return cls
            elif "location" in name or name == "storage":
                return cls
        found = sorted(
            cls.__name__ for cls in self.entities.values()
            if inspect.isclass(cls))
        fail(f"generated models do not define {wanted}; found {found}")

    def shape_for(self, entity):
        target = norm(entity)
        if target == norm(self.wine.cls.__name__) or "wine" in target:
            return self.wine
        if target == norm(self.location.cls.__name__) \
                or "location" in target or "storage" in target:
            return self.location
        fail(f"no model shape for {entity}")

    def repo_for(self, entity):
        shape = self.shape_for(entity)
        target = norm(shape.cls.__name__)
        for repo in self.repo_objects:
            if norm(getattr(repo, "ENTITY", "")) == target:
                return repo
        for name, repo in self.repos.items():
            flat = norm(name)
            if target in flat or flat.startswith(target):
                return repo
        fail(f"no generated repository for {shape.cls.__name__}; "
             f"have {sorted(self.repos)}")


# --------------------------------------------------------------------------
# generated operation lookups
# --------------------------------------------------------------------------

def _entity_tokens(entity_name):
    tokens = {norm(entity_name)}
    words = re.findall(r"[A-Z][a-z0-9]*", str(entity_name))
    for word in words:
        tokens.add(norm(word))
        tokens.add(norm(word) + "s")
    tokens.update(token + "s" for token in list(tokens))
    return tokens


def _repo_name_matches(entity, name, operation):
    remainder = verb_remainder(name, operation)
    if not remainder:
        return True
    tokens = _entity_tokens(entity)
    if operation in ("create", "update", "delete"):
        # add_stock, update_stock, remove_wine_from_location and similar
        # custom actions are not the entity's CRUD method.
        return remainder in tokens
    if operation == "read_all":
        return remainder in tokens or remainder in ("all",) \
            or (remainder.startswith("all")
                and remainder[3:] in tokens)
    if operation == "read_one":
        return remainder in tokens or remainder in (
            "one", "byid", "bypk", "bykey") \
            or any(remainder.startswith(token) for token in tokens)
    return True


def repo_method(app, entity, operation):
    repo = app.repo_for(entity)
    entity_name = app.shape_for(entity).cls.__name__
    methods = []
    for name, method in public_methods(repo):
        if operation_of(name) != operation:
            continue
        if _repo_name_matches(entity_name, name, operation):
            methods.append((name, method))
    if not methods:
        return None
    exact = {
        "create": ("create", "add"),
        "read_all": ("read_all", "list", "get_all", "all"),
        "read_one": ("read_one", "get", "read"),
        "update": ("update", "edit"),
        "delete": ("delete", "remove"),
    }.get(operation, ())
    methods.sort(key=lambda item: (
        norm(item[0]) not in {norm(name) for name in exact},
        len(item[0]), item[0]))
    return methods[0][1]


def _service_crud_match(class_name, method_name, entity):
    operation = operation_of(method_name)
    if operation not in ("create", "read_all", "read_one", "update",
                         "delete"):
        return None
    remainder = verb_remainder(method_name, operation)
    flat_class = norm(class_name)
    if entity == "Wine":
        if any(word in remainder for word in (
                "location", "stock", "price", "capacity", "assign",
                "quantity", "bottle", "sell")):
            return None
        if "wine" in remainder:
            return operation
        if not remainder and ("wine" in flat_class
                              and "location" not in flat_class):
            return operation
    else:
        if any(word in remainder for word in (
                "wine", "stock", "price", "capacity", "assign",
                "quantity", "bottle")):
            return None
        if "location" in remainder or "storage" in remainder:
            return operation
        if not remainder and ("location" in flat_class
                              or "storage" in flat_class):
            return operation
    return None


def entity_crud_candidates(app, entity, operation):
    """Service implementations first, then the repository's mechanical one."""
    for owner in app.service_objects:
        class_name = type(owner).__name__
        for name, method in public_methods(owner):
            if _service_crud_match(class_name, name, entity) == operation:
                yield f"{class_name}.{name}", method
    method = repo_method(app, entity, operation)
    if method is not None:
        repo = app.repo_for(entity)
        yield f"{type(repo).__name__}.{method.__name__}", method


def assignment_candidates(app):
    """Methods that move a wine to a storage location, service first."""
    for owner in app.service_objects:
        class_name = type(owner).__name__
        flat_class = norm(class_name)
        for name, method in public_methods(owner):
            flat = norm(name)
            if "wine" not in flat and "wine" not in flat_class:
                continue
            if "wine" not in flat and not any(word in flat for word in (
                    "assign", "move", "transfer", "relocate", "place",
                    "store")):
                continue
            if "location" not in flat and "location" not in flat_class:
                continue
            if any(word in flat for word in (
                    "assign", "move", "transfer", "relocate", "place",
                    "store", "set", "update")) \
                    and "remove" not in flat:
                yield f"{class_name}.{name}", method
    if app.wine.location is not None:
        method = repo_method(app, "Wine", "update")
        if method is not None:
            repo = app.repo_for("Wine")
            yield f"{type(repo).__name__}.{method.__name__}", method


def deletion_candidates(app):
    """Methods that delete a storage location, service first."""
    for owner in app.service_objects:
        class_name = type(owner).__name__
        flat_class = norm(class_name)
        for name, method in public_methods(owner):
            flat = norm(name)
            if "wine" in flat:
                continue
            if not any(word in flat for word in ("delete", "remove", "drop")):
                continue
            if "location" in flat or "storage" in flat:
                yield f"{class_name}.{name}", method
            elif flat in ("delete", "remove", "drop") \
                    and ("location" in flat_class or "storage" in flat_class):
                yield f"{class_name}.{name}", method
    method = repo_method(app, "StorageLocation", "delete")
    if method is not None:
        repo = app.repo_for("StorageLocation")
        yield f"{type(repo).__name__}.{method.__name__}", method


# --------------------------------------------------------------------------
# generated models and records
# --------------------------------------------------------------------------

def require_field(shape, attribute, label):
    field = getattr(shape, attribute, None)
    if field is None:
        fail(f"{shape.cls.__name__} has no {label} field; "
             f"fields are {shape.fields}")
    return field


def location_values(shape, capacity, zone, row=1, shelf=1):
    values = {}
    if shape.zone is not None:
        values[shape.zone] = zone
    if shape.row is not None:
        values[shape.row] = row
    if shape.shelf is not None:
        values[shape.shelf] = shelf
    if shape.capacity is not None:
        values[shape.capacity] = capacity
    return values


def wine_values(shape, name, cost, selling, stock, location_id):
    values = {}
    if shape.name is not None:
        values[shape.name] = name
    if shape.vintage is not None:
        values[shape.vintage] = 2020
    if shape.wine_type is not None:
        values[shape.wine_type] = "red"
    if shape.country is not None:
        values[shape.country] = "France"
    if shape.cost is not None:
        values[shape.cost] = cost
    if shape.selling is not None:
        values[shape.selling] = selling
    if shape.stock is not None:
        values[shape.stock] = stock
    if shape.location is not None and location_id is not None:
        values[shape.location] = location_id
    return values


def create_location(app, capacity=10, zone="Main Cellar", row=1, shelf=1):
    shape = app.location
    require_field(shape, "zone", "zone/name")
    require_field(shape, "capacity", "maximum capacity")
    method = repo_method(app, "StorageLocation", "create")
    if method is None:
        fail("StorageLocationRepository has no create method")
    values = location_values(shape, capacity, zone, row, shelf)
    result = call_with_values(method, shape, values)
    key = key_of(result, shape)
    if key is None:
        rows = read_all(app, "StorageLocation")
        if rows:
            key = record_id(rows[-1], shape)
    if key is None:
        fail("creating a storage location returned no identifier")
    return key


def create_wine(app, location_id, name, cost, selling, stock):
    shape = app.wine
    require_field(shape, "name", "name")
    require_field(shape, "cost", "cost price")
    require_field(shape, "selling", "selling price")
    require_field(shape, "stock", "stock quantity")
    method = repo_method(app, "Wine", "create")
    if method is None:
        fail("WineRepository has no create method")
    values = wine_values(shape, name, cost, selling, stock, location_id)
    result = call_with_values(method, shape, values)
    key = key_of(result, shape)
    if key is None:
        rows = read_all(app, "Wine")
        matches = [
            row for row in rows
            if str(record_value(row, shape.name)) == str(name)
        ]
        if matches:
            key = record_id(matches[-1], shape)
    if key is None:
        fail("creating a wine returned no identifier")
    return key


def record_id(record, shape):
    if shape.id is not None:
        value = record_value(record, shape.id)
        if value is not None:
            return value
    return record_value(record, "id")


def read_all(app, entity):
    shape = app.shape_for(entity)
    repo = app.repo_for(entity)
    method = repo_method(app, entity, "read_all")
    if method is not None:
        try:
            result = call_with_values(method, shape, {})
        except (SkipCall, NotImplementedError):
            result = None
        else:
            rows = [as_record(item) for item in as_list(result)]
            return [row for row in rows if row is not None]
    try:
        return [dict(row) for row in app.store.all(
            getattr(repo, "ENTITY", shape.cls.__name__))]
    except Exception as error:  # noqa: BLE001
        fail(f"cannot list {shape.cls.__name__} records: {error}")


def read_by_id(app, entity, key):
    shape = app.shape_for(entity)
    for row in read_all(app, entity):
        if record_id(row, shape) == key:
            return row
    fail(f"no {shape.cls.__name__} record has id {key!r}")


def update_entity(app, entity, key, values):
    shape = app.shape_for(entity)
    method = repo_method(app, entity, "update")
    if method is None:
        fail(f"{shape.cls.__name__} repository has no update method")
    payload = dict(values)
    payload[shape.id] = key
    return call_with_values(method, shape, payload)


def delete_entity(app, entity, key):
    shape = app.shape_for(entity)
    method = repo_method(app, entity, "delete")
    if method is None:
        fail(f"{shape.cls.__name__} repository has no delete method")
    return call_with_values(method, shape, {shape.id: key})


def numeric(record, field, label):
    value = record_value(record, field)
    try:
        return float(value)
    except (TypeError, ValueError):
        fail(f"{label} is not numeric: {value!r}")


# --------------------------------------------------------------------------
# custom domain exception names
# --------------------------------------------------------------------------

def _error_matches(kind, flat):
    if kind == "duplicate_wine_name":
        return ("duplicate" in flat or "already" in flat
                or "exists" in flat or "notunique" in flat) \
            and ("wine" in flat or "name" in flat)
    if kind == "pricing":
        return "price" in flat or "pricing" in flat
    if kind == "negative_stock":
        return ("stock" in flat or "inventory" in flat) \
            and ("negative" in flat or "insufficient" in flat
                 or "belowzero" in flat or "underflow" in flat)
    if kind == "capacity":
        return ("capacity" in flat or "quota" in flat
                or "location" in flat or "storage" in flat) \
            and ("over" in flat or "exceed" in flat or "full" in flat
                 or "overflow" in flat)
    if kind == "location_delete":
        # WineNotAssignedToLocationError is about removing a wine, not about
        # deleting its location; do not demand it here.
        if flat.startswith("wine"):
            return False
        return ("location" in flat or "storage" in flat) \
            and ("notempty" in flat or "inuse" in flat
                 or "occupied" in flat or "assigned" in flat
                 or "haswine" in flat or "contains" in flat
                 or "nonempty" in flat or "cannotdelete" in flat)
    return False


def preferred_error_classes(package, kind):
    return [
        cls for cls in package.error_classes
        if _error_matches(kind, norm(cls.__name__))
    ]


def check_error_class(package, error, kind, label):
    """A rejection is only complete when a generated custom error is used."""
    classes = preferred_error_classes(package, kind)
    if classes:
        if not isinstance(error, tuple(classes)):
            names = ", ".join(cls.__name__ for cls in classes)
            fail(f"{label}: generated {names} for this rule but raised "
                 f"{type(error).__name__}: {error}")
        return f"raised {type(error).__name__}"
    return f"raised {type(error).__name__}"


def expect_rejected(app, entity, operation, values, kind, label):
    """An invalid write must be refused by the first implemented entry point."""
    last_problem = None
    for candidate_label, method in entity_crud_candidates(
            app, entity, operation):
        try:
            result = call_with_values(
                method, app.shape_for(entity), values)
        except SkipCall as error:
            last_problem = f"{candidate_label}: {error}"
            continue
        except NotImplementedError as error:
            last_problem = f"{candidate_label}: {error}"
            continue
        except TypeError as error:
            if candidate_label.startswith(
                    type(app.repo_for(entity)).__name__):
                fail(f"{candidate_label} failed with TypeError: {error}")
            last_problem = f"{candidate_label}: TypeError: {error}"
            continue
        except Exception as error:  # noqa: BLE001 - the rule under test
            return f"{candidate_label} {check_error_class(
                app.package, error, kind, candidate_label)}"
        else:
            fail(f"{candidate_label} accepted invalid {label}: "
                 f"returned {result!r}")
    fail(f"no generated create/update method could reject {label}; "
         f"last attempt: {last_problem}")


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check_gui_structure(package):
    """The GUI module is real: two entity panels and a pyimgui frame loop."""
    path = package.generated / "gui.py"
    if not path.is_file():
        fail(f"generated GUI module is missing: {path}")
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        fail(f"gui.py does not parse: {error}")
    panels = None
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == "PANELS"
               for target in targets):
            try:
                panels = ast.literal_eval(node.value)
            except (ValueError, TypeError) as error:
                fail(f"PANELS is not a literal description: {error}")
            break
    if not isinstance(panels, list) or not panels:
        fail("gui.py does not define a non-empty PANELS list")

    def panel_for(token):
        matches = [
            panel for panel in panels
            if isinstance(panel, dict)
            and isinstance(panel.get("entity"), str)
            and token in norm(panel["entity"])
        ]
        return matches[0] if matches else None

    wine_panel = panel_for("wine")
    storage_panel = next(
        (panel for panel in panels
         if isinstance(panel, dict)
         and isinstance(panel.get("entity"), str)
         and ("location" in norm(panel["entity"])
              or "storage" in norm(panel["entity"]))),
        None)
    if wine_panel is None:
        fail(f"PANELS has no Wine panel: {panels!r}")
    if storage_panel is None:
        fail(f"PANELS has no StorageLocation panel: {panels!r}")

    def fields_of(panel):
        return [
            field.get("name") for field in panel.get("fields") or []
            if isinstance(field, dict) and isinstance(field.get("name"), str)
        ]

    wine_fields = fields_of(wine_panel)
    storage_fields = fields_of(storage_panel)
    if not wine_fields or not storage_fields:
        fail("a GUI panel has no editable fields")

    def has_field(names, tokens, exclude=()):
        return any(
            any(token in norm(name) for token in tokens)
            and not any(word in norm(name) for word in exclude)
            for name in names
        )

    required_wine = (
        ("name", ("name",), ()),
        ("vintage year", ("vintage", "year"), ()),
        ("wine type", ("type", "varietal", "variety", "style"), ()),
        ("country", ("country", "origin"), ()),
        ("cost price", ("cost", "purchase"), ()),
        ("selling price", ("selling", "sell", "retail", "price"), ("cost",)),
        ("stock", ("stock", "quantity", "qty", "bottle"), ("capacity",)),
        ("storage location", ("location", "storage"), ()),
    )
    for label, tokens, exclude in required_wine:
        if not has_field(wine_fields, tokens, exclude):
            fail(f"Wine GUI panel does not expose {label}: {wine_fields}")
    required_storage = (
        ("zone", ("zone", "area", "location", "name")),
        ("row", ("row",)),
        ("shelf", ("shelf",)),
        ("capacity", ("capacity", "limit", "max")),
    )
    for label, tokens in required_storage:
        if not has_field(storage_fields, tokens):
            fail(f"StorageLocation GUI panel does not expose {label}: "
                 f"{storage_fields}")

    wine_ops = set(wine_panel.get("ops") or {})
    storage_ops = set(storage_panel.get("ops") or {})
    for operation in ("create", "read_all", "update"):
        if operation not in wine_ops:
            fail(f"Wine GUI panel has no {operation} operation: {wine_ops}")
    for operation in ("create", "read_all"):
        if operation not in storage_ops:
            fail(f"StorageLocation GUI panel has no {operation} operation: "
                 f"{storage_ops}")

    for needle in (
            "import imgui", "import glfw", "GlfwRenderer", "def build_gui",
            "while not glfw.window_should_close", "imgui.new_frame()",
            "imgui.render()", "glfw.swap_buffers", "PANELS",
            "from schema import SCHEMA", "Store(DEFAULT_DB, SCHEMA)",
            "repos[panel['repo']]"):
        if needle not in source:
            fail(f"gui.py does not contain {needle!r}")
    if "repos[panel['entity']]" in source:
        fail("gui.py indexes repositories by entity instead of repository class")
    return (f"PANELS expose {wine_panel['entity']} and "
            f"{storage_panel['entity']}; imgui/glfw frame loop present")


def check_records_and_persistence(package):
    """Both entities persist, read back, and an update survives a reopen."""
    database = package.scratch("records")
    with App(package, database) as app:
        for attribute, label in (
                ("name", "name"), ("vintage", "vintage year"),
                ("wine_type", "wine type"), ("country", "country"),
                ("cost", "cost price"), ("selling", "selling price"),
                ("stock", "stock quantity"),
                ("location", "primary storage location")):
            require_field(app.wine, attribute, label)
        for attribute, label in (
                ("zone", "zone name"), ("row", "row number"),
                ("shelf", "shelf number"), ("capacity", "maximum capacity")):
            require_field(app.location, attribute, label)
        location = create_location(
            app, capacity=20, zone="Main Cellar", row=1, shelf=2)
        wine = create_wine(
            app, location, name="Domaine Acceptance", cost=10, selling=25,
            stock=4)
        rows = read_all(app, "Wine")
        if len(rows) != 1:
            fail(f"expected one wine after creation, found {len(rows)}")
        stored = read_by_id(app, "Wine", wine)
        if str(record_value(stored, app.wine.name)) != "Domaine Acceptance":
            fail(f"created wine has the wrong name: {stored}")
        if numeric(stored, app.wine.stock, "stock") != 4:
            fail(f"created wine has the wrong stock: {stored}")
        if record_value(stored, app.wine.location) != location:
            fail(f"created wine does not point at its location: {stored}")
        if read_by_id(app, "StorageLocation", location) is None:
            fail("created storage location cannot be read back")
        update_entity(app, "Wine", wine, {
            app.wine.stock: 7,
            app.wine.selling: 30,
        })
        stored = read_by_id(app, "Wine", wine)
        if numeric(stored, app.wine.stock, "updated stock") != 7:
            fail(f"updating stock did not persist: {stored}")
        if numeric(stored, app.wine.selling, "updated selling price") != 30:
            fail(f"updating selling price did not persist: {stored}")

    with App(package, database) as app:
        rows = read_all(app, "Wine")
        if len(rows) != 1:
            fail(f"reopening the database lost the wine: {rows}")
        stored = rows[0]
        if str(record_value(stored, app.wine.name)) != "Domaine Acceptance":
            fail(f"reopened wine has the wrong name: {stored}")
        if numeric(stored, app.wine.stock, "reopened stock") != 7:
            fail(f"stock did not survive reopening: {stored}")
        if record_value(stored, app.wine.location) != location:
            fail(f"location assignment did not survive reopening: {stored}")
        if len(read_all(app, "StorageLocation")) != 1:
            fail("reopening the database lost the storage location")
    return "location and wine CRUD, stock update, and file persistence agree"


def check_unique_wine_names(package):
    """A second wine with the same name is refused and stores no row."""
    database = package.scratch("unique")
    with App(package, database) as app:
        location = create_location(app, capacity=20, zone="Unique Cellar")
        create_wine(app, location, name="Château Unique", cost=10,
                    selling=20, stock=1)
        values = wine_values(
            app.wine, "Château Unique", cost=12, selling=24, stock=2,
            location_id=location)
        rejection = expect_rejected(
            app, "Wine", "create", values, "duplicate_wine_name",
            "a duplicate wine name")
        rows = read_all(app, "Wine")
        names = [str(record_value(row, app.wine.name)) for row in rows]
        if names.count("Château Unique") != 1:
            fail(f"duplicate name was stored more than once: {names}")
        if len(rows) != 1:
            fail(f"rejected duplicate changed the wine count: {len(rows)}")

        second = create_wine(
            app, location, name="Second Unique", cost=10, selling=20,
            stock=1)
        rename_rejection = expect_rejected(
            app, "Wine", "update", {
                app.wine.id: second,
                app.wine.name: "Château Unique",
            }, "duplicate_wine_name", "a rename onto another wine's name")
        rows = read_all(app, "Wine")
        names = [str(record_value(row, app.wine.name)) for row in rows]
        if len(set(names)) != len(names):
            fail(f"renaming onto an existing name was stored: {names}")
    return (f"duplicate create refused ({rejection}); duplicate rename "
            f"refused ({rename_rejection}); names stayed unique")


def check_pricing_rule(package):
    """Selling price must be strictly greater than cost, on create and update."""
    database = package.scratch("pricing")
    with App(package, database) as app:
        location = create_location(app, capacity=20, zone="Price Cellar")
        rejections = []
        for index, selling in enumerate((10, 9)):
            values = wine_values(
                app.wine, f"Bad Margin {index}", cost=10, selling=selling,
                stock=1, location_id=location)
            rejections.append(expect_rejected(
                app, "Wine", "create", values, "pricing",
                f"selling price {selling} against cost price 10"))
        good = create_wine(
            app, location, name="Good Margin", cost=10, selling=11,
            stock=1)
        stored = read_by_id(app, "Wine", good)
        if numeric(stored, app.wine.selling, "selling price") != 11:
            fail(f"a valid margin was not stored: {stored}")
        rejections.append(expect_rejected(
            app, "Wine", "update", {
                app.wine.id: good,
                app.wine.selling: 5,
            }, "pricing", "an update to a loss-making price"))
        stored = read_by_id(app, "Wine", good)
        if numeric(stored, app.wine.selling, "unchanged selling price") != 11:
            fail(f"a rejected price update was partially applied: {stored}")
    return (f"equal and lower selling prices refused "
            f"({'; '.join(rejections)}); valid margin kept")


def check_non_negative_stock(package):
    """Stock cannot be created or updated below zero; zero itself is valid."""
    database = package.scratch("stock")
    with App(package, database) as app:
        location = create_location(app, capacity=20, zone="Stock Cellar")
        create_rejection = expect_rejected(
            app, "Wine", "create", wine_values(
                app.wine, "Negative Stock", cost=10, selling=20, stock=-1,
                location_id=location),
            "negative_stock", "a negative stock quantity")
        zero = create_wine(
            app, location, name="Empty Bin", cost=10, selling=20, stock=0)
        stored = read_by_id(app, "Wine", zero)
        if numeric(stored, app.wine.stock, "zero stock") != 0:
            fail(f"a wine with zero stock was not stored as zero: {stored}")
        valid = create_wine(
            app, location, name="Stock Witness", cost=10, selling=20,
            stock=3)
        update_rejection = expect_rejected(
            app, "Wine", "update", {
                app.wine.id: valid,
                app.wine.stock: -2,
            }, "negative_stock", "an update to a negative stock quantity")
        stored = read_by_id(app, "Wine", valid)
        if numeric(stored, app.wine.stock, "unchanged stock") != 3:
            fail(f"a rejected stock update was partially applied: {stored}")
    return (f"negative create refused ({create_rejection}); negative update "
            f"refused ({update_rejection}); zero and positive stock kept")


def check_assignment(package):
    """A wine can be assigned to exactly one location and reads back there."""
    database = package.scratch("assignment")
    with App(package, database) as app:
        require_field(app.wine, "location", "primary storage location")
        first = create_location(
            app, capacity=50, zone="Main Cellar", row=1, shelf=1)
        second = create_location(
            app, capacity=50, zone="Front Display", row=2, shelf=4)
        wine = create_wine(
            app, first, name="Assigned Wine", cost=10, selling=20, stock=2)
        candidates = list(assignment_candidates(app))
        if not candidates:
            fail("no generated service or repository can assign a wine to a "
                 "storage location")
        used = None
        last_problem = None
        result = None
        for label, method in candidates:
            try:
                result = call_with_values(method, app.wine, {
                    app.wine.id: wine,
                    app.wine.location: second,
                })
            except SkipCall as error:
                last_problem = f"{label}: {error}"
                continue
            except NotImplementedError as error:
                last_problem = f"{label}: {error}"
                continue
            except TypeError as error:
                last_problem = f"{label}: TypeError: {error}"
                continue
            except Exception as error:  # noqa: BLE001 - valid input refused
                fail(f"{label} refused a valid assignment: "
                     f"{type(error).__name__}: {error}")
            else:
                used = label
                break
        if used is None:
            fail(f"no assignment method could be called; "
                 f"last attempt: {last_problem}")
        stored = read_by_id(app, "Wine", wine)
        if record_value(stored, app.wine.location) != second:
            fail(f"{used} did not persist the new location: {stored}")
        returned = as_record(result)
        if returned is not None \
                and record_value(returned, app.wine.location) != second:
            fail(f"{used} returned a wine still at the old location: {result}")
    return f"{used} moved the wine to {second!r} and the read-back agrees"


def check_location_capacity(package):
    """A location may not be given more bottles than its capacity."""
    database = package.scratch("capacity")
    with App(package, database) as app:
        require_field(app.wine, "location", "primary storage location")
        big = create_location(
            app, capacity=50, zone="Main Cellar", row=1, shelf=1)
        small = create_location(
            app, capacity=2, zone="Front Display", row=1, shelf=3)
        wine = create_wine(
            app, big, name="Overflow Wine", cost=10, selling=20, stock=3)
        candidates = list(assignment_candidates(app))
        if not candidates:
            fail("no generated service or repository can assign a wine to a "
                 "storage location")
        rejection = None
        used = None
        last_problem = None
        for label, method in candidates:
            try:
                result = call_with_values(method, app.wine, {
                    app.wine.id: wine,
                    app.wine.location: small,
                })
            except SkipCall as error:
                last_problem = f"{label}: {error}"
                continue
            except NotImplementedError as error:
                last_problem = f"{label}: {error}"
                continue
            except TypeError as error:
                last_problem = f"{label}: TypeError: {error}"
                continue
            except Exception as error:  # noqa: BLE001 - the rule under test
                rejection = check_error_class(
                    package, error, "capacity", label)
                used = label
                break
            else:
                fail(f"{label} assigned {3} bottles to a location whose "
                     f"capacity is 2 (returned {result!r})")
        if rejection is None:
            fail(f"no assignment method enforced location capacity; "
                 f"last attempt: {last_problem}")
        stored = read_by_id(app, "Wine", wine)
        if record_value(stored, app.wine.location) != big:
            fail(f"a rejected over-capacity assignment moved the wine "
                 f"anyway: {stored}")
    return f"{used} refused an over-capacity assignment ({rejection})"


def check_location_deletion_guard(package):
    """An occupied location cannot be deleted; an empty one can."""
    database = package.scratch("deletion")
    with App(package, database) as app:
        location = create_location(
            app, capacity=10, zone="Occupied Cellar", row=1, shelf=1)
        wine = create_wine(
            app, location, name="Resident Wine", cost=10, selling=20,
            stock=1)
        candidates = list(deletion_candidates(app))
        if not candidates:
            fail("no generated service or repository can delete a storage "
                 "location")
        rejection = None
        used = None
        last_problem = None
        for label, method in candidates:
            try:
                result = call_with_values(
                    method, app.location, {app.location.id: location})
            except SkipCall as error:
                last_problem = f"{label}: {error}"
                continue
            except NotImplementedError as error:
                last_problem = f"{label}: {error}"
                continue
            except TypeError as error:
                last_problem = f"{label}: TypeError: {error}"
                continue
            except Exception as error:  # noqa: BLE001 - the rule under test
                rejection = check_error_class(
                    package, error, "location_delete", label)
                used = label
                break
            else:
                fail(f"{label} deleted a storage location while wine "
                     f"{wine!r} was assigned to it (returned {result!r})")
        if used is None:
            fail(f"no deletion method could be exercised; "
                 f"last attempt: {last_problem}")
        if record_id(read_by_id(app, "StorageLocation", location),
                     app.location) != location:
            fail("a rejected deletion removed the storage location anyway")
        stored = read_by_id(app, "Wine", wine)
        if record_value(stored, app.wine.location) != location:
            fail(f"a rejected deletion changed the wine's location: {stored}")

        empty = create_location(
            app, capacity=5, zone="Empty Cellar", row=3, shelf=1)
        method = next(
            item for label, item in candidates if label == used)
        try:
            call_with_values(method, app.location, {app.location.id: empty})
        except SkipCall as error:
            fail(f"{used} cannot delete even an empty location: {error}")
        except NotImplementedError as error:
            fail(f"{used} cannot delete even an empty location: {error}")
        except Exception as error:  # noqa: BLE001
            fail(f"{used} refused to delete an empty location: "
                 f"{type(error).__name__}: {error}")
        remaining = {
            record_id(row, app.location)
            for row in read_all(app, "StorageLocation")
        }
        if empty in remaining:
            fail(f"{used} did not remove an empty location")
    return (f"{used} refused the occupied location ({rejection}) and "
            f"deleted the empty one")


def check_location_capacity_shrink(package):
    """Shrinking a location below its assigned stock is refused."""
    database = package.scratch("shrink")
    with App(package, database) as app:
        location = create_location(
            app, capacity=10, zone="Shrink Cellar", row=1, shelf=1)
        create_wine(
            app, location, name="Shrink Wine", cost=10, selling=20, stock=4)
        rejection = expect_rejected(
            app, "StorageLocation", "update",
            {app.location.id: location, app.location.capacity: 2},
            "capacity", "a capacity below the assigned stock")
        stored = read_by_id(app, "StorageLocation", location)
        if numeric(stored, app.location.capacity, "stored capacity") != 10:
            fail(f"a refused shrink changed the capacity: {stored}")
        update_entity(app, "StorageLocation", location,
                      {app.location.capacity: 20})
        stored = read_by_id(app, "StorageLocation", location)
        if numeric(stored, app.location.capacity, "grown capacity") != 20:
            fail(f"a valid capacity increase was not persisted: {stored}")
    return f"refused a shrink below assigned stock ({rejection})"


def _named_service(app, name):
    for service in app.service_objects:
        method = getattr(service, name, None)
        if callable(method):
            return method
    fail(f"no generated service implements {name}")


def check_service_extras(package):
    """The extracted service extras that sit beside the GUI CRUD surface."""
    database = package.scratch("service_extras")
    with App(package, database) as app:
        cellars = create_location(
            app, capacity=20, zone="Extra Cellar", row=1, shelf=1)
        wine = create_wine(
            app, cellars, name="Domaine Extra", cost=10, selling=20, stock=4)

        confirm = _named_service(app, "confirm_order")
        cancel = _named_service(app, "cancel_order")
        if not confirm(wine, 2):
            fail("confirm_order returned false for a valid reservation")
        after_confirm = numeric(
            read_by_id(app, "Wine", wine), app.wine.stock, "confirmed stock")
        if after_confirm != 2:
            fail(f"confirm_order reserved the wrong quantity: {after_confirm}")
        if not cancel(wine, 2):
            fail("cancel_order returned false for a valid release")
        after_cancel = numeric(
            read_by_id(app, "Wine", wine), app.wine.stock, "cancelled stock")
        if after_cancel != 4:
            fail(f"cancel_order did not restore the reserved stock: {after_cancel}")

        search = _named_service(app, "search_wines_by_name")
        found = {record_id(item, app.wine)
                 for item in as_list(search("Dom"))}
        if wine not in found:
            fail(f"partial wine-name search missed the wine: {found}")

        second = create_wine(
            app, cellars, name="Second Extra", cost=5, selling=9, stock=7)
        full_location = create_location(
            app, capacity=7, zone="Full Extra", row=2, shelf=1)
        create_wine(
            app, full_location, name="Full Extra Wine", cost=5, selling=9,
            stock=7)
        capacity = _named_service(app, "check_storage_location_capacity")
        if capacity(full_location, wine):
            fail("capacity check accepted a location that is already full")
        unused_location = create_location(
            app, capacity=10, zone="Empty Extra", row=3, shelf=1)
        if not capacity(unused_location, wine):
            fail("capacity check refused a valid assignment")
        # Keep the second wine assigned so the summary has two rows of
        # different bottle counts.
        if read_by_id(app, "Wine", second) is None:
            fail("second wine was not stored")

        summary = _named_service(app, "get_storage_location_summary")()
        bucket = summary.get("Extra Cellar")
        if not isinstance(bucket, dict):
            bucket = next(
                (value for value in summary.values()
                 if isinstance(value, dict)
                 and (value.get("zone_name") == "Extra Cellar"
                      or value.get("location_id") == cellars)),
                None)
        if bucket is None:
            fail(f"storage summary omitted the location: {summary}")
        assigned = bucket.get("assigned_bottles",
                              bucket.get("total_bottles_assigned"))
        if assigned != 11:
            fail(f"storage summary counts rows, not bottles: {bucket}")

        pricing = _named_service(app, "validate_wine_pricing")
        if not pricing(wine, cost_price=15, selling_price=None):
            fail("partial pricing validation ignored the existing selling price")

        export = _named_service(app, "export_inventory_to_csv")
        target = package.scratch("service-export").with_suffix(".csv")
        if not export(str(target)):
            fail("export_inventory_to_csv returned false for a valid path")
        if not target.is_file() or "Wine Name" not in target.read_text(
                encoding="utf-8"):
            fail("export_inventory_to_csv did not write the inventory header")
        bad = package.scratch("missing-parent") / "nested" / "out.csv"
        try:
            export(str(bad))
        except Exception as error:  # noqa: BLE001 - the error shape under test
            if "ValueError" not in type(error).__name__:
                fail(f"export path failure raised {type(error).__name__}, "
                     "not ValueError")
        else:
            if not bad.is_file():
                fail("export path failure neither raised nor wrote a file")
    return "cancel, search, capacity, summary, pricing and export extras agree"


CHECKS = (
    ("GUI panels and pyimgui render loop", check_gui_structure),
    ("location/wine creation, update and persistence",
     check_records_and_persistence),
    ("unique wine names", check_unique_wine_names),
    ("selling price strictly above cost", check_pricing_rule),
    ("stock cannot become negative", check_non_negative_stock),
    ("wine assignment to a storage location", check_assignment),
    ("storage location capacity", check_location_capacity),
    ("occupied location cannot be deleted",
     check_location_deletion_guard),
    ("shrinking an occupied location is refused",
     check_location_capacity_shrink),
    ("service extras", check_service_extras),
)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def run(out_dir):
    package = Package(out_dir)
    results = []
    failures = []
    for name, check in CHECKS:
        try:
            note = check(package)
        except AssertionError as error:
            failures.append((name, str(error)))
            results.append({"name": name, "status": "failed",
                            "error": str(error)})
            print(f"FAIL: {name}: {error}", file=sys.stderr)
        except Exception as error:  # noqa: BLE001 - report, keep going
            failures.append((name, f"{type(error).__name__}: {error}"))
            results.append({"name": name, "status": "failed",
                            "error": f"{type(error).__name__}: {error}"})
            print(f"FAIL: {name}: {type(error).__name__}: {error}",
                  file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        else:
            results.append({"name": name, "status": "passed",
                            "note": note})
            print(f"PASS: {name}: {note}")
    result = {
        "status": "passed" if not failures else "failed",
        "checks": results,
        "generated": str(package.generated),
    }
    try:
        (package.out / "e2e_gui_results.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    if failures:
        print(f"FAIL: {len(failures)} of {len(CHECKS)} acceptance checks "
              f"failed", file=sys.stderr)
        return 1
    print(f"PASS: {len(CHECKS)} end-to-end acceptance checks")
    return 0


def main(argv):
    if len(argv) != 2:
        print(f"usage: {sys.argv[0]} OUT_DIR", file=sys.stderr)
        return 2
    try:
        return run(argv[1])
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
