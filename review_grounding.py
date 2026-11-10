#!/usr/bin/env python3
"""Report service methods with no evidence in the requirements/intentions.

This is a review check, not a mutating generator step.  It writes a report;
the reviewed drops go in ``grounding_decisions.json`` and the generator applies
them before adapters/commands are emitted.

Usage:
    python review_grounding.py out/60_program_clean
    python review_grounding.py out/60_program_clean --write-report
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel.extraction import grounding  # noqa: E402


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("--write-report", action="store_true",
                        help="write grounding_report.json beside the documents")
    args = parser.parse_args(argv)
    requirements_path = os.path.join(args.out_dir, "requirements.txt")
    try:
        with open(requirements_path, encoding="utf-8") as handle:
            requirements = handle.read()
    except OSError:
        print(f"error: no requirements.txt under {args.out_dir}", file=sys.stderr)
        return 2
    intentions = _read(os.path.join(args.out_dir, "intentions.json"), {})
    if isinstance(intentions, dict):
        intentions = intentions.get("intentions") or []
    services = _read(os.path.join(args.out_dir, "service_contracts.json"), {})
    if isinstance(services, dict):
        services = services.get("service_contracts") or []
    decisions = _read(os.path.join(args.out_dir, "grounding_decisions.json"), {})
    drop_services = {grounding._flat(name) for name in
                     decisions.get("drop_services") or []}
    drop_methods = {(grounding._flat(item.get("holder") or ""),
                     grounding._flat(item.get("method") or ""))
                    for item in decisions.get("drop_methods") or []
                    if isinstance(item, dict)}
    effective = []
    for service in services:
        holder = grounding._flat(service.get("service_name") or "")
        if holder in drop_services:
            continue
        methods = [method for method in service.get("methods") or []
                   if isinstance(method, dict)
                   and (holder, grounding._flat(method.get("name") or ""))
                   not in drop_methods]
        if methods:
            service = dict(service)
            service["methods"] = methods
            effective.append(service)
    report = grounding.report(requirements, intentions, effective)
    report["applied_decisions"] = {
        "drop_services": sorted(drop_services),
        "drop_methods": sorted(".".join(item) for item in drop_methods),
    }
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    print(text, end="")
    if args.write_report:
        target = os.path.join(args.out_dir, "grounding_report.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {target}", file=sys.stderr)
    return 1 if report["extra_methods"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
