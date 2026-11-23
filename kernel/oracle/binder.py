"""Bind a prompt-derived case to the generated public scenario DSL.

Only invocation names and setup shapes are taken from the extracted documents.
Expected values always come from the case. A case that cannot be bound is a
coverage gap, never a guessed test.
"""

from __future__ import annotations

import re

from kernel import codegen
from kernel.consistency.naming import normalize

_MISSING = object()


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
    # The prompt may shorten a model name (`Audit` for `AuditLog`). Accept
    # only an unambiguous prefix match; otherwise the alias stays unresolved.
    prefixes = [name for name in models
                if name.startswith(wanted) or wanted.startswith(name)]
    if len(prefixes) == 1:
        return models[prefixes[0]]["name"]
    return None


_FIELD_ALIASES = {
    "phone": ("phone_number", "phonenumber"),
    "phonenumber": ("phone",),
    "stockquantity": ("stock_qty", "quantity"),
    "stockqty": ("stock_quantity", "quantity"),
    "quantity": ("qty", "stock_quantity", "stock_qty"),
    "availability": ("available_status", "available_copies"),
    "availablecopies": ("availability",),
    "category": ("category_id",),
    "title": ("name",),
}


def _field_name(model, name):
    if not isinstance(model, dict):
        return name
    fields = {normalize(field.get("name")): field.get("name")
              for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")}
    wanted = normalize(name)
    if wanted in fields:
        return fields[wanted]
    if wanted in ("state", "status"):
        for alias in ("state", "status"):
            if alias in fields:
                return fields[alias]
    for alias in _FIELD_ALIASES.get(wanted, ()):
        if normalize(alias) in fields:
            return fields[normalize(alias)]
    if wanted == "id":
        keys = [field.get("name") for field in model.get("fields") or []
                if isinstance(field, dict) and field.get("name")
                and field.get("primary_key")]
        if len(keys) == 1:
            return keys[0]
    if wanted + "id" in fields:
        return fields[wanted + "id"]
    return name


_TRUE_WORDS = {"true", "yes", "1", "available", "active", "enabled",
               "completed", "returned"}
_FALSE_WORDS = {"false", "no", "0", "borrowed", "unavailable", "inactive",
                "disabled", "pending", "not available", "not_available"}


def _field_value(model, field_name, value):
    """Coerce a prompt vocabulary value to the declared field type."""
    if not isinstance(model, dict):
        return value
    field = next((item for item in model.get("fields") or []
                  if isinstance(item, dict)
                  and normalize(item.get("name")) == normalize(field_name)), None)
    if field is None:
        return value
    declared = str(field.get("type") or "").lower()
    if declared in ("bool", "boolean") and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_WORDS:
            return True
        if lowered in _FALSE_WORDS:
            return False
    return value


def _normalise_step(step, docs):
    """Use model field spellings and value types inside a setup step."""
    model = next((item for item in docs.get("models") or []
                  if isinstance(item, dict) and item.get("name") == step.get("entity")),
                 None)
    if model is None:
        return step
    values = {}
    for key, value in (step.get("values") or {}).items():
        canonical = _field_name(model, key)
        values[canonical] = _field_value(model, canonical, value)
    step["values"] = values
    return step


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


def _setup_fields(setup):
    """`{normalized field: (alias, value)}` from flat setup rows."""
    fields = {}
    for step in setup:
        alias = step.get("as") or step.get("entity")
        for key, value in (step.get("values") or {}).items():
            if not isinstance(value, dict) or "ref" not in value:
                fields.setdefault(normalize(key), (alias, value))
    return fields


def _has_row_identity(method, args):
    """True when an update/delete call supplies its key or a key reference."""
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if not params:
        return False
    first = normalize(params[0])
    if isinstance(args, dict):
        return any(normalize(key) in ("id", first) for key in args)
    values = args if isinstance(args, list) else [args]
    if not values:
        return False
    for value in values:
        if isinstance(value, dict) and isinstance(value.get("ref"), str)                 and value["ref"].split(".")[-1] in ("id", first):
            return True
        if isinstance(value, str) and "." in value                 and value.split(".")[-1] in ("id", first):
            return True
    if first in ("id", "key") or first.endswith("id"):
        return isinstance(values[0], (int, float)) or (
            isinstance(values[0], str) and values[0].isdigit())
    return False


def _coerce_value(value, declared):
    if not isinstance(value, str) or value.startswith("{"):
        return value
    kind = str(declared or "").lower()
    if any(token in kind for token in ("int", "integer")):
        try:
            return int(value)
        except ValueError:
            return value
    if kind in ("float", "double", "decimal", "money", "number"):
        try:
            return float(value)
        except ValueError:
            return value
    if kind in ("bool", "boolean"):
        if value.strip().lower() in ("true", "false"):
            return value.strip().lower() == "true"
    return value


def _coerce_args(method, args):
    """Literal CLI values are strings in cases; generated methods are typed."""
    params = [param for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    by_name = {normalize(param["name"]): param.get("type") for param in params}
    if isinstance(args, dict):
        return {key: _coerce_value(value, by_name.get(normalize(key)))
                for key, value in args.items()}
    if isinstance(args, list):
        return [_coerce_value(value,
                              params[index].get("type")
                              if index < len(params) else None)
                for index, value in enumerate(args)]
    return args


def _has_soft_delete(model, requirements):
    text = str(requirements or "").lower()
    if "soft delete" not in text and "soft-delete" not in text:
        return False
    fields = {normalize(field.get("name")): field for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")}
    return any(name in fields and str(fields[name].get("type") or "").lower()
               in ("bool", "boolean")
               for name in ("isdeleted", "deleted", "isarchived", "archived"))


def _delete_state_error(case, docs, setup, method, requirements):
    if codegen.classify_crud(method.get("name") or "") != "delete":
        return None
    state = (case.get("then") or {}).get("state")
    if not isinstance(state, dict) or not state:
        return None
    by_alias = {normalize(step.get("as") or ""): step for step in setup}
    for target in state:
        alias, _, _field = str(target).partition(".")
        step = by_alias.get(normalize(alias))
        if step is None:
            continue
        model = next((item for item in docs.get("models") or []
                      if isinstance(item, dict)
                      and item.get("name") == step.get("entity")), None)
        if model is None or _has_soft_delete(model, requirements):
            continue
        return (f"delete case expects state on deleted {model.get('name')}; "
                "a hard-deleted row has no state to read")
    return None


def _complete_id_args(method, args, setup):
    """Fill `<entity>_id` parameters from the matching seeded aliases."""
    aliases = {normalize(step.get("as") or ""): step for step in setup}
    kwargs = {}
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = normalize(param["name"])
        if not name.endswith("id"):
            continue
        base = name[:-2]
        step = aliases.get(base)
        if step is not None:
            kwargs[param["name"]] = {"ref": f"{step.get('as')}.id"}
    if not kwargs:
        return args
    if isinstance(args, dict):
        kwargs.update(args)
        return kwargs
    # If the method only needs IDs, ignore the case's noisy positional values.
    ids = [param for param in method.get("params") or []
           if isinstance(param, dict) and normalize(param.get("name") or "").endswith("id")]
    non_ids = [param for param in method.get("params") or []
               if isinstance(param, dict) and not normalize(param.get("name") or "").endswith("id")]
    if not non_ids and len(kwargs) == len(ids):
        return kwargs
    # `list_books` may say `["author"]`; the method expects `author_id`.
    # A bare alias is a row reference, so use the FK when the method has one.
    bare = [value for value in args if isinstance(value, dict)
            and isinstance(value.get("ref"), str)
            and "." not in value["ref"]]
    if kwargs and bare and len(bare) == len(args):
        return kwargs
    return args


def _scalar(text):
    """A named case value as the scalar it spells, not always a string."""
    if not isinstance(text, str):
        return text
    lowered = text.strip().lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("none", "null"):
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        try:
            return float(text)
        except (TypeError, ValueError):
            return text


def _param_keys(params):
    """Map canonical and common field aliases to a method parameter name."""
    keys = {normalize(name): name for name in params}
    for alias, targets in _FIELD_ALIASES.items():
        target_names = {normalize(target) for target in targets}
        for name in params:
            if normalize(name) in target_names:
                keys.setdefault(alias, name)
    return keys


def _payload_param(method):
    """The mapping/entity parameter an update method uses for changed fields."""
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = normalize(param["name"])
        declared = str(param.get("type") or "").lower()
        if name in ("data", "payload", "values", "changes"):
            return param["name"]
        if "dict" in declared or "mapping" in declared:
            return param["name"]
    return None


def _complete_update_args(method, args, setup):
    """Build update kwargs from the lookup row, setup values and changes.

    Update cases arrive in several shapes: flat positional fields, named
    `field=value` pairs, a `{field: value}` payload, or `field, value` pairs.
    The first method parameter is the row identity; all other values are
    changes. A change is never silently replaced by the seeded value.
    """
    if codegen.classify_crud(method.get("name") or "") != "update":
        return args
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    if not params:
        return args
    param_keys = _param_keys(params)
    setup_fields = _setup_fields(setup)
    setup_values = {value for _alias, value in setup_fields.values()}
    aliases = {normalize(step.get("as") or ""): step for step in setup}
    key_name = params[0]
    payload = _payload_param(method)
    non_key = [name for name in params[1:] if name != payload]
    overrides = {}
    positional = []

    raw = args if isinstance(args, list) else [args]
    if isinstance(args, dict):
        # A mapping argument may already be the method's payload.
        if payload and payload in args:
            value = args.get(payload)
            if isinstance(value, dict):
                raw = [value]
            else:
                raw = []
        elif any(key in args for key in params):
            raw = [args]
        else:
            raw = [args]

    index = 0
    while index < len(raw):
        value = raw[index]
        if isinstance(value, dict):
            for key, item in value.items():
                target = param_keys.get(normalize(key))
                if target and target != key_name and target != payload:
                    overrides[target] = item
                elif key == payload:
                    pass
            index += 1
            continue
        if (isinstance(value, str) and "." in value
                and value.split(".")[0] in aliases):
            # A reference names the lookup row, not a new value.
            index += 1
            continue
        if isinstance(value, str) and "=" in value:
            key, _, text = value.partition("=")
            target = param_keys.get(normalize(key))
            if target and target != key_name and target != payload:
                overrides[target] = _scalar(text)
            index += 1
            continue
        if isinstance(value, str):
            target = param_keys.get(normalize(value))
            if target and target != key_name and target != payload:
                # `field, value`, or `lookup_field, changed_field, value`.
                if index + 1 < len(raw):
                    following = raw[index + 1]
                    following_key = (param_keys.get(normalize(following))
                                     if isinstance(following, str) else None)
                    if following_key and index + 2 < len(raw):
                        new_target = following_key
                        if new_target != key_name and new_target != payload:
                            overrides[new_target] = raw[index + 2]
                        index += 3
                        continue
                    if not following_key:
                        overrides[target] = following
                        index += 2
                        continue
        positional.append(value)
        index += 1

    # A two-value email change (`old@example`, `new@example`) names the
    # lookup field by its current value; the second value is the change.
    if len(positional) == 2 and not overrides:
        first, second = positional
        matches = [name for name, (value_alias, value) in setup_fields.items()
                   if value == first and name not in (normalize(key_name),
                                                      normalize(payload or ""))]
        if len(matches) == 1:
            overrides[param_keys[matches[0]]] = second
            positional = []

    if positional and len(positional) == len(non_key):
        overrides = {name: value for name, value in zip(non_key, positional)}
        positional = []
    if positional:
        # Values equal to the seeded row are lookup data, not changes, unless
        # the positional list described every non-key field above.
        positional = [value for value in positional
                      if value not in setup_values]
        candidates = [name for name in non_key
                      if name not in overrides and name not in setup_fields]
        for value in positional:
            if isinstance(value, str) and "@" in value:
                email = next((name for name in candidates
                              if "email" in normalize(name)), None)
                if email:
                    overrides[email] = value
                    candidates.remove(email)
                    continue
            if candidates:
                target = candidates.pop(0)
                overrides[target] = value

    kwargs = {}
    key_alias = None
    key_base = normalize(key_name)
    if key_base.endswith("id"):
        key_base = key_base[:-2]
    key_alias = aliases.get(key_base) or next(iter(aliases.values()), None)
    if key_alias is not None:
        kwargs[key_name] = {"ref": f"{key_alias.get('as')}.id"}
    elif isinstance(args, dict) and key_name in args:
        kwargs[key_name] = args[key_name]

    for name in non_key:
        key = normalize(name)
        setup_key = key
        if setup_key not in setup_fields:
            setup_key = next((alias for alias, target in param_keys.items()
                              if target == name and alias in setup_fields), "")
        if setup_key in setup_fields:
            kwargs[name] = setup_fields[setup_key][1]
        elif key.endswith("id"):
            step = aliases.get(key[:-2])
            if step is not None:
                kwargs[name] = {"ref": f"{step.get('as')}.id"}
    kwargs.update(overrides)

    if payload:
        if overrides:
            kwargs[payload] = dict(overrides)
        for name in list(kwargs):
            if name != payload and name not in (key_name,):
                kwargs.pop(name, None)
    return kwargs or args


def _changed_update_fields(method, args):
    """The field names an update case actually supplies as changes."""
    if not isinstance(args, dict):
        return set()
    payload = _payload_param(method)
    if payload and isinstance(args.get(payload), dict):
        return {normalize(key) for key in args[payload]}
    key_name = (method.get("params") or [{}])[0].get("name")
    return {normalize(key) for key in args if key != key_name}


def _update_values(method, args):
    """The normalized field/value pairs an update call actually supplies."""
    if not isinstance(args, dict):
        return {}
    payload = _payload_param(method)
    if payload and isinstance(args.get(payload), dict):
        return {normalize(key): value for key, value in args[payload].items()}
    key_name = (method.get("params") or [{}])[0].get("name")
    return {normalize(key): value for key, value in args.items()
            if key != key_name}


def _complete_create_args(method, args, setup):
    """For a create, take its values from the case setup, not from positional noise."""
    if codegen.classify_crud(method.get("name") or "") != "create":
        return args
    fields = _setup_fields(setup)
    params = [param.get("name") for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")]
    param_keys = _param_keys(params)
    kwargs = {}
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = normalize(param["name"])
        setup_key = name
        if setup_key not in fields:
            setup_key = next((alias for alias, target in param_keys.items()
                              if target == param["name"] and alias in fields), "")
        if setup_key in fields:
            kwargs[param["name"]] = fields[setup_key][1]
            continue
        if name.endswith("id"):
            base = name[:-2]
            alias = next((step.get("as") for step in setup
                          if normalize(step.get("as") or "") == base), None)
            if alias:
                kwargs[param["name"]] = {"ref": f"{alias}.id"}
    if isinstance(args, dict):
        for key, value in args.items():
            kwargs.setdefault(key, value)
    return kwargs or args


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
            steps.append(_normalise_step({
                "entity": entity,
                "as": item.get("as") or entity,
                "values": item.get("values") or {},
            }, docs))
        return steps, None
    if not isinstance(given, dict):
        return None, "given must be a mapping or list"
    for alias, values in given.items():
        if not isinstance(values, dict):
            return None, f"given {alias!r} is not a mapping"
        entity = _entity_for(alias, models)
        if entity is None:
            return None, f"cannot resolve given entity {alias!r}"
        steps.append(_normalise_step(
            {"entity": entity, "as": alias, "values": values}, docs))
    return steps, None


def _action_words(raw):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(raw or ""))
    words = []
    for word in re.split(r"[^A-Za-z0-9]+", text):
        token = normalize(word)
        if not token or token in (
                "add", "create", "list", "read", "all", "search", "filter",
                "get", "update", "delete", "remove", "the"):
            continue
        # `list_projects` should match ProjectRepository's `read_all`.
        if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
            token = token[:-1]
        words.append(token)
    return set(words)


def _mark_create_target(case, setup):
    """The given row a create will create, not a row that already exists."""
    action = (case.get("when") or {}).get("action") or ""
    if codegen.classify_crud(action) != "create":
        return None
    words = _action_words(action)
    matches = [step for step in setup
               if normalize(step.get("entity")) in words
               or any(word and word in normalize(step.get("entity"))
                      for word in words)]
    if len(matches) != 1:
        return None
    matches[0]["seed"] = False
    return matches[0]


def _missing_setup(case, docs, setup):
    """A related row a create/update case needs but never seeds."""
    if (case.get("then") or {}).get("error"):
        # An expected error may be exactly the missing relation.
        return None
    by_entity = {normalize(step["entity"]): step for step in setup}
    for step in setup:
        model = next((model for model in docs.get("models") or []
                      if isinstance(model, dict)
                      and normalize(model.get("name")) == normalize(step["entity"])),
                     None)
        if model is None:
            continue
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            value = (step.get("values") or {}).get(field["name"])
            if value is None:
                continue
            foreign = field.get("foreign_key")
            target = (foreign.get("target_entity")
                      if isinstance(foreign, dict) else None)
            if target and normalize(target) not in by_entity:
                return (f"setup needs a {target} row for "
                        f"{step['entity']}.{field['name']}")
            if target and isinstance(value, dict) and "ref" in value:
                head = str(value["ref"]).partition(".")[0]
                if normalize(head) not in {normalize(step["as"]) for step in setup}:
                    return (f"setup reference {value['ref']!r} has no "
                            f"{head} row")
    return None


def _missing_error_rows(case, docs, setup, method):
    """A success case whose method names a missing related row in its raises."""
    if (case.get("then") or {}).get("error"):
        return None
    present = {normalize(step.get("entity")) for step in setup}
    for name in method.get("raises") or []:
        if not isinstance(name, str):
            continue
        flat = normalize(name)
        for model in docs.get("models") or []:
            if not isinstance(model, dict) or not model.get("name"):
                continue
            entity = model["name"]
            if normalize(entity) in present:
                continue
            if normalize(entity) in flat:
                return (f"setup needs a {entity} row required by {name}")
    return None


def _literal_param_error(case, method, kind):
    """Reject a read case that passes a parameter name as its value.

    `search_books("query")` is not a search for the word "query"; it is the
    builder naming the slot instead of supplying a value. The same applies to
    other read/list cases whose arguments are bare parameter identifiers.
    """
    if kind not in ("read_all", "filter", "read_one"):
        return None
    params = {normalize(param.get("name")) for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")}
    raw = (case.get("when") or {}).get("args")
    for value in raw if isinstance(raw, list) else [raw]:
        if not isinstance(value, str) or "." in value or "=" in value:
            continue
        if normalize(value) in params:
            return f"case passes parameter name {value!r} as a literal value"
    return None


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


def _create_value_error(create_target, docs, method, args, holder=None):
    """Reject a create whose case omits a required method field."""
    if not isinstance(args, dict):
        return None
    entity = create_target.get("entity") if create_target else None
    models = [item for item in docs.get("models") or []
              if isinstance(item, dict) and item.get("name")]
    if entity is None:
        returned = normalize(method.get("return_type") or "")
        entity = next((item["name"] for item in models
                       if normalize(item["name"]) in returned
                       and normalize(item["name"]) not in ("none", "void")), None)
    if entity is None and holder:
        base = normalize(holder)
        for suffix in ("repository", "service"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        entity = next((item["name"] for item in models
                       if normalize(item["name"]) == base), None)
    model = next((item for item in models if item["name"] == entity), None)
    if model is None:
        return None
    params = {normalize(param.get("name")) for param in method.get("params") or []
              if isinstance(param, dict) and param.get("name")}
    auto_defaults = {
        "created_at", "created_date", "updated_at", "updated_date",
        "modified_at", "generated_at", "registration_date",
        "membership_date", "joined_date", "is_deleted", "deleted",
        "is_archived", "archived",
    }
    for field in model.get("fields") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = field["name"]
        if (field.get("primary_key") or field.get("nullable") is not False
                or field.get("default") is not None
                or normalize(name) in {normalize(item) for item in auto_defaults}):
            continue
        if normalize(name) in params and name not in args:
            return (f"create case supplies no value for required field "
                    f"{entity}.{name}")
    return None


def _read_result_error(case, kind, setup, models, args):
    """A list case cannot return fewer rows than setup when it changes nothing."""
    if kind not in ("read_all", "filter"):
        return None
    rows = (case.get("then") or {}).get("rows")
    if not isinstance(rows, dict) or args:
        return None
    expected = 0
    counted = set()
    for alias, count in rows.items():
        entity = _entity_for(alias, models) or alias
        expected += int(count)
        counted.add(normalize(entity))
    seeded = sum(1 for step in setup
                 if normalize(step.get("entity")) in counted
                 and step.get("seed") is not False)
    if expected < seeded:
        return ("list case expects fewer rows than its setup but performs "
                "no delete or filter action")
    return None


def _update_value_error(case, docs, models, setup, method, args):
    """Reject an update case that expects a change it never supplies.

    `prompt_14` asked for `description = "An updated description"` while its
    arguments were only references to the seeded row. Executing that case
    compares an update that was never requested; it is a case defect, not a
    generator defect.
    """
    if codegen.classify_crud(method.get("name") or "") != "update":
        return None
    state = (case.get("then") or {}).get("state")
    if not isinstance(state, dict):
        return None
    by_alias = {normalize(step.get("as") or ""): step for step in setup}
    supplied = _update_values(method, args)
    for target, expected in state.items():
        alias, _, field_name = str(target).partition(".")
        if not alias or not field_name:
            continue
        step = by_alias.get(normalize(alias))
        if step is None:
            entity = _entity_for(alias, models)
            step = next((item for item in setup
                         if normalize(item.get("entity") or "") ==
                         normalize(entity or "")), None)
        if step is None:
            continue
        model = next((item for item in docs.get("models") or []
                      if isinstance(item, dict)
                      and item.get("name") == step.get("entity")), None)
        if model is None:
            continue
        canonical = _field_name(model, field_name)
        primary = next((item.get("name") for item in model.get("fields") or []
                        if isinstance(item, dict) and item.get("primary_key")), "id")
        if normalize(canonical) == normalize(primary):
            continue
        values = step.get("values") or {}
        current = values.get(canonical, values.get(field_name))
        if expected == current:
            continue
        value = supplied.get(normalize(canonical),
                             supplied.get(normalize(field_name), _MISSING))
        if value is _MISSING or value == current:
            return (f"update case supplies no new value for {target!r} "
                    f"(setup has {current!r})")
        if value != expected:
            return (f"update case supplies {value!r} for {target!r}, "
                    f"but expects {expected!r}")
    return None


def _state_field_error(case, docs, models):
    state = (case.get("then") or {}).get("state")
    if not isinstance(state, dict):
        return None
    for target in state:
        alias, _, field = str(target).partition(".")
        if not alias or not field:
            continue
        entity = _entity_for(alias, models)
        model = next((item for item in docs.get("models") or []
                      if isinstance(item, dict) and item.get("name") == entity), None)
        if model is None:
            continue
        canonical = _field_name(model, field)
        fields = {normalize(item.get("name")) for item in model.get("fields") or []
                  if isinstance(item, dict) and item.get("name")}
        if (normalize(canonical) not in fields
                and normalize(field) not in ("state", "status")):
            return (f"expected state field {target!r} is not declared on {entity}")
    return None


def bind_case(case, docs):
    """`(scenario, reason)` for the existing worker scenario DSL."""
    models = _models(docs)
    setup, reason = _setup(case, docs, models)
    if setup is None:
        return None, reason
    create_target = _mark_create_target(case, setup)
    missing = _missing_setup(case, docs, setup)
    if missing:
        return None, missing
    state_error = _state_field_error(case, docs, models)
    if state_error:
        return None, state_error
    case_when = case.get("when") or {}
    cli = case_when.get("cli")
    if isinstance(cli, list) and cli:
        scenario_when = {"cli": [str(item) for item in cli]}
        return _scenario(case, setup, scenario_when, models, create_target), None
    if not case_when.get("action"):
        return None, "case has no action or cli"
    if " " in str(case_when.get("action")):
        path = _cli_path(case_when.get("action"), docs)
        if path is None:
            return None, f"no generated CLI path for {case_when.get('action')!r}"
        scenario_when = {"cli": path + _cli_args(case_when.get("args") or [])}
        return _scenario(case, setup, scenario_when, models, create_target), None
    bound, reason = _method(docs, case)
    if bound is None:
        return None, reason
    holder, method = bound
    args = _complete_id_args(
        method, _service_args(case_when.get("args") or [], setup), setup)
    args = _complete_create_args(method, args, setup)
    args = _complete_update_args(method, args, setup)
    args = _coerce_args(method, args)
    missing_row = _missing_error_rows(case, docs, setup, method)
    if missing_row:
        return None, missing_row
    kind = codegen.classify_crud(method.get("name") or "")
    literal_error = _literal_param_error(case, method, kind)
    if literal_error:
        return None, literal_error
    delete_error = _delete_state_error(
        case, docs, setup, method, docs.get("requirements") or "")
    if delete_error:
        return None, delete_error
    if kind in ("update", "delete") and not _has_row_identity(method, args):
        return None, "update/delete case supplies no primary-key argument"
    if kind == "update":
        update_error = _update_value_error(
            case, docs, models, setup, method, args)
        if update_error:
            return None, update_error
    if kind == "create":
        create_error = _create_value_error(
            create_target, docs, method, args, holder)
        if create_error:
            return None, create_error
    read_error = _read_result_error(case, kind, setup, models, args)
    if read_error:
        return None, read_error
    when = {
        "service": holder,
        "method": method.get("name"),
        "args": args,
    }
    rows_as_result = kind in ("read_all", "filter", "read_one")
    return _scenario(case, setup, when, models, create_target,
                     rows_as_result), None


def _scenario(case, setup, when, models=None, create_target=None,
              rows_as_result=False):
    expect = {}
    then = case.get("then") or {}
    if isinstance(then.get("state"), dict):
        fields = dict(then["state"])
        if models:
            canonical = {}
            for target, value in fields.items():
                alias, _, field_name = str(target).partition(".")
                entity = _entity_for(alias, models) if alias else None
                model = models.get(normalize(entity or ""))
                # Keep state/status spelling: the worker already aliases the
                # two at execution time.
                if (model is not None and field_name
                        and normalize(field_name) not in ("state", "status")):
                    field_name = _field_name(model, field_name)
                if model is not None:
                    value = _field_value(model, field_name, value)
                canonical[f"{alias}.{field_name}" if alias else target] = value
            fields = canonical
        expect["fields"] = fields
    if isinstance(then.get("rows"), dict):
        rows = dict(then["rows"])
        if models:
            setup_counts = {}
            for step in setup:
                if step.get("seed") is False:
                    continue
                entity = _entity_for(step.get("entity"), models) or step.get("entity")
                setup_counts[normalize(entity)] = setup_counts.get(
                    normalize(entity), 0) + 1
            canonical = {}
            for alias, count in rows.items():
                entity = _entity_for(alias, models) or alias
                if rows_as_result:
                    # A read/list result count is already the returned count,
                    # not a table delta from setup.
                    canonical[entity] = count
                else:
                    # The model states absolute row counts after the action;
                    # the worker compares deltas from the setup baseline.
                    canonical[entity] = count - setup_counts.get(
                        normalize(entity), 0)
            rows = canonical
        expect["rows"] = rows
    error = then.get("error")
    if isinstance(error, str) and error.strip().lower() in (
            "", "none", "null", "no error"):
        error = None
    if error:
        expect["error"] = str(error)
    scenario = {
        "name": f"oracle:{case.get('id')}",
        "setup": setup,
        "when": when,
        "expect": expect,
    }
    if create_target is not None:
        scenario["result"] = {
            "alias": create_target.get("as"),
            "entity": create_target.get("entity"),
        }
    if rows_as_result and isinstance(expect.get("rows"), dict):
        scenario["rows_as_result"] = True
    return scenario
