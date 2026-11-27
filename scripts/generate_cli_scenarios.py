#!/usr/bin/env python3
"""Generate CLI scenarios from the extracted command surface.

Each leaf becomes a JSON scenario executed by tests/runtime/worker.py. Required
and typed options are filled from the model invariants; semantic scenarios
already present for a prompt are preserved and appear first.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "runtime"))

import generator  # noqa: E402
import worker  # noqa: E402


def _help_flags(cli_path, path):
    """Option spellings the emitted parser accepts for one leaf."""
    try:
        result = subprocess.run(
            [sys.executable, str(cli_path), *path, "--help"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    flags = []
    for match in re.finditer(r"--[a-z0-9][a-z0-9-]*", result.stdout + result.stderr):
        flag = match.group(0)
        if flag in ("--db", "--help") or flag in flags:
            continue
        flags.append(flag)
    return flags


def _seed_arg_value(field):
    kind = str(field.get("type") or "").strip().lower()
    name = str(field.get("name") or "").lower()
    if field.get("primary_key") or name.endswith("_id"):
        return "1"
    if "email" in name:
        return "seed1@example.test"
    if kind in ("int", "integer"):
        return "100" if "capacity" in name else "2"
    if kind in ("float", "double", "decimal", "money"):
        return "2.0"
    if kind in ("datetime", "timestamp"):
        return "2024-01-01T00:00:00"
    if kind == "date":
        return "2024-01-01"
    if kind in ("bool", "boolean"):
        return "false"
    return "value1"


def _model_for_path(docs, path):
    models = {worker.normalize(model.get("name") or ""): model
              for model in docs.get("models") or []
              if isinstance(model, dict) and model.get("name")}
    for token in reversed(path[:-1]):
        model = models.get(worker.normalize(token))
        if model is not None:
            return model
    return None


def _field_for_option(model, key):
    wanted = worker.normalize(key)
    fields = [field for field in model.get("fields") or []
              if isinstance(field, dict) and field.get("name")]
    for field in fields:
        if worker.normalize(field["name"]) == wanted:
            return field
    for field in fields:
        if worker.normalize(field["name"]) == wanted + "id":
            return field
    suffixes = [field for field in fields
                if worker.normalize(field["name"]).endswith(wanted)]
    if len(suffixes) == 1:
        return suffixes[0]
    for field in fields:
        foreign = field.get("foreign_key")
        if isinstance(foreign, dict) \
                and worker.normalize(foreign.get("target_entity") or "") == wanted:
            return field
    return None


def _coerce_seed(value, field):
    kind = str(field.get("type") or "").lower()
    try:
        if kind in ("int", "integer"):
            return int(value)
        if kind in ("float", "double", "decimal", "money"):
            return float(value)
        if kind in ("bool", "boolean"):
            return str(value).lower() in ("1", "true", "yes", "on")
    except (TypeError, ValueError):
        return value
    return value


def _update_seed_overrides(docs, path, args):
    """Seed filter fields with the values an update/delete command looks up."""
    model = _model_for_path(docs, path)
    if model is None:
        return {}
    overrides = {}
    index = 0
    while index < len(args):
        flag = str(args[index])
        if (not flag.startswith("--") or index + 1 >= len(args)
                or str(args[index + 1]).startswith("--")):
            index += 1
            continue
        key = flag.lstrip("-").replace("-", "_")
        field = _field_for_option(model, key)
        if field is not None and not field.get("primary_key"):
            overrides[field["name"]] = _coerce_seed(args[index + 1], field)
        index += 2
    return overrides


_UNIQUE_COUNTER = 0


def _coerce_declared(value, declared):
    """Spell a fixture value the parser's declared option type accepts."""
    kind = str(declared or "").lower()
    if value is None:
        return value
    if kind in ("int", "integer"):
        try:
            return str(int(float(str(value))))
        except (TypeError, ValueError):
            return value
    if kind in ("float", "double", "decimal", "money"):
        try:
            return str(float(value))
        except (TypeError, ValueError):
            return value
    return value


def _unique_value(value):
    """Make a generated string unique across scenarios."""
    global _UNIQUE_COUNTER
    if not isinstance(value, str) or not value.startswith("value"):
        return value
    _UNIQUE_COUNTER += 1
    return f"{value}-{_UNIQUE_COUNTER}"


def _coerce_args(args, declared):
    for index, item in enumerate(args):
        if not isinstance(item, str) or item not in declared:
            continue
        if index + 1 >= len(args) or str(args[index + 1]).startswith("--"):
            continue
        args[index + 1] = _coerce_declared(args[index + 1], declared[item])
    return args


def _repair_total(args):
    """Keep quantity x unit-price consistent with a total/line-total flag."""
    positions = {str(value): index for index, value in enumerate(args)
                 if isinstance(value, str) and value.startswith("--")}
    quantity = positions.get("--quantity")
    unit = positions.get("--unit-price")
    total = positions.get("--total-price", positions.get("--line-total"))
    if quantity is None or unit is None or total is None:
        return args
    try:
        product = float(args[quantity + 1]) * float(args[unit + 1])
    except (IndexError, TypeError, ValueError):
        return args
    args[total + 1] = str(int(product)) if product.is_integer() else str(product)
    return args


def _seed_args_from_flags(docs, flags, node=None):
    declared = getattr(_seed_args_from_flags, "declared", {})
    if node is not None:
        declared = {option.get("name"): option
                    for option in node.get("options") or []
                    if isinstance(option, dict) and option.get("name")}
        _seed_args_from_flags.declared = declared
    args = []
    for flag in flags:
        args.append(flag)
        key = str(flag).lstrip("-").replace("-", "_")
        found = None
        for model in docs.get("models") or []:
            for field in model.get("fields") or []:
                if (isinstance(field, dict)
                        and str(field.get("name") or "").lower() == key):
                    found = field
                    break
            if found is not None:
                break
        if found is not None:
            args.append(_seed_arg_value(found))
    kinds = {name: str(option.get("type") or "")
             for name, option in declared.items()
             if isinstance(option, dict)}
    return _coerce_args(args, kinds)


def _args_from_flags(docs, flags, node=None, path=None):
    declared = {}
    required = set()
    for option in (node or {}).get("options") or []:
        if isinstance(option, dict) and isinstance(option.get("name"), str):
            declared[option["name"]] = str(option.get("type") or "")
            if option.get("required"):
                required.add(option["name"])
    all_flags = list(flags)
    # A success scenario should exercise the required surface, not every
    # optional flag. Optional booleans such as --is-deleted otherwise turn a
    # create into a delete and break the following read.
    if required:
        flags = [flag for flag in flags if flag in required]

    model = _model_for_path(docs, path or [])
    def sort_field():
        for field in (model or {}).get("fields") or []:
            if (isinstance(field, dict) and field.get("name")
                    and not field.get("primary_key")
                    and not field.get("foreign_key")):
                return str(field["name"])
        return "name"

    args = []
    for flag in flags:
        key = flag.lstrip("-").replace("-", "_")
        if key in ("is_deleted", "deleted", "is_archived", "archived"):
            continue
        if flag == "--sort-by":
            args += [flag, sort_field()]
            continue
        if (str(declared.get(flag, "")).lower() in ("bool", "boolean")
                or key.startswith(("is_", "has_"))
                or key in ("closed", "available", "active", "recurring",
                           "enabled", "disabled", "archived", "paid",
                           "confirmed", "completed")):
            args.append(flag)
            continue
        field = _field_for_option(model, key) if model else None
        allowed = []
        if (field is not None and not field.get("primary_key")
                and not key.endswith("id")
                and str(field.get("type") or "").lower() in
                ("str", "string", "text")):
            allowed = worker._allowed_values(
                docs, model.get("name"), field["name"])
        if flag == "--capacity":
            value = "100"
        elif allowed:
            value = allowed[0]
        else:
            value = worker._cli_value(docs, flag, declared.get(flag, ""), 1)
        if value is not None:
            if field is not None and field.get("unique"):
                value = _unique_value(value)
            args += [flag, value]
    # A model can require a non-null field whose CLI option is optional or
    # absent. Only create-like commands need those fields; update/sort/delete
    # commands should exercise their required lookup surface.
    if not path or str(path[-1]).lower() not in ("add", "create", "register"):
        return _coerce_args(_repair_total(args), declared)
    for field in (model or {}).get("fields") or []:
        if not isinstance(field, dict) or not field.get("name"):
            continue
        key = worker.normalize(field["name"])
        if (field.get("primary_key") or field.get("nullable") is not False
                or field.get("default") is not None
                or key in ("isdeleted", "deleted", "isarchived", "archived")):
            continue
        flag = next((item for item in all_flags
                     if worker.normalize(item.lstrip("-").replace("-", "_")) == key
                     or key.endswith(worker.normalize(item.lstrip("-").replace("-", "_")))
                     or worker.normalize(item.lstrip("-").replace("-", "_")) in key),
                    None)
        # Never invent a flag the emitted parser does not accept: a scenario
        # that passes `--balance` when the surface declares
        # `--initial-balance` tests argparse, not the application.
        if flag is None or flag in args:
            continue
        if str(field.get("type") or "").lower() in ("bool", "boolean"):
            args.append(flag)
        else:
            allowed = []
            if (not field.get("primary_key") and not key.endswith("id")
                    and str(field.get("type") or "").lower() in
                    ("str", "string", "text")):
                allowed = worker._allowed_values(
                    docs, model.get("name"), field["name"])
            value = ("100" if key == "capacity"
                     else allowed[0] if allowed else _seed_arg_value(field))
            if field.get("unique"):
                value = _unique_value(value)
            args += [flag, value]
    return _coerce_args(_repair_total(args), declared)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0] if args else "out/validation/bench")
    target = Path(args[1]) if len(args) > 1 else ROOT / "tests" / "runtime" / "scenarios"
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for prompt in worker.discover_projects(root):
        docs = worker._documents(prompt)
        # Scenarios describe the surface the generator actually emits: reviewed
        # drops, required create flags, and adapter repairs are applied there.
        try:
            context = generator.load_context(prompt)
            docs = dict(docs)
            docs["components"] = context.get("components") or docs["components"]
        except Exception:
            pass
        path_file = target / f"{prompt.name}.json"
        existing = []
        if path_file.is_file():
            try:
                existing = json.loads(path_file.read_text()).get("scenarios") or []
            except ValueError:
                existing = []
        scenarios = [item for item in existing
                     if not str(item.get("name", "")).startswith("cli:")]
        cli_path = prompt / "generated" / "cli.py"
        leaves = worker._leaf_entries(docs.get("components")) if cli_path.is_file() else []
        for number, (path, node) in enumerate(leaves, start=1):
            flags = _help_flags(cli_path, path)
            # An import/input leaf needs a real file, not the placeholder the
            # generic seeder supplies. Auto-generating `--file-path value1`
            # tests JSON parsing of a non-file, not the import; the explicit
            # scenario owns that command.
            file_flags = {
                "filepath", "inputfile", "csvfile", "jsonfile",
                "inputpath", "sourcefile", "file",
            }
            if any(worker.normalize(str(flag).lstrip("-")) in file_flags
                   for flag in flags):
                continue
            # A structured request/DTO flag (`--order-data`) cannot be
            # supplied by a one-token CLI fixture; the explicit scenario owns
            # that shape.
            if any(worker.normalize(str(flag).lstrip("-")).endswith(
                    ("data", "request", "payload", "dto")) for flag in flags):
                continue
            args = (_args_from_flags(docs, flags, node, path) if flags
                    else worker._cli_args(docs, node, 1))
            if str(path[-1]).lower() in ("delete", "remove") and flags:
                args = _seed_args_from_flags(docs, flags, node)
            variants = [list(path) + list(args)]
            if str(path[-1]).lower() in ("delete", "remove"):
                key_args = []
                for flag in flags:
                    if str(flag).endswith("-id"):
                        key_args = [flag, "1"]
                        break
                if not key_args:
                    for option in node.get("options") or []:
                        if (isinstance(option, dict) and option.get("required")
                                and str(option.get("name") or "").endswith("id")):
                            key_args = [option["name"], "1"]
                            break
                if key_args:
                    variants.append(list(path) + key_args)
            # A boolean flag can be emitted either as a presence switch or as
            # a value-taking option. Add the value-taking spelling as a
            # fallback; the first variant remains the canonical one.
            base = list(path) + list(args)
            value_variant = list(base)
            for index, item in enumerate(base):
                if not str(item).startswith("--"):
                    continue
                key = str(item).lstrip("-").replace("-", "_")
                if (key.startswith(("is_", "has_"))
                        or key in ("closed", "available", "active",
                                   "recurring", "enabled", "disabled",
                                   "archived", "paid", "confirmed",
                                   "completed")):
                    continue
                following = base[index + 1] if index + 1 < len(base) else None
                if following is None or str(following).startswith("--"):
                    value_variant.insert(
                        value_variant.index(item) + 1, "true")
            if value_variant != base:
                variants.append(value_variant)
            overrides = {}
            verb = str(path[-1]).lower()
            state_value = {"confirm": "pending", "ship": "confirmed",
                           "cancel": "confirmed"}.get(verb)
            if state_value:
                for model in docs.get("models") or []:
                    if not isinstance(model, dict) or not model.get("name"):
                        continue
                    for field in model.get("fields") or []:
                        if not isinstance(field, dict) or not field.get("name"):
                            continue
                        field_key = worker.normalize(field["name"])
                        if (field_key in ("state", "status")
                                or field_key.endswith("status")):
                            overrides[model["name"]] = {
                                field["name"]: state_value}
                            break
            if verb in ("update", "delete", "remove"):
                target_model = _model_for_path(docs, path)
                if target_model is not None:
                    values = _update_seed_overrides(docs, path, args)
                    if values:
                        overrides.setdefault(target_model["name"], {}).update(
                            values)
            when = {"cli_variants": variants}
            if overrides:
                when["seed_overrides"] = overrides
            if verb in ("add", "create"):
                join_models = []
                for model in docs.get("models") or []:
                    if not isinstance(model, dict) or not model.get("name"):
                        continue
                    fields = [field for field in model.get("fields") or []
                              if isinstance(field, dict) and field.get("name")]
                    if fields and not any(
                            not field.get("primary_key")
                            and not field.get("foreign_key")
                            for field in fields):
                        join_models.append(model["name"])
                if join_models:
                    when["seed_exclude"] = join_models
            scenarios.append({
                "name": "cli:" + " ".join(path),
                "when": when,
                "expect": {"exit": 0},
            })
        if scenarios or path_file.is_file():
            path_file.write_text(json.dumps({"scenarios": scenarios},
                                            indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        total += len(scenarios)
        print(f"{prompt.name}: {len(scenarios)} scenario(s)")
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
