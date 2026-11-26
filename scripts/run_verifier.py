#!/usr/bin/env python3
"""Run the canonical merged verifier: legacy passes plus confirmed intents."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_verifier_cases  # noqa: E402
import run_oracle  # noqa: E402

CASE_BUILDER = ROOT / "scripts" / "build_oracle_cases.py"
ORACLE_RUNNER = ROOT / "scripts" / "run_oracle.py"


def regenerate_cases(root: Path, wanted: str | None, case_model: str,
                     two_stage: bool, repair_attempts: int) -> int:
    """Regenerate prompt-only oracle cases, then execute the legacy report.

    This stage must run before `build_verifier_cases`: the merge keeps only
    legacy cases whose report passed, so a fresh case set needs its own
    execution report. The verifier model sees only requirements and the
    prompt-derived case schema; it never sees extracted documents or generated
    code.
    """
    command = [sys.executable, str(CASE_BUILDER), str(root),
               "--model", case_model]
    if wanted:
        command += ["--only", wanted]
    if two_stage:
        command.append("--two-stage")
        if repair_attempts:
            command += ["--repair-attempts", str(repair_attempts)]
    print(f"regenerate verifier cases: {' '.join(command)}", flush=True)
    built = subprocess.run(command, cwd=str(ROOT))
    if built.returncode:
        return built.returncode
    run = [sys.executable, str(ORACLE_RUNNER), str(root),
           "--output", str(root / "oracle_report.json")]
    if wanted:
        run += ["--only", wanted]
    print(f"execute regenerated cases: {' '.join(run)}", flush=True)
    return subprocess.run(run, cwd=str(ROOT)).returncode


def verifier_quality(root: Path) -> int:
    """Report regenerated-case quality and stop on real behavior defects.

    Case defects and coverage gaps are verifier-quality metrics: they mean the
    case set could not bind or the prompt is under-specified. They are not
    generated-code failures. A `behavior:*` failure is a real finding and
    blocks the merged verifier.
    """
    report_path = root / "oracle_report.json"
    if not report_path.is_file():
        return 0
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    summary = report.get("summary") or {}
    triage = summary.get("triage_counts") or {}
    behavior = {kind: count for kind, count in triage.items()
                if str(kind).startswith("behavior:")}
    metrics = {
        "cases": summary.get("cases"),
        "counts": summary.get("counts"),
        "triage_counts": triage,
        "behavior_failures": behavior,
    }
    # Compare this fresh case set with the prior sidecar snapshot so verifier
    # variability is measured beside extraction/generation variance.
    variance = {"new_cases": 0, "previous_cases": 0, "projects": {}}
    for project in sorted(root.glob("prompt_*")):
        if not project.is_dir():
            continue
        def count(name):
            try:
                payload = json.loads((project / name).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return 0
            return len(payload.get("cases") or []) if isinstance(payload, dict) else 0
        new = count("oracle_cases.json")
        previous = count("oracle_cases.previous.json")
        variance["new_cases"] += new
        variance["previous_cases"] += previous
        if new != previous:
            variance["projects"][project.name] = {
                "new": new, "previous": previous, "delta": new - previous}
    variance["case_count_delta"] = variance["new_cases"] - variance["previous_cases"]
    variance["outcome_counts"] = metrics["counts"]
    variance["triage_counts"] = triage
    variance["behavior_failures"] = behavior
    (root / "verifier_variance.json").write_text(
        json.dumps(variance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verifier": metrics, "variance": {
        "case_count_delta": variance["case_count_delta"],
        "projects_with_case_count_change": len(variance["projects"]),
    }}, indent=2), flush=True)
    return 1 if behavior else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--output", default=None,
                        help="merged report path")
    parser.add_argument("--regenerate-cases", action="store_true",
                        help="regenerate prompt-only oracle cases for every "
                             "project before building the merged verifier")
    parser.add_argument("--case-model", default="server",
                        help="model for oracle case regeneration (default: server)")
    parser.add_argument("--case-two-stage", action="store_true",
                        help="use the case-plan/materialize path when regenerating")
    parser.add_argument("--case-repair-attempts", type=int, default=1,
                        help="repair attempts for regenerated cases")
    args = parser.parse_args(argv)
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    if args.regenerate_cases:
        status = regenerate_cases(
            root, args.only, args.case_model, args.case_two_stage,
            args.case_repair_attempts)
        if status and verifier_quality(root):
            return status
        if status:
            print("regenerated cases have verifier/case gaps but no behavior failures; "
                  "continuing with the passed case subset", flush=True)
    elif verifier_quality(root):
        return 1
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir() and (wanted is None or path.name in wanted)
                and ((path / "oracle_cases.json").is_file()
                     or (path / "oracle_cases_intents.json").is_file())]
    if not projects:
        raise SystemExit(f"no projects under {root}")
    for project in projects:
        build_verifier_cases.build_project(project)
    report = Path(args.output) if args.output else (
        root / "oracle_report_merged.json")
    command = [str(root),
               "--cases", build_verifier_cases.MERGED_CASES,
               "--report-name", build_verifier_cases.MERGED_REPORT,
               "--output", str(report)]
    if wanted is not None:
        command += ["--only", ",".join(sorted(wanted))]
    return run_oracle.main(command)


if __name__ == "__main__":
    raise SystemExit(main())
