"""Mechanical fixture planning for a prompt-derived test intent.

The planner fills only the setup structure the intent does not care about:
types, uniqueness, required nullable fields and foreign-key parents. Values the
assertion depends on come from the intent. A missing parent that the prompt
does not mention is created as a *synthetic* fixture and recorded in the plan
diagnostics; it never changes the expected outcome.

The output is a case-shaped object that the existing binder and runtime worker
already understand. No generated code is imported here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kernel import codegen
from kernel.consistency.naming import normalize
from kernel.oracle import alignment, cases

_AUTO_FIELDS = frozenset(normalize(name) for name in {
    "created_at", "created_date", "updated_at", "updated_date",
    "modified_at", "generated_at", "registration_date", "membership_date",
    "joined_date", "is_deleted", "deleted", "is_archived", "archived",
})
_FIELD_ALIASES = {
    "phone": ("phone_number", "phonenumber"),
    "phonenumber": ("phone",),
    "stockquantity": ("stock_qty", "quantity"),
    "stockqty": ("stock_quantity", "quantity"),
    "quantity": ("qty", "stock_quantity", "stock_qty"),
    "availability": ("available_status", "available_copies"),
    "available": ("available_status", "available_copies", "is_available"),
    "isavailable": ("available_status", "available_copies"),
    "maxcapacity": ("maximum_capacity",),
    "maximumcapacity": ("max_capacity",),
    "totalstock": ("stock_quantity",),
    "createdat": ("creation_date", "created_date", "date_created"),
    "creationdate": ("created_at", "created_date", "date_created"),
    "category": ("category_id",),
    "title": ("name",),
}


class PlanError(ValueError):
    """The intent cannot be planned without inventing required semantics."""


@dataclass
class Plan:
    case: dict
    diagnostics: dict = field(default_factory=dict)


def _models(docs):
    return [model for model in docs.get("models") or []
            if isinstance(model, dict) and model.get("name")]


def _has_methods(docs):
    for key in ("services", "repos"):
        for holder in docs.get(key) or []:
            if isinstance(holder, dict) and holder.get("methods"):
                return True
    return False


def _method_for_action(docs, canonical):
    if not canonical or "." not in canonical:
        return None
    wanted = canonical.rsplit(".", 1)[-1]
    for key in ("services", "repos"):
        for holder in docs.get(key) or []:
            if not isinstance(holder, dict):
                continue
            for method in holder.get("methods") or []:
                if isinstance(method, dict) and method.get("name") == wanted:
                    return method
    return None


def _model(docs, name):
    return next((model for model in _models(docs)
                 if normalize(model.get("name")) == normalize(name)), None)


def _model_for_parameter(docs, base):
    model = _model(docs, base)
    if model is not None:
        return model
    if base.endswith("s") and len(base) > 3:
        return _model(docs, base[:-1])
    return None


def _fields(model):
    return {normalize(field.get("name")): field
            for field in model.get("fields") or []
            if isinstance(field, dict) and field.get("name")}


def _field(model, name):
    fields = _fields(model)
    wanted = normalize(name)
    if wanted in fields:
        return fields[wanted]
    for alias in _FIELD_ALIASES.get(wanted, ()):
        if normalize(alias) in fields:
            return fields[normalize(alias)]
    if wanted == "id":
        keys = [field for field in fields.values() if field.get("primary_key")]
        if len(keys) == 1:
            return keys[0]
    if wanted + "id" in fields:
        return fields[wanted + "id"]
    return None


def _canonical_field(model, name):
    found = _field(model, name)
    if found is None:
        raise PlanError(f"field {name!r} is not declared on {model.get('name')}")
    return found["name"]


def _canonical_ref_field(model, field_name, alias):
    found = _field(model, field_name)
    if found is not None:
        return found["name"]
    if normalize(field_name) in ("id", normalize(alias),
                                 normalize(alias) + "id"):
        return _primary_key(model)
    raise PlanError(
        f"reference field {field_name!r} is not declared on {model.get('name')}")


def _primary_key(model):
    found = next((field.get("name") for field in model.get("fields") or []
                  if isinstance(field, dict) and field.get("primary_key")), None)
    return found or "id"


def _foreign(field):
    value = field.get("foreign_key")
    if not isinstance(value, dict):
        return None
    target = value.get("target_entity")
    if not target:
        return None
    return target, value.get("target_field") or "id"


def _required(field):
    return (field.get("nullable") is False
            and not field.get("primary_key")
            and field.get("default") is None
            and normalize(field.get("name")) not in _AUTO_FIELDS)


def _type_compatible(field, value):
    kind = str(field.get("type") or "").lower()
    if "int" in kind:
        return (isinstance(value, int) and not isinstance(value, bool)) or (
            isinstance(value, str) and value.lstrip("-").isdigit())
    if any(token in kind for token in ("float", "double", "decimal", "money")):
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False
    if "bool" in kind:
        return isinstance(value, bool)
    return True


def _sample(field, alias):
    name = normalize(field.get("name"))
    kind = str(field.get("type") or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(alias)).strip("-") or "row"
    if "email" in name:
        return f"{slug}@example.test"
    if name in ("sku", "code", "isbn", "reference", "reference_code"):
        return f"{slug.upper()}-1"
    if name in ("name", "full_name", "title"):
        return f"{slug} name"
    if "phone" in name:
        return "555-0100"
    if "description" in name or name in ("notes", "comment"):
        return f"{slug} description"
    if name in ("status", "state"):
        return "active"
    if kind in ("int", "integer"):
        return 1
    if kind in ("float", "double", "decimal", "money", "number"):
        return 10.0
    if kind in ("bool", "boolean"):
        return False
    if kind in ("date",):
        return "2024-01-01"
    if kind in ("datetime", "timestamp"):
        return "2024-01-01T00:00:00"
    if kind in ("list", "array"):
        return []
    if kind in ("dict", "mapping"):
        return {}
    return f"{slug} value"


def _split_ref(value):
    if not isinstance(value, str) or "." not in value:
        return None
    head, _, tail = value.partition(".")
    if not head or not tail:
        return None
    return head, tail


def _align_entity(entity, fields, intent, docs, requirements):
    result = alignment.align_entity(
        entity, fields, intent.get("source") or "", requirements, docs)
    if result.status not in ("aligned", "alias") or not result.canonical:
        raise PlanError(
            f"entity {entity!r} is {result.status}; cannot plan a fixture")
    return result.canonical


def _unique_alias(base, used):
    candidate = re.sub(r"[^a-z0-9_]+", "_", normalize(base)) or "row"
    if candidate not in used:
        return candidate
    number = 2
    while f"{candidate}_{number}" in used:
        number += 1
    return f"{candidate}_{number}"


def _canonicalize_aliases(intent, pairs, setup_values, requirements):
    """Use the extracted entity name when the intent alias is not in the prompt."""
    renames = {}
    used = set()
    for alias, item in pairs.items():
        canonical = item["entity"]
        new_alias = alias
        if not cases._entity_named(alias, requirements):
            base = normalize(canonical) or alias
            new_alias = base
            number = 2
            while new_alias in used:
                new_alias = f"{base}_{number}"
                number += 1
        used.add(new_alias)
        renames[alias] = new_alias
    if all(alias == new_alias for alias, new_alias in renames.items()):
        return intent, pairs, setup_values

    def rename_key(value):
        if not isinstance(value, str) or "." not in value:
            return value
        head, _, rest = value.partition(".")
        return f"{renames.get(head, head)}.{rest}"

    def rename_value(value):
        if isinstance(value, str) and "." in value:
            head = value.split(".", 1)[0]
            if head in renames:
                return f"{renames[head]}.{value.split('.', 1)[1]}"
        return value

    updated = dict(intent)
    updated["args"] = [rename_value(value) for value in intent.get("args") or []]
    updated["lookup"] = [rename_value(value) for value in intent.get("lookup") or []]
    for section in ("setup_values", "changes"):
        updated[section] = {
            rename_key(key): value
            for key, value in (intent.get(section) or {}).items()
        }
    updated["where"] = {
        rename_key(key): rename_value(value)
        for key, value in (intent.get("where") or {}).items()
    }
    expect = dict(intent.get("expect") or {})
    if isinstance(expect.get("state"), dict):
        expect["state"] = {
            rename_key(key): value
            for key, value in expect["state"].items()
        }
    updated["expect"] = expect
    updated["setup_entities"] = [
        {**step, "alias": renames.get(step.get("alias"), step.get("alias"))}
        for step in intent.get("setup_entities") or []
        if isinstance(step, dict)
    ]
    new_pairs = {
        renames[alias]: item for alias, item in pairs.items()
    }
    new_setup_values = {
        renames[alias]: values for alias, values in setup_values.items()
    }
    return updated, new_pairs, new_setup_values


def _target_alias(intent, pairs):
    wanted = normalize(intent.get("entity") or "")
    matches = [alias for alias, item in pairs.items()
               if normalize(item["entity"]) == wanted]
    if len(matches) == 1:
        return matches[0]
    targets = [alias for alias, item in pairs.items()
               if item.get("role") == "target"]
    if len(targets) == 1:
        return targets[0]
    return next(iter(pairs), None)


def _case_when(intent, target_alias, aliases):
    if intent.get("kind") == "app":
        app = intent.get("app") or {}
        return {
            "app": True,
            "args": [str(value) for value in app.get("args") or []],
            "stdin": app.get("stdin") or "",
            **({"files": app["files"]} if isinstance(app.get("files"), dict)
               and app["files"] else {}),
        }
    if intent.get("kind") == "cli" and intent.get("cli"):
        return {"cli": [str(value) for value in intent["cli"]]}

    def ref(value):
        split = _split_ref(value)
        if split and split[0] in aliases:
            return {"ref": value}
        return value

    raw_args = [ref(value) for value in intent.get("args") or []]
    changes = {}
    for target, value in (intent.get("changes") or {}).items():
        head, _, field_name = str(target).partition(".")
        if head == target_alias:
            changes[field_name] = value
    where = {}
    for target, value in (intent.get("where") or {}).items():
        head, _, field_name = str(target).partition(".")
        if head == target_alias:
            where[field_name] = value
    if where and intent.get("kind") in ("list", "aggregate"):
        args = where
    elif changes and codegen.classify_crud(intent.get("action") or "") in (
            "create", "update"):
        args = changes
    else:
        args = raw_args
    return {"action": intent.get("action"), "args": args}


def _case_then(intent):
    expect = intent.get("expect") or {}
    then = {}
    for key in ("state", "rows", "stdout_contains", "exit_code"):
        if key in expect and expect[key] is not None:
            then[key] = expect[key]
    if expect.get("error") not in (None, "", "none", "null"):
        then["error"] = expect["error"]
    return then


def plan_case(intent, docs, requirements=""):
    """Plan one intent into a case-shaped fixture; raise `PlanError` if unsafe."""
    if intent.get("kind") == "app":
        case = {
            "id": intent["id"],
            "source": intent["source"],
            "given": {},
            "when": _case_when(intent, None, {}),
            "then": _case_then(intent),
            "status": intent.get("status") or "assumed",
            "assumptions": list(intent.get("assumptions") or []),
            "ambiguities": list(intent.get("ambiguities") or []),
        }
        return Plan(case, {"synthetic": [], "aliases": {}})

    if not _models(docs):
        raise PlanError("no extracted models are available")

    setup_values = {}
    for target, value in (intent.get("setup_values") or {}).items():
        head, _, field_name = str(target).partition(".")
        if not head or not field_name:
            raise PlanError(f"setup value {target!r} is not alias.field")
        setup_values.setdefault(head, {})[field_name] = value

    pairs = {}
    for step in intent.get("setup_entities") or []:
        alias = step.get("alias")
        entity = step.get("entity")
        if not alias or not entity:
            raise PlanError("setup entity needs alias and entity")
        fields = list((setup_values.get(alias) or {}).keys())
        canonical = _align_entity(entity, fields, intent, docs, requirements)
        pairs[alias] = {"entity": canonical, "role": step.get("role") or "setup"}
    if not pairs:
        entity = intent.get("entity")
        if not entity:
            raise PlanError("domain intent has no setup entity")
        alias = _unique_alias(entity, set())
        canonical = _align_entity(entity, [], intent, docs, requirements)
        pairs[alias] = {"entity": canonical, "role": "target"}
    intent, pairs, setup_values = _canonicalize_aliases(
        intent, pairs, setup_values, requirements)
    target_alias = _target_alias(intent, pairs)
    if target_alias is None:
        raise PlanError("intent target entity is not in setup_entities")
    for alias in setup_values:
        if alias not in pairs:
            raise PlanError(f"setup_values references unknown alias {alias!r}")

    action_result = alignment.align_action(
        intent.get("action") or "", intent.get("source") or "",
        requirements, docs)
    if _has_methods(docs) and action_result.status not in ("aligned", "alias"):
        raise PlanError(
            f"action {intent.get('action')!r} is {action_result.status}: "
            f"{'; '.join(action_result.evidence)}")

    # Prompt spelling and method spelling are allowed to differ, but the
    # fixture must use actual model field names so the worker can resolve
    # setup references and assert state. Auxiliary lookup/filter fields that
    # the model invented and the prompt never names are removed; an unnamed
    # identity reference falls back to the target primary key.
    requirement_text = normalize(requirements)

    def _model_for_alias(alias):
        if alias not in pairs:
            raise PlanError(f"reference alias {alias!r} is not in setup")
        model = _model(docs, pairs[alias]["entity"])
        if model is None:
            raise PlanError(f"model {pairs[alias]['entity']!r} is not extracted")
        return model

    def _field_mentioned(field_name):
        wanted = normalize(field_name)
        return bool(wanted) and wanted in requirement_text

    def _canonical_key(value, auxiliary=False):
        head, _, field_name = str(value).partition(".")
        model = _model_for_alias(head)
        if _field(model, field_name) is not None:
            return f"{head}.{_canonical_ref_field(model, field_name, head)}"
        if auxiliary and not _field_mentioned(field_name):
            return f"{head}.{_primary_key(model)}"
        return f"{head}.{_canonical_ref_field(model, field_name, head)}"

    def _rewrite_arg(value):
        if not isinstance(value, str) or "." not in value:
            return value
        head = value.split(".", 1)[0]
        if head not in pairs:
            return value
        return _canonical_key(value, auxiliary=True)

    intent = dict(intent)
    intent["args"] = [_rewrite_arg(value) for value in intent.get("args") or []]
    lookup = []
    for value in intent.get("lookup") or []:
        if isinstance(value, str) and "." in value:
            head, _, field_name = value.partition(".")
            if head in pairs and _field(_model_for_alias(head), field_name) is None \
                    and not _field_mentioned(field_name):
                continue
        lookup.append(_rewrite_arg(value))
    intent["lookup"] = lookup
    for section in ("setup_values", "changes"):
        rewritten = {}
        for target, value in (intent.get(section) or {}).items():
            rewritten[_canonical_key(target)] = value
        intent[section] = rewritten
    where = {}
    for target, value in (intent.get("where") or {}).items():
        head, _, field_name = str(target).partition(".")
        if head not in pairs:
            raise PlanError(f"reference {target!r} has no setup alias")
        model = _model_for_alias(head)
        if _field(model, field_name) is None:
            if _field_mentioned(field_name):
                raise PlanError(
                    f"filter field {field_name!r} is named by the prompt but "
                    f"not declared on {model.get('name')}")
            continue
        key = _canonical_key(target)
        if isinstance(value, str) and "." in value \
                and value.split(".", 1)[0] in pairs:
            value = {"ref": _canonical_key(value)}
        where[key] = value
    intent["where"] = where
    expect = dict(intent.get("expect") or {})
    if isinstance(expect.get("state"), dict):
        expect["state"] = {
            _canonical_key(target): value
            for target, value in expect["state"].items()
        }
    intent["expect"] = expect
    setup_values = {}
    for target, value in intent["setup_values"].items():
        head, _, field_name = target.partition(".")
        setup_values.setdefault(head, {})[field_name] = value
    for alias, values in setup_values.items():
        model = _model(docs, pairs[alias]["entity"])
        for field_name, value in values.items():
            field = _field(model, field_name)
            if field is not None and field.get("primary_key") \
                    and not _type_compatible(field, value):
                raise PlanError(
                    f"primary key {alias}.{field_name} value {value!r} does "
                    f"not match type {field.get('type')!r}")
    for target, value in (intent["expect"].get("state") or {}).items():
        alias, _, field_name = target.partition(".")
        if alias not in pairs:
            continue
        field = _field(_model(docs, pairs[alias]["entity"]), field_name)
        if field is not None and field.get("primary_key") \
                and not _type_compatible(field, value):
            raise PlanError(
                f"expected primary key {target}={value!r} does not match "
                f"type {field.get('type')!r}")

    planned = {}
    order = []
    visiting = set()
    diagnostics = {"synthetic": [], "aliases": {
        alias: item["entity"] for alias, item in pairs.items()
    }}

    def alias_for(entity):
        wanted = normalize(entity)
        return next((alias for alias, item in pairs.items()
                     if normalize(item["entity"]) == wanted), None)

    # A service operation often needs one related row per `*_id` parameter,
    # while the intent names only the row its assertion is about. Fill that
    # setup graph mechanically, but record every synthetic row.
    method = _method_for_action(
        docs, action_result.canonical if action_result else None)
    if intent.get("kind") in ("list", "filter", "aggregate") \
            and ("page" in normalize(intent.get("source"))
                 or "paginat" in normalize(intent.get("source"))):
        params = {normalize(param.get("name")) for param in
                  (method or {}).get("params") or []
                  if isinstance(param, dict) and param.get("name")}
        if not params & {"page", "pagesize", "perpage", "limit", "offset"}:
            raise PlanError(
                "clause requires pagination but the generated method has no "
                "page/page_size/limit/offset parameter")
    for param in (method or {}).get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = normalize(param["name"])
        if not name.endswith("id") or name == "id":
            continue
        base = name[:-2]
        model = _model_for_parameter(docs, base)
        if model is None or alias_for(model["name"]) is not None:
            continue
        error_name = normalize(
            (intent.get("expect") or {}).get("error") or "")
        if error_name and normalize(base) in error_name:
            # The missing row is the expected rejection, not setup to fill.
            continue
        alias = _unique_alias(base, set(pairs))
        pairs[alias] = {"entity": model["name"], "role": "synthetic-parameter"}
        diagnostics["synthetic"].append({
            "alias": alias,
            "entity": model["name"],
            "reason": f"required parameter {param['name']}",
        })
        diagnostics["aliases"][alias] = model["name"]

    used_entities = set()
    for param in (method or {}).get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = normalize(param["name"])
        base = ""
        if name.endswith("ids") and len(name) > 3:
            base = name[:-3]
        elif name.endswith("id") and len(name) > 2:
            base = name[:-2]
        model = _model_for_parameter(docs, base) if base else None
        if model is not None:
            used_entities.add(model["name"])
    target_used = None
    target_entity = pairs[target_alias]["entity"]
    if used_entities:
        target_used = target_entity in used_entities
    diagnostics["target_usage"] = {
        "entity": target_entity,
        "used_entities": sorted(used_entities),
        "used": target_used,
    }
    target_ambiguity = None
    if target_used is False:
        target_ambiguity = (
            f"target entity {target_entity} is not used by the action; "
            f"the action uses {', '.join(sorted(used_entities))}")

    def ensure(alias):
        if alias in planned:
            return
        if alias in visiting:
            raise PlanError(f"cyclic required foreign keys at {alias!r}")
        item = pairs.get(alias)
        if item is None:
            raise PlanError(f"unknown setup alias {alias!r}")
        model = _model(docs, item["entity"])
        if model is None:
            raise PlanError(f"model {item['entity']!r} is not extracted")
        visiting.add(alias)
        values = {}
        for name, value in (setup_values.get(alias) or {}).items():
            values[_canonical_field(model, name)] = value

        # Parents must exist before the child row is seeded.
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            foreign = _foreign(field)
            if foreign is None:
                continue
            parent_entity, target_field = foreign
            if field["name"] in values:
                continue
            parent_alias = alias_for(parent_entity)
            if parent_alias is None:
                if field.get("nullable") is not False:
                    continue
                parent_alias = _unique_alias(parent_entity, set(pairs))
                pairs[parent_alias] = {
                    "entity": parent_entity,
                    "role": "synthetic",
                }
                diagnostics["synthetic"].append({
                    "alias": parent_alias,
                    "entity": parent_entity,
                    "reason": f"required {model['name']}.{field['name']}",
                })
            if parent_alias == alias:
                raise PlanError(
                    f"self-referential required foreign key {model['name']}."
                    f"{field['name']}")
            ensure(parent_alias)
            target = _model(docs, parent_entity)
            target_name = (target_field if target is not None
                           and _field(target, target_field) is not None
                           else _primary_key(target) if target is not None else "id")
            values[field["name"]] = {"ref": f"{parent_alias}.{target_name}"}

        expect_state = (intent.get("expect") or {}).get("state")
        create_changes = (intent.get("changes") or {}) \
            if intent.get("kind") == "create" and alias == target_alias else {}
        for target, value in create_changes.items():
            head, _, field_name = str(target).partition(".")
            if head == alias:
                values.setdefault(_canonical_field(model, field_name), value)
        if isinstance(expect_state, dict) and intent.get("kind") == "create" \
                and alias == target_alias:
            for target, value in expect_state.items():
                head, _, field_name = str(target).partition(".")
                if head == alias:
                    values.setdefault(_canonical_field(model, field_name), value)

        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            name = field["name"]
            if name in values or field.get("primary_key") \
                    or field.get("default") is not None:
                continue
            if field.get("nullable") is not False:
                continue
            if normalize(name) in _AUTO_FIELDS:
                continue
            values[name] = _sample(field, alias)

        planned[alias] = {
            "entity": model["name"],
            "as": alias,
            "values": values,
        }
        order.append(alias)
        visiting.remove(alias)

    for alias in list(pairs):
        ensure(alias)
    for alias in setup_values:
        ensure(alias)

    # A list/filter assertion is a returned row count. If the intent names
    # fewer setup rows than the expected result, replicate mechanically; never
    # invent the expected count.
    replicated = []
    if intent.get("kind") in ("list", "filter"):
        for row_key, count in ((intent.get("expect") or {}).get("rows") or {}).items():
            try:
                wanted = int(count)
            except (TypeError, ValueError):
                continue
            model = _model(docs, row_key)
            if model is None:
                continue
            existing = [alias for alias in order
                        if normalize(planned[alias]["entity"]) ==
                        normalize(model["name"])]
            if not existing:
                continue
            template = planned[existing[0]]
            while len(existing) < wanted:
                alias = _unique_alias(
                    f"{model['name']}_{len(existing) + 1}", set(planned))
                values = {}
                for field in model.get("fields") or []:
                    if not isinstance(field, dict) or not field.get("name"):
                        continue
                    name = field["name"]
                    if field.get("primary_key") or field.get("default") is not None:
                        continue
                    foreign = _foreign(field)
                    if foreign is not None:
                        parent = next(
                            (value for key, value in template["values"].items()
                             if normalize(key) == normalize(name)), None)
                        if isinstance(parent, dict) and "ref" in parent:
                            values[name] = parent
                        continue
                    if field.get("nullable") is not False:
                        continue
                    if normalize(name) in _AUTO_FIELDS:
                        continue
                    values[name] = _sample(field, alias)
                planned[alias] = {
                    "entity": model["name"],
                    "as": alias,
                    "values": values,
                }
                order.append(alias)
                existing.append(alias)
                replicated.append(alias)
    if replicated:
        diagnostics["replicated_rows"] = replicated

    given = {alias: dict(planned[alias]["values"]) for alias in order}
    ambiguities = list(intent.get("ambiguities") or [])
    status = intent.get("status") or "assumed"
    if target_ambiguity:
        ambiguities.append(target_ambiguity)
        if status == "confirmed":
            status = "assumed"
    if replicated and status == "confirmed":
        status = "assumed"
        ambiguities.append(
            "expected row count exceeds the named setup; extra rows were "
            "added mechanically to exercise the list result")
    case = {
        "id": intent["id"],
        "source": intent["source"],
        "given": given,
        "when": _case_when(intent, target_alias, set(given)),
        "then": _case_then(intent),
        "status": status,
        "assumptions": list(intent.get("assumptions") or []),
        "ambiguities": ambiguities,
    }
    return Plan(case, diagnostics)
