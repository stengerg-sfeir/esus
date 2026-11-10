"""Mechanically complete the standard CRUD methods of entity services.

The model still owns custom domain methods: guards, state transitions,
aggregates and capability methods. The ordinary create/read/list/update/delete
wrappers are fixed by the entity list, so asking the small model to write them
again spends output tokens on a shape the data model already proves.
"""

from __future__ import annotations

import re

from kernel import codegen
from kernel.extraction.interfaces import normalize


DEFAULT_OPERATIONS = ("create", "read_one", "read_all", "update", "delete")

_TYPE_NAMES = {
    "int": "int",
    "integer": "int",
    "string": "str",
    "text": "str",
    "boolean": "bool",
    "bool": "bool",
    "decimal": "int",
    "float": "float",
    "date": "datetime.date",
    "datetime": "datetime.datetime",
    "timestamp": "datetime.datetime",
}


def _type_name(field):
    return _TYPE_NAMES.get(str(field.get("type") or "").strip().lower(), "str")


def _snake(entity):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", entity).lower()


def _plural(entity):
    lowered = entity.lower()
    if lowered.endswith(("s", "x", "z", "ch", "sh")):
        return entity + "es"
    if len(lowered) > 1 and lowered.endswith("y") and lowered[-2] not in "aeiou":
        return entity[:-1] + "ies"
    return entity + "s"


def _fields(data_models):
    result = {}
    for model in data_models or ():
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if isinstance(name, str) and name.strip():
            result[name] = [
                field for field in (model.get("fields") or ())
                if isinstance(field, dict) and isinstance(field.get("name"), str)
            ]
    return result


def _primary_key(fields):
    for field in fields:
        if field.get("primary_key") and field.get("name"):
            return field["name"]
    return "id"


def _not_found(errors, entity):
    wanted = f"{entity}NotFoundError"
    for error in errors or ():
        if isinstance(error, dict) and error.get("name") == wanted:
            return wanted
    return None


def _method(name, description, params, return_type, raises=()):
    return {
        "name": name,
        "description": description,
        "params": list(params),
        "return_type": return_type,
        "raises": list(raises),
        "mechanical": True,
    }


def _standard_methods(entity, fields, operations, errors):
    snake = _snake(entity)
    primary = _primary_key(fields)
    writable = [field for field in fields
                if field.get("name") and field["name"] != primary]
    write_params = [{"name": field["name"], "type": _type_name(field)}
                    for field in writable]
    not_found = _not_found(errors, entity)
    lookup_raises = [not_found] if not_found else []
    methods = []
    for operation in operations:
        if operation == "create":
            methods.append(_method(
                f"create_{snake}", f"Creates a new {entity}.",
                write_params, "None"))
        elif operation == "read_one":
            methods.append(_method(
                f"read_{snake}_by_id", f"Reads one {entity} by its key.",
                [{"name": primary, "type": "int"}],
                f"{entity} | None", lookup_raises))
        elif operation == "read_all":
            methods.append(_method(
                f"read_all_{_plural(snake)}", f"Lists every {entity}.",
                [], f"list[{entity}]"))
        elif operation == "update":
            methods.append(_method(
                f"update_{snake}", f"Updates an existing {entity}.",
                [{"name": primary, "type": "int"}, *write_params],
                "None", lookup_raises))
        elif operation == "delete":
            methods.append(_method(
                f"delete_{snake}", f"Deletes an existing {entity}.",
                [{"name": primary, "type": "int"}],
                "None", lookup_raises))
    return methods


def _service_for_entity(services, entity):
    wanted = normalize(f"{entity}Service")
    for service in services:
        if isinstance(service, dict) and normalize(
                service.get("service_name") or "") == wanted:
            return service
    return None


def _has_operation(service, operation):
    for method in service.get("methods") or ():
        if not isinstance(method, dict):
            continue
        if codegen.classify_crud(method.get("name") or "") == operation:
            return True
    return False


def complete(services, data_models, crud_operations, errors, log=None):
    """Add missing standard methods to the entity services.

    Existing methods, including custom create methods with validation, are
    kept. A service absent from the model is left alone: a custom domain
    service such as `LibraryService` may already own the calls, and a composite
    key (`Budget` by category and month) does not fit the generic primary-key
    wrapper. Adapters may target the repository in that case.
    """
    services = list(services) if isinstance(services, list) else []
    fields_by_entity = _fields(data_models)
    added = 0
    for requirement in crud_operations or ():
        entity = requirement.entity
        operations = requirement.operations or DEFAULT_OPERATIONS
        fields = fields_by_entity.get(entity, [])
        service = _service_for_entity(services, entity)
        if service is None:
            # Never invent an entity service: a domain service such as
            # `LibraryService` may already own the CRUD calls, and a composite
            # key (`Budget` by category and month) does not fit the generic
            # primary-key wrapper. Existing services are completed only.
            continue
        methods = service.setdefault("methods", [])
        existing = {normalize(method.get("name") or "")
                    for method in methods if isinstance(method, dict)}
        for method in _standard_methods(entity, fields, operations, errors):
            # `classify_crud` is the authority for operation coverage: a
            # custom `add_expense` already covers create, even though its
            # spelling differs from `create_expense`.
            operation = codegen.classify_crud(method["name"])
            if operation is not None and _has_operation(service, operation):
                continue
            if normalize(method["name"]) in existing:
                continue
            methods.append(method)
            existing.add(normalize(method["name"]))
            added += 1
    if log is not None and added:
        log.write(
            f"[ok] step contracts: added {added} mechanical service method(s)"
        )
    return services
