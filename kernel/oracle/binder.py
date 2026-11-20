"""Bind a prompt-derived case to the generated public scenario DSL.

Only invocation names and setup shapes are taken from the extracted documents.
Expected values always come from the case. A case that cannot be bound is a
coverage gap, never a guessed test.
"""

from __future__ import annotations

import re

from kernel import codegen
from kernel.consistency.naming import normalize


def _models(docs):
    return {normalize(model.get("name")): model
            for model in docs.get("models") or []
            if isinstance(model, dict) and model.get("name")}


def _entity_for(alias, models):
    wanted = normalize(re.sub(r"_?\d+$", "", str(alias)))
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


def _leaf_paths(components):
    invocation = ((components or {}).get("facade") or {}).get("invocation") or {}
    commands = invocation.get("commands") if isinstance(invocation, dict) else None

    def walk(nodes, prefix=()):
        for node in nodes or []:
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                continue
            path = prefix + tuple(node["name"].split())
            subs = node.get("subcommands")
            if isinstance(subs, list) and subs:
                yield from walk(subs, path)
            else:
                yield path

    return list(walk(commands))


def _cli_path(action, docs):
    words = [normalize(word) for word in str(action or "").split() if word]
    if not words:
        return None
    leaves = _leaf_paths(docs.get("components"))
    exact = [path for path in leaves
             if [normalize(word) for word in path] == words]
    if len(exact) == 1:
        return list(exact[0])
    for length in range(len(words), 0, -1):
        tail = words[-length:]
        suffix = [path for path in leaves
                  if [normalize(word) for word in path[-length:]] == tail]
        if len(suffix) == 1:
            return list(suffix[0])
    return None


def _service_args(raw, setup):
    if isinstance(raw, dict):
        return raw
    values = raw if isinstance(raw, list) else [raw]
    if values and all(isinstance(value, str) and "=" in value
                      for value in values):
        parsed = {}
        for value in values:
            key, _, text = value.partition("=")
            try:
                text = int(text)
            except ValueError:
                try:
                    text = float(text)
                except ValueError:
                    pass
            parsed[key.strip()] = text
        return parsed
    aliases = {step["as"] for step in setup}
    out = []
    for value in values:
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


def _cli_args(raw):
    if isinstance(raw, dict):
        return [f"--{key.replace('_', '-')}={value}" for key, value in raw.items()]
    return [str(value) for value in (raw if isinstance(raw, list) else [raw])]


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


def _action_words(raw):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(raw or ""))
    return {normalize(word) for word in re.split(r"[^A-Za-z0-9]+", text)
            if word and normalize(word) not in (
                "add", "create", "list", "read", "all", "search", "filter",
                "get", "update", "delete", "remove", "the")}


def _method(docs, case):
    raw_action = case.get("when", {}).get("action") or ""
    action = normalize(raw_action)
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
    candidates = _dedupe(candidates)
    if not candidates:
        # The prompt often uses a domain verb (`add_task`, `list_books`) while
        # the generated surface uses CRUD names (`create_task`, `read_all`).
        # This is a naming alias, not a semantic guess: both sides classify to
        # the same CRUD kind and share the action noun.
        kind = codegen.classify_crud(action)
        if kind is not None:
            words = _action_words(raw_action)
            for group_key, name_key in (("services", "service_name"),
                                        ("repos", "interface_name")):
                for holder in docs.get(group_key) or []:
                    if not isinstance(holder, dict):
                        continue
                    holder_name = holder.get(name_key)
                    if wanted_service and normalize(holder_name or "") != wanted_service:
                        continue
                    for method in holder.get("methods") or []:
                        if not isinstance(method, dict):
                            continue
                        if codegen.classify_crud(method.get("name") or "") != kind:
                            continue
                        flat = normalize(str(method.get("name") or "") + " " +
                                         str(holder_name or ""))
                        if words and not any(word in flat for word in words):
                            continue
                        candidates.append((holder_name, method))
        candidates = _dedupe(candidates)
    if not candidates:
        return None, f"no generated method matches {case['when'].get('action')!r}"
    real_services = [item for item in candidates
                     if item[0] and normalize(str(item[0])).endswith("service")]
    if real_services:
        candidates = real_services
    else:
        services = [item for item in candidates
                    if item[0] and any(item[0] == holder.get("service_name")
                                       for holder in docs.get("services") or []
                                       if isinstance(holder, dict))]
        if services:
            candidates = services
    if len(candidates) > 1:
        names = ", ".join(f"{holder}.{method['name']}"
                          for holder, method in candidates[:5])
        return None, f"ambiguous action binding: {names}"
    return candidates[0], None


def _dedupe(candidates):
    seen = set()
    out = []
    for holder, method in candidates:
        key = (holder, method.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append((holder, method))
    return out


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
    case_when = case.get("when") or {}
    cli = case_when.get("cli")
    if isinstance(cli, list) and cli:
        scenario_when = {"cli": [str(item) for item in cli]}
        return _scenario(case, setup, scenario_when), None
    if not case_when.get("action"):
        return None, "case has no action or cli"
    if " " in str(case_when.get("action")):
        path = _cli_path(case_when.get("action"), docs)
        if path is None:
            return None, f"no generated CLI path for {case_when.get('action')!r}"
        scenario_when = {"cli": path + _cli_args(case_when.get("args") or [])}
        return _scenario(case, setup, scenario_when), None
    bound, reason = _method(docs, case)
    if bound is None:
        return None, reason
    holder, method = bound
    when = {
        "service": holder,
        "method": method.get("name"),
        "args": _service_args(case_when.get("args") or [], setup),
    }
    return _scenario(case, setup, when), None


def _scenario(case, setup, when):
    expect = {}
    then = case.get("then") or {}
    if isinstance(then.get("state"), dict):
        expect["fields"] = dict(then["state"])
    if isinstance(then.get("rows"), dict):
        expect["rows"] = dict(then["rows"])
    error = then.get("error")
    if isinstance(error, str) and error.strip().lower() in (
            "", "none", "null", "no error"):
        error = None
    if error:
        expect["error"] = str(error)
    return {
        "name": f"oracle:{case.get('id')}",
        "setup": setup,
        "when": when,
        "expect": expect,
    }
