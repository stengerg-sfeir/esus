"""Compile a human-confirmed method contract into declarative program steps.

This is deliberately narrower than the LLM body pass.  It accepts only a
closed, scalar contract:

- every entity is read by primary key through a named repository method;
- every create field and every effect operand resolves to a parameter, a
  bound entity field, a literal, or ``today``/``now``;
- no collection read, loop, derived value, export, or arbitrary call is
  present;
- a multi-write method has an explicit order.

The output is the same step vocabulary already emitted by
``generator._program_steps``.  A contract that does not satisfy every rule is
returned with a reason so the caller can keep the existing LLM fallback.
"""

from __future__ import annotations

import ast
import json
import re

from kernel import codegen
from kernel.consistency.naming import normalize


BUILTIN_ERRORS = {"ValueError", "LookupError", "TypeError"}
DATE_TYPES = {"date", "datetime", "timestamp"}
PRIMITIVE_TRUE_FALSE = {"True", "False", "None"}


def _model(ctx, entity):
    wanted = normalize(entity or "")
    for model in ctx.get("models") or []:
        if isinstance(model, dict) and normalize(model.get("name") or "") == wanted:
            return model
    return None


def _fields(ctx, entity):
    model = _model(ctx, entity)
    return [field for field in (model or {}).get("fields") or []
            if isinstance(field, dict) and field.get("name")]


def _field(ctx, entity, name):
    wanted = normalize(name or "")
    for field in _fields(ctx, entity):
        if normalize(field.get("name") or "") == wanted:
            return field
    return None


def _pk(ctx, entity):
    for field in _fields(ctx, entity):
        if field.get("primary_key"):
            return field["name"]
    return "id"


def _repo(ctx, name):
    wanted = normalize(name or "")
    for repo in ctx.get("repositories") or []:
        if not isinstance(repo, dict):
            continue
        if normalize(repo.get("interface_name") or "") == wanted \
                or normalize(repo.get("entity") or "") == wanted:
            return repo
    return None


def _repo_method(ctx, repo_name, method_name):
    repo = _repo(ctx, repo_name)
    if repo is None:
        return None, None
    wanted = normalize(method_name or "")
    for method in repo.get("methods") or []:
        if isinstance(method, dict) and normalize(method.get("name") or "") == wanted:
            return repo, method
    return repo, None


def _param_names(method):
    return [param.get("name") for param in method.get("params") or []
            if isinstance(param, dict) and isinstance(param.get("name"), str)]


def _error_expr(ctx, name):
    if not isinstance(name, str) or not name:
        return None
    if name in BUILTIN_ERRORS:
        return name
    for error in ctx.get("errors") or []:
        if isinstance(error, dict) and error.get("name") == name:
            return f"errors.{codegen.sanitize(name)}"
    return None


def _validate_ref(value, params, bindings, ctx):
    """Resolve one argument/operand reference to a safe Python expression."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value in params:
        return value
    if value.startswith("param:"):
        name = value[6:].strip()
        return name if name in params else None
    if value.startswith("field:"):
        value = value[6:].strip()
    match = re.fullmatch(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)", value)
    if match and match.group(1) in bindings:
        entity = bindings[match.group(1)]["entity"]
        return value if _field(ctx, entity, match.group(2)) else None
    return None


def _value_expr(value, field_type, params, bindings, ctx):
    """Translate a contract value into an expression from the primitive set."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.startswith("param:"):
        name = text[6:].strip()
        return name if name in params else None
    if text.startswith("literal:"):
        literal = text[8:].strip()
        try:
            parsed = json.loads(literal)
        except ValueError:
            parsed = literal
        return repr(parsed)
    if text in ("today", "now"):
        base = "datetime.datetime.now()" if normalize(field_type) in (
            "datetime", "timestamp") else "datetime.date.today()"
        if normalize(field_type) not in DATE_TYPES:
            return None
        return base
    match = re.fullmatch(r"today\+(\d+)d", text)
    if match:
        if normalize(field_type) not in DATE_TYPES:
            return None
        return (f"datetime.date.today() + datetime.timedelta(days={int(match.group(1))})")
    reference = _validate_ref(text, params, bindings, ctx)
    if reference:
        return reference
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return text
    if text in PRIMITIVE_TRUE_FALSE:
        return text
    if (text.startswith("'") and text.endswith("'")) \
            or (text.startswith('"') and text.endswith('"')):
        return text
    return None


def _validate_condition(expression, params, bindings):
    """Whitelist the small check language accepted by the compiler."""
    if not isinstance(expression, str) or not expression.strip():
        return False
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return False
    allowed_names = set(params) | set(bindings) | {"True", "False", "None"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in allowed_names:
                return False
        elif isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id not in bindings:
                return False
        elif isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name)
                    and node.func.id == "getattr"
                    and len(node.args) in (2, 3)
                    and isinstance(node.args[0], ast.Name)
                    and node.args[0].id in bindings
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                return False
            if len(node.args) == 3 and not isinstance(node.args[2], ast.Constant):
                return False
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                               ast.GeneratorExp, ast.Lambda, ast.Subscript,
                               ast.Await, ast.Yield, ast.YieldFrom)):
            return False
    return True


def _binding_steps(contract, method, ctx, params):
    bindings = {}
    steps = []
    for raw in contract.get("bindings") or []:
        if not isinstance(raw, dict):
            return None, "binding is not an object"
        name = raw.get("name")
        repo_name = raw.get("repository")
        method_name = raw.get("method")
        if not (isinstance(name, str) and name and isinstance(repo_name, str)
                and isinstance(method_name, str)):
            return None, "binding needs name, repository and method"
        if name in bindings or name in params:
            return None, f"binding name {name!r} is not unique"
        repo, target = _repo_method(ctx, repo_name, method_name)
        if repo is None or target is None:
            return None, f"unknown repository method {repo_name}.{method_name}"
        args = raw.get("args") or []
        if not isinstance(args, list):
            return None, f"binding {name} has invalid args"
        rendered = []
        for arg in args:
            reference = _validate_ref(arg, params, bindings, ctx)
            if reference is None:
                return None, f"binding {name} has unresolvable arg {arg!r}"
            rendered.append(reference)
        target_params = [p.get("name") for p in target.get("params") or []
                         if isinstance(p, dict) and p.get("name")]
        if len(rendered) != len(target_params):
            return None, f"binding {name} supplies {len(rendered)} args for {len(target_params)} parameters"
        entity = repo.get("entity")
        if not entity or _model(ctx, entity) is None:
            return None, f"binding {name} names no model entity"
        error = raw.get("error")
        error_expr = _error_expr(ctx, error) if error else None
        if error and error_expr is None:
            return None, f"binding {name} names unregistered error {error!r}"
        item = {"name": name, "entity": entity, "repo": repo_name,
                "method": method_name, "args": rendered, "error": error}
        bindings[name] = item
        step = {"op": "read", "repo": repo_name, "method": method_name,
                "args": rendered, "as": name}
        if error:
            step["error"] = error
            step["message"] = f"{name} not found"
        steps.append(step)
    return (bindings, steps), None


def _check_steps(contract, bindings, params, ctx):
    steps = []
    for raw in contract.get("preconditions") or []:
        if not isinstance(raw, dict):
            return None, "precondition is not an object"
        check = raw.get("check")
        if not isinstance(check, str) or not check.strip():
            return None, "precondition has no check"
        error = raw.get("error")
        if error and _error_expr(ctx, error) is None:
            return None, f"precondition names unregistered error {error!r}"
        exists = re.fullmatch(r"([A-Za-z_]\w*)\s+exists", check.strip())
        if exists:
            if exists.group(1) not in bindings:
                return None, f"existence check names unbound {exists.group(1)}"
            continue
        if not _validate_condition(check, params, bindings):
            return None, f"unsupported precondition {check!r}"
        raise_when = raw.get("raise_when")
        if raise_when not in ("true", "false"):
            return None, f"precondition {check!r} has no raise_when"
        condition = check if raise_when == "true" else f"not ({check})"
        steps.append({"op": "check", "condition": condition,
                      "error": error, "message": check})
    return steps, None


def _create_steps(contract, ctx, params, bindings):
    steps = []
    creates = contract.get("creates") or []
    if len(creates) > 1:
        return None, "more than one create is not supported"
    for raw in creates:
        if not isinstance(raw, dict):
            return None, "create is not an object"
        class_name = raw.get("class")
        call = raw.get("call")
        if not isinstance(class_name, str) or not isinstance(call, str):
            return None, "create needs class and call"
        model = _model(ctx, class_name)
        if model is None:
            return None, f"create class {class_name!r} is not a model"
        repo_name, _, method_name = call.partition(".")
        if not repo_name or not method_name:
            return None, f"create call {call!r} is not Dotted.method"
        repo, target = _repo_method(ctx, repo_name, method_name)
        if repo is None or target is None:
            return None, f"unknown create call {call}"
        if normalize(repo.get("entity") or "") != normalize(class_name):
            return None, f"create class {class_name} disagrees with {repo_name}"
        fields = raw.get("fields") or {}
        if not isinstance(fields, dict):
            return None, f"create {class_name} fields are not an object"
        model_fields = {field["name"]: field for field in _fields(ctx, class_name)}
        required = {name for name, field in model_fields.items()
                    if not field.get("primary_key") and not field.get("nullable")}
        missing = sorted(required - set(fields))
        if missing:
            return None, f"create {class_name} misses required field(s): {', '.join(missing)}"
        extra = sorted(set(fields) - set(model_fields))
        if extra:
            return None, f"create {class_name} names unknown field(s): {', '.join(extra)}"
        target_params = {p.get("name") for p in target.get("params") or []
                         if isinstance(p, dict) and p.get("name")}
        rendered = {}
        for field_name, raw_value in fields.items():
            if field_name not in target_params:
                return None, f"create {class_name} field {field_name!r} is not a create parameter"
            expression = _value_expr(raw_value, model_fields[field_name].get("type"),
                                     params, bindings, ctx)
            if expression is None:
                return None, f"create {class_name}.{field_name} has unresolvable value {raw_value!r}"
            rendered[field_name] = expression
        steps.append({"op": "create", "repo": repo_name, "method": method_name,
                      "fields": rendered})
    return steps, None


def _effect_groups(contract, ctx, params, bindings):
    groups = {}
    order = []
    for raw in contract.get("effects") or []:
        if not isinstance(raw, dict):
            return None, "effect is not an object"
        target = raw.get("target")
        op = raw.get("op")
        write = raw.get("write")
        if not isinstance(target, str) or "." not in target:
            return None, "effect target must be Entity.field"
        if op not in ("set", "increment", "decrement"):
            return None, f"unsupported effect op {op!r}"
        if not isinstance(write, str) or "." not in write:
            return None, "effect write must be Repository.method"
        binding_name, field_name = target.split(".", 1)
        if binding_name not in bindings:
            return None, f"effect target {target} is not bound"
        entity = bindings[binding_name]["entity"]
        field = _field(ctx, entity, field_name)
        if field is None:
            return None, f"effect target {target} names no field"
        repo_name, method_name = write.split(".", 1)
        repo, target_method = _repo_method(ctx, repo_name, method_name)
        if repo is None or target_method is None:
            return None, f"unknown update call {write}"
        target_params = {p.get("name") for p in target_method.get("params") or []
                         if isinstance(p, dict) and p.get("name")}
        if field_name not in target_params:
            return None, f"update {write} does not accept {field_name}"
        key = (write, binding_name)
        if key not in groups:
            primary_key = _pk(ctx, entity)
            if primary_key not in target_params:
                return None, f"update {write} has no {primary_key!r} key parameter"
            groups[key] = {"op": "update", "repo": repo_name,
                           "method": method_name, "binding": binding_name,
                           "args": [f"{binding_name}.{primary_key}"],
                           "fields": {}}
            order.append(key)
        value = raw.get("value") if op == "set" else raw.get("by")
        expression = _value_expr(value, field.get("type"), params, bindings, ctx)
        if expression is None:
            return None, f"effect {target} has unresolvable value {value!r}"
        if op == "set":
            groups[key]["fields"][field_name] = expression
        else:
            operator = "+" if op == "increment" else "-"
            groups[key]["fields"][field_name] = (
                f"{binding_name}.{field_name} {operator} {expression}")
    return (groups, order), None


def compile_contract(contract, method, ctx):
    """`(program, reason)` for a closed contract, or `(None, reason)`."""
    if not isinstance(contract, dict) or not contract:
        return None, "no contract"
    if contract.get("reads") or contract.get("derives"):
        return None, "contract has reads/derives outside the scalar graph"
    if normalize(method.get("return_type") or "") not in ("none", "nonetype", "void", ""):
        return None, "closed compiler only emits None-returning methods"
    params = _param_names(method)
    bindings_result, reason = _binding_steps(contract, method, ctx, params)
    if bindings_result is None:
        return None, reason
    bindings, read_steps = bindings_result
    if not read_steps:
        return None, "contract has no entity bindings"
    checks_result, reason = _check_steps(contract, bindings, params, ctx)
    if checks_result is None:
        return None, reason
    checks = checks_result
    creates_result, reason = _create_steps(contract, ctx, params, bindings)
    if creates_result is None:
        return None, reason
    creates = creates_result
    groups_result, reason = _effect_groups(contract, ctx, params, bindings)
    if groups_result is None:
        return None, reason
    groups, group_order = groups_result
    if not creates and not groups:
        return None, "contract has no writes"
    if not all(_error_expr(ctx, item.get("error")) or item.get("error") in BUILTIN_ERRORS
               for item in contract.get("preconditions") or []
               if isinstance(item, dict) and item.get("error")):
        return None, "contract preconditions name unregistered errors"

    write_names = {}
    if checks:
        write_names["preconditions"] = checks
    for key, group in groups.items():
        name = f"{group['repo']}.{group['method']}"
        if name in write_names:
            return None, f"two bindings share write step {name}"
        write_names[name] = [group]
    if creates:
        create = creates[0]
        create_name = f"{create['repo']}.{create['method']}"
        if create_name in write_names:
            return None, f"create step {create_name} collides with an effect"
        write_names[create_name] = [create]

    supplied_order = [step for step in (contract.get("order") or [])
                      if isinstance(step, str) and step]
    write_steps = len(groups) + (1 if creates else 0)
    if write_steps > 1 and not supplied_order:
        return None, "multiple writes need an explicit order"
    if supplied_order:
        effective_order = [step for step in supplied_order
                           if step != "preconditions" or checks]
        unknown = [step for step in effective_order if step not in write_names]
        if unknown:
            return None, f"order names unknown step(s): {', '.join(unknown)}"
        if len(effective_order) != len(write_names):
            return None, "order does not list every write exactly once"
        ordered = []
        for step in effective_order:
            ordered.extend(write_names[step])
    else:
        ordered = []
        for step in ("preconditions",):
            if step in write_names:
                ordered.extend(write_names[step])
        if creates:
            ordered.extend(creates)
        for key in group_order:
            ordered.append(groups[key])

    steps = list(read_steps)
    steps.extend(ordered)
    return {"steps": steps}, "closed scalar contract"
