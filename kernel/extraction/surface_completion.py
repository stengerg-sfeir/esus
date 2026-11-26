"""Complete the CLI surface from the CRUD contracts.

Step D records the entity operations, and step E records the repository and
service methods that implement them. The model can still omit a command from
the surface even when both lists agree, especially for prose-only prompts
("provide create, list, update and delete operations"). The omission is
structural: the operation has a method and a data model, so the command can be
derived rather than guessed.

This pass only adds a missing standard verb to an existing CLI command group.
It never renames, removes or invents a domain method; if no service or
repository method backs the verb, the command is left absent for the probe.
"""

from __future__ import annotations

import re

from kernel.codegen import classify_crud
from kernel.consistency.naming import normalize

# The CLI spelling of each mechanical operation. `read_one` is deliberately
# absent: a single-row lookup is usually reached through a domain verb
# (`search`, `report`, `get`) and is not a useful generic command.
VERBS = {
    "create": "add",
    "read_all": "list",
    "update": "update",
    "delete": "delete",
}
ALIASES = {
    "create": ("add", "create", "insert", "new"),
    "read_all": ("list", "browse", "all", "readall"),
    "update": ("update", "edit"),
    "delete": ("delete", "remove"),
}
OPTION_TYPES = {
    "int": "int", "integer": "int",
    "float": "float", "double": "float", "decimal": "float",
    "bool": "bool", "boolean": "bool",
}


def _model_fields(models):
    result = {}
    for model in models or ():
        if not isinstance(model, dict) or not isinstance(model.get("name"), str):
            continue
        result[model["name"]] = [
            field for field in model.get("fields") or ()
            if isinstance(field, dict) and isinstance(field.get("name"), str)
        ]
    return result


def _option_type(field):
    kind = str((field or {}).get("type") or "").strip().lower()
    return OPTION_TYPES.get(kind, "str")


def _options_for(method, fields, operation):
    options = []
    primary = next((field.get("name") for field in fields
                    if field.get("primary_key")), None)
    for param in method.get("params") or ():
        if not isinstance(param, dict) or not isinstance(param.get("name"), str):
            continue
        name = param["name"]
        field = next((item for item in fields if item.get("name") == name), None)
        if field is None:
            # A method parameter can name the key with a different spelling
            # (`id` vs `event_id`); map it to the model's key when unique.
            field = next((item for item in fields
                          if normalize(item.get("name") or "") == normalize(name)), None)
        if field is None and primary and normalize(name) == normalize(primary):
            field = next((item for item in fields
                          if item.get("name") == primary), None)
        if field is None:
            continue
        required = False
        if operation in ("create", "update"):
            required = bool(field.get("primary_key"))
        if operation == "delete":
            required = bool(field.get("primary_key"))
        options.append({
            "name": "--" + name.replace("_", "-"),
            "short": None,
            "type": _option_type(field),
            "required": required,
            "default": None,
        })
    return options


def _method_for(services, entity, operation):
    candidates = []
    for service in services or ():
        if not isinstance(service, dict):
            continue
        holder = service.get("service_name") or service.get("interface_name") or ""
        for method in service.get("methods") or ():
            if not isinstance(method, dict) or not isinstance(method.get("name"), str):
                continue
            if classify_crud(method["name"]) != operation:
                continue
            score = 0
            if normalize(entity) in normalize(holder):
                score += 2
            if "repository" in normalize(holder):
                score += 1
            candidates.append((score, holder, method))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]["name"]))
    return candidates[0][2]


def _command(invocation, entity):
    commands = invocation.get("commands")
    if not isinstance(commands, list):
        return None
    for command in commands:
        if not isinstance(command, dict):
            continue
        if normalize(command.get("name") or "") == normalize(entity):
            return command
    return None


def _has_verb(command, operation):
    subs = command.get("subcommands")
    if not isinstance(subs, list):
        return False
    wanted = {normalize(item) for item in ALIASES[operation]}
    return any(isinstance(sub, dict)
               and normalize(sub.get("name") or "") in wanted
               for sub in subs)


def complete(components, services, models, requirements="", log=None):
    """Add a missing *requirements-named* read-all command.

    The broad CRUD surface is a product decision, not a fact of every prompt:
    adding commands the requirements never ask for creates dead CLI leaves and
    ambiguous adapters. This pass is limited to the explicit list operation,
    which is the one gap the prose prompts repeatedly hide.
    """
    if not isinstance(components, dict):
        return components
    wants_list = bool(re.search(r"\b(?:list|listing|browse|enumerate)\b",
                                requirements or "", re.I))
    facade = components.get("facade")
    if not isinstance(facade, dict) or str(facade.get("type")).lower() != "cli":
        return components
    invocation = facade.get("invocation")
    if not isinstance(invocation, dict) or not isinstance(invocation.get("commands"), list):
        return components
    fields_by_entity = _model_fields(models)
    added = []
    for requirement in components.get("crud_services") or ():
        if not isinstance(requirement, dict):
            continue
        entity = requirement.get("entity")
        if not isinstance(entity, str) or not entity:
            continue
        command = _command(invocation, entity)
        operations = requirement.get("operations") or ()
        if command is None:
            # The component step can omit an entire command group while the
            # data model and the CRUD contract still name the entity. Restore
            # the group from those documents; a group with no derivable verb
            # stays absent rather than becoming an empty parser node.
            command = {"name": entity, "options": [], "subcommands": []}
            group_is_new = True
        else:
            group_is_new = False
        for operation, verb in VERBS.items():
            if operation not in operations:
                continue
            if operation == "read_all":
                if not wants_list and not group_is_new:
                    continue
                # A new group does not expose read-all unless the prose names
                # listing; the baseline CRUD groups are add/update/delete.
                if not wants_list:
                    continue
            if _has_verb(command, operation):
                continue
            method = _method_for(services, entity, operation)
            if method is None:
                continue
            subcommands = command.setdefault("subcommands", [])
            if not isinstance(subcommands, list):
                continue
            subcommands.append({
                "name": verb,
                "options": _options_for(
                    method, fields_by_entity.get(entity) or (), operation),
            })
            added.append(f"{command.get('name')} {verb}")
        if group_is_new and command.get("subcommands"):
            invocation["commands"].append(command)
    if added and log is not None:
        log.write(
            f"[ok] step components: added {len(added)} CRUD subcommand(s) "
            f"from the service contracts: {', '.join(added[:8])}"
        )
    return components
