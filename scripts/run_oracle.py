#!/usr/bin/env python3
"""Run prompt-derived oracle cases across a validation tree."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "scripts" / "run_oracle_worker.py"
sys.path.insert(0, str(ROOT))

from kernel.oracle import cases as case_rules  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="root containing prompt_* project directories")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--exclude", default=None,
                        help="comma-separated prompt names to leave out")
    parser.add_argument("--include-assumed", action="store_true",
                        help="run assumed cases as advisory checks")
    parser.add_argument("--output", default=None,
                        help="report path (default: <root>/oracle_report.json)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
    excluded = {item.strip() for item in args.exclude.split(",") if item.strip()} \
        if args.exclude else set()
    projects = [path for path in sorted(root.glob("prompt_*"))
                if path.is_dir() and (path / case_rules.CASES_NAME).is_file()
                and path.name not in excluded
                and (wanted is None or path.name in wanted)]
    results = []
    for project in projects:
        command = [sys.executable, str(WORKER), str(project)]
        if args.include_assumed:
            command.append("--include-assumed")
        process = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                 text=True)
        try:
            payload = json.loads(process.stdout)
        except ValueError:
            payload = {"prompt": project.name, "status": "failed",
                       "results": [{"name": "worker", "status": "failed",
                                    "reason": (process.stderr or process.stdout)[-1000:]}],
                       "counts": {"failed": 1}}
        (project / "oracle_report.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        results.append(payload)
    counts = {}
    for payload in results:
        for status, count in (payload.get("counts") or {}).items():
            counts[status] = counts.get(status, 0) + count
    report = {"root": str(root), "summary": {
        "projects": len(results),
        "cases": sum(sum((payload.get("counts") or {}).values())
                     for payload in results),
        "counts": counts,
    }, "results": results}
    output = Path(args.output) if args.output else root / "oracle_report.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if not counts.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
