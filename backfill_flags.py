#!/usr/bin/env python3
"""Backfill requirements-passed flags into an existing components.json.

Applies `repairs.repair_missing_flags` — the same deterministic repair the
pipeline runs — to documents an earlier run wrote without it, so a fixed
pipeline heals old output without a model call. Only grounded additions
happen (flag name from the run's own requirements, type from its data
model); anything else is left for the retry and the probe.

Usage:
    python backfill_flags.py out/inventory

Exit code is always 0: this reports what it changed, and the probe judges
whether anything remains.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kernel.consistency.loader import load_requirements  # noqa: E402
from kernel.extraction import repairs  # noqa: E402


class Log:
    def __init__(self):
        self.lines = []

    def write(self, text):
        self.lines.append(text)
        print(text)


def backfill(output_dir, log=None):
    """Add grounded flags to components.json; return the number added."""
    log = log or Log()
    path = os.path.join(output_dir, "components.json")
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"error: cannot read {path}: {error}")
        return 0
    requirements = load_requirements(output_dir)
    if not requirements:
        print(f"error: {output_dir} has no requirements.txt to ground flags in")
        return 0
    models = []
    try:
        with open(os.path.join(output_dir, "data_models.json"), encoding="utf-8") as handle:
            models = json.load(handle).get("data_models") or []
    except (OSError, ValueError, AttributeError):
        pass
    before = json.dumps(payload.get("components"), sort_keys=True)
    repairs.repair_missing_flags(payload.get("components"), requirements, models, log)
    after = json.dumps(payload.get("components"), sort_keys=True)
    if before == after:
        print("no grounded flags to add")
        return 0
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return len(log.lines)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__.splitlines()[0], file=sys.stderr)
        print("usage: python backfill_flags.py OUT_DIR", file=sys.stderr)
        return 2
    backfill(args[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
