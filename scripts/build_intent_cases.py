#!/usr/bin/env python3
"""Turn prompt-derived test intents into case-shaped fixtures.

This is the mechanical half of the verifier: extracted models provide field
types, required values and FK ordering; the intent provides every asserted
value. The output is a sidecar case set, not a replacement for the main oracle.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.extraction.decisions import requirements_sha  # noqa: E402
from kernel.oracle import cases as case_rules, fixtures, intents  # noqa: E402


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _documents(project):
    project = Path(project)
    return {
        "models": _read(project / "data_models.json").get("data_models") or [],
        "services": _read(project / "service_contracts.json").get(
            "service_contracts") or [],
        "repos": _read(project / "persistence_ports.json").get(
            "persistence_ports", {}).get("repositories") or [],
        "contracts": _read(project / "method_contracts.json").get(
            "method_contracts") or [],
        "invariants": _read(project / "invariants.json").get("invariants") or [],
        "components": _read(project / "components.json").get("components") or {},
        "requirements": ((project / "requirements.txt").read_text(
            encoding="utf-8") if (project / "requirements.txt").is_file()
            else ""),
    }


def build_one(project, cases_name="oracle_cases_intents.json", out=print):
    project = Path(project)
    requirements = (project / "requirements.txt").read_text(encoding="utf-8")
    source_intents = intents.load_intents(project / intents.INTENTS_NAME)
    source_intents = intents.ground_intents(source_intents, requirements)
    if not source_intents:
        return [], project / cases_name
    docs = _documents(project)
    planned, rejected = [], []
    for intent in source_intents:
        try:
            plan = fixtures.plan_case(intent, docs, requirements)
        except fixtures.PlanError as error:
            rejected.append({"id": intent.get("id"), "errors": [str(error)]})
            continue
        planned.append(plan)
    valid, errors = case_rules.validate_cases(
        {"cases": [plan.case for plan in planned]}, requirements,
        requirements_sha(requirements))
    plan_path = project / "oracle_intent_plans.json"
    plan_path.write_text(json.dumps({
        "plans": [{
            "id": plan.case.get("id"),
            "diagnostics": plan.diagnostics,
        } for plan in planned],
        "rejected": rejected,
        "validation_errors": errors,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    path = case_rules.save_cases(
        project / cases_name, valid, prompt_sha=requirements_sha(requirements))
    out(f"{project.name}: {len(valid)} planned case(s) -> {path}")
    if rejected or errors:
        out(f"{project.name}: {len(rejected)} plan rejection(s), "
            f"{len(errors)} validation error(s)")
    return valid, path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--cases-name", default="oracle_cases_intents.json")
    args = parser.parse_args(argv)
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir()
                and (path / intents.INTENTS_NAME).is_file()
                and (wanted is None or path.name in wanted)]
    if not projects:
        raise SystemExit(f"no test intents under {root}")
    total = 0
    failed = []
    for project in projects:
        try:
            valid, _path = build_one(project, cases_name=args.cases_name)
        except (OSError, RuntimeError) as error:
            failed.append(project.name)
            print(f"{project.name}: intent planning failed ({error})")
            continue
        total += len(valid)
    print(f"total: {total} planned case(s)")
    if failed:
        print("failed prompts: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
