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
            args = worker._cli_args(docs, node, 1)
            variants = [list(path) + list(args)]
            if str(path[-1]).lower() in ("delete", "remove"):
                key_args = []
                for option in node.get("options") or []:
                    if (isinstance(option, dict) and option.get("required")
                            and str(option.get("name") or "").endswith("id")):
                        key_args = [option["name"], "1"]
                        break
                if key_args:
                    variants.append(list(path) + key_args)
            if any(isinstance(option, dict)
                   and str(option.get("type") or "").lower() in ("bool", "boolean")
                   for option in node.get("options") or []):
                valued = []
                for item in list(path) + list(args):
                    if item.startswith("--") and item not in valued:
                        valued.append(item)
                # Try the value-taking spelling as an additional variant.
                value_variant = [item for item in list(path) + list(args)]
                for option in node.get("options") or []:
                    if (isinstance(option, dict)
                            and str(option.get("type") or "").lower() in ("bool", "boolean")
                            and option.get("required")):
                        idx = value_variant.index(option["name"]) + 1 if option["name"] in value_variant else None
                        if idx is not None and idx >= len(value_variant):
                            value_variant.insert(idx, "true")
                variants.append(value_variant)
            scenarios.append({
                "name": "cli:" + " ".join(path),
                "when": {"cli_variants": variants},
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
