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
import sys
import tempfile
import traceback
from pathlib import Path


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sample(field, number):
    name = str(field.get("name") or "")
    kind = str(field.get("type") or "").strip().lower()
    if "email" in name:
        return f"user{number}@example.test"
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


def _check_contract(docs, deps, contract, store, sequence):
    holder, method_name = contract.get("holder"), contract.get("method")
    method = _find_method(docs, holder, method_name)
    if method is None:
        return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                "reason": "method not in documents"}
    bindings = contract.get("bindings") or []
    effects = contract.get("effects") or []
    preconditions = contract.get("preconditions") or []
    if not effects:
        return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                "reason": "contract has no scalar effect"}
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
    for binding in bindings:
        repo = next((item for item in docs["repos"]
                     if item.get("interface_name") == binding.get("repository")), None)
        entity = repo.get("entity") if repo else None
        model = model_by_entity.get(entity)
        if model is None:
            return {"name": f"contract:{holder}.{method_name}", "status": "skipped",
                    "reason": f"unknown binding entity {entity!r}"}
        overrides = _precondition_values(contract, binding.get("name") or "")
        record, pk = _seed(store, model, sequence, overrides)
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
    store = deps.get("store")
    sequence = 1
    for contract in docs["contracts"]:
        checks.append(_check_contract(docs, deps, contract, store, sequence))
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
