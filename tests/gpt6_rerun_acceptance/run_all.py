"""Run acceptance suites against the 2026-11-13 GPT-6 Luna outputs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECTS = {
    "hello": "hello",
    "cli_tool": "cli_tool",
    "inventory": "inventory",
    "gui": "gui",
    "expenses": "expenses",
    "library": "library",
    "60": "60",
}
SUITES = {"60": "business"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default="out/gpt6_rerun",
                        help="directory containing the rerun outputs")
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    selected = list(PROJECTS)
    if args.only:
        selected = [name.strip() for name in args.only.split(",") if name.strip()]
    unknown = [name for name in selected if name not in PROJECTS]
    if unknown:
        print(f"unknown suite(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    results = []
    for name in selected:
        project = root / PROJECTS[name]
        script = Path(__file__).with_name(f"{SUITES.get(name, name)}.py")
        print(f"\n=== {name} ({project}) ===", flush=True)
        result = subprocess.run([sys.executable, str(script), str(project)],
                                cwd=str(Path(__file__).resolve().parents[2]))
        checks = None
        try:
            payload = json.loads((project / f"chatgpt_{name}_results.json").read_text(
                encoding="utf-8"))
            checks = {
                "passed": sum(item.get("status") == "passed"
                              for item in payload.get("checks", [])),
                "total": len(payload.get("checks", [])),
            }
        except (OSError, ValueError):
            pass
        results.append({"suite": name, "exit": result.returncode, "checks": checks})

    payload = {
        "root": str(root),
        "interpreter": sys.version,
        "results": results,
        "status": "passed" if all(item["exit"] == 0 for item in results) else "failed",
    }
    (root / "chatgpt_acceptance_summary.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("\n" + json.dumps(payload, indent=2))
    return 0 if payload["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
