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
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel.extraction import grounding  # noqa: E402
from kernel.extraction.decisions import requirements_sha  # noqa: E402


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _effective_services(out_dir, services):
    decisions = _read(os.path.join(out_dir, "grounding_decisions.json"), {})
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
    return effective, decisions


def _build_report(out_dir):
    requirements_path = os.path.join(out_dir, "requirements.txt")
    try:
        with open(requirements_path, encoding="utf-8") as handle:
            requirements = handle.read()
    except OSError:
        return None, None, None
    intentions = _read(os.path.join(out_dir, "intentions.json"), {})
    if isinstance(intentions, dict):
        intentions = intentions.get("intentions") or []
    services = _read(os.path.join(out_dir, "service_contracts.json"), {})
    if isinstance(services, dict):
        services = services.get("service_contracts") or []
    effective, decisions = _effective_services(out_dir, services)
    report = grounding.report(requirements, intentions, effective)
    aggregates = _read(os.path.join(out_dir, "aggregate_decisions.json"), {})
    aggregate_keys = {
        (grounding._flat(item.get("holder") or ""),
         grounding._flat(item.get("method") or ""))
        for item in aggregates.get("decisions") or []
        if isinstance(item, dict) and item.get("include_empty_groups") is not None
    }
    report["ambiguous_aggregate_groups"] = [
        item for item in report.get("ambiguous_aggregate_groups") or []
        if (grounding._flat(item.get("holder") or ""),
            grounding._flat(item.get("method") or "")) not in aggregate_keys
    ]
    report["applied_decisions"] = {
        "drop_services": sorted({grounding._flat(name) for name in
                                 decisions.get("drop_services") or []}),
        "drop_methods": sorted(
            ".".join((grounding._flat(item.get("holder") or ""),
                      grounding._flat(item.get("method") or "")))
            for item in decisions.get("drop_methods") or []
            if isinstance(item, dict)),
        "aggregate_groups": sorted(".".join(item) for item in aggregate_keys),
    }
    return report, requirements, services


def _aggregate_parent(out_dir, method, models):
    flat = grounding._flat(method)
    for model in models or []:
        name = model.get("name") if isinstance(model, dict) else None
        if not isinstance(name, str) or grounding._flat(name) not in flat:
            continue
        primary = next((field.get("name") for field in model.get("fields") or []
                        if isinstance(field, dict) and field.get("primary_key")),
                       None)
        if isinstance(primary, str):
            return name, primary
    return None, None


def _merge_decision(path, payload):
    existing = _read(path, {})
    if not isinstance(existing, dict):
        existing = {}
    for key, value in payload.items():
        if isinstance(value, list):
            previous = existing.get(key) or []
            existing[key] = sorted({json.dumps(item, sort_keys=True)
                                    for item in [*previous, *value]})
            existing[key] = [json.loads(item) for item in existing[key]]
        else:
            existing[key] = value
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(existing, indent=2, ensure_ascii=False) + "\n")


def collect_questions(out_dir):
    """Questions the attended grounding review would ask."""
    report, _requirements, _services = _build_report(out_dir)
    if report is None:
        return []
    questions = []
    extras = report.get("extra_methods") or []
    by_holder = {}
    for item in extras:
        by_holder.setdefault(item["holder"], []).append(item["method"])
    for holder, methods in by_holder.items():
        questions.append({"kind": "extra", "holder": holder,
                          "methods": methods})
    for item in report.get("ambiguous_aggregate_groups") or []:
        questions.append({"kind": "aggregate", **item})
    return questions


def run_review(out_dir, ask=input, out_fn=print):
    """Ask the grounded-surface questions and write decision sidecars."""
    report, requirements, services = _build_report(out_dir)
    if report is None:
        return 1, 0
    asked = answered = 0
    decisions = {"decided_by": "user",
                 "requirements_sha": requirements_sha(requirements or "")}
    aggregates = {"decided_by": "user",
                  "requirements_sha": decisions["requirements_sha"],
                  "decisions": []}
    extras = report.get("extra_methods") or []
    by_holder = {}
    for item in extras:
        by_holder.setdefault(item["holder"], []).append(item["method"])
    for holder, methods in by_holder.items():
        service = next((item for item in services
                        if item.get("service_name") == holder), {})
        all_methods = {method.get("name") for method in service.get("methods") or []
                       if isinstance(method, dict)}
        target = holder if all_methods and set(methods) == all_methods             else ", ".join(methods)
        asked += 1
        out_fn(f"Grounding: {holder} has no prompt evidence for {target}.")
        reply = ask("  Drop it/them? [y/N] ", "n")
        answered += 1
        if not reply:
            continue
        if target == holder:
            decisions.setdefault("drop_services", []).append(holder)
        else:
            decisions.setdefault("drop_methods", []).extend(
                {"holder": holder, "method": method} for method in methods)
    models = _read(os.path.join(out_dir, "data_models.json"), {}).get(
        "data_models") or []
    for item in report.get("ambiguous_aggregate_groups") or []:
        holder = item.get("holder")
        method = item.get("method")
        parent, key = _aggregate_parent(out_dir, method, models)
        asked += 1
        out_fn(f"Grounding: {holder}.{method} groups by a parent with no "
               "stated empty-group policy.")
        reply = ask("  Include empty groups with zero? [Y/n] ", "y")
        answered += 1
        if parent is None or key is None:
            out_fn("  parent model not identified; decision not recorded")
            continue
        record = {
            "holder": holder,
            "method": method,
            "layer": "service" if str(holder).endswith("Service")
                     else "repository",
            "include_empty_groups": bool(reply),
            "parent_entity": parent,
            "key_field": key,
            "question": item.get("question"),
        }
        aggregates["decisions"].append(record)
        # The same grouped aggregate often has a repository twin under a
        # different method name (aggregate_* vs stock_*).  Record the same
        # answer for repository mappings that group by the same parent.
        parent_flat = grounding._flat(parent)
        for service in services:
            repo_name = service.get("service_name") or ""
            if not repo_name.endswith("Repository"):
                continue
            for candidate in service.get("methods") or []:
                if not isinstance(candidate, dict):
                    continue
                name = candidate.get("name") or ""
                if parent_flat not in grounding._flat(name):
                    continue
                if not any(word in grounding._flat(name)
                           for word in ("aggregate", "value", "total", "spend")):
                    continue
                if "dict" not in str(candidate.get("return_type") or "").lower() \
                        and "mapping" not in str(candidate.get("return_type") or "").lower():
                    continue
                twin = dict(record)
                twin.update({"holder": repo_name, "method": name,
                             "layer": "repository"})
                if twin not in aggregates["decisions"]:
                    aggregates["decisions"].append(twin)
    if decisions.get("drop_services") or decisions.get("drop_methods"):
        verbs = []
        for holder in decisions.get("drop_services") or []:
            for method in by_holder.get(holder, []):
                tokens = grounding._tokens(method)
                if tokens:
                    verbs.append(tokens[0])
        decisions["drop_command_verbs"] = sorted(set(verbs))
        _merge_decision(os.path.join(out_dir, "grounding_decisions.json"),
                        decisions)
    if aggregates["decisions"]:
        _merge_decision(os.path.join(out_dir, "aggregate_decisions.json"),
                        aggregates)
    return asked, answered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("--write-report", action="store_true",
                        help="write grounding_report.json beside the documents")
    parser.add_argument("--review", action="store_true",
                        help="ask the grounding questions and write decisions")
    args = parser.parse_args(argv)
    if args.review:
        asked, answered = run_review(args.out_dir)
        print(f"grounding review: {answered} answer(s) for {asked} question(s)")
        return 0
    report, _requirements, _services = _build_report(args.out_dir)
    if report is None:
        print(f"error: no requirements.txt under {args.out_dir}", file=sys.stderr)
        return 2
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
