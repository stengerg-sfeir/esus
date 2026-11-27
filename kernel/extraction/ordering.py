"""Canonical ordering for the name-keyed collections of extracted documents.

The order in which the model emits entities, services, errors or methods is not
a fact about the program.  It is still observable: it changes the vocabulary
block a later step reads, the order of the alternatives in a GBNF grammar, and
the bytes written to disk.  Two runs that extracted the same facts could
therefore differ only because the first list came back in a different order.

This module puts those collections in a stable order at the document boundary.
It deliberately does **not** sort fields, method parameters or CLI options:
their order is part of the model (the first field is the primary key), the
call signature, or the user-facing surface.
"""

from __future__ import annotations

CASE_INSENSITIVE = str.casefold


def name_key(value):
    """A deterministic key for an identifier, tolerant of missing values.

    Case-insensitive first so `Expense` and `expense` sit together, then the
    original spelling as a tie-breaker so the result never depends on the
    input order for two identifiers that differ only in case.
    """
    text = "" if value is None else str(value)
    return (CASE_INSENSITIVE(text), text)


def _entry_name(entry, *keys):
    if not isinstance(entry, dict):
        return ""
    for key in keys:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _sorted_dicts(items, *keys):
    if not isinstance(items, list):
        return items
    return sorted(items, key=lambda item: name_key(_entry_name(item, *keys)))


def _sorted_methods(holder):
    if not isinstance(holder, dict):
        return holder
    methods = holder.get("methods")
    if not isinstance(methods, list):
        return holder
    return {
        **holder,
        "methods": _sorted_dicts(methods, "name"),
    }


def canonicalize(key, body):
    """Return `body` with its name-keyed lists in canonical order.

    Unknown document keys and malformed bodies are returned unchanged: ordering
    is a presentation concern, never a reason to reject a document.
    """
    if key == "intentions":
        if isinstance(body, list):
            phrases = [item for item in body if isinstance(item, str)]
            if len(phrases) == len(body):
                return sorted(phrases, key=name_key)
        return body

    if key == "errors":
        return _sorted_dicts(body, "name")

    if key == "data_models":
        return _sorted_dicts(body, "name")

    if key == "invariants":
        return _sorted_dicts(body, "text")

    if key == "service_contracts":
        if not isinstance(body, list):
            return body
        return [_sorted_methods(service)
                for service in _sorted_dicts(body, "service_name")]

    if key == "persistence_ports":
        if not isinstance(body, dict):
            return body
        canonical = dict(body)
        repositories = body.get("repositories")
        if isinstance(repositories, list):
            canonical["repositories"] = [
                _sorted_methods(repository)
                for repository in _sorted_dicts(
                    repositories, "interface_name", "entity")]
        mappings = body.get("entity_mappings")
        if isinstance(mappings, list):
            canonical["entity_mappings"] = _sorted_dicts(
                mappings, "entity", "table")
        return canonical

    if key == "interaction_adapters":
        return _sorted_dicts(body, "action_name")

    if key == "components":
        if not isinstance(body, dict):
            return body
        crud = body.get("crud_services")
        if isinstance(crud, list):
            crud = _sorted_dicts(crud, "entity")
        return {**body, "crud_services": crud}

    if key == "pattern_matches":
        return _sorted_dicts(body, "text", "pattern_id", "source")

    return body
