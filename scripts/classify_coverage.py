#!/usr/bin/env python3
"""Classify untested requirement clauses by the verifier evidence available.

The requirement trace says a clause is untested. This report explains why:

- a confirmed/assumed case exists;
- an intent was rejected by the fixture planner;
- intent generation was rejected;
- no intent was produced;
- an intent exists but was never run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.oracle import cases as case_rules  # noqa: E402


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _clean(value):
    return " ".join(str(value or "").replace("`", "").replace("*", "")
                    .split()).strip().casefold().rstrip(" .;:")


def _same(a, b):
    left, right = _clean(a), _clean(b)
    return bool(left and right) and (
        left == right or left in right or right in left)


def _plan_kind(errors):
    text = " ".join(str(error).lower() for error in errors or [])
    if "ambiguous" in text:
        return "ambiguous_action"
    if "no generated method" in text or "coverage_gap" in text \
            or "invented" in text and "action" in text:
        return "missing_action"
    if "not declared" in text or "reference field" in text:
        return "missing_field"
    if "invented" in text and "entity" in text:
        return "missing_entity"
    if "primary key" in text or "argument" in text or "bulk" in text:
        return "mechanical_argument"
    return "other_plan_rejection"


def _result_map(project):
    for filename in ("oracle_report_intents_all.json",
                     "oracle_report_intents.json"):
        report = _read(project / filename) or {}
        found = {}
        for result in report.get("results") or []:
            if isinstance(result, dict):
                found[result.get("case") or result.get("name")] = result
        if found:
            return found
    return {}


def classify(root, coverage_path):
    root = Path(root)
    coverage = _read(coverage_path) or {}
    rows = []
    counts = {}
    for project_row in coverage.get("projects") or []:
        project = root / str(project_row.get("project") or "")
        if not project.is_dir():
            continue
        intents = (_read(project / "test_intents.json") or {}).get("intents") or []
        plans = _read(project / "oracle_intent_plans.json") or {}
        cases = case_rules.load_cases(project / "oracle_cases_intents.json")
        results = _result_map(project)
        meta = _read(project / "test_intents_meta.json") or {}
        for row in project_row.get("rows") or []:
            if row.get("status") != "mapped_untested":
                continue
            source = row.get("text") or ""
            matching_intents = [intent for intent in intents
                                if _same(intent.get("source"), source)]
            matching_cases = [case for case in cases
                              if _same(case.get("source"), source)]
            outcomes = [results.get(case.get("id")) or {} for case in matching_cases]
            category = "not_run"
            detail = ""
            if any(result.get("status") == "passed"
                   and case.get("status") == "confirmed"
                   for case, result in zip(matching_cases, outcomes)):
                category = "confirmed_pass"
            elif any(result.get("status") == "passed" for result in outcomes):
                category = "assumed_pass"
            elif any(result.get("status") == "failed" for result in outcomes):
                category = "assumed_failure"
            elif any(result.get("status") == "unbound" for result in outcomes):
                category = "unbound"
            else:
                ids = {intent.get("id") for intent in matching_intents}
                rejected = [item for item in plans.get("rejected") or []
                            if item.get("id") in ids]
                if rejected:
                    category = _plan_kind(rejected[0].get("errors"))
                    detail = "; ".join(rejected[0].get("errors") or [])[:300]
                else:
                    generated = [item for item in meta.get("rejected") or []
                                 if _same(item.get("clause"), source)]
                    if generated:
                        category = "generation_rejected"
                        detail = "; ".join(generated[0].get("errors") or [])[:300]
                    elif not matching_intents:
                        category = "no_intent"
                    elif matching_intents:
                        category = "intent_not_planned"
            counts[category] = counts.get(category, 0) + 1
            rows.append({
                "project": project_row.get("project"),
                "source": source,
                "category": category,
                "detail": detail,
                "intents": [intent.get("id") for intent in matching_intents],
                "cases": [case.get("id") for case in matching_cases],
            })
    return {"root": str(root), "counts": counts, "rows": rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--coverage", default=None,
                        help="coverage.json from run_bench_acceptance")
    parser.add_argument("--report", default=None,
                        help="classification JSON path")
    args = parser.parse_args(argv)
    root = Path(args.root)
    coverage = Path(args.coverage) if args.coverage else (
        root / "acceptance" / "coverage.json")
    if not coverage.is_file():
        raise SystemExit(f"coverage report not found: {coverage}")
    result = classify(root, coverage)
    path = Path(args.report) if args.report else (
        root / "coverage_classification.json")
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    print(json.dumps({"untested": len(result["rows"]),
                      "counts": result["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
