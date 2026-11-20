#!/usr/bin/env python3
"""Run prompt-derived oracle cases for one generated project.

This worker is intentionally black-box: it uses the existing scenario DSL to
seed records and call the public generated service, then compares the case's
expected state/error/rows. Cases that cannot bind are reported as unbound.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "runtime"))

import worker  # noqa: E402
from kernel.oracle import binder, cases as case_rules, triage  # noqa: E402


def run(project, include_assumed=False):
    project = Path(project)
    docs = worker._documents(project)
    case_path = project / case_rules.CASES_NAME
    raw_cases = case_rules.load_cases(case_path)
    all_cases, _errors = case_rules.validate_cases(
        raw_cases, docs.get("requirements") or "")
    case_rules.save_cases(
        case_path, all_cases,
        prompt_sha=(all_cases[0].get("prompt_sha") if all_cases else None))
    selected = [case for case in all_cases
                if case.get("status") in ("confirmed", "unbound")
                or (include_assumed and case.get("status") == "assumed")]
    if not selected:
        return {"prompt": project.name, "results": [], "counts": {}}
    try:
        cli, deps, db = worker._load_package(project)
    except Exception as error:  # noqa: BLE001
        return {"prompt": project.name, "status": "failed",
                "results": [{"status": "failed", "name": "import",
                             "reason": f"{type(error).__name__}: {error}"}],
                "counts": {"failed": 1}}
    store = deps.get("store")
    cli_path = project / "generated" / "cli.py"
    results = []
    case_by_id = {case.get("id"): case for case in all_cases}
    for index, case in enumerate(selected, start=1):
        scenario, reason = binder.bind_case(case, docs)
        if scenario is None:
            outcome = {"name": case["id"], "status": "unbound",
                       "reason": reason}
            case["status"] = "unbound"
            case["triage"] = triage.classify("unbound", reason)
            case["needs_review"] = False
            case["execution"] = {"status": "unbound", "reason": reason}
            results.append(outcome)
            continue
        try:
            outcome = worker._run_scenario(
                docs, deps, store, scenario, index,
                cli_path=cli_path if cli_path.is_file() else None,
                db=db, cli_module=cli)
        except Exception as error:  # noqa: BLE001
            outcome = {"name": scenario["name"], "status": "failed",
                       "reason": f"harness error: {type(error).__name__}: {error}"}
        outcome["case"] = case["id"]
        case["execution"] = {
            "status": outcome.get("status"),
            "reason": outcome.get("reason", ""),
        }
        kind = triage.classify(outcome.get("status"), outcome.get("reason"))
        case["triage"] = kind
        case["needs_review"] = kind.startswith("behavior")
        results.append(outcome)
    payload = {"prompt_sha": case_by_id.get(
        selected[0].get("id"), {}).get("prompt_sha"), "cases": all_cases}
    case_rules.save_cases(case_path, all_cases,
                          prompt_sha=payload.get("prompt_sha"))
    counts = {}
    for result in results:
        status = result.get("status")
        counts[status] = counts.get(status, 0) + 1
    return {"prompt": project.name, "results": results, "counts": counts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project")
    parser.add_argument("--include-assumed", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.project, args.include_assumed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
