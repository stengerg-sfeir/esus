#!/usr/bin/env python3
"""Plan or apply review-sidecar reuse after a fresh extraction.

A sidecar is only meaningful for the extraction surface it was reviewed
against. Compare the fresh project's commands, models, services, repositories,
adapters and requirements hash with a reference run. Matching projects may
copy the reviewed sidecars; mismatching projects must be reviewed/regenerated
instead of replaying stale decisions.

Usage:
    python3 scripts/plan_review_sidecars.py RUN_ROOT --reference REF_ROOT
    python3 scripts/plan_review_sidecars.py RUN_ROOT --reference REF_ROOT --copy

The comparison is read-only unless --copy is passed. It writes
<RUN_ROOT>/sidecar_plan.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SIDECARS = (
    "decisions.json",
    "method_slots.json",
    "surface_decisions.json",
    "method_contracts.json",
    "grounding_decisions.json",
    "unique_decisions.json",
    "flag_decisions.json",
    "aggregate_decisions.json",
)


def load(path, key):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload.get(key) if isinstance(payload, dict) else payload


def commands(components):
    facade = (components or {}).get("facade") if isinstance(components, dict) else None
    invocation = (facade or {}).get("invocation") if isinstance(facade, dict) else None
    found = []
    for command in (invocation or {}).get("commands") or []:
        if not isinstance(command, dict):
            continue
        found.append([
            command.get("name"),
            sorted(sub.get("name") for sub in command.get("subcommands") or []
                   if isinstance(sub, dict) and sub.get("name")),
        ])
    return sorted(found, key=lambda item: str(item[0]))


def names(values, key):
    return sorted(str(item.get(key) or "") for item in values or []
                  if isinstance(item, dict) and item.get(key))


def signatures(project):
    components = load(project / "components.json", "components")
    models = load(project / "data_models.json", "data_models")
    services = load(project / "service_contracts.json", "service_contracts")
    ports = load(project / "persistence_ports.json", "persistence_ports") or {}
    adapters = load(project / "interaction_adapters.json", "interaction_adapters")
    requirements = project / "requirements.txt"
    requirement_hash = (
        hashlib.sha256(requirements.read_bytes()).hexdigest()
        if requirements.is_file() else None)
    service_signatures = {}
    for service in services or []:
        if isinstance(service, dict) and service.get("service_name"):
            service_signatures[service["service_name"]] = names(
                service.get("methods"), "name")
    repo_signatures = {}
    for repo in (ports.get("repositories") if isinstance(ports, dict) else []) or []:
        if isinstance(repo, dict) and repo.get("interface_name"):
            repo_signatures[repo["interface_name"]] = names(
                repo.get("methods"), "name")
    adapter_signature = sorted(
        (str(adapter.get("action_name") or ""),
         str(adapter.get("target_service") or ""),
         str(adapter.get("target_method") or ""))
        for adapter in adapters or [] if isinstance(adapter, dict))
    return {
        "requirements_sha256": requirement_hash,
        "commands": commands(components),
        "models": names(models, "name"),
        "services": sorted(service_signatures.items()),
        "repositories": sorted(repo_signatures.items()),
        "adapters": adapter_signature,
    }


def diff(fresh, reference):
    changes = {}
    for key in fresh:
        if fresh.get(key) != reference.get(key):
            changes[key] = {"fresh": fresh.get(key), "reference": reference.get(key)}
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", help="fresh validation run root")
    parser.add_argument("--reference", required=True, help="reviewed reference run")
    parser.add_argument("--copy", action="store_true",
                        help="copy matching sidecars into the fresh run")
    parser.add_argument("--output", default=None,
                        help="plan path (default: <run>/sidecar_plan.json)")
    args = parser.parse_args(argv)

    run = Path(args.run)
    reference = Path(args.reference)
    projects = []
    matched = mismatched = pending = copied = 0
    for fresh_project in sorted(run.glob("prompt_*")):
        if not fresh_project.is_dir():
            continue
        ref_project = reference / fresh_project.name
        fresh_sig = signatures(fresh_project)
        ref_sig = signatures(ref_project)
        if not (fresh_project / "components.json").is_file():
            status = "pending"
            changes = {}
            pending += 1
        elif (fresh_sig["requirements_sha256"] is not None
              and fresh_sig["requirements_sha256"] == ref_sig["requirements_sha256"]
              and not diff(fresh_sig, ref_sig)):
            status = "match"
            changes = {}
            matched += 1
        else:
            status = "mismatch"
            changes = diff(fresh_sig, ref_sig)
            mismatched += 1
        sidecars = [name for name in SIDECARS if (ref_project / name).is_file()]
        record = {
            "prompt": fresh_project.name,
            "status": status,
            "changes": changes,
            "sidecars": sidecars,
        }
        if status != "match" or not sidecars:
            record["action"] = "review" if status == "mismatch" else "wait"
        else:
            record["action"] = "copy"
            if args.copy:
                for name in sidecars:
                    shutil.copy2(ref_project / name, fresh_project / name)
                record["copied"] = sidecars
                copied += len(sidecars)
        projects.append(record)

    root_sidecars = []
    if args.copy:
        root_policy = reference / "unique_policy.json"
        if root_policy.is_file():
            shutil.copy2(root_policy, run / "unique_policy.json")
            root_sidecars.append("unique_policy.json")

    plan = {
        "run": run.name,
        "reference": str(reference),
        "summary": {
            "projects": len(projects),
            "match": matched,
            "mismatch": mismatched,
            "pending": pending,
            "sidecars_copied": copied,
            "root_sidecars_copied": root_sidecars,
        },
        "projects": projects,
    }
    output = Path(args.output) if args.output else run / "sidecar_plan.json"
    output.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(json.dumps(plan["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
