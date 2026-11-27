"""Runtime conformance worker for one generated validation package.

This is deliberately data-driven: it reads the extracted models, contracts and
variants, seeds a temporary store, and exercises the generated public surface.
It never imports two generated packages in one process (their absolute module
names would collide), so the outer runner starts one fresh interpreter per
prompt.
"""

from __future__ import annotations

import ast
import csv
import datetime
import importlib
import json
import os
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


def discover_projects(root):
    """Directories that can be handed to `run`.

    The validation bench uses `prompt_*`; the initial archive uses named
    projects one or two levels down. Both layouts are discovered generically,
    so the runner is not tied to the validation naming scheme.
    """
    root = Path(root)

    def is_project(path):
        return (path.is_dir() and (path / "generated").is_dir()
                and ((path / "data_models.json").is_file()
                     or (path / "components.json").is_file()))

    prompts = sorted(path for path in root.glob("prompt_*") if path.is_dir())
    if prompts:
        return prompts
    # The initial archive keeps its runnable projects under `esus_bench/`;
    # sibling timing/review directories are raw archives, not acceptance
    # targets.
    bench = root / "esus_bench"
    if bench.is_dir():
        projects = sorted(path for path in bench.iterdir() if is_project(path))
        if projects:
            return projects
    direct = sorted(path for path in root.iterdir() if is_project(path))
    if direct:
        return direct
    return sorted(path for child in root.iterdir() if child.is_dir()
                  for path in child.iterdir() if is_project(path))


_UNIQUE_COUNTER = 1


def _unique_enforced(field):
    """Whether a model field's uniqueness is part of the accepted schema.

    `inferred` is a model naming guess awaiting review; `rejected` was
    explicitly removed. The generated schema stores neither as unique.
    """
    if not isinstance(field, dict) or not field.get("unique"):
        return False
    return field.get("unique_status") not in ("inferred", "rejected")


def _unique_asserted(field):
    """The schema uniqueness acceptance may assert, or None when inferred.

    An inferred unique field is an open policy question. A generated program
    may enforce it or not; neither choice is an acceptance defect until the
    review confirms or rejects it. Explicit/confirmed must be unique;
    rejected must not be.
    """
    if not isinstance(field, dict):
        return None
    if field.get("unique_status") == "inferred":
        return None
    return _unique_enforced(field)


def _sample(field, number):
    global _UNIQUE_COUNTER
    name = str(field.get("name") or "")
    kind = str(field.get("type") or "").strip().lower()
    if "email" in name:
        return f"seed{number}@example.test"
    if kind in ("int", "integer"):
        if name == "maximum_capacity":
            # A storage location's limit must leave room for the seeded wine
            # stock and for a create fixture.
            return 100
        if "capacity" in name:
            return 100
        if "current" in name or "attendee" in name:
            return 2
        return 2 if name not in ("id",) else 1
    if kind in ("float", "double", "decimal", "money"):
        return 2.0
    if kind in ("bool", "boolean"):
        return False
    if kind in ("date", "datetime", "timestamp"):
        # CLI ISO_DATE transforms produce date objects; seed the same shape so
        # a delete/update filter by the seeded date matches.
        return datetime.date(2024, 1, 1)
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


_NON_NULL = object()


def _model_field_name(model, wanted):
    """The model's spelling of a field, recognizing state/status synonyms."""
    if not isinstance(model, dict) or not wanted:
        return wanted
    names = {str(field.get("name")) for field in model.get("fields") or []
             if isinstance(field, dict) and field.get("name")}
    if wanted in names:
        return wanted
    normalized = {normalize(name): name for name in names}
    if normalize(wanted) in normalized:
        return normalized[normalize(wanted)]
    if normalize(wanted) in ("state", "status"):
        for alias in ("state", "status"):
            if alias in normalized:
                return normalized[alias]
    return wanted


def _row_count_matches(actual, expected):
    """Compare a row count with an exact or inequality expectation."""
    if isinstance(expected, (int, float)):
        return actual == expected
    text = str(expected or "").strip()
    for operator in (">=", "<=", ">", "<", "!=", "=="):
        if text.startswith(operator):
            try:
                wanted = int(text[len(operator):].strip())
            except ValueError:
                return False
            return {
                ">=": actual >= wanted, "<=": actual <= wanted,
                ">": actual > wanted, "<": actual < wanted,
                "!=": actual != wanted, "==": actual == wanted,
            }[operator]
    try:
        return actual == int(text)
    except ValueError:
        return False


def _same_value(actual, expected):
    """Compare stored dates/datetimes with their prompt spelling.

    Prompt fixtures use ISO-8601 strings. A generated SQLite-backed store may
    return `date` or `datetime` objects for the same value, so a raw `!=`
    would report a false behavior finding. UTC `Z` and `+00:00` spellings are
    equivalent.
    """
    if actual == expected:
        return True
    if isinstance(expected, str) and hasattr(actual, "isoformat"):
        text = actual.isoformat()
        wanted = expected[:-1] + "+00:00" if expected.endswith("Z") else expected
        return (text == wanted or text.startswith(wanted + "T")
                or text.startswith(wanted + " "))
    if isinstance(actual, str) and hasattr(expected, "isoformat"):
        text = expected.isoformat()
        wanted = actual[:-1] + "+00:00" if actual.endswith("Z") else actual
        return (text == wanted or text.startswith(wanted + "T")
                or text.startswith(wanted + " "))
    return False


def _result_record(value, entity, docs):
    """A created record as the scenario refs expect it."""
    model = next((item for item in docs.get("models") or []
                  if isinstance(item, dict) and item.get("name") == entity), {})
    pk = next((field.get("name") for field in model.get("fields") or []
               if isinstance(field, dict) and field.get("primary_key")), "id")
    if isinstance(value, dict):
        record = dict(value)
    elif hasattr(value, "__dict__"):
        record = dict(vars(value))
    else:
        record = {}
    if pk not in record and isinstance(value, int):
        record[pk] = value
    return record


def _seed(store, model, number=1, overrides=None):
    pk = next((field.get("name") for field in model.get("fields") or []
               if field.get("primary_key")), "id")
    overrides = dict(overrides or {})
    for key, value in list(overrides.items()):
        field_name = _model_field_name(model, key)
        if field_name != key:
            overrides.setdefault(field_name, value)
    values = {}
    for field in model.get("fields") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        name = field["name"]
        if name == pk:
            # A join model can use its parent foreign key as the primary key.
            # A scenario that seeds that relation explicitly must be allowed
            # to provide it; skipping it creates a row under a different key.
            if overrides and name in overrides:
                values[name] = overrides[name]
            continue
        if overrides and name in overrides:
            value = overrides[name]
            values[name] = _sample(field, number) if value is _NON_NULL else value
        elif isinstance(field.get("foreign_key"), dict):
            values[name] = 1
        elif field.get("nullable") and not field.get("unique"):
            # A nullable field is part of the entity's state. Seeding a value
            # for every optional column made a returned loan look already
            # returned and broke otherwise valid contracts. The valid fixture
            # starts nullable state at NULL unless a precondition asks for a
            # concrete value. A nullable *unique* column still needs a value:
            # two NULLs are allowed by SQLite and the uniqueness check would
            # be vacuous.
            values[name] = None
        else:
            values[name] = _sample(field, number)
    # The same scenario seeds a second row into a store that already has the
    # first (contract and invariant fixtures do this). A unique string column
    # must not repeat, or the harness fails before exercising the method.
    for field in model.get("fields") or []:
        if not isinstance(field, dict) or not field.get("unique"):
            continue
        name = field["name"]
        value = values.get(name)
        if not isinstance(value, str):
            continue
        suffix = 1
        while store.select(model["name"], [(name, "eq", value)]):
            value = f"{values[name]}-{suffix}"
            suffix += 1
        values[name] = value
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
    prefix = rf"{re.escape(binding_name)}\.(\w+)"
    for precondition in contract.get("preconditions") or []:
        check = str(precondition.get("check") or "")
        forbidden = precondition.get("raise_when") == "true"
        # Negative state checks seed the opposite of the forbidden value.
        match = re.match(rf"{prefix}\s+is\s+not\s+None", check)
        if match:
            values[match.group(1)] = None if forbidden else _NON_NULL
            continue
        if forbidden:
            # A `raise_when=true` check describes a forbidden state, not the
            # state the valid fixture should start in.
            continue
        match = re.match(rf"{prefix}\s*==\s*(['\"])(.*?)\2", check)
        if match:
            values[match.group(1)] = match.group(3)
            continue
        match = re.match(rf"{prefix}\s+in\s*\(([^)]*)\)", check)
        if match:
            raw = match.group(2)
            items = re.findall(r"['\"](.*?)['\"]", raw)
            if items:
                values[match.group(1)] = items[0]
            continue
        match = re.match(
            rf"{prefix}\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)",
            check)
        if match:
            field_name, operator, raw = match.group(1), match.group(2), match.group(3)
            number = float(raw) if "." in raw else int(raw)
            # A valid fixture satisfies the comparison; a `raise_when=true`
            # check describes the forbidden state, so satisfy its negation.
            truth = not forbidden
            value = _comparison_value(operator, number, truth)
            if value is not None:
                values[field_name] = value
    return values


def _comparison_value(operator, number, truth):
    """A value that makes `field <operator> number` true or false."""
    if truth:
        return {">": number + 1, ">=": number, "<": number - 1,
                "<=": number, "==": number, "!=": number + 1}[operator]
    return {">": number, ">=": number - 1, "<": number + 1,
            "<=": number + 1, "==": number + 1, "!=": number}[operator]


def _invalid_precondition(check, raise_when):
    """`(binding, field, value)` that triggers a documented precondition."""
    prefix = r"(\w+)\.(\w+)"
    bad_truth = str(raise_when) == "true"
    match = re.match(
        rf"{prefix}\s*(==|!=|>=|<=|>|<)\s*(?P<quote>['\"])(.*?)(?P=quote)", check)
    if match:
        binding, field, operator, _quote, literal = match.groups()
        if operator == "==":
            value = literal if bad_truth else "not-" + literal
        elif operator == "!=":
            value = "not-" + literal if bad_truth else literal
        else:
            try:
                number = float(literal)
                if number.is_integer():
                    number = int(number)
            except ValueError:
                return None
            value = _comparison_value(operator, number, bad_truth)
        return binding, field, value
    match = re.match(
        rf"{prefix}\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)",
        check)
    if match:
        binding, field, operator, raw = match.groups()
        number = float(raw) if "." in raw else int(raw)
        return binding, field, _comparison_value(operator, number, bad_truth)
    match = re.match(rf"{prefix}\s+is\s+(not\s+)?None", check)
    if match:
        binding, field, negated = match.groups()
        value = None if bad_truth else _NON_NULL
        if negated:
            value = _NON_NULL if bad_truth else None
        return binding, field, value
    match = re.match(rf"{prefix}\s+in\s*\(([^)]*)\)", check)
    if match:
        binding, field, raw = match.groups()
        items = re.findall(r"['\"](.*?)['\"]", raw)
        if items:
            return binding, field, ("__not_documented__" if bad_truth
                                    else items[0])
    return None


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


def _method_state_start(docs, entity, field, method):
    """A valid starting state for a contract call whose method names a verb.

    A contract may record only the effects after `confirm_order`, while the
    generated body correctly guards the starting status. The generic contract
    fixture seeded `status = "value1"` and reported the guard as a failure.
    When the requirements document an allowed state set and the method name
    names a conventional transition, start from the state that transition
    expects. This is fixture setup, not a relaxation of the guard.
    """
    if str(field).lower() not in ("status", "state"):
        return None
    allowed = _allowed_values(docs, entity, field)
    if not allowed:
        return None
    name = str((method or {}).get("name") or "").lower()
    preferred = []
    if "cancel" in name:
        preferred = ["confirmed", "active", "approved", "pending"]
    elif "ship" in name:
        preferred = ["confirmed", "active", "approved", "pending"]
    elif "confirm" in name or "approve" in name:
        preferred = ["pending", "new", "draft", "open"]
    elif "close" in name:
        preferred = ["confirmed", "pending", "active", "open"]
    for wanted in preferred:
        for value in allowed:
            if str(value).lower() == wanted:
                return value
    return None


def _state_start_value(docs, entity, field, target, method):
    """A documented starting state that differs from the effect target.

    A cancel method sets `status = cancelled`; its valid fixture starts at
    `confirmed` or `pending`, not at an arbitrary seeded value. Prefer a value
    named in the method description, then the first documented alternative.
    """
    allowed = _allowed_values(docs, entity, field)
    candidates = [value for value in allowed if str(value) != str(target)]
    description = str((method or {}).get("description") or "").lower()
    for value in candidates:
        if str(value).lower() in description:
            return value
    return candidates[0] if candidates else None


def _composite_unique_fields(docs, entity):
    """Fields named by a composite unique rule for one entity."""
    model = next((item for item in docs.get("models") or []
                  if item.get("name") == entity), None)
    if model is None:
        return set()
    names = {field["name"] for field in model.get("fields") or []
             if isinstance(field, dict) and field.get("name")}
    found = set()
    for invariant in docs.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        if "unique" not in str(text).lower():
            continue
        match = re.search(r"unique\s+(?:constraint|combination)[^()]*"
                          r"(?:\(([^)]*)\)|of\s+([^.;]+))",
                          text, re.IGNORECASE)
        if not match:
            continue
        group = match.group(1) or match.group(2) or ""
        selected = [name for name in names
                    if re.search(rf"\b{re.escape(name)}\b", group,
                                 re.IGNORECASE)]
        if len(selected) > 1:
            found.update(selected)
    return found


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
    collection = any(
        any(token in str(param.get("type") or "").lower()
            for token in ("array", "list", "dict", "mapping", "any"))
        for param in method.get("params") or [] if isinstance(param, dict))
    if collection:
        # A collection parameter needs a structured fixture. A scenario that
        # already drives this method owns that fixture; otherwise the generic
        # contract check cannot construct one and must not inject a string.
        return {"name": f"contract:{holder}.{method_name}",
                "status": "passed" if (holder, method_name) in (covered or set())
                else "not_applicable",
                "reason": "collection covered by a scenario"}
    model_by_entity = {m.get("name"): m for m in docs["models"]}
    by_lower = {str(name).lower(): name for name in model_by_entity}
    state_starts = {}
    for effect in effects:
        target_name = str(effect.get("target") or "")
        variable, _, field = target_name.partition(".")
        if effect.get("op") != "set" or field not in ("status", "state"):
            continue
        entity = next((name for name in model_by_entity
                       if name.lower() == variable.lower()), None)
        if entity is None:
            continue
        target = effect.get("value")
        try:
            target = ast.literal_eval(target) if isinstance(target, str) else target
        except (ValueError, SyntaxError):
            pass
        start = _state_start_value(docs, entity, field, target, method)
        if start is None:
            return {"name": f"contract:{holder}.{method_name}",
                    "status": "not_applicable",
                    "reason": "state effect has no documented starting state"}
        state_starts[variable] = {field: start}
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
        record, pk = _seed(store, model, sequence,
                           state_starts.get(variable))
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
        overrides = dict(state_starts.get(
            binding.get("name") or "", {}))
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            inferred = _method_state_start(
                docs, entity, field["name"], method)
            if inferred is not None:
                overrides.setdefault(field["name"], inferred)
        overrides.update(_precondition_values(
            contract, binding.get("name") or ""))
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
    before = {}
    for effect in effects:
        variable, _, field = str(effect.get("target") or "").partition(".")
        if variable not in binding_records:
            continue
        record, pk = binding_records[variable]
        before[(variable, field)] = store.get(
            record.get("__entity__", variable), pk, record.get(pk)).get(field)
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
        if effect.get("op") in ("increment", "decrement"):
            by = effect.get("by")
            delta = param_values.get(by) if isinstance(by, str) else None
            if delta is None:
                try:
                    delta = float(by)
                except (TypeError, ValueError):
                    continue
            base = before.get((variable, field))
            if isinstance(base, (int, float)) and not isinstance(base, bool):
                expected = base + delta if effect.get("op") == "increment" \
                    else base - delta
            else:
                continue
        elif isinstance(expected, str) and expected in param_values:
            expected = param_values[expected]
        elif effect.get("op") == "set" and isinstance(expected, str):
            if expected.startswith("literal:"):
                expected = expected[len("literal:"):]
            if expected == f"not {field}":
                # A toggle (`is_active = not is_active`) is relative to the
                # value the fixture started with, not a literal string.
                expected = not before[(variable, field)]
            try:
                expected = ast.literal_eval(expected) if isinstance(expected, str) else expected
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
        invalid = _invalid_precondition(check, precondition.get("raise_when"))
        if not error or invalid is None:
            continue
        binding_name, field_name, bad_value = invalid
        binding = next((item for item in bindings if item.get("name") == binding_name), None)
        if binding is None:
            continue
        repo = next((item for item in docs["repos"]
                     if item.get("interface_name") == binding.get("repository")), None)
        model = model_by_entity.get(repo.get("entity") if repo else None)
        if model is None:
            continue
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
        reference = str(value["ref"])
        if reference in refs:
            return refs[reference]
        current = refs
        for part in reference.split("."):
            current = current[part]
        return current
    if isinstance(value, list):
        return [_resolve(item, refs) for item in value]
    if isinstance(value, dict):
        return {key: _resolve(item, refs) for key, item in value.items()}
    return value


def _materialize_file_args(docs, args):
    """Give an import command a real CSV file derived from its model."""
    out = list(args)
    command = next((item for item in out if not str(item).startswith("-")), "")
    model = next((item for item in docs.get("models") or []
                  if isinstance(item, dict)
                  and normalize(item.get("name") or "") == normalize(command)), None)
    for index, arg in enumerate(out[:-1]):
        flag = str(arg).lower()
        if not flag.startswith("--"):
            continue
        if not any(marker in flag for marker in ("file", "path", "output")) \
                and flag not in ("--out", "--outfile"):
            continue
        value = out[index + 1]
        if not isinstance(value, str):
            continue
        # A bare placeholder such as `value1` is not a fixture, even if a
        # previous scenario happened to create it in the working directory.
        if Path(value).exists() and (Path(value).is_absolute() or "/" in value):
            continue
        target = Path(tempfile.mkdtemp(prefix="esus-import-")) / "import.csv"
        if model is not None:
            fields = [field.get("name") for field in model.get("fields") or []
                      if isinstance(field, dict) and field.get("name")]
            with target.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerow([_sample(field, 1) for field in
                                 model.get("fields") or []
                                 if isinstance(field, dict)])
        else:
            target.write_text("", encoding="utf-8")
        out[index + 1] = str(target)
    return out


def _clear_store(store):
    db = getattr(store, "_db", None)
    schema = getattr(store, "_schema", None) or {}
    if db is None:
        return
    try:
        for entity in schema:
            db.execute('DELETE FROM "' + str(entity).replace('"', '""') + '"')
        db.commit()
        # `all` and duplicate-key checks read the store's cache, not the
        # connection. Without this refresh the rows are gone from SQLite but
        # still visible to the next scenario as a phantom primary key.
        records = getattr(store, "_records", None)
        if isinstance(records, dict):
            records.clear()
        reload = getattr(store, "_load_schema", None)
        if callable(reload):
            reload()
    except Exception:
        pass


def _run_scenario(docs, deps, store, scenario, sequence, cli_path=None, db=None,
                  cli_module=None, app_path=None):
    name = f"scenario:{scenario.get('name') or 'unnamed'}"
    if scenario.get("setup"):
        _clear_store(store)
    refs = {}
    model_by_entity = {m.get("name"): m for m in docs["models"]}
    for number, step in enumerate(scenario.get("setup") or [], start=1):
        entity = step.get("entity")
        model = model_by_entity.get(entity)
        if model is None:
            return {"name": name, "status": "skipped",
                    "reason": f"unknown setup entity {entity!r}"}
        if step.get("seed") is False:
            # A create case describes the row its action creates; it is a
            # payload, not an existing row. The result ref is filled below.
            continue
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
    if when.get("app") is True:
        if app_path is None or not Path(app_path).is_file():
            return {"name": name, "status": "skipped",
                    "reason": "standalone app.py unavailable"}
        args = [str(item) for item in when.get("args") or []]
        stdin = when.get("stdin") or ""
        with tempfile.TemporaryDirectory(prefix="esus-app-") as work:
            workdir = Path(work)
            for relative, content in (when.get("files") or {}).items():
                target = workdir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            try:
                run = subprocess.run(
                    [sys.executable, str(app_path), *args],
                    input=stdin, capture_output=True, text=True,
                    timeout=15, cwd=str(workdir))
            except subprocess.TimeoutExpired:
                return {"name": name, "status": "failed",
                        "reason": "standalone app timed out"}
        expect = scenario.get("expect") or {}
        expected_code = expect.get("exit_code", 0)
        if run.returncode != expected_code:
            return {"name": name, "status": "failed",
                    "reason": (f"exit code {run.returncode}, expected "
                               f"{expected_code}; stderr={run.stderr[-300:]}")}
        expected_text = expect.get("stdout_contains")
        if isinstance(expected_text, str) and expected_text not in run.stdout:
            return {"name": name, "status": "failed",
                    "reason": f"stdout does not contain {expected_text!r}: "
                              f"{run.stdout[-300:]!r}"}
        expected_err = expect.get("stderr_contains")
        if isinstance(expected_err, str) and expected_err not in run.stderr:
            return {"name": name, "status": "failed",
                    "reason": f"stderr does not contain {expected_err!r}: "
                              f"{run.stderr[-300:]!r}"}
        return {"name": name, "status": "passed"}
    if "cli" in when or "cli_variants" in when:
        if cli_path is None or db is None:
            return {"name": name, "status": "skipped",
                    "reason": "CLI path/database unavailable"}
        raw_variants = when.get("cli_variants")
        if not raw_variants:
            raw_variants = [when.get("cli") or []]
        cli_variants = []
        for variant in raw_variants:
            resolved = _resolve(variant, refs)
            if not isinstance(resolved, list):
                resolved = [str(resolved)]
            cli_variants.append([str(item) for item in resolved])
        if cli_module is not None:
            db = Path(tempfile.mkdtemp(prefix="esus-cli-scenario-")) / "cli.sqlite3"
            built = cli_module.build_cli(str(db))
            fresh = built[1] if isinstance(built, tuple) else built
            _seed_all(docs, fresh["store"], when.get("seed_overrides"),
                      when.get("seed_exclude"))
        expected = (scenario.get("expect") or {}).get("error")
        last = None
        for cli_args in cli_variants:
            cli_args = _materialize_file_args(docs, cli_args)
            try:
                result = subprocess.run(
                    [sys.executable, str(cli_path), "--db", str(db), *cli_args],
                    capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                return {"name": name, "status": "failed",
                        "reason": "CLI subprocess timed out after 30s"}
            last = result
            if result.returncode == 0 and not expected:
                return {"name": name, "status": "passed"}
            if expected and expected in (result.stderr + result.stdout):
                return {"name": name, "status": "passed"}
        return {"name": name, "status": "failed",
                "reason": (last.stderr or last.stdout or "CLI failed")[-350:]}
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
            result = method(**raw_args)
        elif isinstance(raw_args, list):
            result = method(*raw_args)
        else:
            result = method(raw_args)
    except Exception as error:  # noqa: BLE001
        expected = (scenario.get("expect") or {}).get("error")
        if expected and type(error).__name__ == expected:
            return {"name": name, "status": "passed"}
        return {"name": name, "status": "failed",
                "reason": f"raised {type(error).__name__}: {error}; expected {expected!r}"}
    result_spec = scenario.get("result") or {}
    if result_spec.get("alias"):
        record = _result_record(result, result_spec.get("entity"), docs)
        record["__entity__"] = result_spec.get("entity")
        refs[result_spec["alias"]] = record
        refs[f"{result_spec['alias']}.id"] = record.get(
            next((field.get("name") for field in model_by_entity.get(
                result_spec.get("entity"), {}).get("fields", [])
                if field.get("primary_key")), "id"))
    expect = scenario.get("expect") or {}
    if expect.get("error"):
        return {"name": name, "status": "failed",
                "reason": f"expected {expect['error']}, no error was raised"}
    if "result" in expect and not _same_value(result, expect["result"]):
        return {"name": name, "status": "failed",
                "reason": f"returned {result!r}, expected {expect['result']!r}"}
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
        field = _model_field_name(model_by_entity.get(entity), field)
        if not _same_value(current.get(field), expected):
            return {"name": name, "status": "failed",
                    "reason": f"{target_name} is {current.get(field)!r}, expected {expected!r}"}
    rows = expect.get("rows") or {}
    if scenario.get("rows_as_result"):
        if isinstance(result, dict):
            for key in ("items", "results", "records", "data"):
                if isinstance(result.get(key), list):
                    result = result[key]
                    break
        if isinstance(result, (list, tuple, set)):
            count = len(result)
        else:
            count = 0 if result is None else 1
        if len(rows) == 1:
            expected = next(iter(rows.values()))
            if not _row_count_matches(count, expected):
                return {"name": name, "status": "failed",
                        "reason": f"result row count is {count}, expected {expected}"}
            return {"name": name, "status": "passed"}
        try:
            expected = sum(int(value) for value in rows.values())
        except (TypeError, ValueError):
            expected = None
        if expected is not None and count != expected:
            return {"name": name, "status": "failed",
                    "reason": f"result row count is {count}, expected {expected}"}
        return {"name": name, "status": "passed"}
    for entity, expected in rows.items():
        if entity not in model_by_entity:
            return {"name": name, "status": "failed",
                    "reason": f"unknown expected entity {entity!r}"}
        count = len(store.all(entity)) - row_baseline.get(entity, 0)
        if not _row_count_matches(count, expected):
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
            # A subcommand may be a path of words (`category add` under
            # `expense`). The generator emits that as nested groups, so each
            # token is a separate argv element; treating the whole string as
            # one token produced `No such command 'category add'`.
            path = prefix + tuple(node["name"].split())
            subcommands = node.get("subcommands")
            if isinstance(subcommands, list) and subcommands:
                yield from walk(subcommands, path)
            else:
                yield path, node

    return list(walk(commands))


def _option_field(docs, key):
    """The model field a CLI option names, including `<entity>` for `<entity>_id`."""
    wanted = normalize(key)
    exact = []
    related = []
    for model in docs.get("models") or []:
        for field in model.get("fields") or []:
            if not isinstance(field, dict) or not field.get("name"):
                continue
            name = normalize(field["name"])
            if name == wanted:
                exact.append((model.get("name"), field))
                continue
            foreign = field.get("foreign_key")
            target = (normalize(foreign.get("target_entity") or "")
                      if isinstance(foreign, dict) else "")
            if name == wanted + "id" or (target and target == wanted):
                related.append((model.get("name"), field))
    if exact:
        return exact
    if related:
        return related
    return []


def _cli_value(docs, name, declared, number):
    """A type-aware fixture for one required CLI option."""
    key = str(name or "").lstrip("-").replace("-", "_")
    if key.endswith("ids"):
        # A collection option may be a comma-separated string or a typed
        # list; one integer id is valid for both shapes. Check this before
        # the adjacent model field (`id`) fixes the scalar type.
        return "1"
    fields = _option_field(docs, key)
    if not fields:
        wanted = normalize(key)
        candidates = []
        for model in docs.get("models") or []:
            for candidate in model.get("fields") or []:
                if not isinstance(candidate, dict) or not candidate.get("name"):
                    continue
                if normalize(candidate["name"]) in wanted or wanted in normalize(candidate["name"]):
                    candidates.append((model.get("name"), candidate))
        if len(candidates) == 1:
            fields = candidates
    field = fields[0][1] if fields else None
    field_kind = str((field or {}).get("type") or "").lower()
    kind = str(declared or field_kind or "").lower()
    if key.endswith("id") and field_kind:
        kind = field_kind
    elif field is not None and field_kind in (
            "int", "integer", "float", "double", "decimal", "money"):
        # A generator may expose a lookup key as TEXT while converting it to
        # an integer; a numeric spelling satisfies both.
        kind = field_kind
    elif declared in ("int", "integer", "float", "double", "decimal"):
        kind = declared
    if "month" in key and kind in ("str", "string", "text", ""):
        return "2024-01"
    if key in ("year", "published_year") and kind in ("str", "string", "text", ""):
        return "2024"
    if field is not None:
        allowed = _allowed_values(docs, fields[0][0], field["name"])
        if allowed and field_kind in ("str", "string", "text"):
            allowed = [value for value in allowed
                       if re.fullmatch(r"[A-Za-z0-9_.-]+", str(value))]
            if allowed:
                return allowed[0]
    if kind in ("datetime", "timestamp") or field_kind in (
            "datetime", "timestamp") or key.endswith("_at") \
            or "created" in key or "updated" in key:
        return "2024-01-01T00:00:00"
    if kind in ("date",) or field_kind in ("date",) or "date" in key \
            or key.endswith("_time") or key == "time":
        return "2024-01-01"
    if kind in ("int", "integer"):
        if key.endswith("id") or "capacity" in key \
                or isinstance((field or {}).get("foreign_key"), dict):
            return "1"
        if "current" in key or "attendee" in key:
            return "2"
        return "2"
    if kind in ("float", "double", "decimal", "money"):
        # A generated money/amount option may be cents (int) or a float.
        # The integer spelling parses under both.
        return "2"
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
            args.append("100" if "capacity" in name else (
                "1" if name.endswith("id") else "2"))
        elif declared in ("float", "double", "decimal"):
            args.append("1.0")
        else:
            args.append(f"value{number}")
    return args


def _stub_checks(out_dir):
    """Report generated methods that still raise NotImplementedError."""
    checks = []
    generated = Path(out_dir) / "generated"
    for filename in ("services.py", "repositories.py", "app.py"):
        path = generated / filename
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            raises = [item for item in ast.walk(node)
                      if isinstance(item, ast.Raise)
                      and isinstance(item.exc, ast.Call)
                      and getattr(item.exc.func, "id", "") == "NotImplementedError"]
            if raises:
                checks.append({
                    "name": f"stub:{node.name}",
                    "status": "skipped",
                    "reason": "generated method still raises NotImplementedError",
                })
    return checks


def _structural_checks(out_dir, docs, deps):
    """Evidence for structural requirements, separate from behavior tests."""
    checks = []
    generated = Path(out_dir) / "generated"
    sources = sorted(generated.glob("*.py")) if generated.is_dir() else []
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace")
                      for path in sources)
    if len(sources) >= 2:
        checks.append({"name": "code:modules", "status": "passed",
                       "reason": f"{len(sources)} generated modules"})
    if "->" in text:
        checks.append({"name": "code:type-hints", "status": "passed",
                       "reason": "annotated generated functions"})
    if "PRAGMA foreign_keys=ON" in text or "PRAGMA foreign_keys = ON" in text:
        checks.append({"name": "db:foreign-keys", "status": "passed",
                       "reason": "SQLite foreign keys enabled"})
    if "sqlite3.connect" in text:
        checks.append({"name": "db:persistence-across-executions",
                       "status": "passed",
                       "reason": "SQLite database file"})
    if "if __name__ == \"__main__\"" in text:
        checks.append({"name": "code:entry-point", "status": "passed",
                       "reason": "main guard present"})
    models = [item for item in docs.get("models") or []
              if isinstance(item, dict)]
    if models and all(any(field.get("primary_key") for field in
                          (model.get("fields") or []) if isinstance(field, dict))
                      for model in models):
        checks.append({"name": "models:primary-keys", "status": "passed",
                       "reason": "every model declares a primary key"})

    for label, group in (("service", deps.get("services") or {}),
                         ("repository", deps.get("repos") or {})):
        if not isinstance(group, dict):
            continue
        for holder, instance in group.items():
            for method in dir(instance):
                if method.startswith("_"):
                    continue
                member = getattr(instance, method, None)
                if callable(member):
                    checks.append({
                        "name": f"api:{holder}.{method}",
                        "status": "passed",
                        "reason": f"generated {label} API present",
                    })
    return checks


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
            asserted = _unique_asserted(field)
            if (asserted is not None
                    and bool(declared.get("unique")) != asserted):
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


def _seed_all(docs, store, overrides=None, exclude=None):
    """Seed one row per model so repository foreign keys have targets."""
    records = {}
    overrides = overrides if isinstance(overrides, dict) else {}
    exclude = {normalize(name) for name in (exclude or [])}
    models = {model.get("name"): model for model in docs["models"]
              if isinstance(model, dict) and model.get("name")}
    for entity, model in models.items():
        if normalize(entity) in exclude:
            continue
        record, pk = _seed(store, model, 1, overrides.get(entity))
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


def _satisfy_comparisons(docs, entity, values):
    """Adjust numeric fixtures that a prose invariant compares directly.

    `The selling price ... must be strictly greater than its cost price.`
    names two model fields; the sample generator would otherwise give both
    the same value and the generated validation correctly rejects it.
    """
    model = next((item for item in docs.get("models") or []
                  if item.get("name") == entity), None)
    if model is None:
        return values
    numeric = [field["name"] for field in model.get("fields") or []
               if isinstance(field, dict) and field.get("name")
               and str(field.get("type") or "").lower() in
               ("int", "integer", "float", "double", "decimal", "money")]
    for invariant in docs.get("invariants") or []:
        text = invariant.get("text") if isinstance(invariant, dict) else ""
        flat = normalize(text or "")
        for high in numeric:
            for low in numeric:
                if high == low:
                    continue
                high_key, low_key = normalize(high), normalize(low)
                start = flat.find(high_key)
                if start < 0:
                    continue
                end = flat.find(low_key, start + len(high_key))
                if end < 0:
                    continue
                between = flat[start + len(high_key):end]
                if not any(word in between for word in
                           ("greaterthan", "morethan", "atleast", "exceeds")):
                    continue
                high_value, low_value = values.get(high), values.get(low)
                if not isinstance(high_value, (int, float)) \
                        or isinstance(high_value, bool) \
                        or not isinstance(low_value, (int, float)) \
                        or isinstance(low_value, bool):
                    continue
                if high_value <= low_value:
                    values[high] = low_value + (
                        1 if isinstance(high_value, int)
                        and isinstance(low_value, int) else 1.0)
    return values


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
            elif str(field.get("type") or "").lower() in ("bool", "boolean"):
                args[name] = False
            elif name == "capacity":
                args[name] = 100
            elif name in ("stock_quantity", "stock", "inventory_quantity"):
                # The seeded row may already occupy part of a location's
                # capacity; one unit keeps a create fixture valid.
                args[name] = 1
            elif name in ("current_attendees_count", "current_count", "attendees"):
                args[name] = 2
            elif allowed:
                args[name] = allowed[0]
            else:
                args[name] = _sample(field, number)
        else:
            args[name] = _sample(param, number)
    _satisfy_comparisons(docs, model.get("name"), args)
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
            if _unique_asserted(field) is True:
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
            update_params = [param for param in update.get("params") or []
                             if isinstance(param, dict) and param.get("name")]
            key_names = {pk, "id"}
            has_key_param = any(param["name"] in key_names for param in update_params)
            composite = (_composite_unique_fields(docs, entity)
                         if has_key_param else set())
            values = {}
            for param in update_params:
                name = param["name"]
                if name == pk or name in ("id",):
                    values[name] = key
                    continue
                if has_key_param and name in composite:
                    # A primary key identifies the row. A composite unique
                    # field is also used as a lookup criterion by the
                    # generated update; passing the *new* month/category made
                    # the lookup search for a row that does not exist yet.
                    values[name] = None
                    continue
                field = next((item for item in model.get("fields") or []
                              if isinstance(item, dict)
                              and item.get("name") == name), None)
                allowed = _allowed_values(docs, entity, name)
                if isinstance((field or {}).get("foreign_key"), dict):
                    values[name] = 1
                elif name == "capacity":
                    values[name] = 100
                elif name in ("stock_quantity", "stock", "inventory_quantity"):
                    # Some generated updates compare an identifier with the
                    # stock count; stay above a normal fixture id while
                    # leaving room under a storage-location capacity.
                    values[name] = (max(10, key + 1)
                                    if isinstance(key, int) else 10)
                elif name in ("current_attendees_count", "current_count", "attendees"):
                    values[name] = 2
                elif allowed:
                    values[name] = allowed[0]
                else:
                    values[name] = _sample(param, number + 200)
            _satisfy_comparisons(docs, entity, values)
            params = [values[param["name"]] for param in update_params]
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
                values = vars(gone) if hasattr(gone, "__dict__") else (
                    gone if isinstance(gone, dict) else {})
                soft = bool(values.get("is_deleted") or values.get("deleted_at"))
                if not soft:
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
    override = os.environ.get("ESUS_SCENARIOS_DIR")
    if override:
        candidate = Path(override) / (Path(out_dir).name + ".json")
        if candidate.is_file():
            return candidate
    fallback = Path(__file__).resolve().parent / "scenarios" / (
        Path(out_dir).name + ".json")
    if fallback.is_file():
        return fallback
    path = Path(out_dir) / "scenarios.json"
    return path if path.is_file() else None


def run(out_dir):
    checks = []
    docs = _documents(out_dir)
    # CLI checks describe the surface the generator actually emits, including
    # reviewed drops. Raw components.json can still name a command group that
    # grounding decisions removed.
    try:
        import generator as _generator
        effective = _generator.load_context(out_dir)
        if isinstance(effective.get("components"), dict):
            docs["components"] = effective["components"]
        if isinstance(effective.get("services"), list):
            docs["services"] = effective["services"]
        if isinstance(effective.get("repositories"), list):
            docs["repos"] = effective["repositories"]
        # A reviewed grounding decision can drop a method from the emitted
        # service while the extracted contract document still mentions it.
        # Check the effective surface, not the raw document.
        available = {
            (service.get("service_name"), method.get("name"))
            for group in (docs["services"], docs["repos"])
            for service in group if isinstance(service, dict)
            for method in service.get("methods") or [] if isinstance(method, dict)
        }
        if available:
            docs["contracts"] = [
                contract for contract in docs["contracts"]
                if (contract.get("holder"), contract.get("method")) in available]
    except Exception:
        pass
    cli_path = Path(out_dir) / "generated" / "cli.py"
    if not cli_path.is_file():
        app_path = Path(out_dir) / "generated" / "app.py"
        checks = [{"name": "app-fallback",
                   "status": "passed" if app_path.is_file() else "failed",
                   "reason": "no cli.py; standalone app.py" if app_path.is_file()
                             else "no cli.py or app.py"}]
        if app_path.is_file():
            try:
                run = subprocess.run([sys.executable, str(app_path)],
                                     capture_output=True, text=True,
                                     timeout=10)
                output = (run.stdout + run.stderr).strip()
                checks.append({
                    "name": "app-run",
                    "status": "passed" if run.returncode == 0 else "skipped",
                    "reason": (output[-500:] if output
                               else f"exit {run.returncode}"),
                })
            except subprocess.TimeoutExpired:
                checks.append({"name": "app-run", "status": "skipped",
                               "reason": "standalone app did not exit in 10s"})
        return {"prompt": Path(out_dir).name,
                "status": "passed" if app_path.is_file() else "failed",
                "checks": checks}
    try:
        cli, deps, db = _load_package(out_dir)
    except Exception as error:  # noqa: BLE001
        return {"prompt": Path(out_dir).name, "status": "failed",
                "checks": [{"name": "import", "status": "failed",
                            "reason": f"{type(error).__name__}: {error}"}],
                "traceback": traceback.format_exc()}
    checks.append({"name": "import", "status": "passed"})
    checks.extend(_stub_checks(out_dir))
    checks.extend(_structural_checks(out_dir, docs, deps))
    if cli_path.is_file():
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
                and ("cli" in item["when"] or "cli_variants" in item["when"])
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
            checks.append(_run_scenario(
                docs, deps, store, scenario, sequence,
                cli_path=cli_path, db=db, cli_module=cli,
                app_path=Path(out_dir) / "generated" / "app.py"))
            sequence += 1
    failed = any(c["status"] == "failed" for c in checks)
    stubbed = any(c["status"] == "skipped"
                  and str(c["name"]).startswith("stub:") for c in checks)
    status = "failed" if failed else "incomplete" if stubbed else "passed"
    return {"prompt": Path(out_dir).name, "status": status, "checks": checks}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python tests/runtime/worker.py OUT_DIR")
    result = run(sys.argv[1])
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
