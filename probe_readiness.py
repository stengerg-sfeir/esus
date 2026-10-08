"""Would a code generator have to invent anything? Checks the documents directly.

The consistency checker proves the documents agree with each other. A generator
needs more: every command backed by a method, every adapter resolving, every
parameter well-typed, every raised error registered. This probe measures those,
per prompt, and prints the blockers a generator would have to paper over.

A CLI verb and a service method rarely share a spelling (`add` is `create_book`,
`list` is `read_all_books`), so a verb is matched by a family of method-name
stems — that is a rename the generator does once, not an invention.
"""

import json
import os

OUT = "out"
PROMPTS = ("hello", "cli_tool", "inventory", "gui", "expenses", "60", "library")

VERB_STEMS = {
    "add": ("add", "create", "save", "insert", "new"),
    "create": ("add", "create", "save", "insert", "new"),
    "list": ("all", "list"),
    "search": ("search", "query", "find", "filter"),
    "update": ("update", "edit", "set"),
    "delete": ("delete", "remove"),
    "get": ("get", "find", "read"),
    "report": ("report", "stats", "summary", "value"),
    "low-stock": ("lowstock",),
    "value": ("value",),
    "confirm": ("confirm",),
    "cancel": ("cancel",),
    "restock": ("restock",),
}
OP_STEMS = {
    "create": ("add", "create", "save", "insert"),
    "read_one": ("byid", "readone", "read", "find", "get"),
    "read_all": ("all", "list"),
    "update": ("update", "edit"),
    "delete": ("delete", "remove"),
}


def load(name, key):
    path = os.path.join(OUT, name, f"{key}.json")
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        return json.load(handle).get(key)


def norm(value):
    return value.replace("_", "").replace("-", "").lower() if isinstance(value, str) else ""


def service_index(services):
    index = {}
    for service in services or []:
        methods = {norm(m.get("name")) for m in service.get("methods", [])}
        index[norm(service.get("service_name"))] = methods
    return index


def flatten_commands(commands):
    pairs = []
    for command in commands or []:
        pairs.append((command.get("name"), None))
        for sub in command.get("subcommands") or []:
            pairs.append((command.get("name"), sub.get("name")))
    return pairs


def served_by_stems(stems, methods):
    return any(any(stem in method for stem in stems) for method in methods)


def check_prompt(name):
    blockers = []
    services = load(name, "service_contracts") or []
    ports = load(name, "persistence_ports") or {}
    components = load(name, "components") or {}
    models = load(name, "data_models") or []
    errors = load(name, "errors") or []
    adapters = load(name, "interaction_adapters") or []
    index = service_index(services)
    all_methods = set().union(*index.values()) if index else set()

    facade = components.get("facade") or {}
    invocation = facade.get("invocation") or {}
    for command, sub in flatten_commands(invocation.get("commands")):
        verb = norm(sub or command)
        stems = VERB_STEMS.get(verb, (verb,))
        if verb and not served_by_stems(stems, all_methods):
            where = f"{command} {sub}" if sub else f"{command}"
            blockers.append(f"command '{where}' has no method")

    for adapter in adapters:
        target = norm(adapter.get("target_service"))
        if target not in index:
            blockers.append(f"adapter -> unknown service '{adapter.get('target_service')}'")
            continue
        method = norm(adapter.get("target_method"))
        if method not in index[target]:
            blockers.append(f"adapter -> method '{adapter.get('target_method')}' not in service")
            continue
        params = {
            norm(p.get("name"))
            for service in services
            if norm(service.get("service_name")) == target
            for m in service.get("methods", [])
            if norm(m.get("name")) == method
            for p in m.get("params", [])
        }
        for field in adapter.get("input_fields", []):
            if norm(field.get("target_param")) not in params:
                blockers.append(
                    f"adapter {adapter.get('action_name')} -> unknown param '{field.get('target_param')}'"
                )

    for entry in components.get("crud_services") or []:
        for op in entry.get("operations", []):
            stems = OP_STEMS.get(op, (norm(op),))
            if not served_by_stems(stems, all_methods):
                blockers.append(f"{entry.get('entity')} op '{op}' has no method")

    fields_by_entity = {
        norm(model.get("name")): {norm(f.get("name")) for f in model.get("fields", [])}
        for model in models
    }
    mapped = {norm(m.get("entity")) for m in ports.get("entity_mappings", [])}
    for repo in ports.get("repositories", []):
        if norm(repo.get("entity")) not in mapped:
            blockers.append(f"repository '{repo.get('entity')}' has no mapping")
    for mapping in ports.get("entity_mappings", []):
        entity = norm(mapping.get("entity"))
        pk = norm(mapping.get("primary_key"))
        if entity in fields_by_entity and pk and pk not in fields_by_entity[entity]:
            blockers.append(f"mapping pk '{mapping.get('primary_key')}' not a field of {mapping.get('entity')}")

    holders = list(services) + list(ports.get("repositories", []))
    for holder in holders:
        owner = holder.get("service_name") or holder.get("interface_name") or holder.get("entity")
        for method in holder.get("methods", []):
            if not (method.get("return_type") or "").strip():
                blockers.append(f"{owner}.{method.get('name')} has no return type")
            for param in method.get("params", []):
                pname = (param.get("name") or "").strip()
                ptype = (param.get("type") or "").strip()
                if not pname or pname.lower() in ("none", "void", ":", "nonetype"):
                    blockers.append(f"{owner}.{method.get('name')} placeholder param name '{pname}'")
                if not ptype:
                    blockers.append(f"{owner}.{method.get('name')}.{pname} has no type")

    registered = {norm(e.get("name")) for e in errors}
    for holder in holders:
        owner = holder.get("service_name") or holder.get("interface_name")
        for method in holder.get("methods", []):
            for raised in method.get("raises") or []:
                if norm(raised) not in registered:
                    blockers.append(f"{owner}.{method.get('name')} raises unregistered '{raised}'")
    return blockers


def main():
    total = 0
    for name in PROMPTS:
        if not os.path.isdir(os.path.join(OUT, name)):
            print(f"{name:10} MISSING OUTPUT")
            continue
        blockers = check_prompt(name)
        total += len(blockers)
        print(f"{name:10} {len(blockers)} blocker(s)")
        for blocker in blockers:
            print(f"           - {blocker}")
    print(f"\nTOTAL generator blockers: {total}")


if __name__ == "__main__":
    main()
