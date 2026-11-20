#!/usr/bin/env python3
"""Run the generic contract/runtime checks over the validation bench.

One fresh worker process is used per prompt because generated packages use the
same top-level module names (`models`, `cli`, ...). The worker reads the
extracted contracts and drives the generated package; it never edits a
generated file.

Usage:
    python scripts/run_bench_acceptance.py out/validation/bench
    python scripts/run_bench_acceptance.py out/initial
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "tests" / "runtime" / "worker.py"
sys.path.insert(0, str(WORKER.parent))
sys.path.insert(0, str(ROOT / "scripts"))

import requirement_trace  # noqa: E402
import worker  # noqa: E402


def run_one(prompt_dir: Path, output_dir: Path, scenarios: str | None = None) -> dict:
    env = os.environ.copy()
    if scenarios:
        env["ESUS_SCENARIOS_DIR"] = scenarios
    result = subprocess.run(
        [sys.executable, str(WORKER), str(prompt_dir)],
        cwd=str(ROOT), capture_output=True, text=True, env=env)
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {
            "prompt": prompt_dir.name,
            "status": "failed",
            "checks": [{"name": "worker", "status": "failed",
                        "reason": (result.stderr or result.stdout)[-1000:]}],
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{prompt_dir.name}.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="bench root containing prompt_* directories")
    parser.add_argument("--output", default=None,
                        help="result directory (default: <root>/acceptance)")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--scenarios", default=None,
                        help="directory overriding tests/runtime/scenarios")
    args = parser.parse_args(argv)
    root = Path(args.root)
    output = Path(args.output) if args.output else root / "acceptance"
    selected = ({item.strip() for item in args.only.split(",") if item.strip()}
                if args.only else None)
    prompts = [path for path in worker.discover_projects(root)
               if selected is None or path.name in selected]
    if not prompts:
        print(f"no runnable projects under {root}", file=sys.stderr)
        return 2
    results = []
    for prompt in prompts:
        payload = run_one(prompt, output, scenarios=args.scenarios)
        results.append(payload)
        passed = sum(1 for check in payload["checks"]
                     if check.get("status") == "passed")
        failed = sum(1 for check in payload["checks"]
                     if check.get("status") == "failed")
        skipped = sum(1 for check in payload["checks"]
                      if check.get("status") == "skipped")
        print(f"{prompt.name}: {payload['status']} "
              f"({passed} passed, {failed} failed, {skipped} skipped)",
              flush=True)
        for check in payload["checks"]:
            if check.get("status") == "failed":
                print(f"  - {check['name']}: {check.get('reason', '')}", flush=True)
    traces = [requirement_trace.trace_project(prompt, payload["checks"])
              for prompt, payload in zip(prompts, results)]
    (output / "coverage.json").write_text(
        json.dumps({"root": str(root),
                    "summary": requirement_trace.summarize(traces),
                    "projects": traces}, indent=2) + "\n",
        encoding="utf-8")
    counts = dict(Counter(item["status"] for item in results))
    failed = counts.get("failed", 0)
    incomplete = counts.get("incomplete", 0)
    overall = "failed" if failed else "incomplete" if incomplete else "passed"
    summary = {
        "root": str(root),
        "status": overall,
        "counts": counts,
        "stubs": sum(1 for item in results for check in item["checks"]
                     if str(check.get("name", "")).startswith("stub:")),
        "coverage": requirement_trace.summarize(traces),
        "results": results,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k not in ("results",)}, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
