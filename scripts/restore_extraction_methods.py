#!/usr/bin/env python3
"""Restore missing extracted service/repository methods from an older archive.

This is only for a verified extraction regression: the target and source
projects must have identical data models. It never adds fields, changes
expected behavior, or touches generated code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, payload):
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False)
                          + "\n", encoding="utf-8")


def _method_index(holder):
    name_key = "service_name" if "service_name" in holder else "interface_name"
    return {
        (str(holder.get(name_key) or ""), str(method.get("name") or "")): method
        for method in holder.get("methods") or []
        if isinstance(method, dict) and method.get("name")
    }


def _model_signature(models):
    return [
        (str(model.get("name") or ""),
         [(str(field.get("name") or ""), str(field.get("type") or ""))
          for field in model.get("fields") or [] if isinstance(field, dict)])
        for model in models or [] if isinstance(model, dict)
    ]


def restore_project(source, target):
    source_models = (_read(source / "data_models.json") or {}).get("data_models")
    target_models = (_read(target / "data_models.json") or {}).get("data_models")
    if _model_signature(source_models) != _model_signature(target_models):
        raise ValueError("source and target data models differ")
    changed = []
    for filename, key, head_key in (
            ("service_contracts.json", "service_contracts", "service_name"),
            ("persistence_ports.json", "persistence_ports", "interface_name")):
        source_payload = _read(source / filename) or {}
        target_payload = _read(target / filename) or {}
        if key == "service_contracts":
            source_holders = source_payload.get("service_contracts") or []
            target_holders = target_payload.get("service_contracts") or []
        else:
            source_holders = (source_payload.get("persistence_ports") or {}).get(
                "repositories") or []
            target_holders = (target_payload.get("persistence_ports") or {}).get(
                "repositories") or []
        targets = {str(holder.get(head_key) or ""): holder
                   for holder in target_holders if isinstance(holder, dict)}
        for holder in source_holders:
            if not isinstance(holder, dict):
                continue
            holder_name = str(holder.get(head_key) or "")
            target_holder = targets.get(holder_name)
            if target_holder is None:
                continue
            existing = {method.get("name") for method in
                        target_holder.get("methods") or [] if isinstance(method, dict)}
            for method in holder.get("methods") or []:
                if not isinstance(method, dict) or not method.get("name"):
                    continue
                if method["name"] in existing:
                    continue
                target_holder.setdefault("methods", []).append(method)
                existing.add(method["name"])
                changed.append(f"{filename}:{holder_name}.{method['name']}")
        if changed:
            _write(target / filename, target_payload)
    return changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source_root")
    parser.add_argument("target_root")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    args = parser.parse_args(argv)
    source_root = Path(args.source_root)
    target_root = Path(args.target_root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    projects = [path for path in sorted(target_root.glob("prompt_*"))
                if path.is_dir()
                and (wanted is None or path.name in wanted)
                and (source_root / path.name).is_dir()]
    if not projects:
        raise SystemExit("no matching projects")
    total = 0
    for target in projects:
        changed = restore_project(source_root / target.name, target)
        total += len(changed)
        print(f"{target.name}: {len(changed)} restored method(s)")
        for item in changed:
            print(f"  + {item}")
    print(f"total: {total} restored method(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
