#!/usr/bin/env python3
"""Run the canonical merged verifier: legacy passes plus confirmed intents."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_verifier_cases  # noqa: E402
import run_oracle  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", help="validation root containing prompt_* directories")
    parser.add_argument("--only", default=None,
                        help="comma-separated prompt names")
    parser.add_argument("--output", default=None,
                        help="merged report path")
    args = parser.parse_args(argv)
    root = Path(args.root)
    wanted = {item.strip() for item in args.only.split(",") if item.strip()} \
        if args.only else None
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
