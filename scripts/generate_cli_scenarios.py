#!/usr/bin/env python3
"""Generate CLI scenarios from the extracted command surface.

Each leaf becomes a JSON scenario executed by tests/runtime/worker.py. Required
and typed options are filled from the model invariants; semantic scenarios
already present for a prompt are preserved and appear first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "runtime"))

import worker  # noqa: E402


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0] if args else "out/validation/bench")
    target = Path(args[1]) if len(args) > 1 else ROOT / "tests" / "runtime" / "scenarios"
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for prompt in sorted(path for path in root.glob("prompt_*") if path.is_dir()):
        docs = worker._documents(prompt)
        path_file = target / f"{prompt.name}.json"
        existing = []
        if path_file.is_file():
            try:
                existing = json.loads(path_file.read_text()).get("scenarios") or []
            except ValueError:
                existing = []
        scenarios = [item for item in existing
                     if not str(item.get("name", "")).startswith("cli:")]
        for number, (path, node) in enumerate(
                worker._leaf_entries(docs.get("components")), start=1):
            args = worker._cli_args(docs, node, number)
            scenarios.append({
                "name": "cli:" + " ".join(path),
                "when": {"cli": list(path) + list(args)},
                "expect": {"exit": 0},
            })
        path_file.write_text(json.dumps({"scenarios": scenarios},
                                        indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        total += len(scenarios)
        print(f"{prompt.name}: {len(scenarios)} scenario(s)")
    print(f"total: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
