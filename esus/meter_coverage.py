#!/usr/bin/env python3
"""Meter mechanical coverage: implemented vs stub methods per prompt.

Usage:
    python meter_coverage.py [OUT_DIR ...]     # default: every out/*/ with documents

For each output directory the gate runs first: blocked ones report BLOCKED
with their count, generatable ones render (pure text, nothing written) and
report methods/implemented/stubs/coverage. The stub ledger groups the rest
by reason, so each line names either a kernel pattern to implement or an LLM
work order — the meter is the loop's scoreboard, not another gate.
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generator  # noqa: E402


def measure(out_dir):
    """`{...}` with coverage numbers, or `{"blocked": message}`."""
    ok, message = generator.gate(out_dir)
    if not ok:
        return {"name": os.path.basename(out_dir.rstrip(os.sep)),
                "blocked": message}
    ctx = generator.load_context(out_dir)
    if generator.is_degenerate(ctx):
        return {"name": os.path.basename(out_dir.rstrip(os.sep)),
                "degenerate": True}
    stats = {"source": out_dir, "implemented": 0, "stubs": 0,
             "stub_reasons": [],
             "prog": os.path.basename(out_dir.rstrip(os.sep))}
    generator.render_program(ctx, stats)
    methods = stats.get("methods", [])
    implemented = [m for m in methods if m["implemented"]]
    stubs = [m for m in methods if not m["implemented"]]
    total = len(methods)
    return {
        "name": os.path.basename(out_dir.rstrip(os.sep)),
        "total": total,
        "implemented": len(implemented),
        "stubs": len(stubs),
        "coverage": (len(implemented) / total) if total else 1.0,
        "reasons": Counter(m["how"] for m in stubs),
    }


def default_dirs():
    """Every `out/*/` holding documents, sorted."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
    found = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isdir(path) and not name.startswith((".", "_")) \
                    and not name.startswith("backup"):
                found.append(path)
    return found


def render(rows):
    """The scoreboard lines for measured rows."""
    lines = [f"{'prompt':<12}{'methods':>9}{'mechanical':>12}{'stubs':>8}{'cover':>8}"]
    totals = Counter()
    for row in rows:
        if "blocked" in row:
            lines.append(f"{row['name']:<12}{'BLOCKED':>9}  {row['blocked'][:70]}")
            continue
        if row.get("degenerate"):
            lines.append(f"{row['name']:<12}{'DEGENERATE':>9}  LLM fallback (no architecture)")
            continue
        lines.append(f"{row['name']:<12}{row['total']:>9}{row['implemented']:>12}"
                     f"{row['stubs']:>8}{row['coverage']:>7.0%}")
        totals["total"] += row["total"]
        totals["implemented"] += row["implemented"]
        totals["stubs"] += row["stubs"]
    if totals["total"]:
        lines.append(f"{'TOTAL':<12}{totals['total']:>9}{totals['implemented']:>12}"
                     f"{totals['stubs']:>8}"
                     f"{totals['implemented'] / totals['total']:>7.0%}")
    reasons = Counter()
    for row in rows:
        reasons.update(row.get("reasons", Counter()))
    if reasons:
        lines.append("stub ledger:")
        for reason, count in reasons.most_common():
            lines.append(f"  {count:>4}  {reason}")
    return "\n".join(lines)


def main(argv=None):
    dirs = list(argv) if argv else default_dirs()
    if not dirs:
        print("no output directories found", file=sys.stderr)
        return 2
    rows = [measure(path) for path in dirs]
    print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
