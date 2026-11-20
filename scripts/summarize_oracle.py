#!/usr/bin/env python3
"""Group oracle execution findings by cause for review.

No decisions are made here. The report separates likely code/requirement
disagreements from incomplete cases, binding misses and ambiguous setup.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def category(result):
    status = result.get("status")
    reason = str(result.get("reason") or "").lower()
    if status == "passed":
        return "passed"
    if status == "unbound":
        if "ambiguous action binding" in reason:
            return "unbound: ambiguous action"
        if "cannot resolve given entity" in reason or "is not a mapping" in reason:
            return "unbound: setup entity"
        if "no generated method" in reason or "no generated cli path" in reason:
            return "unbound: missing action"
        return "unbound: other"
    if status != "failed":
        return f"{status}: other"
    if "notfounderror" in reason or "not found" in reason:
        return "failed: missing setup row"
    if "already exists" in reason:
        return "failed: duplicate setup"
    if "expected" in reason and "no error was raised" in reason:
        return "failed: expected error missing"
    if reason.startswith("raised ") and "expected" in reason:
        return "failed: wrong error"
    if "row count is" in reason:
        return "failed: row count"
    if "is " in reason and ", expected " in reason:
        return "failed: state value"
    if any(word in reason for word in ("keyerror", "unknown scenario reference",
                                       "lookup", "matched 0 records",
                                       "takes from", "unexpected keyword")):
        return "failed: harness/setup shape"
    return "failed: other"


def summarize(report):
    groups = defaultdict(list)
    counts = Counter()
    for project in report.get("results") or []:
        for result in project.get("results") or []:
            kind = category(result)
            counts[kind] += 1
            groups[kind].append({
                "prompt": project.get("prompt"),
                "case": result.get("case"),
                "status": result.get("status"),
                "reason": result.get("reason"),
            })
    return counts, groups


def markdown(report):
    counts, groups = summarize(report)
    lines = ["# Oracle findings", "",
             "Total confirmed executions: "
             f"**{sum(counts.values())}**", ""]
    for kind, count in counts.most_common():
        lines.append(f"- **{kind}**: {count}")
    lines.append("")
    for kind in sorted(groups):
        if kind == "passed":
            continue
        lines += [f"## {kind}", ""]
        for item in groups[kind]:
            lines.append(
                f"- `{item['prompt']}` / `{item['case']}`: "
                f"{item['reason']}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="oracle_report.json")
    parser.add_argument("--markdown", default=None)
    args = parser.parse_args(argv)
    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    counts, _groups = summarize(report)
    print(json.dumps(dict(counts), indent=2))
    if args.markdown:
        Path(args.markdown).write_text(markdown(report) + "\n",
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
