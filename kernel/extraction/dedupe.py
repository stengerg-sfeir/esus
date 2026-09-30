"""Deterministic removal of exactly repeated names from a generated document.

The grammars close the *entity* names, but a method name is free text, and GBNF
cannot express "a list of distinct strings": distinctness over an unbounded
alphabet is not a regular property, so no grammar can forbid a repeat. A model
that starts repeating a name therefore keeps going, and only the list-length cap
stops it — which is not a fix, because a cap low enough to cut a loop is also
low enough to truncate a legitimate long list.

So the repeat is removed after generation instead, and only ever the repeat: the
first occurrence of a name is kept exactly as the model wrote it and later
occurrences of the same name in the same list are dropped. Nothing is renamed,
rewritten or invented, so this cannot change what a document says — it removes
entries that say the same thing twice.

Measured cause: cli_tool's ProductRepository listed `order_items` four times and
`orders`, `products`, `getOrderStats` three times each, after nine genuine
methods — the model enumerating the other entities of the names block and never
deciding to stop. Duplicates appeared only there, in one of seven prompts.
"""

def deduplicate(key, body):
    """Drop exact duplicate names from `body`, returning (body, removed count).

    `body` is the parsed document (the value under `key`), or None.
    """
    if key == "service_contracts":
        return _deduplicate_services(body)
    if key == "persistence_ports":
        return _deduplicate_ports(body)
    return body, 0


def _deduplicate_services(services):
    if not isinstance(services, list):
        return services, 0
    removed = 0
    for service in services:
        if not isinstance(service, dict):
            continue
        methods, count = _deduplicate_named(service.get("methods"))
        service["methods"] = methods
        removed += count
    return services, removed


def _deduplicate_ports(ports):
    if not isinstance(ports, dict):
        return ports, 0
    removed = 0
    for repository in ports.get("repositories") or []:
        if not isinstance(repository, dict):
            continue
        methods, count = _deduplicate_named(repository.get("methods"))
        repository["methods"] = methods
        removed += count
    for mapping in ports.get("entity_mappings") or []:
        if not isinstance(mapping, dict):
            continue
        indexes, count = _deduplicate_strings(mapping.get("indexes"))
        mapping["indexes"] = indexes
        removed += count
    return ports, removed


def _deduplicate_named(methods):
    """Remove items whose `name` repeats, keeping the first of each name.

    Each surviving method also has its own duplicate parameter names removed:
    the same free-text repeat can occur one level down.
    """
    if not isinstance(methods, list):
        return methods, 0

    kept = []
    seen = set()
    removed = 0
    for method in methods:
        if not isinstance(method, dict):
            kept.append(method)
            continue
        name = method.get("name")
        if isinstance(name, str):
            key = name.strip().lower()
            if key in seen:
                removed += 1
                continue
            seen.add(key)
        params, count = _deduplicate_params(method.get("params"))
        method["params"] = params
        removed += count
        kept.append(method)
    return kept, removed


def _deduplicate_params(params):
    if not isinstance(params, list):
        return params, 0
    kept = []
    seen = set()
    removed = 0
    for param in params:
        if not isinstance(param, dict):
            kept.append(param)
            continue
        name = param.get("name")
        if isinstance(name, str):
            key = name.strip().lower()
            if key in seen:
                removed += 1
                continue
            seen.add(key)
        kept.append(param)
    return kept, removed


def _deduplicate_strings(values):
    if not isinstance(values, list):
        return values, 0
    kept = []
    seen = set()
    removed = 0
    for value in values:
        if isinstance(value, str):
            key = value.strip().lower()
            if key in seen:
                removed += 1
                continue
            seen.add(key)
        kept.append(value)
    return kept, removed
