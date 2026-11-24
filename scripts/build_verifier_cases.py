#!/usr/bin/env python3
"""Build the canonical merged verifier case set for each project.

Legacy passing cases remain evidence. Confirmed intent cases are added.
Legacy unbound cases are retired into an audit file instead of being rerun
forever; the requirement trace remains the source of truth for uncovered
clauses.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.oracle import cases as case_rules  # noqa: E402

MERGED_CASES = "oracle_cases_merged.json"
MERGED_REPORT = "oracle_report_merged.json"
RETIRED_CASES = "oracle_cases_retired.json"


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _result_map(report):
    found = {}
    for result in (report or {}).get("results") or []:
        if not isinstance(result, dict):
            continue
        case_id = result.get("case") or result.get("name")
        if case_id:
            found[case_id] = result
    return found


def build_project(project, out=print):
    project = Path(project)
    legacy = case_rules.load_cases(project / case_rules.CASES_NAME)
    legacy_results = _result_map(_read(project / "oracle_report.json"))
    kept, retired = [], []
    for case in legacy:
        case_id = case.get("id")
        result = legacy_results.get(case_id) or {}
        if result.get("status") == "passed":
            kept.append(case)
        else:
            retired.append({
                "case": case,
                "status": result.get("status") or "not_run",
                "reason": result.get("reason") or "",
            })
    intents = case_rules.load_cases(project / "oracle_cases_intents.json")
    confirmed = [case for case in intents
                 if case.get("status") == "confirmed"]
    merged = []
    used_ids = set()
    for source in kept + confirmed:
        item = dict(source)
        base = str(item.get("id") or "case")
        candidate = base
        number = 2
        while candidate in used_ids:
            candidate = f"{base}_intent_{number}"
            number += 1
        item["id"] = candidate
        used_ids.add(candidate)
        merged.append(item)
    path = case_rules.save_cases(
        project / MERGED_CASES, merged,
        prompt_sha=(merged[0].get("prompt_sha") if merged else None))
    (project / RETIRED_CASES).write_text(json.dumps({
        "counts": {
            "legacy": len(legacy),
            "kept": len(kept),
            "retired": len(retired),
            "confirmed_intents": len(confirmed),
            "merged": len(merged),
        },
        "cases": retired,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    out(f"{project.name}: {len(kept)} legacy + {len(confirmed)} intent "
        f"-> {len(merged)} merged, {len(retired)} retired")
    return merged, retired


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    args = parser.parse_args(argv)
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir()
                and (wanted is None or path.name in wanted)
                and (path / case_rules.CASES_NAME).is_file()]
    if not projects:
        raise SystemExit(f"no oracle case sets under {root}")
    total = retired = 0
    for project in projects:
        merged, gone = build_project(project)
        total += len(merged)
        retired += len(gone)
    print(f"total: {total} merged case(s), {retired} retired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
