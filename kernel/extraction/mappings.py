"""Mechanical persistence mappings derived from the data model.

The entity set and primary keys are already fixed by steps B and D.  Table
names and ordinary indexes do not need a model call: they follow directly from
the entity name, the declared fields and the foreign keys.  The model still
owns custom repository methods; this module only supplies the mapping side of
step H.
"""

from __future__ import annotations

import re

_FILTER_FIELDS = frozenset({"month", "payment_method", "status", "is_recurring"})


def _snake(name):
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", str(name))
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def table_name(entity):
    """A conventional plural snake-case table name."""
    stem = _snake(entity)
    if not stem:
        return "records"
    if stem.endswith(("s", "x", "z", "ch", "sh")):
        return stem + "es"
    if stem.endswith("y") and len(stem) > 1 and stem[-2] not in "aeiou":
        return stem[:-1] + "ies"
    return stem + "s"


def _fields(model):
    return [
        field for field in (model.get("fields") or ())
        if isinstance(field, dict) and isinstance(field.get("name"), str)
    ]


def _primary_key(fields):
    for field in fields:
        if field.get("primary_key") and field.get("name"):
            return field["name"]
    return "id"


def _indexes(fields):
    indexes = []
    for field in fields:
        name = field.get("name")
        if not name or name == _primary_key(fields):
            continue
        kind = str(field.get("type") or "").strip().lower()
        if (field.get("unique") or field.get("foreign_key")
                or kind in {"date", "datetime", "timestamp"}
                or name in _FILTER_FIELDS):
            indexes.append(name)
    return indexes


def entity_mappings(data_models, entities):
    """One mapping per persisted entity, in the supplied order."""
    by_name = {
        model.get("name"): model
        for model in (data_models or ())
        if isinstance(model, dict) and isinstance(model.get("name"), str)
    }
    mappings = []
    for entity in entities or ():
        model = by_name.get(entity, {})
        fields = _fields(model)
        mappings.append({
            "entity": entity,
            "table": table_name(entity),
            "primary_key": _primary_key(fields),
            "indexes": _indexes(fields),
        })
    return mappings
