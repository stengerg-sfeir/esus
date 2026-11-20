"""Bind a prompt-derived case to the generated public scenario DSL.

Only invocation names and setup shapes are taken from the extracted documents.
Expected values always come from the case. A case that cannot be bound is a
coverage gap, never a guessed test.
"""

from __future__ import annotations

from kernel.consistency.naming import normalize


def _models(docs):
    return {normalize(model.get("name")): model
            for model in docs.get("models") or []
            if isinstance(model, dict) and model.get("name")}


def _entity_for(alias, models):
    wanted = normalize(alias)
    if wanted in models:
        return models[wanted]["name"]
    # `order_items` should still reach OrderItem when the alias is plural.
    if wanted.endswith("s") and wanted[:-1] in models:
        return models[wanted[:-1]]["name"]
    return None


def _field_name(model, name):
    if not isinstance(model, dict):
        return name
    fields = {normalize(field.get("name")): field.get("name")
              for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")}
    if normalize(name) in fields:
        return fields[normalize(name)]
    if normalize(name) in ("state", "status"):
        for alias in ("state", "status"):
            if alias in fields:
                return fields[alias]
    return name


def _setup(case, docs, models):
    given = case.get("given")
    steps = []
    if isinstance(given, list):
        for item in given:
            if not isinstance(item, dict):
                return None, "given list contains a non-object"
            entity = item.get("entity")
            if entity not in {m.get("name") for m in docs.get("models") or []}:
                return None, f"unknown given entity {entity!r}"
            steps.append({
                "entity": entity,
                "as": item.get("as") or entity,
                "values": item.get("values") or {},
            })
        return steps, None
    if not isinstance(given, dict):
        return None, "given must be a mapping or list"
    for alias, values in given.items():
        if not isinstance(values, dict):
            return None, f"given {alias!r} is not a mapping"
        entity = _entity_for(alias, models)
        if entity is None:
            return None, f"cannot resolve given entity {alias!r}"
        steps.append({"entity": entity, "as": alias, "values": values})
    return steps, None


def _method(docs, case):
    action = normalize(case.get("when", {}).get("action") or "")
    if not action:
        return None, "case has no action"
    service = case.get("when", {}).get("service")
    wanted_service = normalize(service) if service else None
    candidates = []
    for group_key, name_key in (("services", "service_name"),
                                ("repos", "interface_name")):
        for holder in docs.get(group_key) or []:
            if not isinstance(holder, dict):
                continue
            holder_name = holder.get(name_key)
            if wanted_service and normalize(holder_name or "") != wanted_service:
                continue
            for method in holder.get("methods") or []:
                if (isinstance(method, dict)
                        and normalize(method.get("name") or "") == action):
                    candidates.append((holder_name, method))
    if not candidates:
        return None, f"no generated method named {case['when'].get('action')!r}"
    if len(candidates) > 1:
        names = ", ".join(f"{holder}.{method['name']}"
                          for holder, method in candidates[:5])
        return None, f"ambiguous action binding: {names}"
    return candidates[0], None


def _args(case, setup):
    aliases = {step["as"] for step in setup}
    raw = case.get("when", {}).get("args") or []
    if isinstance(raw, dict):
        return raw
    out = []
    for value in raw if isinstance(raw, list) else [raw]:
        if isinstance(value, str) and value in aliases:
            out.append({"ref": value})
            continue
        if isinstance(value, str) and "." in value:
            head, _, _field = value.partition(".")
            if head in aliases:
                out.append({"ref": value})
                continue
        out.append(value)
    return out


def bind_case(case, docs):
    """`(scenario, reason)` for the existing worker scenario DSL."""
    models = _models(docs)
    setup, reason = _setup(case, docs, models)
    if setup is None:
        return None, reason
    bound, reason = _method(docs, case)
    if bound is None:
        return None, reason
    holder, method = bound
    when = {
        "service": holder,
        "method": method.get("name"),
        "args": _args(case, setup),
    }
    expect = {}
    then = case.get("then") or {}
    if isinstance(then.get("state"), dict):
        expect["fields"] = dict(then["state"])
    if isinstance(then.get("rows"), dict):
        expect["rows"] = dict(then["rows"])
    if then.get("error"):
        expect["error"] = str(then["error"])
    return {
        "name": f"oracle:{case.get('id')}",
        "setup": setup,
        "when": when,
        "expect": expect,
    }, None
