"""Run every direct-output acceptance suite and write a summary.

Examples::

    python3.14 tests/chatgpt_acceptance/run_all.py
    python3.12 tests/chatgpt_acceptance/run_all.py --only inventory,60,gui
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECTS = {
    "hello": "hello_world",
    "cli_tool": "cli_tool",
    "inventory": "inventory",
    "gui": "gui",
    "60": "60",
    "expenses": "expenses",
    "library": "library",
}

# "60" is a valid prompt name but not a valid module name; the suite file is
# called business.py.
SUITE_SCRIPTS = {"60": "business"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default="out/initial/chatgpt_compare",
                        help="directory containing the non-60 direct outputs")
    parser.add_argument("--sixty-root", default="out/validation/60/chatgpt_compare",
                        help="directory containing the 60 direct output")
    parser.add_argument("--only", default=None,
                        help="comma-separated suite names")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    sixty_root = Path(args.sixty_root).resolve()
    selected = list(PROJECTS)
    if args.only:
        selected = [name.strip() for name in args.only.split(",") if name.strip()]
    unknown = [name for name in selected if name not in PROJECTS]
    if unknown:
        print(f"unknown suite(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    results = []
    for name in selected:
        project = (sixty_root / PROJECTS[name]) if name == "60" \
            else (root / PROJECTS[name])
        script = Path(__file__).with_name(f"{SUITE_SCRIPTS.get(name, name)}.py")
        print(f"\n=== {name} ({project}) ===", flush=True)
        result = subprocess.run([sys.executable, str(script), str(project)],
                                cwd=str(Path(__file__).resolve().parents[2]))
        checks = None
        try:
            raw = json.loads((project / f"chatgpt_{name}_results.json").read_text(
                encoding="utf-8"))
            checks = {
                "passed": sum(item.get("status") == "passed"
                              for item in raw.get("checks", [])),
                "total": len(raw.get("checks", [])),
            }
        except (OSError, ValueError):
            pass
        results.append({"suite": name, "exit": result.returncode, "checks": checks})
    payload = {
        "root": str(root),
        "sixty_root": str(sixty_root),
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
