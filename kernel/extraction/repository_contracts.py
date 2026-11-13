"""Mechanically complete the repository contracts of step E.

Step E is a model call, and its grammar permits a valid service list that
omits repositories.  The repository set is not a judgement call: it is derived
from the entities and CRUD operations step D declared.  This module fills those
contracts deterministically, while leaving any custom methods the model did
emit alone.
"""

from __future__ import annotations

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


def _fields_by_entity(data_models):
    result = {}
    for model in data_models or ():
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        result[name] = [
            field for field in (model.get("fields") or ())
            if isinstance(field, dict) and isinstance(field.get("name"), str)
        ]
    return result


def _primary_key(fields, entity):
    for field in fields:
        if field.get("primary_key") and field.get("name"):
            return field["name"]
    return "id"


def _not_found_error(errors, entity):
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
    }


def _snake(name):
    return "".join(
        ("_" + char.lower()) if char.isupper() and index else char.lower()
        for index, char in enumerate(str(name or ""))
    ).lstrip("_")


def _plural(entity):
    snake = _snake(entity)
    if snake.endswith("s"):
        return snake
    return snake + "s"


def _child_query(entity, fields):
    """A query by the first foreign key of a dependent entity.

    A child repository without this query is structurally complete but cannot
    serve the parent method that reads its lines (`confirm_order` asks
    `OrderItemRepository.get_order_items_by_order_id`).  The parent entity and
    its key are already in the field's `foreign_key` fact, so the name is
    derived, not guessed.
    """
    for field in fields:
        lookup = field.get("foreign_key")
        if not isinstance(lookup, dict):
            continue
        target = lookup.get("target_entity")
        target_field = lookup.get("target_field")
        # The query name must be the child's own key (`order_id`), not a
        # generic `id` borrowed from the parent.  A data model that writes
        # `target_field: id` does not tell us how the child column is named,
        # so the method would be `get_expenses_by_id` — a query no service
        # calls and a name that pushes the body prompts around.
        if not target or not target_field or target_field == "id" \
                or target_field != field.get("name"):
            continue
        return _method(
            f"get_{_plural(entity)}_by_{target_field}",
            f"Lists the {entity} records belonging to one {target}.",
            [{"name": target_field, "type": "int"}],
            f"list[{entity}]",
        )
    return None


def _shell(entity, fields, operations, errors):
    primary_key = _primary_key(fields, entity)
    writable = [
        field for field in fields
        if field.get("name") and field.get("name") != primary_key
    ]
    create_params = [
        {"name": field["name"], "type": _type_name(field)}
        for field in writable
    ]
    field_params = [
        {"name": field["name"], "type": _type_name(field)}
        for field in writable
    ]
    not_found = _not_found_error(errors, entity)
    lookup_raises = [not_found] if not_found else []
    methods = []
    for operation in operations:
        if operation == "create":
            methods.append(_method(
                "create", f"Creates a new {entity}.",
                create_params, entity,
            ))
        elif operation == "read_one":
            methods.append(_method(
                "read_one", f"Reads one {entity} by its key.",
                [{"name": primary_key, "type": "int"}], entity, lookup_raises,
            ))
        elif operation == "read_all":
            methods.append(_method(
                "read_all", f"Lists every {entity}; optional fields narrow the result.",
                field_params, f"list[{entity}]",
            ))
        elif operation == "update":
            methods.append(_method(
                "update", f"Updates an existing {entity}.",
                [{"name": primary_key, "type": "int"}, *field_params],
                entity, lookup_raises,
            ))
        elif operation == "delete":
            methods.append(_method(
                "delete", f"Deletes an existing {entity}.",
                [{"name": primary_key, "type": "int"}, *field_params],
                "None", lookup_raises,
            ))
    child = _child_query(entity, fields)
    if child is not None:
        methods.append(child)
    return {"service_name": f"{entity}Repository", "methods": methods}


def complete(services, data_models, crud_operations, errors, log=None):
    """Add one repository for every entity with declared CRUD operations.

    Existing repository entries keep their methods, including custom queries;
    the existing coverage retry still owns incomplete method sets.  Only an
    entirely absent repository is filled mechanically here, so a model that
    omits a repository cannot starve the adapter step.
    """
    services = list(services) if isinstance(services, list) else []
    fields_by_entity = _fields_by_entity(data_models)
    by_name = {
        normalize(service.get("service_name")): service
        for service in services
        if isinstance(service, dict) and service.get("service_name")
    }
    added = 0
    for requirement in crud_operations or ():
        entity = requirement.entity
        operations = requirement.operations or DEFAULT_OPERATIONS
        fields = fields_by_entity.get(entity, [])
        shell = _shell(entity, fields, operations, errors)
        name = normalize(shell["service_name"])
        existing = by_name.get(name)
        if existing is not None:
            # The model declared this repository.  Its method set is its own:
            # a missing required operation is still a coverage miss that the
            # existing retry path handles.  Only an entirely absent repository
            # is filled mechanically here.
            continue
        services.append(shell)
        by_name[name] = shell
        added += 1
    if log is not None and added:
        log.write(
            f"[ok] step contracts: added {added} mechanical repository entries"
        )
    return services
