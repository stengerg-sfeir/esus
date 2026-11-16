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
        return "1" if "capacity" in name else "2"
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
    return args


def _args_from_flags(docs, flags, node=None):
    declared = {}
    for option in (node or {}).get("options") or []:
        if isinstance(option, dict) and isinstance(option.get("name"), str):
            declared[option["name"]] = str(option.get("type") or "")
    args = []
    for flag in flags:
        args.append(flag)
        value = worker._cli_value(docs, flag, declared.get(flag, ""), 1)
        if value is not None:
            args.append(value)
    return args


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
            args = (_args_from_flags(docs, flags, node) if flags
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
                        if (isinstance(field, dict)
                                and str(field.get("name")).lower()
                                in ("state", "status")):
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
