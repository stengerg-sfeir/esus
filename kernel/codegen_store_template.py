"""Record store for generated programs: dependency-free, no surprises.

In-memory by default; SQLite-backed when given a path (`Store("shop.db")`,
`:memory:` included). When a schema is supplied, the durable form is real
SQLite: one table per entity, typed columns, INTEGER primary keys, UNIQUE
constraints and foreign keys with `ON DELETE CASCADE`. Without a schema the
fallback is the original one-JSON-document-per-record drawer, which keeps
small generated programs and the store's own tests dependency-free.

All querying still goes through the Python record view (criteria, `_holds`),
so memory and file-backed behavior match. With a schema, SQLite owns inserts,
updates and deletes; the record view is reloaded after every mutation, which
is also what makes cascades visible to callers.

Records are plain dicts keyed by field name. The store knows nothing about
your domain: every operation takes the entity name, the primary-key field,
and explicit criteria, so a wrong call fails loudly (`KeyError`, `ValueError`)
instead of filtering on a field that does not exist.

Criteria are `(field, operator, value)` triples with operators `eq`, `ge`,
`le`. `None` values never reach here — callers skip them — so every criterion
is a real constraint.
"""

import datetime
import json
import sqlite3
from contextlib import contextmanager


class Store:
    """Maps entity names to `{primary_key_value: record}` dicts."""

    def __init__(self, path=None, schema=None):
        self._records = {}
        self._next_id = {}
        self._db = None
        self._schema = schema or {}
        self._tx_depth = 0
        if self._schema:
            self._db = sqlite3.connect(path if path is not None else ":memory:")
            self._db.execute("PRAGMA foreign_keys = ON")
            self._create_schema()
            self._load_schema()
        elif path is not None:
            self._db = sqlite3.connect(path)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS records "
                "(entity TEXT NOT NULL, key TEXT NOT NULL, "
                "doc TEXT NOT NULL, PRIMARY KEY (entity, key))")
            self._load()

    def _key(self, key):
        """A stable TEXT key: `1` and `"1"` stay distinct records."""
        return json.dumps(key, sort_keys=True)

    def _load(self):
        """Restore records and id counters from the file, if any."""
        for entity, key, doc in self._db.execute(
                "SELECT entity, key, doc FROM records"):
            self._records.setdefault(entity, {})[json.loads(key)] = json.loads(doc)
        for entity, space in self._records.items():
            ints = [key for key in space
                    if isinstance(key, int) and not isinstance(key, bool)]
            if ints:
                self._next_id[entity] = max(ints) + 1

    @staticmethod
    def _quote(identifier):
        return '"' + str(identifier).replace('"', '""') + '"'

    def _create_schema(self):
        """Create one typed table per entity, in dependency-safe form.

        SQLite permits a foreign key to name a table created later in the
        same transaction, so declaration order does not matter. `ON DELETE
        CASCADE` is part of the stored schema rather than a Python-side
        cleanup step, and `PRAGMA foreign_keys = ON` makes it effective.
        """
        for entity, spec in self._schema.items():
            columns = []
            for field in spec.get("fields") or []:
                name = self._quote(field.get("name"))
                sql_type = _sql_type(field.get("type"))
                if field.get("primary_key"):
                    declaration = (sql_type + " PRIMARY KEY AUTOINCREMENT"
                                   if sql_type == "INTEGER"
                                   else sql_type + " PRIMARY KEY")
                else:
                    declaration = sql_type
                    if not field.get("nullable", True):
                        declaration += " NOT NULL"
                    if field.get("unique"):
                        declaration += " UNIQUE"
                    if field.get("default") is not None:
                        declaration += " DEFAULT " + _sql_literal(field["default"])
                    foreign = field.get("foreign_key")
                    if isinstance(foreign, dict) and foreign.get("target_entity"):
                        declaration += (
                            " REFERENCES "
                            + self._quote(foreign["target_entity"])
                            + "(" + self._quote(foreign.get("target_field") or "id")
                            + ") ON DELETE CASCADE")
                columns.append(name + " " + declaration)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS "
                + self._quote(entity) + " (" + ", ".join(columns) + ")")
        self._commit()

    def _load_schema(self):
        self._records = {}
        for entity, spec in self._schema.items():
            primary_key = spec.get("primary_key") or "id"
            declared = {field.get("name"): field.get("type")
                        for field in spec.get("fields") or []}
            cursor = self._db.execute(
                "SELECT * FROM " + self._quote(entity))
            names = [description[0] for description in cursor.description]
            space = self._records.setdefault(entity, {})
            for values in cursor:
                record = dict(zip(names, values))
                for name, value in list(record.items()):
                    record[name] = _from_sql(value, declared.get(name))
                space[record.get(primary_key)] = record

    def _add_schema(self, entity, pk_name, values, check_fk):
        spec = self._schema.get(entity)
        if spec is None:
            raise ValueError(f"unknown entity {entity!r} for this schema")
        defaults = {field.get("name"): field.get("default")
                    for field in spec.get("fields") or []}
        record = {name: _iso(value) for name, value in values.items()}
        for name, default in defaults.items():
            if name not in record or record[name] is None:
                if default is not None:
                    record[name] = default
        key = record.get(pk_name)
        if key is not None and key in self._records.get(entity, {}):
            raise ValueError(f"{entity} with {pk_name}={key!r} already exists")
        for field_name, target_entity, target_field, exc in check_fk:
            self._check_fk(entity, record, field_name,
                           target_entity, target_field, exc)
        columns = []
        parameters = []
        for field in spec.get("fields") or []:
            name = field.get("name")
            if name == pk_name and record.get(name) is None:
                continue
            value = record.get(name)
            # Let an explicit SQL default fill a field the caller omitted.
            if value is None and field.get("default") is not None:
                continue
            columns.append(self._quote(name))
            parameters.append(_to_sql(value))
        cursor = self._db.execute(
            "INSERT INTO " + self._quote(entity)
            + (" (" + ", ".join(columns) + ")" if columns else "")
            + " VALUES (" + ", ".join("?" for _ in columns) + ")"
            if columns else
            "INSERT INTO " + self._quote(entity) + " DEFAULT VALUES",
            parameters)
        if key is None:
            key = cursor.lastrowid
        self._commit()
        self._load_schema()
        return dict(self._records[entity][key])

    def _update_schema(self, entity, pk_name, key, values, error):
        spec = self._schema.get(entity)
        if spec is None or key not in self._records.get(entity, {}):
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)
        assignments = []
        parameters = []
        for field in spec.get("fields") or []:
            name = field.get("name")
            if name == pk_name or name not in values or values[name] is None:
                continue
            assignments.append(self._quote(name) + " = ?")
            parameters.append(_to_sql(values[name]))
        if assignments:
            parameters.append(key)
            self._db.execute(
                "UPDATE " + self._quote(entity) + " SET "
                + ", ".join(assignments) + " WHERE "
                + self._quote(pk_name) + " = ?", parameters)
            self._commit()
            self._load_schema()
        return dict(self._records[entity][key])

    def _delete_schema(self, entity, pk_name, key, error):
        spec = self._schema.get(entity)
        if spec is None or key not in self._records.get(entity, {}):
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)
        self._db.execute(
            "DELETE FROM " + self._quote(entity) + " WHERE "
            + self._quote(pk_name) + " = ?", (key,))
        self._commit()
        self._load_schema()

    def _persist(self, entity, key):
        """Write one record through (or its deletion) and commit."""
        if self._db is None:
            return
        if key not in self._records.get(entity, {}):
            self._db.execute("DELETE FROM records WHERE entity = ? AND key = ?",
                             (entity, self._key(key)))
        else:
            self._db.execute(
                "INSERT OR REPLACE INTO records (entity, key, doc) VALUES (?, ?, ?)",
                (entity, self._key(key),
                 json.dumps(self._records[entity][key], sort_keys=True,
                            default=_iso)))
        self._commit()

    def _commit(self):
        """Commit unless an enclosing `transaction()` owns the boundary."""
        if self._db is not None and self._tx_depth == 0:
            self._db.commit()

    @contextmanager
    def transaction(self):
        """Make the writes inside one SQLite transaction, or do nothing."""
        if self._db is None or not self._schema:
            yield
            return
        self._tx_depth += 1
        try:
            yield
        except BaseException:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._db.rollback()
                self._load_schema()
            raise
        else:
            self._tx_depth -= 1
            if self._tx_depth == 0:
                self._db.commit()

    def close(self):
        """Flush and release the file, if any (commits already happened)."""
        if self._db is not None:
            self._db.commit()
            self._db.close()
            self._db = None

    def _space(self, entity):
        return self._records.setdefault(entity, {})

    def add(self, entity, pk_name, values, check_fk=()):
        """Store a copy of `values`; assign an integer key when it is None."""
        if self._schema:
            return self._add_schema(entity, pk_name, values, check_fk)
        space = self._space(entity)
        record = {name: _iso(value) for name, value in values.items()}
        key = record.get(pk_name)
        if key is None:
            key = self._next_id.get(entity, 1)
            while key in space:
                key += 1
            record[pk_name] = key
            self._next_id[entity] = key + 1
        elif key in space:
            raise ValueError(f"{entity} with {pk_name}={key!r} already exists")
        for field_name, target_entity, target_field, exc in check_fk:
            self._check_fk(entity, record, field_name,
                           target_entity, target_field, exc)
        space[key] = record
        self._persist(entity, key)
        return dict(record)

    def _check_fk(self, entity, record, field_name,
                  target_entity, target_field, exc):
        value = record.get(field_name)
        if value is None:
            return
        for candidate in self._space(target_entity).values():
            if candidate.get(target_field) == value:
                return
        message = (f"{entity}.{field_name}={value!r} references missing "
                   f"{target_entity}.{target_field}")
        raise exc(message) if exc is not None else KeyError(message)

    def get(self, entity, pk_name, key, error=None):
        """One record by key, or `error` (default `KeyError`)."""
        try:
            return dict(self._space(entity)[key])
        except KeyError:
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)

    def all(self, entity):
        """Every record of an entity, in insertion order."""
        return [dict(record) for record in self._space(entity).values()]

    def update(self, entity, pk_name, key, values, error=None):
        """Merge `values` into the record at `key`; unknown keys fail like `get`."""
        if self._schema:
            return self._update_schema(entity, pk_name, key, values, error)
        space = self._space(entity)
        if key not in space:
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)
        merged = dict(space[key])
        for field_name, value in values.items():
            if value is not None:
                merged[field_name] = _iso(value)
        space[key] = merged
        self._persist(entity, key)
        return dict(merged)

    def delete(self, entity, pk_name, key, error=None):
        """Remove the record at `key`; unknown keys fail like `get`."""
        if self._schema:
            return self._delete_schema(entity, pk_name, key, error)
        space = self._space(entity)
        if key not in space:
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)
        del space[key]
        self._persist(entity, key)

    def select(self, entity, criteria):
        """Records matching every `(field, operator, value)` criterion."""
        matches = []
        prepared = [(field, operator, _iso(value))
                    for field, operator, value in criteria]
        for record in self._space(entity).values():
            # Schema mode restores date columns to `datetime.date`; the
            # criteria were normalised to ISO text above, so the stored
            # value takes the same path (ISO text sorts chronologically).
            if all(_holds(_iso(record.get(field)), operator, value)
                   for field, operator, value in prepared):
                matches.append(dict(record))
        return matches


def _sql_type(declared):
    """The SQLite affinity for a model type; JSON-ish values stay portable."""
    name = str(declared or "").strip().lower()
    if name in ("int", "integer"):
        return "INTEGER"
    if name in ("bool", "boolean"):
        return "INTEGER"
    if name in ("float", "decimal", "number", "real"):
        return "REAL"
    return "TEXT"


def _to_sql(value):
    """Dates become ISO text; lists/dicts become JSON text for SQLite."""
    value = _iso(value)
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def _from_sql(value, declared):
    """Restore the JSON-ish shapes the generic store promises."""
    name = str(declared or "").strip().lower()
    if value is None:
        return None
    if name in ("bool", "boolean"):
        return bool(value)
    if (name in ("list", "array", "dict", "object", "json")
            or name.startswith(("list[", "array[", "dict[", "set["))):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    if name == "date" and isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return value
    if name in ("datetime", "timestamp") and isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except ValueError:
            return value
    return value


def _sql_literal(value):
    """A safe SQL literal for a schema DEFAULT (values are extraction data)."""
    if value is True:
        return "1"
    if value is False:
        return "0"
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _iso(value):
    """`datetime.date`/`datetime.datetime` become ISO strings; else no-op.

    Dates normalize at the door, for records as for criteria, so memory
    and file agree by construction: a body that stored
    `datetime.date.today()` reads back the same `"2026-10-19"` a reload
    would give, and a criterion comparing against a date object matches
    the stored string instead of failing the comparison.
    """
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _holds(actual, operator, expected):
    if operator == "eq":
        return actual == expected
    if operator == "ge":
        return actual is not None and actual >= expected
    if operator == "le":
        return actual is not None and actual <= expected
    if operator == "gt":
        return actual is not None and actual > expected
    if operator == "lt":
        return actual is not None and actual < expected
    raise ValueError(f"unknown operator {operator!r}")


def match_criterion(field_names, param):
    """Map a filter parameter to `(field, operator)` or None.

    Twin of `kernel.codegen.match_param` — copied here so generated programs
    are dependency-free. Exact normalized equality is `eq`; a `<x>_id`
    parameter names the entity's own `id` when no field matches. A
    `start_`/`from_`/`min_` prefix is `ge` and an `end_`/`to_`/`max_`
    prefix is `le` against the field containing the remainder (`start_date`
    filters `expense_date`); a remainder matching several fields refuses.
    """
    wanted = "".join(character for character in str(param or "").lower()
                     if character.isalnum())
    if not wanted:
        return None
    for field in field_names:
        if "".join(c for c in str(field).lower() if c.isalnum()) == wanted:
            return (field, "eq")
    for prefix, operator in (("start", "ge"), ("from", "ge"),
                             ("end", "le"), ("to", "le"),
                             ("min", "ge"), ("max", "le")):
        if wanted.startswith(prefix) and len(wanted) > len(prefix):
            rest = wanted[len(prefix):]
            candidates = []
            for field in field_names:
                flat = "".join(c for c in str(field).lower()
                               if c.isalnum())
                if rest and (rest in flat or flat in rest):
                    candidates.append(field)
            if len(candidates) == 1:
                return (candidates[0], operator)
    raw = str(param or "").strip().lower()
    if raw.endswith("_id") and len(raw) > 3:
        for field in field_names:
            if "".join(c for c in str(field).lower()
                       if c.isalnum()) == "id":
                return (field, "eq")
    return None
