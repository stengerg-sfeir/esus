#!/usr/bin/env python3
"""Resolve prompt-derived oracle cases that need a human decision."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kernel.oracle import cases as case_rules  # noqa: E402


def _describe(index, total, case):
    lines = [
        f"--- oracle case {index}/{total} ---",
        f"id: {case.get('id')}",
        f"source: {case.get('source')}",
        f"status: {case.get('status')}",
    ]
    for key in ("assumptions", "ambiguities"):
        if case.get(key):
            lines.append(f"{key}: " + "; ".join(case[key]))
    lines.append("given: " + json.dumps(case.get("given"), ensure_ascii=False))
    lines.append("when: " + json.dumps(case.get("when"), ensure_ascii=False))
    lines.append("then: " + json.dumps(case.get("then"), ensure_ascii=False))
    return lines


def _ask(case, input_fn):
    try:
        answer = input_fn(
            "confirm (c), ambiguous (a), contradictory (d), unbound (u), skip (s): "
        ).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return None
    return {
        "c": "confirmed", "confirm": "confirmed",
        "a": "ambiguous", "ambiguous": "ambiguous",
        "d": "contradictory", "contradictory": "contradictory",
        "u": "unbound", "unbound": "unbound",
    }.get(answer)


def run_review(output_dir, input_fn=input, out_fn=print):
    directory = Path(output_dir)
    path = directory / case_rules.CASES_NAME
    payload = json.loads(path.read_text(encoding="utf-8")) \
        if path.is_file() else {}
    records = payload.get("cases") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        out_fn("no oracle cases")
        return 0, 0
    open_cases = case_rules.open_questions(records)
    if not open_cases:
        out_fn("no open oracle cases")
        return 0, 0
    answered = 0
    for index, case in enumerate(open_cases, start=1):
        for line in _describe(index, len(open_cases), case):
            out_fn(line)
        status = _ask(case, input_fn)
        if status is None:
            out_fn("skipped — left open")
            continue
        case["status"] = status
        if status == "confirmed":
            # A human has resolved the listed assumptions/ambiguities.
            case["human_confirmed"] = True
            case["assumptions"] = []
            case["ambiguities"] = []
        answered += 1
    case_rules.save_cases(
        path, records,
        prompt_sha=payload.get("prompt_sha") if isinstance(payload, dict) else None)
    out_fn(f"answered {answered} of {len(open_cases)}; decisions in {path.name}")
    return len(open_cases), answered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output_dir")
    args = parser.parse_args(argv)
    run_review(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
