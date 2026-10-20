"""Record store for generated programs: dependency-free, no surprises.

In-memory by default; SQLite-backed when given a path (`Store("shop.db")`,
`:memory:` included). All querying stays in Python (criteria, `_holds`):
sqlite is a durable record drawer, not a query engine, so file-backed
behavior is identical to memory by construction — every mutation commits
immediately, and loading restores records plus the id counters.

Tables hold one JSON blob per record keyed by the primary-key value, so
there is no column mapping to drift from the models; values must stay
JSON-shaped (str, int, float, bool, None — everything the CLI parses;
`datetime.date`/`datetime.datetime` enter as ISO strings), and anything
else fails loudly instead of persisting wrong. Deleting the file resets
the program; schema migration is a non-goal.

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


class Store:
    """Maps entity names to `{primary_key_value: record}` dicts."""

    def __init__(self, path=None):
        self._records = {}
        self._next_id = {}
        self._db = None
        if path is not None:
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
            if all(_holds(record.get(field), operator, value)
                   for field, operator, value in prepared):
                matches.append(dict(record))
        return matches


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
