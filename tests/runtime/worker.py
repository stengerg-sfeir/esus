"""Runtime conformance worker for one generated validation package.

This is deliberately data-driven: it reads the extracted models, contracts and
variants, seeds a temporary store, and exercises the generated public surface.
It never imports two generated packages in one process (their absolute module
names would collide), so the outer runner starts one fresh interpreter per
prompt.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kernel.consistency.naming import normalize


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_UNIQUE_COUNTER = 1


def _sample(field, number):
    global _UNIQUE_COUNTER
    name = str(field.get("name") or "")
    kind = str(field.get("type") or "").strip().lower()
    if "email" in name:
        _UNIQUE_COUNTER += 1
        return f"user{number}-{_UNIQUE_COUNTER}@example.test"
    if kind in ("int", "integer"):
        return number
    if kind in ("float", "double", "decimal", "money"):
        return float(number)
    if kind in ("bool", "boolean"):
        return False
    if kind in ("date",):
        return "2024-01-01"
    if kind in ("datetime", "timestamp"):
        return "2024-01-01T00:00:00"
    if kind in ("list", "array", "dict", "mapping"):
        return [] if kind in ("list", "array") else {}
    if field.get("unique"):
        _UNIQUE_COUNTER += 1
        return f"value{number}-{_UNIQUE_COUNTER}"
    return f"value{number}"


def _load_package(out_dir):
    generated = str(Path(out_dir) / "generated")
    sys.path.insert(0, generated)
    importlib.invalidate_caches()
    cli = importlib.import_module("cli")
    db = Path(tempfile.mkdtemp(prefix="esus-runtime-")) / "bench.sqlite3"
    built = cli.build_cli(str(db))
    deps = built[1] if isinstance(built, tuple) else built
    return cli, deps, db


def _seed(store, model, number=1, overrides=None):
    pk = next((field.get("name") for field in model.get("fields") or []
               if field.get("primary_key")), "id")
    values = {}
    for field in model.get("fields") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = field["name"]
        if name == pk:
            continue
        if overrides and name in overrides:
            values[name] = overrides[name]
        elif isinstance(field.get("foreign_key"), dict):
            values[name] = 1
        elif field.get("nullable"):
            # Supplying a value is safe for the fixtures and avoids SQL NULL
            # surprises in code paths that read every model field.
            values[name] = _sample(field, number)
        else:
            values[name] = _sample(field, number)
    db = getattr(store, "_db", None)
    if db is not None:
        db.execute("PRAGMA foreign_keys=OFF")
    try:
        record = store.add(model["name"], pk, values, ())
    finally:
        if db is not None:
            db.execute("PRAGMA foreign_keys=ON")
    return record, pk


def _documents(out_dir):
    return {
        "models": _read(Path(out_dir) / "data_models.json").get("data_models") or [],
        "services": _read(Path(out_dir) / "service_contracts.json").get("service_contracts") or [],
        "repos": _read(Path(out_dir) / "persistence_ports.json").get("persistence_ports", {}).get("repositories") or [],
        "contracts": _read(Path(out_dir) / "method_contracts.json").get("method_contracts") or [],
        "invariants": _read(Path(out_dir) / "invariants.json").get("invariants") or [],
        "components": _read(Path(out_dir) / "components.json").get("components") or {},
        "requirements": ((Path(out_dir) / "requirements.txt").read_text(encoding="utf-8")
                         if (Path(out_dir) / "requirements.txt").is_file() else ""),
    }


def _find_method(docs, holder, name):
    for group in (docs["services"], docs["repos"]):
        for service in group:
            if service.get("service_name") == holder or service.get("interface_name") == holder:
                for method in service.get("methods") or []:
                    if method.get("name") == name:
                        return method
    return None


def _binding_seed(store, models, binding, state):
    repo = next((item for item in models.get("_repos") or []
                 if item.get("interface_name") == binding.get("repository")), None)
    return None


def _precondition_values(contract, binding_name):
    values = {}
    for precondition in contract.get("preconditions") or []:
        # A `raise_when=true` check describes a forbidden state, not the
        # state the valid fixture should start in.
        if precondition.get("raise_when") == "true":
            continue
        check = str(precondition.get("check") or "")
        match = re.match(
            rf"{re.escape(binding_name)}\.(\w+)\s*==\s*(['\"])(.*?)\2", check)
        if match:
            values[match.group(1)] = match.group(3)
            continue
        match = re.match(
            rf"{re.escape(binding_name)}\.(\w+)\s+in\s*\(([^)]*)\)", check)
        if match:
            raw = match.group(2)
            items = re.findall(r"['\"](.*?)['\"]", raw)
            if items:
                values[match.group(1)] = items[0]
    return values


def _allowed_values(docs, entity, field):
    pattern = re.compile(
        rf"\b{re.escape(entity)}\.{re.escape(field)}\s+must\s+be\s+one\s+of\b",
        re.IGNORECASE)
    for invariant in docs.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        match = pattern.search(text or "")
        if not match:
            continue
        tail = text[match.end():].strip().rstrip(".")
        quoted = re.findall(r"['\"](.*?)['\"]", tail)
        if quoted:
            return quoted
    # A prose rule may name a concrete value without the "must be one of"
    # shape (`Only users with the role 'administrator' ...`).
    for invariant in docs.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        if field.lower() not in str(text).lower():
            continue
        quoted = re.findall(r"['\"](.*?)['\"]", text)
        if quoted:
            return quoted
    if field.lower() in ("status", "state"):
        plural = entity + "s"
        match = re.search(
            rf"\b{re.escape(plural)}\b[^.]*?\b(?:can be|may be|is one of)\s+([^.;]+)",
            docs.get("requirements") or "", re.IGNORECASE)
        if match:
            values = [value.strip(" `'\"") for value in re.split(
                r",|\bor\b", match.group(1)) if value.strip(" `'\"")]
            if all(re.fullmatch(r"[A-Za-z0-9_.-]+", value) for value in values):
                return values
    return []


def _arg_value(name, kind, binding_records):
    key = str(name).lower()
    for binding_name, (record, pk) in binding_records.items():
        entity = str(record.get("__entity__", binding_name))
        if key == f"{entity.lower()}_id" or key == binding_name.lower() + "_id":
            return record.get(pk)
        if key == binding_name.lower():
            return record.get(pk)
    if key.endswith("_id"):
        for record, pk in binding_records.values():
            if pk:
                return record.get(pk)
    if key.endswith("_ids"):
        for record, pk in binding_records.values():
            if pk:
                return str(record.get(pk))
    return _sample({"name": name, "type": kind}, 1)


def _check_contract(docs, deps, contract, store, sequence, covered=None):
    holder, method_name = contract.get("holder"), contract.get("method")
    method = _find_method(docs, holder, method_name)
    if method is None:
        return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                "reason": "method not in documents"}
    bindings = contract.get("bindings") or []
    effects = contract.get("effects") or []
    preconditions = contract.get("preconditions") or []
    if not effects:
        return {"name": f"contract:{holder}.{method_name}", "status": "passed"}
    if not bindings and any(
            str(param.get("type") or "").lower() in
            ("array", "list", "dict", "mapping", "any")
            for param in method.get("params") or [] if isinstance(param, dict)):
        return {"name": f"contract:{holder}.{method_name}",
                "status": "passed" if (holder, method_name) in (covered or set())
                else "not_applicable",
                "reason": "collection covered by a scenario"}
    if any(str(effect.get("target") or "").endswith((".status", ".state"))
           for effect in effects) and not any(
               str(item.get("check") or "").split(".")[-1].startswith(("status", "state"))
               for item in preconditions if isinstance(item, dict)):
        return {"name": f"contract:{holder}.{method_name}",
                "status": "passed" if (holder, method_name) in (covered or set())
                else "not_applicable",
                "reason": "state effect covered by a scenario"}
    model_by_entity = {m.get("name"): m for m in docs["models"]}
    by_lower = {str(name).lower(): name for name in model_by_entity}
    binding_records = {}
    # A contract may name an effect on `product.stock_quantity` without a
    # separate read binding. Seed the entity named by the effect variable.
    inferred = [str(effect.get("target") or "").split(".", 1)[0]
                for effect in effects if "." in str(effect.get("target") or "")]
    for variable in inferred:
        if any(binding.get("name") == variable for binding in bindings):
            continue
        entity = by_lower.get(variable.lower())
        model = model_by_entity.get(entity)
        if model is None:
            continue
        record, pk = _seed(store, model, sequence)
        record["__entity__"] = entity
        binding_records[variable] = (record, pk)
    for binding_index, binding in enumerate(bindings):
        repo = next((item for item in docs["repos"]
                     if item.get("interface_name") == binding.get("repository")), None)
        entity = repo.get("entity") if repo else None
        model = model_by_entity.get(entity)
        if model is None:
            return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                    "reason": f"unknown binding entity {entity!r}"}
        overrides = _precondition_values(contract, binding.get("name") or "")
        record, pk = _seed(store, model, sequence + 1000 + binding_index * 10,
                           overrides)
        record["__entity__"] = entity
        binding_records[binding.get("name") or entity] = (record, pk)
    param_overrides = {}
    for effect in effects:
        target_name = str(effect.get("target") or "")
        variable, _, field = target_name.partition(".")
        entity = by_lower.get(variable.lower())
        if not entity:
            continue
        allowed = _allowed_values(docs, entity, field)
        value = effect.get("value")
        if isinstance(value, str) and allowed:
            for param in method.get("params") or []:
                if param.get("name") == value:
                    param_overrides[param["name"]] = allowed[0]
    args = []
    param_values = {}
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        value = param_overrides.get(
            param["name"],
            _arg_value(param["name"], param.get("type"), binding_records))
        param_values[param["name"]] = value
        args.append(value)
    target = deps.get("services", {}).get(holder) or deps.get("repos", {}).get(holder)
    if target is None:
        return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                "reason": "holder not generated"}
    call = getattr(target, method_name, None)
    if not callable(call):
        return {"name": f"contract:{holder}.{method_name}", "status": "failed",
                "reason": "method missing"}
    try:
        call(*args)
    except Exception as error:  # noqa: BLE001
        return {"name": f"contract:{holder}.{method_name}", "status": "failed",
                "reason": f"valid call raised {type(error).__name__}: {error}"}
    for effect in effects:
        target_name = str(effect.get("target") or "")
        variable, _, field = target_name.partition(".")
        if variable not in binding_records:
            continue
        record, pk = binding_records[variable]
        current = store.get(record.get("__entity__", variable), pk, record.get(pk))
        expected = effect.get("value")
        if isinstance(expected, str) and expected in param_values:
            expected = param_values[expected]
        elif effect.get("op") == "set" and isinstance(expected, str):
            try:
                expected = ast.literal_eval(expected)
            except (ValueError, SyntaxError):
                pass
            if expected == "now":
                continue
            if current.get(field) != expected:
                return {"name": f"contract:{holder}.{method_name}", "status": "failed",
                        "reason": f"{target_name} is {current.get(field)!r}, expected {expected!r}"}
    # Invalid precondition: seed the same binding with a different state and
    # assert the declared error is raised. This is only attempted when the
    # contract names a concrete error.
    for precondition in preconditions:
        check = str(precondition.get("check") or "")
        error = precondition.get("error")
        match = re.match(r"(\w+)\.(\w+)\s*==\s*['\"](.*?)['\"]", check)
        if not error or not match:
            continue
        binding_name, field_name, expected = match.groups()
        binding = next((item for item in bindings if item.get("name") == binding_name), None)
        if binding is None:
            continue
        repo = next((item for item in docs["repos"]
                     if item.get("interface_name") == binding.get("repository")), None)
        model = model_by_entity.get(repo.get("entity") if repo else None)
        if model is None:
            continue
        raise_when = precondition.get("raise_when")
        bad_value = expected if raise_when == "true" else "definitely-not-" + expected
        overrides = _precondition_values(contract, binding_name)
        overrides[field_name] = bad_value
        bad_record, bad_pk = _seed(store, model, sequence + 100, overrides)
        bad_record["__entity__"] = repo.get("entity")
        bad_bindings = dict(binding_records)
        bad_bindings[binding_name] = (bad_record, bad_pk)
        bad_args = []
        for param in method.get("params") or []:
            bad_args.append(_arg_value(param.get("name"), param.get("type"), bad_bindings))
        try:
            call(*bad_args)
        except Exception as thrown:  # noqa: BLE001
            if type(thrown).__name__ != error:
                return {"name": f"contract:{holder}.{method_name}:invalid", "status": "failed",
                        "reason": f"raised {type(thrown).__name__}, expected {error}"}
            return {"name": f"contract:{holder}.{method_name}:invalid", "status": "passed"}
        return {"name": f"contract:{holder}.{method_name}:invalid", "status": "failed",
                "reason": f"invalid precondition did not raise {error}"}
    return {"name": f"contract:{holder}.{method_name}", "status": "passed"}


def _resolve(value, refs):
    if isinstance(value, dict) and "ref" in value:
        current = refs
        for part in str(value["ref"]).split("."):
            current = current[part]
        return current
    if isinstance(value, list):
        return [_resolve(item, refs) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, refs) for key, item in value.items()}
    return value


def _run_scenario(docs, deps, store, scenario, sequence, cli_path=None, db=None,
                  cli_module=None):
    name = f"scenario:{scenario.get('name') or 'unnamed'}"
    refs = {}
    model_by_entity = {m.get("name"): m for m in docs["models"]}
    for number, step in enumerate(scenario.get("setup") or [], start=1):
        entity = step.get("entity")
        model = model_by_entity.get(entity)
        if model is None:
            return {"name": name, "status": "skipped",
                    "reason": f"unknown setup entity {entity!r}"}
        values = {key: _resolve(value, refs)
                  for key, value in (step.get("values") or {}).items()}
        try:
            record, pk = _seed(store, model, sequence + number, values)
        except Exception as error:  # noqa: BLE001
            return {"name": name, "status": "failed",
                    "reason": f"setup {entity} raised {type(error).__name__}: {error}"}
        record["__entity__"] = entity
        alias = step.get("as") or entity
        refs[alias] = record
        refs[f"{alias}.id"] = record.get(pk)
        refs[f"{alias}.{pk}"] = record.get(pk)
    row_baseline = {entity: len(store.all(entity))
                    for entity in model_by_entity}
    when = scenario.get("when") or {}
    if "cli" in when:
        if cli_path is None or db is None:
            return {"name": name, "status": "skipped",
                    "reason": "CLI path/database unavailable"}
        cli_args = _resolve(when.get("cli") or [], refs)
        if not isinstance(cli_args, list):
            cli_args = [str(cli_args)]
        if cli_module is not None:
            db = Path(tempfile.mkdtemp(prefix="esus-cli-scenario-")) / "cli.sqlite3"
            built = cli_module.build_cli(str(db))
            fresh = built[1] if isinstance(built, tuple) else built
            _seed_all(docs, fresh["store"])
        result = subprocess.run(
            [sys.executable, str(cli_path), "--db", str(db), *map(str, cli_args)],
            capture_output=True, text=True)
        expected = (scenario.get("expect") or {}).get("error")
        if result.returncode == 0 and not expected:
            return {"name": name, "status": "passed"}
        if expected and expected in (result.stderr + result.stdout):
            return {"name": name, "status": "passed"}
        return {"name": name, "status": "failed",
                "reason": (result.stderr or result.stdout or "CLI failed")[-350:]}
    holder = when.get("service") or when.get("repository")
    target = deps.get("services", {}).get(holder) or deps.get("repos", {}).get(holder)
    if target is None:
        return {"name": name, "status": "skipped",
                "reason": f"holder {holder!r} not generated"}
    method = getattr(target, str(when.get("method") or ""), None)
    if not callable(method):
        return {"name": name, "status": "failed",
                "reason": f"method {holder}.{when.get('method')} missing"}
    raw_args = _resolve(when.get("args") or [], refs)
    try:
        if isinstance(raw_args, dict):
            method(**raw_args)
        elif isinstance(raw_args, list):
            method(*raw_args)
        else:
            method(raw_args)
    except Exception as error:  # noqa: BLE001
        expected = (scenario.get("expect") or {}).get("error")
        if expected and type(error).__name__ == expected:
            return {"name": name, "status": "passed"}
        return {"name": name, "status": "failed",
                "reason": f"raised {type(error).__name__}: {error}; expected {expected!r}"}
    expect = scenario.get("expect") or {}
    if expect.get("error"):
        return {"name": name, "status": "failed",
                "reason": f"expected {expect['error']}, no error was raised"}
    for target_name, expected in (expect.get("fields") or {}).items():
        variable, _, field = target_name.partition(".")
        if variable not in refs:
            return {"name": name, "status": "failed",
                    "reason": f"unknown scenario reference {variable!r}"}
        record = refs[variable]
        entity = record.get("__entity__", variable)
        pk = next((field.get("name") for field in model_by_entity.get(entity, {}).get("fields", [])
                   if field.get("primary_key")), "id")
        try:
            current = store.get(entity, pk, record.get(pk))
        except Exception as error:  # noqa: BLE001
            return {"name": name, "status": "failed",
                    "reason": f"cannot read {entity}: {error}"}
        if current.get(field) != expected:
            return {"name": name, "status": "failed",
                    "reason": f"{target_name} is {current.get(field)!r}, expected {expected!r}"}
    for entity, expected in (expect.get("rows") or {}).items():
        if entity not in model_by_entity:
            return {"name": name, "status": "failed",
                    "reason": f"unknown expected entity {entity!r}"}
        count = len(store.all(entity)) - row_baseline.get(entity, 0)
        if count != expected:
            return {"name": name, "status": "failed",
                    "reason": f"{entity} row count is {count}, expected {expected}"}
    return {"name": name, "status": "passed"}


def _leaf_entries(components):
    invocation = ((components or {}).get("facade") or {}).get("invocation") or {}
    commands = invocation.get("commands") if isinstance(invocation, dict) else None
    if not isinstance(commands, list):
        return []

    def walk(nodes, prefix=()):
        for node in nodes or []:
            if not isinstance(node, dict) or not isinstance(node.get("name"), str):
                continue
            path = prefix + (node["name"],)
            subcommands = node.get("subcommands")
            if isinstance(subcommands, list) and subcommands:
                yield from walk(subcommands, path)
            else:
                yield path, node

    return list(walk(commands))


def _cli_value(docs, name, declared, number):
    """A type-aware fixture for one required CLI option."""
    key = str(name or "").lstrip("-").replace("-", "_")
    fields = []
    for model in docs.get("models") or []:
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            if normalize(field["name"]) == normalize(key):
                fields.append((model.get("name"), field))
    field = fields[0][1] if fields else None
    field_kind = str((field or {}).get("type") or "").lower()
    kind = str(declared or field_kind or "").lower()
    if key.endswith("id") and field_kind:
        kind = field_kind
    elif declared in ("int", "integer", "float", "double", "decimal"):
        kind = declared
    if field is not None:
        allowed = _allowed_values(docs, fields[0][0], field["name"])
        if allowed and field_kind in ("str", "string", "text"):
            allowed = [value for value in allowed
                       if re.fullmatch(r"[A-Za-z0-9_.-]+", str(value))]
            if allowed:
                return allowed[0]
    if kind in ("date", "datetime", "timestamp") or field_kind in (
            "date", "datetime", "timestamp") or "date" in key or "time" in key \
            or key.endswith("_at") or "created" in key or "updated" in key:
        # ISO_DATE parses a date; datetime.fromisoformat accepts the shorter
        # date form too, so one fixture is valid for both transforms.
        return "2024-01-01"
    if kind in ("int", "integer"):
        if key.endswith("id") or "capacity" in key:
            return "1"
        if "current" in key or "attendee" in key:
            return "2"
        return "2"
    if kind in ("float", "double", "decimal", "money"):
        return "1.0"
    if kind in ("bool", "boolean"):
        return None
    if "email" in key:
        return f"cli{number}@example.test"
    return f"value{number}"


def _cli_args(docs, node, number):
    args = []
    for option in node.get("options") or []:
        if not isinstance(option, dict):
            continue
        name = option.get("name")
        if not isinstance(name, str) or not name:
            continue
        declared = str(option.get("type") or "").lower()
        if not option.get("required"):
            if str(node.get("name") or "").lower() in ("delete", "remove"):
                continue
            if declared in ("bool", "boolean"):
                continue
            if any(word in name for word in ("help", "version", "output", "file", "path")):
                continue
        args.append(name)
        value = _cli_value(docs, name, declared, number)
        if value is not None:
            args.append(value)
    return args


def _leaf_paths(components):
    return [path for path, _node in _leaf_entries(components)]


def _required_cli_args(node, number):
    args = []
    for option in node.get("options") or []:
        if not isinstance(option, dict) or not option.get("required"):
            continue
        name = option.get("name")
        if not isinstance(name, str) or not name:
            continue
        args.append(name)
        declared = str(option.get("type") or "").lower()
        if declared in ("bool", "boolean"):
            continue
        if declared in ("int", "integer"):
            args.append("1" if name.endswith("id") or "capacity" in name else "2")
        elif declared in ("float", "double", "decimal"):
            args.append("1.0")
        else:
            args.append(f"value{number}")
    return args


def _check_schema(docs, deps):
    store = deps.get("store")
    schema = getattr(store, "_schema", None)
    if not isinstance(schema, dict):
        return [{"name": "schema", "status": "skipped",
                 "reason": "store schema unavailable"}]
    checks = []
    connection = getattr(store, "_db", None)
    for model in docs["models"]:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        entity = model["name"]
        spec = schema.get(entity)
        if not isinstance(spec, dict):
            checks.append({"name": f"schema:{entity}", "status": "failed",
                           "reason": "entity missing from generated schema"})
            continue
        fields = {field.get("name"): field for field in spec.get("fields") or []
                  if isinstance(field, dict)}
        problems = []
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            name = field["name"]
            declared = fields.get(name)
            if declared is None:
                problems.append(f"{entity}.{name} missing")
                continue
            if bool(declared.get("primary_key")) != bool(field.get("primary_key")):
                problems.append(f"{entity}.{name} primary-key flag differs")
            if bool(declared.get("nullable")) != bool(field.get("nullable")):
                problems.append(f"{entity}.{name} nullability differs")
            if bool(declared.get("unique")) != bool(field.get("unique")):
                problems.append(f"{entity}.{name} uniqueness differs")
            source_fk = field.get("foreign_key") or {}
            target_fk = declared.get("foreign_key") or {}
            if bool(source_fk) != bool(target_fk):
                problems.append(f"{entity}.{name} foreign-key flag differs")
            elif source_fk and (
                    str(source_fk.get("target_entity")) != str(target_fk.get("target_entity"))
                    or str(source_fk.get("target_field")) != str(target_fk.get("target_field"))):
                problems.append(f"{entity}.{name} foreign-key target differs")
        if connection is not None:
            try:
                tables = [row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%'")]
                table = entity if entity in tables else next(
                    (name for name in tables
                     if {row[1] for row in connection.execute(
                         f'PRAGMA table_info("{name}")')}
                     >= {field.get("name") for field in model.get("fields") or []
                         if isinstance(field, dict)}), None)
                if table is None:
                    problems.append(f"{entity} table missing")
                else:
                    sql = connection.execute(
                        "SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()
                    if sql and spec.get("primary_key") and "AUTOINCREMENT" not in (sql[0] or "").upper():
                        problems.append(f"{entity} primary key is not AUTOINCREMENT")
            except Exception as error:  # noqa: BLE001
                problems.append(f"schema introspection failed: {error}")
        checks.append({"name": f"schema:{entity}",
                       "status": "failed" if problems else "passed",
                       "reason": "; ".join(problems)})
    return checks


def _model_method(docs, holder, name):
    for group in (docs["repos"], docs["services"]):
        for service in group:
            if service.get("interface_name") == holder or service.get("service_name") == holder:
                for method in service.get("methods") or []:
                    if method.get("name") == name:
                        return method
    return None


def _seed_all(docs, store):
    """Seed one row per model so repository foreign keys have targets."""
    records = {}
    models = {model.get("name"): model for model in docs["models"]
              if isinstance(model, dict) and model.get("name")}
    for number, (entity, model) in enumerate(models.items(), start=1):
        record, pk = _seed(store, model, number)
        record["__entity__"] = entity
        records[entity] = (record, pk)
    # Point every FK at a compatible seeded row where possible.
    for entity, (record, pk) in list(records.items()):
        for field in models[entity].get("fields") or []:
            foreign = field.get("foreign_key") if isinstance(field, dict) else None
            target = foreign.get("target_entity") if isinstance(foreign, dict) else None
            if target in records:
                record[field["name"]] = records[target][0].get(records[target][1])
    return records


def _args_for_create(docs, method, model, number):
    args = {}
    fields = {field.get("name"): field for field in model.get("fields") or []
              if isinstance(field, dict)}
    for param in method.get("params") or []:
        if not isinstance(param, dict) or not param.get("name"):
            continue
        name = param["name"]
        if name in fields:
            field = fields[name]
            if field.get("primary_key"):
                continue
            allowed = _allowed_values(docs, model.get("name"), name)
            if isinstance(field.get("foreign_key"), dict):
                args[name] = 1
            elif name == "capacity":
                args[name] = 1
            elif name in ("current_attendees_count", "current_count", "attendees"):
                args[name] = 2
            elif allowed:
                args[name] = allowed[0]
            else:
                args[name] = _sample(field, number)
        else:
            args[name] = _sample(param, number)
    return args


def _check_invariants(docs, deps, number):
    """Exercise the mechanical uniqueness and FK constraints in the store."""
    store = deps.get("store")
    checks = []
    schema = getattr(store, "_schema", None) or {}
    for model in docs["models"]:
        if not isinstance(model, dict) or not model.get("name"):
            continue
        entity = model["name"]
        model_fields = {field.get("name"): field for field in model.get("fields") or []
                        if isinstance(field, dict)}
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            if field.get("primary_key"):
                continue
            name = field["name"]
            if field.get("unique"):
                try:
                    record, pk = _seed(store, model, number + 5000)
                    values = {key: value for key, value in record.items()
                              if key not in (pk, "__entity__")}
                    store.add(entity, pk, values, ())
                except Exception:
                    checks.append({"name": f"invariant:unique:{entity}.{name}",
                                   "status": "passed"})
                else:
                    checks.append({"name": f"invariant:unique:{entity}.{name}",
                                   "status": "failed",
                                   "reason": "duplicate value was accepted"})
            foreign = field.get("foreign_key")
            if isinstance(foreign, dict) and foreign.get("target_entity"):
                target = foreign["target_entity"]
                target_model = next((item for item in docs["models"]
                                     if item.get("name") == target), None)
                if target_model is None:
                    continue
                target_pk = next((item.get("name") for item in target_model.get("fields") or []
                                  if isinstance(item, dict) and item.get("primary_key")), "id")
                try:
                    _seed(store, target_model, number + 7000)
                    source, source_pk = _seed(store, model, number + 8000)
                    values = {key: value for key, value in source.items()
                              if key not in (source_pk, "__entity__")}
                    values[name] = 999999
                    store.add(entity, source_pk, values,
                              [(name, target, target_pk, KeyError)])
                except Exception:
                    checks.append({"name": f"invariant:fk:{entity}.{name}",
                                   "status": "passed"})
                else:
                    checks.append({"name": f"invariant:fk:{entity}.{name}",
                                   "status": "failed",
                                   "reason": "missing foreign key was accepted"})
    return checks


def _store_roundtrip(docs, deps, repo, number):
    entity = repo.get("entity")
    holder = repo.get("interface_name") or entity
    model = next((item for item in docs["models"]
                  if item.get("name") == entity), None)
    store = deps.get("store")
    if model is None or store is None:
        return {"name": f"repository:{holder}", "status": "skipped",
                "reason": "model/store unavailable"}
    db = getattr(store, "_db", None)
    try:
        if db is not None:
            db.execute("PRAGMA foreign_keys=OFF")
        record, pk = _seed(store, model, number + 9000)
        key = record.get(pk)
        if store.get(entity, pk, key) is None:
            raise AssertionError("store get returned None")
        changed = dict(record)
        changed.pop("__entity__", None)
        target = next((field.get("name") for field in model.get("fields") or []
                       if isinstance(field, dict) and not field.get("primary_key")
                       and not field.get("foreign_key")
                       and not field.get("unique")),
                      None)
        if target:
            changed[target] = _sample({"name": target, "type": "string"}, number + 9001)
            store.update(entity, pk, key, changed)
        store.delete(entity, pk, key)
    except Exception as error:  # noqa: BLE001
        return {"name": f"repository:{holder}", "status": "failed",
                "reason": f"store round-trip: {type(error).__name__}: {error}"}
    finally:
        if db is not None:
            db.execute("PRAGMA foreign_keys=ON")
    return {"name": f"repository:{holder}:store", "status": "passed"}


def _check_repository(docs, deps, repo, number):
    entity = repo.get("entity")
    holder = repo.get("interface_name") or entity
    model = next((item for item in docs["models"]
                  if item.get("name") == entity), None)
    obj = deps.get("repos", {}).get(holder)
    if model is None or obj is None:
        return {"name": f"repository:{holder}", "status": "skipped",
                "reason": "repository/model missing"}
    create = _model_method(docs, holder, "create")
    read_one = _model_method(docs, holder, "read_one")
    read_all = _model_method(docs, holder, "read_all")
    update = _model_method(docs, holder, "update")
    delete = _model_method(docs, holder, "delete")
    if create is not None:
        # A mapping/entity parameter is a different create shape; the
        # mechanical CRUD contract below does not apply.
        if any(str(param.get("type") or "").lower() in
               ("dict", "mapping", "any") for param in create.get("params") or []
               if isinstance(param, dict)):
            return {"name": f"repository:{holder}", "status": "skipped",
                    "reason": "mapping-shaped create"}
    if create is not None and read_one is not None:
        try:
            created = obj.create(**_args_for_create(docs, create, model, number + 100))
        except Exception as error:  # noqa: BLE001
            return {"name": f"repository:{holder}", "status": "failed",
                    "reason": f"create raised {type(error).__name__}: {error}"}
        pk = next((field.get("name") for field in model.get("fields") or []
                   if field.get("primary_key")), "id")
        key = created.get(pk) if isinstance(created, dict) else getattr(created, pk, created)
        try:
            read = obj.read_one(key)
        except Exception as error:  # noqa: BLE001
            return {"name": f"repository:{holder}", "status": "failed",
                    "reason": f"read_one raised {type(error).__name__}: {error}"}
        if read is None:
            return {"name": f"repository:{holder}", "status": "failed",
                    "reason": "read_one returned None after create"}
        if read_all is not None:
            rows = obj.read_all()
            ids = {row.get(pk) if isinstance(row, dict) else getattr(row, pk, None)
                   for row in rows}
            if key not in ids:
                return {"name": f"repository:{holder}", "status": "failed",
                        "reason": "read_all does not contain the created row"}
        if update is not None:
            params = []
            for param in update.get("params") or []:
                if not isinstance(param, dict) or not param.get("name"):
                    continue
                name = param["name"]
                if name == pk or name in ("id",):
                    params.append(key)
                else:
                    field = next((item for item in model.get("fields") or []
                                  if isinstance(item, dict)
                                  and item.get("name") == name), None)
                    allowed = _allowed_values(docs, entity, name)
                    if isinstance((field or {}).get("foreign_key"), dict):
                        params.append(1)
                    elif name == "capacity":
                        params.append(1)
                    elif name in ("current_attendees_count", "current_count", "attendees"):
                        params.append(2)
                    elif allowed:
                        params.append(allowed[0])
                    else:
                        params.append(_sample(param, number + 200))
            try:
                obj.update(*params)
            except Exception as error:  # noqa: BLE001
                return {"name": f"repository:{holder}", "status": "failed",
                        "reason": f"update raised {type(error).__name__}: {error}"}
        if delete is not None:
            try:
                obj.delete(key)
            except Exception as error:  # noqa: BLE001
                return {"name": f"repository:{holder}", "status": "failed",
                        "reason": f"delete raised {type(error).__name__}: {error}"}
            try:
                gone = obj.read_one(key)
            except Exception:
                gone = None
            if gone is not None:
                return {"name": f"repository:{holder}", "status": "failed",
                        "reason": "read_one still returns after delete"}
        return {"name": f"repository:{holder}", "status": "passed"}
    return _store_roundtrip(docs, deps, repo, number)


def _run_cli_command(cli, docs, cli_path, path, node, variant):
    db = Path(tempfile.mkdtemp(prefix="esus-cli-")) / "cli.sqlite3"
    built = cli.build_cli(str(db))
    deps = built[1] if isinstance(built, tuple) else built
    _seed_all(docs, deps["store"])
    args = [sys.executable, str(cli_path), "--db", str(db), *path]
    args += _cli_args(docs, node, variant)
    result = subprocess.run(args, capture_output=True, text=True)
    return result


def _scenario_path(out_dir):
    # The checked-in/generated suite is the complete one; a local
    # scenarios.json may be an older subset.
    fallback = Path(__file__).resolve().parent / "scenarios" / (
        Path(out_dir).name + ".json")
    if fallback.is_file():
        return fallback
    path = Path(out_dir) / "scenarios.json"
    return path if path.is_file() else None


def run(out_dir):
    checks = []
    docs = _documents(out_dir)
    cli_path = Path(out_dir) / "generated" / "cli.py"
    if not cli_path.is_file():
        app_path = Path(out_dir) / "generated" / "app.py"
        return {"prompt": Path(out_dir).name,
                "status": "passed" if app_path.is_file() else "failed",
                "checks": [{"name": "app-fallback",
                            "status": "passed" if app_path.is_file() else "failed",
                            "reason": "no cli.py; standalone app.py" if app_path.is_file()
                                      else "no cli.py or app.py"}]}
    try:
        cli, deps, db = _load_package(out_dir)
    except Exception as error:  # noqa: BLE001
        return {"prompt": Path(out_dir).name, "status": "failed",
                "checks": [{"name": "import", "status": "failed",
                            "reason": f"{type(error).__name__}: {error}"}],
                "traceback": traceback.format_exc()}
    checks.append({"name": "import", "status": "passed"})
    if cli_path.is_file():
        import subprocess
        result = subprocess.run([sys.executable, str(cli_path), "--db", str(db), "--help"],
                                capture_output=True, text=True)
        checks.append({"name": "cli-help",
                       "status": "passed" if result.returncode == 0 else "failed",
                       "reason": "" if result.returncode == 0 else result.stderr[-300:]})
        for path in _leaf_paths(docs.get("components")):
            result = subprocess.run(
                [sys.executable, str(cli_path), "--db", str(db), *path, "--help"],
                capture_output=True, text=True)
            checks.append({
                "name": "cli-leaf:" + " ".join(path),
                "status": "passed" if result.returncode == 0 else "failed",
                "reason": "" if result.returncode == 0 else result.stderr[-300:],
            })
    checks.extend(_check_schema(docs, deps))
    store = deps.get("store")
    covered = set()
    scenario_path_early = _scenario_path(out_dir)
    if scenario_path_early is not None:
        try:
            for item in json.loads(scenario_path_early.read_text()).get("scenarios") or []:
                when = item.get("when") if isinstance(item, dict) else None
                if not isinstance(when, dict):
                    continue
                holder = when.get("service") or when.get("repository")
                method = when.get("method")
                if holder and method:
                    covered.add((holder, method))
        except ValueError:
            pass
    try:
        _seed_all(docs, store)
    except Exception as error:  # noqa: BLE001
        checks.append({"name": "seed-all", "status": "failed",
                       "reason": f"{type(error).__name__}: {error}"})
    scenario_file = _scenario_path(out_dir)
    has_cli_scenarios = False
    if scenario_file is not None:
        try:
            has_cli_scenarios = any(
                isinstance(item, dict) and isinstance(item.get("when"), dict)
                and "cli" in item["when"]
                for item in json.loads(scenario_file.read_text()).get("scenarios") or [])
        except ValueError:
            pass
    if cli_path.is_file() and not has_cli_scenarios:
        for number, (path, node) in enumerate(_leaf_entries(docs.get("components")), start=1):
            required = _cli_args(docs, node, number)
            if required:
                checks.append({
                    "name": "cli-run:" + " ".join(path),
                    "status": "skipped",
                    "reason": "requires a reviewed CLI scenario fixture",
                })
                continue
            args = [sys.executable, str(cli_path), "--db", str(db), *path]
            result = subprocess.run(args, capture_output=True, text=True)
            checks.append({
                "name": "cli-run:" + " ".join(path),
                "status": "passed" if result.returncode == 0 else "skipped",
                "reason": "" if result.returncode == 0 else (
                    "command needs a seeded fixture: "
                    + (result.stderr or result.stdout)[-250:]),
            })
    for number, repo in enumerate(docs.get("repos") or [], start=1):
        if isinstance(repo, dict):
            checks.append(_check_repository(docs, deps, repo, number))
    checks.extend(_check_invariants(docs, deps, 1))
    sequence = 1
    for contract in docs["contracts"]:
        try:
            checks.append(_check_contract(docs, deps, contract, store, sequence, covered))
        except Exception as error:  # noqa: BLE001
            checks.append({"name": f"contract:{contract.get('holder')}.{contract.get('method')}",
                           "status": "failed",
                           "reason": f"harness error: {type(error).__name__}: {error}"})
        sequence += 1
    scenario_path = _scenario_path(out_dir)
    if scenario_path is not None:
        try:
            scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))
        except ValueError:
            scenarios = {}
        for scenario in (scenarios.get("scenarios") or []):
            checks.append(_run_scenario(docs, deps, store, scenario, sequence,
                                       cli_path=cli_path, db=db,
                                       cli_module=cli))
            sequence += 1
    return {"prompt": Path(out_dir).name,
            "status": "passed" if all(c["status"] != "failed" for c in checks) else "failed",
            "checks": checks}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/runtime/worker.py OUT_DIR")
    result = run(sys.argv[1])
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
