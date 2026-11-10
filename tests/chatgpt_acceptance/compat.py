"""Check the direct outputs' imports on the target Python 3.12 interpreter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECTS = (
    ("inventory", "inventory", "inventory"),
    ("gui", "wine_inventory", "wine_inventory"),
    ("60", "shop", "src"),
    ("expenses", "expense_tracker", "src"),
    ("library", "library_system", "src"),
)


def run(root: Path, python: str | None = None) -> int:
    interpreter = python or shutil.which("python3.12")
    if not interpreter:
        print("FAIL  python3.12 is not installed", file=sys.stderr)
        return 2
    results = []
    for name, package, source in PROJECTS:
        project = root / name
        env = dict(os.environ)
        env["PYTHONPATH"] = str(project / source)
        result = subprocess.run(
            [interpreter, "-c", f"import {package}"],
            cwd=str(project), capture_output=True, text=True, env=env, timeout=30,
        )
        status = "passed" if result.returncode == 0 else "failed"
        detail = (result.stderr or result.stdout).strip().splitlines()
        results.append({"project": name, "package": package,
                        "status": status, "detail": detail[-1] if detail else ""})
        print(f"{'PASS' if status == 'passed' else 'FAIL'}  {name}: import {package}")
        if status == "failed" and detail:
            print(f"      {detail[-1]}")
    payload = {"interpreter": interpreter,
               "status": "passed" if all(r["status"] == "passed" for r in results)
               else "failed",
               "projects": results}
    try:
        (root / "chatgpt_python312_compat.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if payload["status"] == "passed" else 1


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path("out/chatgpt_compare").resolve()
    return run(root, argv[2] if len(argv) > 2 else None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
