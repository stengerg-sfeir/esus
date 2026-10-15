"""In-memory record store for generated programs: no dependencies, no surprises.

Records are plain dicts keyed by field name. The store knows nothing about
your domain: every operation takes the entity name, the primary-key field,
and explicit criteria, so a wrong call fails loudly (`KeyError`, `ValueError`)
instead of filtering on a field that does not exist.

Criteria are `(field, operator, value)` triples with operators `eq`, `ge`,
`le`. `None` values never reach here — callers skip them — so every criterion
is a real constraint.
"""


class Store:
    """Maps entity names to `{primary_key_value: record}` dicts."""

    def __init__(self):
        self._records = {}
        self._next_id = {}

    def _space(self, entity):
        return self._records.setdefault(entity, {})

    def add(self, entity, pk_name, values, check_fk=()):
        """Store a copy of `values`; assign an integer key when it is None."""
        space = self._space(entity)
        record = dict(values)
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
                merged[field_name] = value
        space[key] = merged
        return dict(merged)

    def delete(self, entity, pk_name, key, error=None):
        """Remove the record at `key`; unknown keys fail like `get`."""
        space = self._space(entity)
        if key not in space:
            message = f"{entity} with {pk_name}={key!r} not found"
            raise error(message) if error is not None else KeyError(message)
        del space[key]

    def select(self, entity, criteria):
        """Records matching every `(field, operator, value)` criterion."""
        matches = []
        for record in self._space(entity).values():
            if all(_holds(record.get(field), operator, value)
                   for field, operator, value in criteria):
                matches.append(dict(record))
        return matches


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
    are dependency-free. Exact normalized equality is `eq`; a `start_`/`from_`
    prefix is `ge` and an `end_`/`to_` prefix is `le` against the field
    containing the remainder (`start_date` filters `expense_date`).
    """
    wanted = "".join(character for character in str(param or "").lower()
                     if character.isalnum())
    if not wanted:
        return None
    for field in field_names:
        if "".join(c for c in str(field).lower() if c.isalnum()) == wanted:
            return (field, "eq")
    for prefix, operator in (("start", "ge"), ("from", "ge"),
                             ("end", "le"), ("to", "le")):
        if wanted.startswith(prefix) and len(wanted) > len(prefix):
            rest = wanted[len(prefix):]
            for field in field_names:
                flat = "".join(c for c in str(field).lower() if c.isalnum())
                if rest and (rest in flat or flat in rest):
                    return (field, operator)
    return None
